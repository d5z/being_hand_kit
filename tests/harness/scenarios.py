"""Scenario definitions + a local fixture server (L2-L6).

Two kinds of scenarios, both driven through real Chrome:

  * deterministic fixtures — a throwaway HTTP server on 127.0.0.1 serving
    pages with known structure (form, clickable button, oversized tree,
    never-answering socket). No external network → no flake.
  * real sites — beings.town and github.com journeys. These tolerate site
    drift: judges return NEAR when the target moved, SKIP when the network is
    unreachable.

The fixture server runs in-process (ThreadingHTTPServer) so L2/L4 keep working
on an offline box.
"""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── rendered pages ───────────────────────────────────────────────────

BASIC_HTML = """<!doctype html><html><head><title>Fixture Basic</title></head>
<body>
  <h1>Fixture Basic</h1>
  <p>Deterministic page for hand L2 integration.</p>
  <a id="to-form" href="/form">Go to form</a>
  <button id="mark" onclick="window.clicked=(window.clicked||0)+1">Mark</button>
</body></html>"""

FORM_HTML = """<!doctype html><html><head><title>Fixture Form</title></head>
<body>
  <h1>Fixture Form</h1>
  <label for="q">Query</label>
  <input id="q" type="text" name="q" aria-label="Query">
  <a id="back" href="/basic">Back</a>
</body></html>"""

