"""Hand — the Python face (0.8.0, code mode).

Same body, second face. Beings speak MCP; 触手 / agents inside a persistent
Python kernel speak this module:

    from hand import hand
    hand.open("https://beings.town")
    page = hand.see()                       # a11y tree + [idx] handles
    hand.do("click [15]", expect="url:/issues")
    hand.do("type hello")

Nothing here is a new capability — it is the 0.7 body (router + CDP backends +
a11y-v2 perception + receipt contract) behind a Python-shaped surface.

THE RECEIPT IS THE PROTOCOL
---------------------------
This module is the boundary of a future native protocol, so the return shape is
a contract, not a convenience:

  * every call answers one skeleton — `ok`, `action`, `kind`, `method`, `url`,
    `title`, `verified`, `error`, `hint` — plus action-specific fields.
    `ok` is the *call* verdict ("did the layer carry out what you asked");
    `verified` is the *evidence* verdict ("did we read back that it happened").
    They are never collapsed into one boolean.
  * field ORDER is fixed (`FIELD_ORDER`), so `json.dumps(receipt)` is stable
    across runs. No timestamps, no set iteration, no id() — the payload is
    byte-reproducible for a given page state.
  * `[idx]` handles come from `see()` and stay resolvable across calls in the
    same page state (they live in the last snapshot's handle map).
  * truncation is declared, never silent (`truncated` / `nodes_omitted`).
  * `do()` does NOT guess world state: `url`/`title` are None on an action
    receipt because a click is asynchronous. Either call `see()` again or pass
    `expect=` (bounded wait, separate verdict).

Do not rename these fields casually: a rename is a protocol break.

PERSISTENCE
-----------
`browser()` is a lazily created process-wide singleton. In a persistent kernel
your variables, the handles, and the Chrome process all stay alive between
executions — keep handles in variables instead of re-opening the browser.
`reset()` drops the singleton (tests); `close()` shuts the browser down.

ACTION GRAMMAR
--------------
    click [15]              click the node see() numbered [15]
    click selector=a.login  click by CSS selector (bare CSS works too)
    click text=Sign in      click by visible text
    click xy=100,200        click physical pixels (CSS px × dpr; dispatch-only)
    type hello              type into the focused element (click the field first)
    type [3] hello          focus handle [3], then type
    scroll down             down | up | top | bottom
    <target>                bare form == click <target>

No verb means "click that target" — one rule, no surprises. Failures answer with
`error` + `hint` that names the next move (错误消息即文档): a selector miss points
at the `[idx]` handles from `see()`, a stale handle points at `see()`, typing
with no focus points at clicking the field first.
"""

import base64
import builtins          # module-level `open` is the primitive; keep the builtin
import json
import time

from hand.session import get_session, reset_session, Place

__all__ = ["Browser", "browser", "reset", "open", "see", "do", "shot", "close",
           "handles", "resolve", "history", "help", "ACTION_GRAMMAR",
           "FIELD_ORDER", "DEFAULT_EXPECT_TIMEOUT"]

DEFAULT_EXPECT_TIMEOUT = 5.0
EXPECT_POLL_INTERVAL = 0.25
HISTORY_LIMIT = 50

# Fixed field order of every receipt (the protocol contract; append-only).
FIELD_ORDER = (
    # skeleton
    "ok", "action", "kind", "verb", "target", "method", "url", "title",
    "verified", "error", "hint",
    # world-state verdict (only when expect= was given)
    "expect",
    # open
    "place",
    # see
    "tree", "handles", "coords", "truncated", "nodes_omitted", "text_truncated_count",
    "truncation", "visual_state", "visual_signals", "node_count",
    "line_count", "serialized_bytes", "sha256", "format", "ax_version", "header",
    "page_index", "coord",
    # do / shot / close
    "result", "tiers", "changed", "path", "bytes", "data", "pages", "closed",
    "endpoint_gone",
    # evidence last (it is the raw material for the verdicts above)
    "evidence",
)

