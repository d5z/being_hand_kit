"""L2 tests for hand 0.9.4-P5 — clickable point (elementFromPoint hit chain).

Spec: docs/spec-0.9.4-p5-clickable-point.md. Regression covered:

  * getBoundingClientRect returns the *bounding box*. For a multi-line inline
    element the box spans the line gaps — points that belong to no element.
    A coordinate click dispatched at the box centre then hits an ancestor
    container: the click's target chain has no <a>, so the browser never
    performs the default navigation. The receipt said ok; nothing happened.
  * the fix verifies, before dispatching, that the point's elementFromPoint
    hit chain contains the target (element itself or descendant); when the
    centre misses, a 5×15 grid scan of the box finds a point that does.

The fixture recreates GitHub's issue-title geometry: a wide first line, a
short second line and an exaggerated line-height, so the bounding-box centre
sits in a line gap that belongs to no element. A control experiment proves
the danger first (the centre really misses), then the fix is proven by
behaviour (the link's click handler fires), not by receipt claims.

Skipped (never red) when no browser can be brought up.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action.cdp_act import cdp_click_do
from hand import router
from hand.perception.cdp_core import list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixture page ────────────────────────────────────────────────────
# 200px-wide wrapper; the link wraps to two lines with a 60px line-height.
# Line 1 fills the width; line 2 is short. The bounding box is ~200×120,
# so its centre (~100, 60) sits in the inter-line gap — and beyond line 2's
# short text. elementFromPoint there returns the wrapper, not the link.
PAGE = """<!doctype html><html><head><title>Gap</title></head>
<body style="margin:0">
<div id="wrap" style="width:200px">
  <a id="gaplink" href="#" style="line-height:60px">"""
PAGE += "a" * 26 + " bbbb"
PAGE += """</a>
</div>
<div id="covwrap" style="position:relative;width:200px;margin-top:20px">
  <a id="covlink" href="#" style="display:block;width:200px;height:40px">covered link</a>
  <div style="position:absolute;left:0;top:0;width:200px;height:40px;background:#fff"></div>
</div>
<script>
function cnt(id){return function(e){e.preventDefault();window[id]=(window[id]||0)+1;};}
document.getElementById('gaplink').addEventListener('click',cnt('gapClicks'));
document.getElementById('covlink').addEventListener('click',cnt('covClicks'));
</script>
</body></html>"""

PATHS = {"/gap": PAGE}

_FX = None
_CHROME = runner.chrome_available()
if not _CHROME:
    try:
        from hand.perception.cdp_launcher import ensure_chrome
        ensure_chrome()
    except Exception:
        pass
    _CHROME = runner.chrome_available()


def setUpModule():
    global _FX
    if _CHROME:
        _FX = FixtureServer(extra_pages=PATHS)


def tearDownModule():
    if _FX:
        _FX.close()


def _open_fixture(path):
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    pages, idx = [], None
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            idx = match[0]
            _write_last(idx)
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{path} never loaded in tab {tab['id']}")
    time.sleep(0.2)
    return tab


def _js(expr):
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, msg_id=91)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def _see():
    r = router.route_see(kind="a11y")
    if not r.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {r}")
    return r


def _handle(see, role, name):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and (h.get("name") or "") == name:
            return idx
    raise AssertionError(f"{role} {name!r} not in handle map: {see.get('handles')}")


@unittest.skipUnless(_CHROME, "no browser available")
class ClickablePoint(unittest.TestCase):
    """The line-gap trap: the centre misses, the grid scan lands, behaviour proves it."""

    def _open(self):
        _open_fixture("/gap")

    def test_centre_really_misses_the_link(self):
        """Control experiment: the bounding-box centre is in the gap."""
        self._open()
        r = _js("(function(){var a=document.getElementById('gaplink');"
                "var b=a.getBoundingClientRect();"
                "var cx=b.left+b.width/2,cy=b.top+b.height/2;"
                "var e=document.elementFromPoint(cx,cy);"
                "return JSON.stringify({centre:[cx,cy],box:[b.left,b.top,b.width,b.height],"
                "hit:e?e.tagName+'#'+e.id:'none',"
                "hitIsLink:!!(e&&(e===a||a.contains(e)))});})()")
        import json
        d = json.loads(r)
        self.assertFalse(d["hitIsLink"],
                         f"centre {d['centre']} unexpectedly hits the link — "
                         f"fixture no longer recreates the danger: {d}")
        self.assertNotEqual(d["hit"], "A#gaplink", d)

    def test_text_click_fires_the_link(self):
        """text= click on the multi-line link → the handler really fires."""
        self._open()
        before = _js("window.gapClicks||0")
        r = cdp_click_do("text=bbbb")
        self.assertTrue(r.get("verified"), r)
        self.assertEqual(r["evidence"]["click_point"]["how"], "grid_scan", r)
        after = _js("window.gapClicks||0")
        self.assertEqual(after, before + 1,
                         "receipt claimed a click but the link never fired")

    def test_handle_click_fires_the_link(self):
        """[idx] click on the multi-line link → the handler really fires."""
        self._open()
        see = _see()
        h = _handle(see, "link", "a" * 26 + " bbbb")
        before = _js("window.gapClicks||0")
        r = cdp_click_do(f"[{h}]")
        self.assertTrue(r.get("verified"), r)
        self.assertEqual(r["evidence"]["click_point"]["how"], "grid_scan", r)
        after = _js("window.gapClicks||0")
        self.assertEqual(after, before + 1,
                         "receipt claimed a click but the link never fired")

    def test_covered_link_fails_loudly(self):
        """A fully covered link has no clickable point → explicit failure."""
        self._open()
        r = cdp_click_do("text=covered link")
        self.assertFalse(r.get("verified"), r)
        self.assertIn("no clickable point", r.get("error", ""), r)


if __name__ == "__main__":
    unittest.main()
