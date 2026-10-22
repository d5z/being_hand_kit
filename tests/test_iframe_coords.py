"""L2 tests for hand 0.13.1 — a click into a merged child frame.

Regression covered (measured live 2026-10-22, hand 0.13.0):

  * 0.13 merges child-frame content into the a11y tree, and cdp_see draws those
    nodes at the right pixel (`DOM.getBoxModel` is top-level). But
    `cdp_click_handle` read the same element through `getBoundingClientRect` and
    the `elementFromPoint` probe — both FRAME-local — and dispatched those
    numbers as if they were top-level. On a fixture whose iframe sits at
    (8, 59.4) that means a 61px vertical miss: the click landed on the frame's
    own padding, the frame did not navigate, and the receipt still said
    result=ok / resolved=true / landed=true (the probe had verified a hit in
    frame-local space).

The test proves the fix by behaviour, not by receipt claims: after the click the
child frame's URL must have changed. It also pins the invariant that made the bug
visible — the dispatch point must equal the point cdp_see reported for that
handle — and checks the main-frame path is unchanged (offset 0).

Real headless Chrome against the repo's own fixture server; skipped (never red)
when no browser can be brought up.
"""

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

# ── fixture pages ────────────────────────────────────────────────────
# The iframe is offset from the page origin on purpose: a frame at (0,0) would
# hide the very translation this test exists for (frame-local == top-level).
FRAME_LEFT, FRAME_TOP = 120, 80
FRAME_W, FRAME_H = 240, 120
LINK_LABEL = "go to B"

PARENT_HTML = """<!doctype html><html><head><title>Frame Coords</title></head>
<body style="margin:0">
  <h3 id="headline" onclick="window.parentClicked=(window.parentClicked||0)+1"
      style="margin:8px">parent headline</h3>
  <iframe src="/framecoords-inner"
          style="position:absolute;left:%dpx;top:%dpx;width:%dpx;height:%dpx;border:2px solid #333">
  </iframe>
</body></html>""" % (FRAME_LEFT, FRAME_TOP, FRAME_W, FRAME_H)

INNER_HTML = """<!doctype html><html><head><title>Inner A</title></head>
<body style="margin:0;padding:12px">
  <a id="tob" href="/framecoords-b">%s</a>
</body></html>""" % LINK_LABEL

B_HTML = """<!doctype html><html><head><title>Inner B</title></head>
<body style="margin:0;padding:12px">arrived at B</body></html>"""

PATHS = {"/framecoords-parent": PARENT_HTML,
         "/framecoords-inner": INNER_HTML,
         "/framecoords-b": B_HTML}

_FX = None
_CHROME = runner.chrome_available()
if not _CHROME:  # same launcher path the kit uses; a missing binary is a SKIP
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


# ── helpers ──────────────────────────────────────────────────────────

def _open_fixture(path):
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    pages, idx = [], None
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            idx = match[0]
            _write_last(idx)      # resolve_page(None) == this tab for every call
            if _js("location.pathname") == path:
                break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{path} never loaded in tab {tab['id']}")
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


def _frame_urls():
    """URLs of every frame in the session page, top frame first."""
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        ft = cdp_call(ws, "Page.getFrameTree", {}, msg_id=92)["frameTree"]
    finally:
        ws.close()
    out = []
    stack = [ft]
    while stack:
        node = stack.pop(0)
        out.append((node.get("frame") or {}).get("url") or "")
        stack.extend(node.get("childFrames") or [])
    return out


def _see():
    see = router.route_see(kind="a11y")
    if not see.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {see}")
    return see


def _handle_for(see, role, label_part):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and label_part in (h.get("name") or ""):
            return idx, h
    raise AssertionError(f"{role} {label_part!r} not in handle map: "
                         f"{see.get('handles')}")


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class IframeClickCoords(unittest.TestCase):
    """A frame-internal handle must be dispatched at its top-level pixel."""

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

    # ── 1 ───────────────────────────────────────────────────────────
    def test_frame_node_carries_its_frame_id(self):
        """A merged node's handle says which frame it lives in (0 → unknown)."""
        self.tab = _open_fixture("/framecoords-parent")
        see = _see()
        idx, handle = _handle_for(see, "link", LINK_LABEL)
        self.assertTrue(handle.get("frame_id"),
                        f"handle lost its frame id — a reader cannot tell the "
                        f"box is frame-local: {handle}")
        # the parent's own nodes must NOT claim a frame
        pidx, phandle = _handle_for(see, "heading", "parent headline")
        self.assertIsNone(phandle.get("frame_id"),
                          f"main-frame node wrongly tagged: {phandle}")

    # ── 2 ───────────────────────────────────────────────────────────
    def test_click_inside_frame_reaches_the_link(self):
        """Behaviour: the iframe must actually navigate to B."""
        self.tab = _open_fixture("/framecoords-parent")
        see = _see()
        idx, handle = _handle_for(see, "link", LINK_LABEL)
        center = see["coords"][str(idx)]
        before = _frame_urls()

        r = cdp_click_handle(f"[{idx}]")

        self.assertTrue(r.get("verified"), r)
        ev = r.get("evidence") or {}
        # the dispatch point must be the point see drew — the invariant that
        # 0.13.0 violated while still reporting landed=true
        self.assertEqual(list(ev.get("dispatched") or []),
                         [round(center["x"]), round(center["y"])],
                         f"dispatch disagrees with cdp_see's centre: {ev}")
        frame = ev.get("frame") or {}
        self.assertTrue(frame.get("frame_id"),
                        f"receipt does not say which frame it translated from: {ev}")
        self.assertGreater(frame["origin"]["x"] + frame["origin"]["y"], 0,
                           f"suspicious frame origin: {frame}")
        # behaviour, not receipt: the child frame really navigated
        after = _frame_urls()
        self.assertTrue(any(u.endswith("/framecoords-b") for u in after),
                        f"frame did not navigate — before={before} after={after}")
        self.assertNotEqual(before, after)

    # ── 3 ───────────────────────────────────────────────────────────
    def test_main_frame_click_keeps_zero_offset(self):
        """Regression: a main-frame handle still dispatches its own centre."""
        self.tab = _open_fixture("/framecoords-parent")
        see = _see()
        idx, handle = _handle_for(see, "heading", "parent headline")
        center = see["coords"][str(idx)]
        r = cdp_click_handle(f"[{idx}]")
        ev = r.get("evidence") or {}
        self.assertIsNone(ev.get("frame"),
                          f"main-frame click invented a frame translation: {ev}")
        self.assertEqual(list(ev.get("dispatched") or []),
                         [round(center["x"]), round(center["y"])], ev)
        self.assertEqual(_js("window.parentClicked||0"), 1,
                         "receipt ok but the parent heading handler never fired")


if __name__ == "__main__":
    unittest.main()