# Which channel actually answered → the `kind` a caller should reason about.
_KIND_BY_METHOD = {
    "cdp_a11y": "a11y",
    "cdp_snapshot": "dom",
    "cdp_interactive": "interactive",
    "cdp_network": "network",
    "ax_app": "ax_app",
    "ax_ui": "ax_ui",
    "vision_ocr": "vision_ocr",
}

ACTION_GRAMMAR = (
    ("click [15]", "click the node whose [idx] handle see() printed"),
    ("click selector=a.login",
     "click by CSS selector (a bare selector works too: click a.login)"),
    ("click text=Sign in", "click by visible text"),
    ("click xy=100,200",
     "click physical pixels (CSS px × dpr); dispatch-only, nothing to read back"),
    ("type hello", "type into the focused element — click the field first"),
    ("type [3] hello", "focus handle [3], then type"),
    ("scroll down", "scroll down | up | top | bottom"),
    ("do(action, expect='url:/issues')",
     "after the action, wait up to 5s for the world state; reports met + evidence"),
)

_GRAMMAR_TEXT = "\n".join(f'  hand.do("{form}")'.ljust(46) + meaning
                          for form, meaning in ACTION_GRAMMAR)

_SEE_KINDS = ("a11y", "dom", "interactive", "network", "vlm", "screenshot")

# Backend receipt keys the face replaces with its own normalized field.
_LEGACY_KEYS = ("open",)          # "open": "ok"  →  ok: true


# ── receipt helpers ──────────────────────────────────────────────────

def _order(receipt: dict) -> dict:
    """Fixed field order, then any leftovers in sorted order (deterministic)."""
    out = {}
    for key in FIELD_ORDER:
        if key in receipt:
            out[key] = receipt[key]
    for key in sorted(set(receipt) - set(out)):
        out[key] = receipt[key]
    return out


def _receipt(action, raw=None, *, kind=None, verb=None, target=None, error=None,
             hint=None, expect=None, url=None, title=None, extra=None) -> dict:
    raw = dict(raw or {})
    if error is None:
        error = raw.get("error")
    ok = not error
    if hint is None:
        hint = raw.get("hint") if action == "see" else None
        if ok and hint is None:
            hint = _unverified_hint(raw)
        elif not ok:
            hint = _failure_hint(error, raw)
    out = {
        "ok": ok,
        "action": action,
        "kind": kind if kind is not None else _KIND_BY_METHOD.get(raw.get("method") or ""),
        "method": raw.get("method"),
        "url": url if url is not None else raw.get("url"),
        "title": title if title is not None else raw.get("page_title"),
        "verified": raw.get("verified"),
        "error": error,
        "hint": hint,
    }
    if verb is not None:
        out["verb"] = verb
    if target is not None:
        out["target"] = target
    # `expect` is always present (None unless do(expect=...) was used): a stable
    # skeleton beats a key that appears and disappears.
    out["expect"] = expect
    out["evidence"] = raw.get("evidence")
    if extra:
        out.update(extra)
    # everything else the backend reported (tree, handles, place, result, …).
    # `open` is dropped: the MCP face's `"open": "ok"` is exactly what `ok`
    # normalizes (PRD S1) and a receipt must not carry two verdicts.
    for key, value in raw.items():
        if key in _LEGACY_KEYS:
            continue
        out.setdefault(key, value)
    return _order(out)


def _unverified_hint(raw) -> str | None:
    """A successful-but-unconfirmed call must say how to confirm it."""
    if raw.get("verified") is not False:
        return None
    evidence = raw.get("evidence") or {}
    reason = evidence.get("reason") or evidence.get("level") or "no read-back"
    if evidence.get("level") == "endpoint_alive":
        return (f"opened the endpoint but the navigation was not confirmed "
                f"(evidence.level=endpoint_alive: {evidence.get('detail')}). "
                f"Confirm with hand.see() — url/title come from the live page.")
    return (f"dispatched but unverified ({reason}). This call has nothing to read "
            f"back (a coordinate click is dispatch-only) — confirm with hand.see() "
            f"or use an [idx] handle / selector for a verified receipt.")


