"""L2 tests for hand 0.13.2 — a click into a TRANSFORMED child frame.

0.13.1 translated frame-local points by the frame's content-box origin. That is
correct only when the <iframe> owner is untransformed. Measured live 2026-10-22
with `iframe{transform:scale(0.5)}`:

  cdp_see drew the link at (112, 89)   ← getBoxModel, transform-aware, correct
  cdp_click dispatched (123, 126)      ← local (21.6,75.3) + origin (101,51)

i.e. the translation was applied and the scale silently dropped: 0.13.0's
failure one level deeper, with the same receipt shape (landed=true, nothing
happened). The fix takes the dispatch point from the element's own border quad —
the same read cdp_see draws with — so translate / scale / rotate / skew all come
from one source.

Behaviour is the proof: after the click the child frame must navigate to B.
"""

import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action.cdp_act import (
    cdp_click_handle, _map_local_to_top, _quad_center_size,
)
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

LINK_LABEL = "go to B"
SCALE = 0.5

_PARENT = """<!doctype html><html><head><title>Frame Transform</title></head>
<body style="margin:0">
  <iframe src="/iframetf-inner"
          style="position:absolute;left:120px;top:80px;width:240px;height:160px;
                 border:0;transform:scale(0.5);transform-origin:0 0">
  </iframe>
</body></html>"""

_INNER = """<!doctype html><html><head><title>Inner A</title></head>
<body style="margin:0;padding:16px">
  <a id="tob" href="/iframetf-b">%s</a>
</body></html>""" % LINK_LABEL

_B = """<!doctype html><html><head><title>Inner B</title></head>
<body style="margin:0;padding:16px">arrived at B</body></html>"""

PATHS = {"/iframetf-parent": _PARENT,
         "/iframetf-inner": _INNER,
         "/iframetf-b": _B}

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


def _open_fixture(path):
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])
            # wait for the document, not just the tab: a snapshot taken while the
            # fixture is still loading returns an empty tree (measured here)
            if _js("location.pathname") == path:
                break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{path} never loaded in tab {tab['id']}")
    return tab


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


def _handle_for(see, role, label_part):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and label_part in (h.get("name") or ""):
            return idx, h
    raise AssertionError(f"{role} {label_part!r} not in handle map")


class MappingMath(unittest.TestCase):
    """The bilinear map must be exact for every affine, not just translation."""

    def test_translation_only(self):
        quad = [110.0, 90.0, 210.0, 90.0, 210.0, 190.0, 110.0, 190.0]
        bounds = {"left": 10.0, "top": 10.0, "width": 100.0, "height": 100.0}
        x, y = _map_local_to_top(quad, bounds, (60.0, 60.0))
        self.assertAlmostEqual(x, 160.0, places=3)
        self.assertAlmostEqual(y, 140.0, places=3)

    def test_scale_is_applied(self):
        """0.5-scaled quad: local centre must land at the scaled pixel."""
        quad = [100.0, 80.0, 200.0, 80.0, 200.0, 130.0, 100.0, 130.0]
        bounds = {"left": 0.0, "top": 0.0, "width": 200.0, "height": 100.0}
        x, y = _map_local_to_top(quad, bounds, (120.0, 40.0))
        # local (120,40) = 60% across, 40% down → (100 + 0.6*100, 80 + 0.4*50)
        self.assertAlmostEqual(x, 160.0, places=3)
        self.assertAlmostEqual(y, 100.0, places=3)

    def test_rotation_centre_maps_to_centre(self):
        """A 90°-rotated quad: the local centre still maps to the quad centre.

        getBoxModel's quad is TL,TR,BR,BL in the element's own orientation, so a
        rotate(90deg) quad around the local box (0,0)-(200,100) placed at
        (300,100) reads TL(300,100) TR(300,300) BR(200,300) BL(200,100).
        """
        quad = [300.0, 100.0, 300.0, 300.0, 200.0, 300.0, 200.0, 100.0]
        bounds = {"left": 0.0, "top": 0.0, "width": 200.0, "height": 100.0}
        x, y = _map_local_to_top(quad, bounds, (100.0, 50.0))
        cx, cy, w, h = _quad_center_size(quad)
        self.assertAlmostEqual(x, cx, places=3)
        self.assertAlmostEqual(y, cy, places=3)
        self.assertAlmostEqual(x, 250.0, places=3)
        self.assertAlmostEqual(y, 200.0, places=3)
        # w/h are measured along the quad's own edges: local width and height
        self.assertAlmostEqual(w, 200.0, places=3)
        self.assertAlmostEqual(h, 100.0, places=3)

    def test_zero_size_does_not_divide_by_zero(self):
        quad = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
        bounds = {"left": 5.0, "top": 5.0, "width": 0.0, "height": 0.0}
        self.assertEqual(_map_local_to_top(quad, bounds, (5.0, 5.0)), (10.0, 10.0))


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class TransformedIframeClick(unittest.TestCase):
    def setUp(self):
        self.tab = None

    def tearDown(self):
        if not self.tab:
            return
        try:
            if len(list_pages()) > 1:
                req = urllib.request.Request(
                    f'{CDP_HOST}/json/close/{self.tab["id"]}', method="PUT")
                urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass

    def test_dispatch_matches_see_and_frame_navigates(self):
        self.tab = _open_fixture("/iframetf-parent")
        see = router.route_see(kind="a11y")
        self.assertTrue(see.get("verified"), see)
        idx, handle = _handle_for(see, "link", LINK_LABEL)
        self.assertTrue(handle.get("frame_id"), handle)
        center = see["coords"][str(idx)]
        before = _frame_urls()

        r = cdp_click_handle(f"[{idx}]")

        self.assertTrue(r.get("verified"), r)
        ev = r.get("evidence") or {}
        got = list(ev.get("dispatched") or [])
        want = [round(center["x"]), round(center["y"])]
        self.assertTrue(abs(got[0] - want[0]) <= 1 and abs(got[1] - want[1]) <= 1,
                        f"dispatch {got} disagrees with cdp_see's centre {want}: {ev}")
        frame = ev.get("frame") or {}
        self.assertIn("quad", (frame.get("mapping") or ""),
                      f"receipt does not say the mapping came from the quad: {frame}")

        after = _frame_urls()
        self.assertTrue(any(u.endswith("/iframetf-b") for u in after),
                        f"scaled frame did not navigate — before={before} after={after}")


if __name__ == "__main__":
    unittest.main()