BIG_HTML = ("<!doctype html><html><head><title>Fixture Big</title></head><body>"
            "<h1>Fixture Big</h1>"
            + "".join(f'<p>paragraph number {i} with some words to fill the tree</p>'
                      for i in range(900))
            + "</body></html>")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        pages = {"/basic": BASIC_HTML, "/form": FORM_HTML, "/big": BIG_HTML,
                 "/": BASIC_HTML}
        body = pages.get(path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>404</h1>")
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FixtureServer:
    """In-process HTTP server + a raw socket that accepts and never answers.

    Usage:  with FixtureServer() as fx: fx.url("/basic")
    """

    def __init__(self):
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._http.daemon_threads = True
        self._t = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._t.start()
        # Blackhole socket: TCP accept, then hold the connection open. Used for
        # the "slow page / timeout is honest" L4 scenario.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._blackhole_port = self._sock.getsockname()[1]
        self._held = []
        self._stop = False
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
                self._held.append(conn)  # hold it open forever
            except OSError:
                return

    @property
    def port(self):
        return self._http.server_address[1]

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def blackhole_url(self, path="/slow"):
        return f"http://127.0.0.1:{self._blackhole_port}{path}"

    def close(self):
        self._stop = True
        try:
            self._http.shutdown()
            self._http.server_close()
        except Exception:
            pass
        for c in self._held:
            try:
                c.close()
            except Exception:
                pass
        try:
            self._sock.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ── L3 real-site journey definitions (data-driven) ───────────────────
# Each journey: a list of steps (name, callable) + a judge that returns a
# three-state verdict. `host` gates the whole journey: unreachable → SKIP.

class Journey:
    def __init__(self, name, start_url, host, steps, judge, layer="L3"):
        self.name = name
        self.start_url = start_url
        self.host = host
        self.steps = steps            # list[(step_name, callable(ctx) -> dict)]
        self.judge = judge            # callable(ctx) -> Verdict
        self.layer = layer


JOUNREYS_PLACEHOLDER = None


# ── step helpers (data-driven journeys) ──────────────────────────────

def _fail(reason, **fields):
    out = {"error": reason, "verified": False,
           "evidence": {"verified": False, "reason": reason}}
    out.update(fields)
    return out


def step_open(url, key="open"):
    def f(ctx):
        from hand import router
        r = router.route_open(url)
        ctx[key] = r
        return r
    return f


def step_see(kind="a11y", key="see", settle=0.0):
    def f(ctx):
        import time as _t
        from hand import router
        if settle:
            _t.sleep(settle)
        r = router.route_see(kind=kind)
        ctx[key] = r
        return r
    return f


def step_find_link(candidates, key="target_idx", roles=("link", "tab", "button")):
    """Locate a handle whose accessible name matches one of `candidates`."""
    def f(ctx):
        see = ctx.get("see") or {}
        handles = see.get("handles") or {}
        for idx, h in handles.items():
            if h.get("role") not in roles:
                continue
            name = h.get("name") or ""
            for c in candidates:
                if c.lower() in name.lower():
                    ctx[key] = idx
                    ctx["target_name"] = name
                    ctx["target_role"] = h.get("role")
                    return {"method": "find", "handle": f"[{idx}]", "name": name,
                            "role": h.get("role"), "result": "ok", "verified": True,
                            "evidence": {"role": h.get("role"), "name": name,
                                         "handle": f"[{idx}]"}}
        return _fail(f"no handle matching {candidates!r} among {len(handles)} nodes",
                     searched=list(candidates))
    return f


def step_click_handle(key="target_idx"):
    def f(ctx):
        from hand import router
        idx = ctx.get(key)
        if not idx:
            return _fail("no target handle located in a previous find step")
        return router.route_do(f"[{idx}]")
    return f


def step_find_role(role, key="target_idx"):
    def f(ctx):
        see = ctx.get("see") or {}
        for idx, h in (see.get("handles") or {}).items():
            if h.get("role") == role:
                ctx[key] = idx
                ctx["target_name"] = h.get("name")
                return {"method": "find", "handle": f"[{idx}]", "name": h.get("name"),
                        "role": role, "result": "ok", "verified": True,
                        "evidence": {"role": role, "name": h.get("name")}}
        return _fail(f"no handle with role {role!r} in tree")
    return f


def step_type_focused(text, key="type"):
    def f(ctx):
        from hand.action.cdp_act import cdp_type_focused
        r = cdp_type_focused(text)
        ctx[key] = r
        return r
    return f


def step_read_input(selector, key="read_back"):
    def f(ctx):
        from hand.perception.cdp_core import (
            list_pages, resolve_page, cdp_connect, cdp_call, _init_domains)
        pages = list_pages()
        _, page = resolve_page(None, pages)
        ws = cdp_connect(page["webSocketDebuggerUrl"])
        try:
            _init_domains(ws, "Runtime")
            expr = ("(function(){var e=document.querySelector("
                    + __import__("json").dumps(selector) + ");"
                    "return e?e.value:null;})()")
            raw = cdp_call(ws, "Runtime.evaluate",
                           {"expression": expr, "returnByValue": True}, msg_id=88)
            value = raw.get("result", {}).get("value")
        finally:
            ws.close()
        ctx[key] = value
        return {"method": "read_back", "selector": selector, "value": value,
                "verified": value is not None,
                "evidence": {"selector": selector, "value": value}}
    return f


def _step_receipts(ctx, step):
    for rec in ctx.get("trace", {}).get("steps", []):
        if rec["step"] == step:
            return rec["receipt"]
    return None


# ── journey judges ───────────────────────────────────────────────────

def judge_navigation_journey(ctx):
    """open -> see -> find target -> click -> see again, ending on expect_url."""
    from tests.harness import judge as J
    name = ctx["trace"]["journey"]
    r_open = _step_receipts(ctx, "open")
    r_see = _step_receipts(ctx, "see")
    r_find = _step_receipts(ctx, "find")
    r_click = _step_receipts(ctx, "click")
    r_see2 = _step_receipts(ctx, "see-again")

    vo = J.judge_open(r_open, task=f"{name}/open")
    if vo.state != J.HIT:
        return J.miss(name, f"open failed: {vo.reason}", receipts={"open": r_open})
    vs = J.judge_a11y(r_see, task=f"{name}/see")
    if not vs.ok():
        return J.miss(name, f"see failed: {vs.reason}", receipts={"see": r_see})
    if r_find is None or r_find.get("error"):
        return J.near(name, f"target not found in this page state (site drift): "
                            f"{(r_find or {}).get('error')}", searched=ctx.get("candidates"))
    vc = J.judge_click(r_click, task=f"{name}/click")
    if not vc.ok():
        return J.miss(name, f"click failed: {vc.reason}", receipts={"click": r_click})
    after_url = (r_see2 or {}).get("url") or ""
    expect = ctx.get("expect_url")
    if expect and expect.lower() in after_url.lower():
        return J.hit(name, f"journey landed on {after_url}",
                     url=after_url, target=ctx.get("target_name"))
    if after_url and after_url != (r_see or {}).get("url"):
        return J.near(name, f"click navigated to {after_url} (expected *{expect}*) — site drift",
                      url=after_url, expect=expect)
    return J.miss(name, f"click landed but page did not change (url={after_url})",
                  receipts={"click": r_click, "see-again": r_see2})


def judge_form_journey(ctx):
    from tests.harness import judge as J
    name = ctx["trace"]["journey"]
    r_open = _step_receipts(ctx, "open")
    r_see = _step_receipts(ctx, "see")
    r_focus = _step_receipts(ctx, "focus")
    r_type = _step_receipts(ctx, "type")
    if not J.judge_open(r_open, task=f"{name}/open").ok():
        return J.miss(name, "open failed")
    if not J.judge_a11y(r_see, task=f"{name}/see").ok():
        return J.miss(name, "see failed")
    vf = J.judge_click(r_focus, task=f"{name}/focus")
    if not vf.ok():
        return J.miss(name, f"focus click failed: {vf.reason}")
    text = ctx.get("type_text", "")
    return J.judge_type(r_type, text, read_back=ctx.get("read_back"),
                        task=f"{name}/type")
