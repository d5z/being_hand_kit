"""L2 tests for the quad mapping beyond scale: rotate, skew, and 3D.

tests/test_iframe_transform.py proved `scale(0.5)` on the <iframe> owner, and
tests/test_release_0132.py held the claim at the math level. The open account
(#35017) was that rotation / skew / 3D had no behavioural proof at all — the
math said "bilinear is exact for any affine", which is a statement about the
math, not about the browser reading the quad.

Measured 2026-10-25 through this fixture (see-see centre vs dispatched point,
child frame navigates or not):

  scale(0.5)                             (179,118) / (179,118)   navigated
  rotate(18deg)                          (194,152) / (194,152)   navigated
  skewX(20deg)                           (220,136) / (220,136)   navigated
  perspective(600px) rotateY(25deg)      (199,135) / (199,134)   navigated
  perspective(120px) rotateY(40deg) scale(1.6)  (191,146) / (191,140)   navigated

So: affine (translate/scale/rotate/skew) — the two reads agree to <=1px, which
is what "one source for both" meant. Perspective is NOT affine: the browser
projects the quad projectively, while the dispatch point is a bilinear blend of
the four corners, and cdp_see's own centre comes from a third read. On a 48x64
target at 40deg the two are 6px apart — 1/10 of the target's height. The click
still landed because the target was bigger than the error; on a smaller target
it would miss. That is a documented limit, not a regression: a perspective
transform has no affine preimage, so a bilinear map cannot be exact there.

This module asserts the affine behaviour, and asserts the perspective case only
by its behaviour (the frame navigating), not by the two reads agreeing.
"""

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action.cdp_act import cdp_click_handle
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

LINK_LABEL = "go to B"

AFFINE_TRANSFORMS = {
    "rotate18": "rotate(18deg)",
    "skewx20": "skewX(20deg)",
    "rotate_skew": "rotate(-12deg) skewX(14deg)",
}

PERSPECTIVE_TRANSFORMS = {
    "persp_close": "perspective(120px) rotateY(40deg) scale(1.6)",
}

_INNER = """<!doctype html><html><head><title>Inner A</title></head>
<body style="margin:0;padding:16px">
  <a id="tob" href="/geoinner-b" style="display:inline-block;padding:8px 12px;
     font-size:20px">%s</a>
</body></html>""" % LINK_LABEL

_B = """<!doctype html><html><head><title>Inner B</title></head>
<body style="margin:0;padding:16px">arrived at B</body></html>"""

_PARENT_TMPL = """<!doctype html><html><head><title>geo %s</title></head>
<body style="margin:0;background:#fff">
  <iframe src="/geoinner-a"
          style="position:absolute;left:150px;top:100px;width:240px;height:160px;
                 border:0;transform:%s;transform-origin:0 0">
  </iframe>
</body></html>"""

PATHS = {"/geoinner-a": _INNER, "/geoinner-b": _B}
for _name, _tf in list(AFFINE_TRANSFORMS.items()) + list(PERSPECTIVE_TRANSFORMS.items()):
    PATHS["/geo-%s" % _name] = _PARENT_TMPL % (_name, _tf)

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


def _js(expr):
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


def _open(path):
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])
            if _js("location.pathname") == path:
                return tab
        time.sleep(0.2)
    raise AssertionError("%s never loaded in tab %s" % (path, tab["id"]))


def _close(tab):
    try:
        req = urllib.request.Request("%s/json/close/%s" % (CDP_HOST, tab["id"]),
                                    method="PUT")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def _frame_urls():
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


def _handle_for(see, role, part):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and part in (h.get("name") or ""):
            return idx, h
    raise AssertionError("%s %r not in handle map" % (role, part))


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class TransformedIframeBehaviour(unittest.TestCase):
    """The click must reach the child frame under every transform we accept."""

    def setUp(self):
        self.tab = None

    def tearDown(self):
        if self.tab:
            _close(self.tab)

    def _click_and_read(self, name):
        self.tab = _open("/geo-%s" % name)
        see = router.route_see(kind="a11y")
        self.assertTrue(see.get("verified"), see)
        idx, handle = _handle_for(see, "link", LINK_LABEL)
        self.assertTrue(handle.get("frame_id"),
                        "handle did not record the owning frame: %s" % handle)
        centre = see["coords"][str(idx)]
        before = _frame_urls()
        r = cdp_click_handle("[%s]" % idx)
        after = _frame_urls()
        return centre, r, before, after

    def test_affine_dispatch_agrees_with_see_and_navigates(self):
        for name in AFFINE_TRANSFORMS:
            with self.subTest(transform=name):
                centre, r, before, after = self._click_and_read(name)
                ev = r.get("evidence") or {}
                got = list(ev.get("dispatched") or [])
                self.assertTrue(r.get("verified"), r)
                self.assertTrue(
                    abs(got[0] - centre["x"]) <= 1 and abs(got[1] - centre["y"]) <= 1,
                    "%s: dispatch %s disagrees with see centre (%s,%s)"
                    % (name, got, centre["x"], centre["y"]))
                self.assertIn("quad", (ev.get("frame") or {}).get("mapping") or "",
                              "%s: receipt does not name the quad mapping: %s"
                              % (name, ev.get("frame")))
                self.assertTrue(any(u.endswith("/geoinner-b") for u in after),
                                "%s: child frame did not navigate — before=%s after=%s"
                                % (name, before, after))
                _close(self.tab)
                self.tab = None

    def test_perspective_lands_but_two_reads_may_diverge(self):
        """Documented limit: perspective is not affine, so the two reads drift.

        Asserted by behaviour only. The measured gap (191,146) vs (191,140) on
        2026-10-25 is 6px on a 48x64 target — inside the target, which is why
        the click still lands. Pinning the exact pixel here would pin the
        browser's projection, not hand's behaviour.
        """
        for name in PERSPECTIVE_TRANSFORMS:
            with self.subTest(transform=name):
                centre, r, before, after = self._click_and_read(name)
                ev = r.get("evidence") or {}
                got = list(ev.get("dispatched") or [])
                self.assertTrue(r.get("verified"), r)
                gap = max(abs(got[0] - centre["x"]), abs(got[1] - centre["y"]))
                self.assertLessEqual(
                    gap, 12,
                    "%s: dispatch %s vs see centre (%s,%s) — gap %.1fpx is larger "
                    "than the bilinear-vs-projective drift measured on 2026-10-25 "
                    "(6px). Either the target got smaller or the mapping changed."
                    % (name, got, centre["x"], centre["y"], gap))
                self.assertTrue(any(u.endswith("/geoinner-b") for u in after),
                                "%s: child frame did not navigate — before=%s after=%s"
                                % (name, before, after))
                _close(self.tab)
                self.tab = None


if __name__ == "__main__":
    unittest.main()