_FAILURE_HINTS = (
    ("selector did not match",
     'selector=... matched nothing on this page. Look again with hand.see() and click '
     'an [idx] handle: hand.do("click [15]"), or pass the CSS explicitly: '
     'hand.do("click selector=a.login").'),
    ("not in the last AX snapshot",
     "that [idx] handle is not in the last see(). Call hand.see() again and use one of "
     "the [idx] values it printed."),
    ("is gone (backendNodeId",
     "the element behind that [idx] handle is no longer in the page (the page moved or "
     "re-rendered). Call hand.see() again for fresh handles."),
    ("has no box",
     "the element behind that [idx] handle is not rendered (display:none / zero-size). "
     "Call hand.see() again — it only numbers what is actually there."),
    ("no focused element",
     'nothing was focused, so the text had nowhere to go. Click the field first: '
     'hand.do("click [3]") then hand.do("type hello").'),
    ("no place",
     'no browser is attached to this session yet. Call hand.open("https://...") first '
     '(hand.see() also works on an already-running Chrome).'),
    ("no chrome binary",
     "no browser binary was found. Install Chrome/Chromium or point $CHROME at one "
     "(see the README 'Requirements')."),
    ("no pages",
     'Chrome is not answering on the CDP port. Call hand.open("https://...") to '
     "(re)start it, then hand.see() again."),
)


def _failure_hint(error, raw) -> str | None:
    text = str(error or "")
    if "expect" in text:
        return ("expect= takes a world-state check: expect='url:/issues', "
                "'title:Issues' or 'text:hello'. The action itself still ran — "
                "see() shows the current url/title.")
    for needle, hint in _FAILURE_HINTS:
        if needle in text:
            return hint
    return ('look again with hand.see() and retry with a fresh [idx] handle. '
            "hand.help() prints the whole action table.")


# ── action grammar parsing ───────────────────────────────────────────

def parse_action(action) -> dict:
    """'click [15]' → {"verb": "click", "target": "[15]", "action": "[15]"}.

    Returns {"error": ...} for an unusable action. One rule for the bare form:
    no verb means "click that target".
    """
    if not isinstance(action, str) or not action.strip():
        return {"error": "empty action", "hint": _GRAMMAR_TEXT}
    text = action.strip()
    verb, _, rest = text.partition(" ")
    verb = verb.lower()
    rest = rest.strip()

    if verb == "click":
        if not rest:
            return {"error": "click needs a target",
                    "hint": 'hand.do("click [15]") / "click selector=a.login" / '
                            '"click text=Sign in" / "click xy=100,200"'}
        return {"verb": "click", "target": rest, "action": _click_target(rest)}

    if verb == "type":
        if not rest:
            return {"error": "type needs text",
                    "hint": 'click the field first, then hand.do("type hello"); '
                            'or do("type [3] hello") to focus a handle and type'}
        head, _, tail = rest.partition(" ")
        if _is_handle(head) and tail.strip():
            return {"verb": "type", "target": head, "text": tail.strip(),
                    "handle": head, "action": None}
        return {"verb": "type", "target": None, "text": rest, "handle": None,
                "action": None}

    if verb == "scroll":
        direction = rest.lower() or "down"
        if direction not in ("down", "up", "top", "bottom"):
            return {"error": f"scroll direction {direction!r} is not one of "
                             f"down/up/top/bottom",
                    "hint": 'hand.do("scroll down")'}
        return {"verb": "scroll", "target": direction, "action": f"scroll {direction}"}

    # No verb: one rule — click that target (bare selectors keep working).
    return {"verb": "click", "target": text, "action": _click_target(text)}


