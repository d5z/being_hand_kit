"""Where do see's drawn centre and the dispatch point part company, under perspective?

Measured 2026-10-25 with iframe{perspective(120px) rotateY(40deg) scale(1.6)}
holding a 48x64 link:

  cdp_see drew      (191, 146)
  cdp_click         (191, 140)        <- bilinear blend of the four corners
  _quad_center_size (191.4, 140.3)    <- the quad's own corner average

The two haves of hand read the same element through different functions of the
same quad: see's centre comes from its own box read, the dispatch point from a
bilinear blend. Under an affine transform those agree (that is what 0.13.2's
"one source for both" bought). Under perspective they cannot: a perspective
projection has no affine preimage, so no bilinear map is exact. This script
prints the raw numbers so the limit stays a measurement, not a belief.

Usage: cd /home/alice/Hand && python3 experiments/geo_persp_detail.py
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, "/home/alice/Hand")

from hand import router
from hand.action.cdp_act import _element_border_quad, _quad_center_size
from hand.perception.cdp_core import (
    CDP_HOST, _init_domains, _write_last, cdp_call, cdp_connect, list_pages,
    resolve_page,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness.scenarios import FixtureServer

TF = "perspective(120px) rotateY(40deg) scale(1.6)"

INNER = """<!doctype html><html><head><title>Inner A</title></head>
<body style="margin:0;padding:16px">
  <a id="tob" href="/geo-b" style="display:inline-block;padding:8px 12px;
     font-size:20px">go to B</a>
</body></html>"""

B = """<!doctype html><html><head><title>Inner B</title></head>
<body style="margin:0;padding:16px">arrived at B</body></html>"""

PARENT = """<!doctype html><html><head><title>p</title></head>
<body style="margin:0;background:#fff">
  <iframe src="/geo-inner"
          style="position:absolute;left:150px;top:100px;width:240px;height:160px;
                 border:0;transform:%s;transform-origin:0 0">
  </iframe>
</body></html>""" % TF


def _load(fx, path):
    tab = open_new_tab(fx.url(path))
    for _ in range(60):
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])
            time.sleep(0.5)
            return tab
        time.sleep(0.2)
    raise AssertionError("%s never loaded" % path)


def _find_anchor(ws):
    doc = cdp_call(ws, "DOM.getDocument", {"depth": -1, "pierce": True}, msg_id=52)
    stack = [doc["root"]]
    while stack:
        node = stack.pop()
        if (node.get("nodeName") or "").upper() == "A":
            return node["backendNodeId"]
        stack.extend(node.get("children") or [])
        stack.extend(node.get("shadowRoots") or [])
        if node.get("contentDocument"):
            stack.append(node["contentDocument"])
    return None


def main():
    fx = FixtureServer(extra_pages={"/geo-inner": INNER, "/geo-b": B,
                                    "/geo-p": PARENT})
    tab = None
    try:
        tab = _load(fx, "/geo-p")
        see = router.route_see(kind="a11y")
        for idx, handle in (see.get("handles") or {}).items():
            if handle.get("role") == "link" and "go to B" in (handle.get("name") or ""):
                print("see centre      ", json.dumps(see["coords"][str(idx)]))
                print("handle frame_id ", (handle.get("frame_id") or "")[:12])
                break
        pages = list_pages()
        _, page = resolve_page(None, pages)
        ws = cdp_connect(page["webSocketDebuggerUrl"])
        try:
            _init_domains(ws, "DOM", "Runtime")
            bid = _find_anchor(ws)
            print("backendNodeId   ", bid)
            quad = _element_border_quad(ws, bid)
            print("border quad     ", quad)
            content = ((cdp_call(ws, "DOM.getBoxModel",
                                 {"backendNodeId": bid}, msg_id=53)
                        .get("model") or {}).get("content"))
            print("content quad    ", content)
            print("quad centre     ", _quad_center_size(quad))
            quads = cdp_call(ws, "DOM.getContentQuads",
                             {"backendNodeId": bid}, msg_id=54).get("quads")
            print("getContentQuads ", quads)
        finally:
            ws.close()
    finally:
        if tab:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    "%s/json/close/%s" % (CDP_HOST, tab["id"]), method="PUT"),
                    timeout=5).read()
            except Exception:
                pass
        fx.close()


if __name__ == "__main__":
    main()
