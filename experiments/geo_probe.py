"""Probe: does the quad-mapping dispatch hold for rotate / skew / 3D?

Not a test yet — a reading. For each transform variant on the <iframe> owner:
  - open fixture, cdp_see, find the link, click it by handle
  - record: see centre vs dispatched point, frame mapping, whether the child
    frame actually navigated (behavioural proof, the only one that counts)
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, "/home/alice/Hand")

from hand import router
from hand.action.cdp_act import cdp_click_handle
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness.scenarios import FixtureServer

LINK_LABEL = "go to B"

VARIANTS = {
    "scale05": "scale(0.5)",
    "rotate18": "rotate(18deg)",
    "skewx20": "skewX(20deg)",
    "persp_roty25": "perspective(600px) rotateY(25deg)",
    "roty25_nopersp": "rotateY(25deg)",
    "persp_strong": "perspective(200px) rotateY(45deg)",
    "persp_close": "perspective(120px) rotateY(40deg) scale(1.6)",
}

INNER = """<!doctype html><html><head><title>Inner A</title></head>
<body style="margin:0;padding:16px">
  <a id="tob" href="/geo-b" style="display:inline-block;padding:8px 12px;
     font-size:20px">%s</a>
</body></html>""" % LINK_LABEL

B = """<!doctype html><html><head><title>Inner B</title></head>
<body style="margin:0;padding:16px">arrived at B</body></html>"""

PAGES = {"/geo-inner": INNER, "/geo-b": B}
for name, tf in VARIANTS.items():
    PAGES["/geo-%s" % name] = """<!doctype html><html><head><title>%s</title></head>
<body style="margin:0;background:#fff">
  <iframe src="/geo-inner"
          style="position:absolute;left:150px;top:100px;width:240px;height:160px;
                 border:0;transform:%s;transform-origin:0 0">
  </iframe>
</body></html>""" % (name, tf)


def js(expr):
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, msg_id=94)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def frame_urls():
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        tree = cdp_call(ws, "Page.getFrameTree", {}, msg_id=93)["frameTree"]
    finally:
        ws.close()
    out, stack = [], [tree]
    while stack:
        node = stack.pop(0)
        out.append((node.get("frame") or {}).get("url") or "")
        stack.extend(node.get("childFrames") or [])
    return out


def open_fixture(fx, path):
    tab = open_new_tab(fx.url(path))
    deadline = time.time() + 10
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])
            if js("location.pathname") == path:
                return tab
        time.sleep(0.2)
    raise AssertionError("%s never loaded" % path)


def close_tab(tab):
    try:
        req = urllib.request.Request("%s/json/close/%s" % (CDP_HOST, tab["id"]),
                                    method="PUT")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        print("   (close failed: %s)" % e)


def handle_for(see, role, part):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and part in (h.get("name") or ""):
            return idx, h
    return None, None


def main():
    fx = FixtureServer(extra_pages=PAGES)
    try:
        for name in VARIANTS:
            tab = None
            try:
                tab = open_fixture(fx, "/geo-%s" % name)
                see = router.route_see(kind="a11y")
                idx, handle = handle_for(see, "link", LINK_LABEL)
                if idx is None:
                    print("%-14s SEE-FAIL verified=%s" % (name, see.get("verified")))
                    continue
                center = see["coords"][str(idx)]
                before = frame_urls()
                r = cdp_click_handle("[%s]" % idx)
                ev = r.get("evidence") or {}
                after = frame_urls()
                nav = any(u.endswith("/geo-b") for u in after)
                print("%-14s verified=%-5s frame=%s" %
                      (name, r.get("verified"), bool(handle.get("frame_id"))))
                print("   see centre      %s" % json.dumps(
                    [round(center["x"], 2), round(center["y"], 2)]))
                print("   dispatched      %s" % (ev.get("dispatched"),))
                print("   mapping         %s" % ((ev.get("frame") or {}).get("mapping")))
                print("   landed          %s" % (r.get("landed"),))
                print("   child navigated %s   before=%s" % (nav, before[1:]))
            finally:
                if tab:
                    close_tab(tab)
    finally:
        fx.close()


if __name__ == "__main__":
    main()