def _click_target(target: str) -> str:
    """Translate the face syntax into the router/backend syntax."""
    if target.startswith("selector="):
        return target[len("selector="):].strip()
    if target.startswith("xy="):
        return "xy:" + target[len("xy="):].strip()
    return target          # '[15]', 'text=...', 'xy:...', bare CSS


def _is_handle(token) -> bool:
    from hand.perception.ax_tree import looks_like_handle
    return looks_like_handle(token)


# ── world state (expect) ─────────────────────────────────────────────

def _page_state(need_text=False, need_visual=False) -> dict:
    """Cheap world-state read: {url, title[, text][, visual_state]}. Never raises.

    `need_visual` (0.9 S2) adds the DOM-side visual state marker so
    `expect="visual_state:loading"` can be evaluated.
    """
    try:
        from hand.perception.cdp_core import (
            list_pages, resolve_page, cdp_connect, cdp_call)
        pages = list_pages()
        idx, page = resolve_page(None, pages)
        ws = cdp_connect(page["webSocketDebuggerUrl"])
        try:
            fields = "url:location.href,title:document.title"
            if need_text:
                fields += ",text:((document.body&&document.body.innerText)||'').substring(0,2000)"
            raw = cdp_call(ws, "Runtime.evaluate",
                           {"expression": "JSON.stringify({%s})" % fields,
                            "returnByValue": True}, msg_id=77, timeout=5)
            value = (raw.get("result") or {}).get("value") or "{}"
            data = json.loads(value)
            if need_visual:
                from hand.perception.visual_state import probe as visual_probe
                data.update(visual_probe(ws, call=cdp_call))
        finally:
            try:
                ws.close()
            except Exception:
                pass
        return data if isinstance(data, dict) else {"error": "non-dict page state"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


EXPECT_KINDS = ("url", "title", "text", "visual_state")


def parse_expect(expect):
    """'url:/issues' / 'url=/issues' / 'title:Issues' / 'text:hello'
    / 'visual_state:loading' (0.9 S2)."""
    if not isinstance(expect, str) or ":" not in expect and "=" not in expect:
        return {"error": f"expect must look like 'url:/issues' (got {expect!r})",
                "hint": "forms: expect='url:/issues', 'title:Issues', "
                        "'text:hello', 'visual_state:loading'"}
    sep = ":" if ":" in expect else "="
    kind, _, needle = expect.partition(sep)
    kind, needle = kind.strip().lower(), needle.strip()
    if kind not in EXPECT_KINDS:
        return {"error": f"expect kind {kind!r} is not one of "
                         f"{'/'.join(EXPECT_KINDS)}",
                "hint": "expect kinds: url / title / text / visual_state — "
                        "e.g. expect='url:/issues', 'title:Issues', "
                        "'text:hello', 'visual_state:loading'"}
    if not needle:
        return {"error": f"expect {expect!r} has an empty value",
                "hint": "forms: expect='url:/issues', 'title:Issues', "
                        "'text:hello', 'visual_state:loading'"}
    if kind == "visual_state":
        from hand.perception.visual_state import VISUAL_STATES
        needle_l = needle.lower()
        if needle_l not in VISUAL_STATES:
            return {"error": f"visual_state {needle!r} is not one of "
                             f"{'/'.join(VISUAL_STATES)}",
                    "hint": "expect='visual_state:loading' where the state is "
                            "one of loading/error/blank/interactive/unknown"}
        needle = needle_l
    return {"kind": kind, "needle": needle, "spec": expect.strip()}


def _matches(kind, value, needle) -> bool:
    if not isinstance(value, str):
        return False
    if kind == "visual_state":
        # an enum, not a substring: the state either is or is not the one asked
        return value.lower() == needle.lower()
    # URLs are case-sensitive (paths are); human text is not.
    return needle in value if kind == "url" else needle.lower() in value.lower()


def _wait_for_world(parsed, timeout) -> dict:
    """Bounded wait for a world state. Never raises, never blocks forever."""
    deadline = time.time() + max(0.0, float(timeout))
    checks = 0
    state = {}
    started = time.time()
    ev_keys = ("url", "title", "visual_state")
    if parsed["kind"] == "visual_state":
        reason = (f"'visual_state' was never {parsed['needle']!r} "
                  f"within {timeout}s")
    else:
        reason = (f'{parsed["kind"]} never contained '
                  f'{parsed["needle"]!r} within {timeout}s')
    while True:
        if parsed["kind"] == "visual_state":
            state = _page_state(need_visual=True)
        else:
            state = _page_state(need_text=parsed["kind"] == "text")
        checks += 1
        if _matches(parsed["kind"], state.get(parsed["kind"]), parsed["needle"]):
            return {"spec": parsed["spec"], "kind": parsed["kind"],
                    "needle": parsed["needle"], "met": True,
                    "waited_ms": int((time.time() - started) * 1000), "checks": checks,
                    "evidence": {k: state.get(k) for k in ev_keys if k in state}}
        if time.time() >= deadline:
            return {"spec": parsed["spec"], "kind": parsed["kind"],
                    "needle": parsed["needle"], "met": False,
                    "waited_ms": int((time.time() - started) * 1000), "checks": checks,
                    "timeout_s": float(timeout),
                    "evidence": {k: state.get(k) for k in ev_keys if k in state},
                    "reason": reason}
        time.sleep(min(EXPECT_POLL_INTERVAL, max(0.0, deadline - time.time())))


# ── the singleton ────────────────────────────────────────────────────

class Browser:
    """The persistent half of the Python face: one browser, many calls."""

    def __init__(self):
        self.opened = False
        self.url = None
        self.title = None
        self.calls = 0
        self.last_receipt = None
        self.last_see = None
        self._history = []

    # -- internals

    def _record(self, receipt):
        self.calls += 1
        self.last_receipt = receipt
        summary = {"n": self.calls, "action": receipt.get("action"),
                   "verb": receipt.get("verb"), "target": receipt.get("target"),
                   "ok": receipt.get("ok"), "error": receipt.get("error"),
                   "met": (receipt.get("expect") or {}).get("met")}
        self._history.append(summary)
        del self._history[:-HISTORY_LIMIT]
        if receipt.get("action") == "see" and receipt.get("ok"):
            self.last_see = receipt
            self.url = receipt.get("url")
            self.title = receipt.get("title")
        return receipt

    def _ensure_place(self):
        """A live browser is a place — keeps do() working in a fresh kernel."""
        session = get_session()
        if session.place is not None:
            return session.place
        try:
            from hand.perception.cdp_core import list_pages
            if list_pages():
                session.place = Place(type="browser", identifier="cdp-detected")
        except Exception:
            pass
        return session.place

    # -- primitives

    def open(self, url=None, expect=None, timeout=DEFAULT_EXPECT_TIMEOUT) -> dict:
        if not isinstance(url, str) or not url.strip():
            return self._record(_receipt(
                "open", error="open needs a URL",
                hint='hand.open(url) needs a URL, e.g. '
                     'hand.open("https://beings.town") — see() works without it '
                     "if Chrome is already running"))
        try:
            from hand.router import route_open
            raw = route_open(url.strip())
        except Exception as e:
            return self._record(_receipt("open",
                                         error=f"{type(e).__name__}: {e}"))
        place = raw.get("place") or {}
        self.opened = True
        self.url = place.get("identifier") or url.strip()
        return self._record(_receipt("open", raw, url=self.url,
                                     extra={"place": place}))

    def see(self, kind=None) -> dict:
        try:
            from hand.router import route_see
            raw = route_see(kind=kind)
        except Exception as e:
            return self._record(_receipt("see", error=f"{type(e).__name__}: {e}"))
        requested = kind if kind in _SEE_KINDS else None
        return self._record(_receipt("see", raw, kind=requested))

    def do(self, action, expect=None, timeout=DEFAULT_EXPECT_TIMEOUT) -> dict:
        parsed = parse_action(action)
        if "error" in parsed:
            return self._record(_receipt("do", error=parsed["error"],
                                         hint=parsed.get("hint")))
        verb, target = parsed["verb"], parsed.get("target")
        try:
            raw = self._dispatch(parsed)
        except Exception as e:
            raw = {"error": f"{type(e).__name__}: {e}", "verified": False,
                   "evidence": {"verified": False, "reason": str(e)}}

        expect_out = None
        spec_error = None
        if expect is not None:
            expect_out = self._expect(expect, timeout, raw)
            # A spec we cannot honour is a caller error, not a world verdict: the
            # action still ran, so `verified`/`evidence` keep reporting it, while
            # `ok` says the call as specified could not be carried out.
            spec_error = expect_out.get("reason") if expect_out.get("spec_error") else None

        # do() does not guess world state: url/title stay None unless expect
        # measured them (a click is asynchronous — see the README).
        return self._record(_receipt("do", raw, verb=verb, target=target,
                                     expect=expect_out, url=None, title=None,
                                     error=spec_error,
                                     extra={"result": raw.get("result")}))

    def _dispatch(self, parsed) -> dict:
        if parsed["verb"] == "click":
            self._ensure_place()
            from hand.router import route_do
            return route_do(parsed["action"])
        if parsed["verb"] == "scroll":
            self._ensure_place()
            from hand.router import route_do
            return route_do(parsed["action"])
        # type: same path as MCP cdp_type — the focus backends, not route_do
        from hand.action.cdp_act import cdp_type_focused, cdp_type_handle
        if parsed.get("handle"):
            return cdp_type_handle(parsed["handle"], parsed["text"])
        return cdp_type_focused(parsed["text"])

    def _expect(self, expect, timeout, raw) -> dict:
        parsed = parse_expect(expect)
        if "error" in parsed:
            return {"spec": expect, "met": False, "skipped": True,
                    "spec_error": True, "reason": parsed["error"],
                    "hint": parsed.get("hint")}
        if raw.get("error"):
            # The action never landed: waiting for a world state would be a lie
            # about what was attempted (and a 5s stall).
            return {"spec": parsed["spec"], "kind": parsed["kind"],
                    "needle": parsed["needle"], "met": False, "skipped": True,
                    "reason": f"action failed: {raw.get('error')}"}
        return _wait_for_world(parsed, timeout)

    def shot(self, path=None, with_data=False) -> dict:
        try:
            from hand.router import route_screenshot
            raw = route_screenshot(with_data=True)
        except Exception as e:
            return self._record(_receipt("shot", error=f"{type(e).__name__}: {e}"))
        data = raw.get("data") or ""
        extra = {"format": raw.get("format"), "page_index": raw.get("page_index")}
        if data:
            try:
                blob = base64.b64decode(data)
                extra["bytes"] = len(blob)
                if path:
                    with builtins.open(path, "wb") as f:
                        f.write(blob)
                    extra["path"] = path
                    if not with_data:
                        raw = dict(raw)
                        raw.pop("data", None)
            except Exception as e:
                raw = dict(raw)
                raw.setdefault("evidence", {})
                raw["error"] = f"could not write screenshot: {type(e).__name__}: {e}"
        return self._record(_receipt("shot", raw, extra=extra))

    def close(self, timeout=8.0) -> dict:
        """Shut the CDP browser down and read back that it is gone.

        Same protocol as the MCP `cdp_close` receipt (verified only when the
        endpoint stops answering); kept here so the Python face has an explicit
        teardown instead of leaving a Chrome behind.
        """
        try:
            from hand.perception.cdp_core import list_pages, cdp_connect, cdp_call
            from hand.perception.cdp_launcher import chrome_running
            pages = list_pages()
        except Exception as e:
            return self._record(_receipt("close", error=f"{type(e).__name__}: {e}"))
        closed = 0
        for page in pages:
            ws = None
            try:
                ws = cdp_connect(page["webSocketDebuggerUrl"])
                cdp_call(ws, "Browser.close", {}, msg_id=1, timeout=5)
                closed += 1
            except Exception:
                pass
            finally:
                try:
                    if ws:
                        ws.close()
                except Exception:
                    pass
        deadline = time.time() + float(timeout)
        while time.time() < deadline and chrome_running():
            time.sleep(0.4)
        gone = not chrome_running()
        raw = {"method": None, "verified": gone,
               "evidence": {"verified": gone, "endpoint_gone": gone,
                            "read_back": "GET /json/version after Browser.close"}}
        if not gone:
            raw["evidence"]["reason"] = "endpoint still alive after Browser.close"
        if gone:
            self.opened = False
            self.last_see = None
        return self._record(_receipt("close", raw, extra={"pages": len(pages),
                                                          "closed": closed,
                                                          "endpoint_gone": gone}))

    def handles(self) -> dict:
        if self.last_see and self.last_see.get("handles"):
            return self.last_see["handles"]
        from hand.perception.ax_tree import load_handle_map
        return load_handle_map()

    def resolve(self, handle) -> dict:
        """[idx] → handle entry: last see() in this session first, then disk.

        The disk map is what the action layer clicks through, so the two agree
        whenever see() ran in this process; the in-memory copy is preferred
        because it is the snapshot the caller actually looked at.
        """
        from hand.perception.ax_tree import handle_index, resolve_handle
        idx = handle_index(handle)
        live = self.handles()
        if idx is not None and str(idx) in live:
            entry = dict(live[str(idx)])
            entry["idx"] = idx
            return entry
        return resolve_handle(handle)

    def history(self):
        return list(self._history)


_BROWSER = None


def browser() -> Browser:
    """The lazily created process-wide singleton."""
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = Browser()
    return _BROWSER


def reset():
    """Drop the singleton (tests, or a deliberate fresh start)."""
    global _BROWSER
    _BROWSER = None
    reset_session()


# ── module-level API (the same singleton) ────────────────────────────

def open(url=None, expect=None, timeout=DEFAULT_EXPECT_TIMEOUT):
    return browser().open(url, expect=expect, timeout=timeout)


def see(kind=None):
    return browser().see(kind)


def do(action, expect=None, timeout=DEFAULT_EXPECT_TIMEOUT):
    return browser().do(action, expect=expect, timeout=timeout)


def shot(path=None, with_data=False):
    return browser().shot(path=path, with_data=with_data)


def close(timeout=8.0):
    return browser().close(timeout=timeout)


def handles():
    return browser().handles()


def resolve(handle):
    return browser().resolve(handle)


def history():
    return browser().history()


def help(as_receipt=False):
    """The action table + return shape — 错误消息即文档, in one place."""
    from hand import __version__
    kinds = ", ".join(_SEE_KINDS)
    text = (
        f"hand {__version__} — Python face\n\n"
        "actions:\n" + _GRAMMAR_TEXT + "\n\n"
        "see(kind=...): " + kinds + "   (default: a11y tree with [idx] handles)\n\n"
        "returns (fixed field order):\n"
        "  ok        did the call do what you asked (bool)\n"
        "  action    open | see | do | shot | close | help\n"
        "  verified  did we read back that it happened (bool | None)\n"
        "  error     why it failed (None on success)\n"
        "  hint      what to do next (None when nothing needs saying)\n"
        "  expect    {'met': bool, 'waited_ms': int, 'evidence': {...}} with expect=\n"
        "  evidence  raw evidence behind the verdicts\n\n"
        "handles: see() numbers every node [idx]; do(\"click [15]\") uses them.\n"
        "do() does not guess world state — see() again or pass expect=.\n"
    )
    if not as_receipt:
        return text
    return _receipt("help", {"method": None, "verified": True, "evidence": {}},
                    extra={"actions": [{"form": f, "meaning": m}
                                       for f, m in ACTION_GRAMMAR],
                           "kinds": list(_SEE_KINDS),
                           "text": text})
