"""L2 tests for hand 0.13.4 — frames that are not the same document, and a
count that has to be about lines.

Two things measured live on 2026-10-22 (hand 0.13.3):

  * Cross-origin (OOPIF) child frames and *two-level* nesting both work: the
    content merges, every visible node keeps a backend id, coordinates come
    back in top-level space and a click really lands (the child document's own
    title flips). The 0.13.1 note claiming inner-frame nodes arrive without a
    backend id was measured before frame ids were carried through the merge,
    and it outlived its truth.

  * …but the note's *counter* was taken over raw AX nodes instead of printed
    lines, so a page whose every visible frame node was addressable still
    reported "3 node(s) in child frames carry no backend id — their text is
    readable here but they have no [idx] handle". A reader acts on lines; the
    count has to be about lines. That is the one code change in 0.13.4.

Real headless Chrome against in-process fixture servers; skipped (never red)
when no browser can be brought up. The cross-origin case uses two servers so
the child really is another origin (same host, different port).
"""

import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action.cdp_act import cdp_click_handle
from hand.perception import ax_tree
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _write_last, CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixtures ─────────────────────────────────────────────────────────
# The iframe is offset from the page origin on purpose: a frame at (0,0) would
# hide any frame-local / top-level confusion this suite exists to catch.
FRAME_LEFT, FRAME_TOP, FRAME_W, FRAME_H = 60, 90, 300, 140

XOR_PARENT_HTML = """<!doctype html><meta charset="utf-8"><title>xor parent</title>
<body style="margin:0">
  <h1 style="margin:8px">xor parent</h1>
  <iframe src="%s"
    style="position:absolute;left:%dpx;top:%dpx;width:%dpx;height:%dpx;border:2px solid #333">
  </iframe>
</body>""" % ("__CHILD_URL__", FRAME_LEFT, FRAME_TOP, FRAME_W, FRAME_H)

XOR_CHILD_HTML = """<!doctype html><meta charset="utf-8"><title>xor child</title>
<body style="margin:0;padding:12px">
  <h2>xor child heading</h2>
  <a href="#" onclick="event.preventDefault();document.title='xor clicked'">cross-origin link</a>
</body>"""

NEST_OUTER_HTML = """<!doctype html><meta charset="utf-8"><title>nest outer</title>
<body style="margin:0">
  <iframe src="/origins-nest-mid"
    style="position:absolute;left:100px;top:50px;width:300px;height:200px;border:0"></iframe>
</body>"""

NEST_MID_HTML = """<!doctype html><meta charset="utf-8"><title>nest mid</title>
<body style="margin:0">
  <iframe src="/origins-nest-inner"
    style="position:absolute;left:20px;top:30px;width:200px;height:100px;border:0"></iframe>
</body>"""

NEST_INNER_HTML = """<!doctype html><meta charset="utf-8"><title>nest inner</title>
<body style="margin:0;padding:10px">
  <button style="margin:10px;padding:6px 12px"
    onclick="document.title='inner clicked'">nested button</button>
</body>"""

PARENT_PATHS = {
    "/origins-xor-parent": XOR_PARENT_HTML,
    "/origins-nest-outer": NEST_OUTER_HTML,
    "/origins-nest-mid": NEST_MID_HTML,
    "/origins-nest-inner": NEST_INNER_HTML,
}
CHILD_PATHS = {"/origins-xor-child": XOR_CHILD_HTML}

_FX = None       # parent origin
_FX2 = None      # child origin (different port → different origin)
_CHROME = runner.chrome_available()
if not _CHROME:  # same launcher path the kit uses; a missing binary is a SKIP
    try:
        from hand.perception.cdp_launcher import ensure_chrome
        ensure_chrome()
    except Exception:
        pass
    _CHROME = runner.chrome_available()


def setUpModule():
    global _FX, _FX2
    if _CHROME:
        _FX2 = FixtureServer(extra_pages=CHILD_PATHS)
        paths = dict(PARENT_PATHS)
        paths["/origins-xor-parent"] = XOR_PARENT_HTML.replace(
            "__CHILD_URL__", _FX2.url("/origins-xor-child"))
        _FX = FixtureServer(extra_pages=paths)


def tearDownModule():
    for fx in (_FX, _FX2):
        if fx:
            fx.close()


# ── helpers ──────────────────────────────────────────────────────────

def _open_fixture(path):
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])   # resolve_page(None) == this tab
            if _js("location.pathname") == path:
                return tab
        time.sleep(0.2)
    raise AssertionError(f"{path} never loaded in tab {tab['id']}")


def _ws():
    _, page = resolve_page(None, list_pages())
    return cdp_connect(page["webSocketDebuggerUrl"])


def _js(expr):
    ws = _ws()
    try:
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, msg_id=91)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def _frames():
    """[(frame_id, url)] for every frame in the session page, top first."""
    ws = _ws()
    try:
        tree = cdp_call(ws, "Page.getFrameTree", {}, msg_id=92)["frameTree"]
    finally:
        ws.close()
    out, stack = [], [tree]
    while stack:
        node = stack.pop(0)
        f = node.get("frame") or {}
        out.append((f.get("id"), f.get("url") or ""))
        stack.extend(node.get("childFrames") or [])
    return out


def _frame_title(url_part):
    """document.title of the frame whose URL contains `url_part` — the ground
    truth a page's own JS cannot give us across origins."""
    fid = next((i for i, u in _frames() if url_part in u), None)
    if not fid:
        raise AssertionError(f"no frame with {url_part!r} in {_frames()}")
    ws = _ws()
    try:
        world = cdp_call(ws, "Page.createIsolatedWorld",
                         {"frameId": fid, "worldName": "groundtruth"}, msg_id=93)
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": "document.title",
                        "contextId": world["executionContextId"],
                        "returnByValue": True}, msg_id=94)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def _see():
    see = router.route_see(kind="a11y")
    if not see.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {see}")
    return see


def _wait_for_handle(role, label_part, timeout=10):
    """Frames load asynchronously — poll the snapshot instead of trusting the
    first one (a nested frame's button is absent for a beat after navigate)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = _see()
        try:
            return last, _handle_for(last, role, label_part)
        except AssertionError:
            time.sleep(0.25)
    raise AssertionError(f"{role} {label_part!r} never appeared; last seen: "
                         f"{list((last.get('handles') or {}).values())}")


def _handle_for(see, role, label_part):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and label_part in (h.get("name") or ""):
            return idx, h
    raise AssertionError(f"{role} {label_part!r} not in handle map: "
                         f"{list((see.get('handles') or {}).values())}")


def _bounds(handle):
    """centre+w/h → (left, top, right, bottom)."""
    hw, hh = (handle.get("w") or 0) / 2.0, (handle.get("h") or 0) / 2.0
    return (handle["x"] - hw, handle["y"] - hh,
            handle["x"] + hw, handle["y"] + hh)


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class CrossOriginFrame(unittest.TestCase):
    """A frame from another origin is a separate renderer, same treatment."""

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

    def test_merged_content_is_addressable_and_placed_on_screen(self):
        self.tab = _open_fixture("/origins-xor-parent")
        see, (idx, link) = _wait_for_handle("link", "cross-origin link")
        self.assertTrue(link.get("frame_id"),
                        f"cross-origin handle lost its frame id: {link}")
        self.assertTrue(link.get("backend_node_id"),
                        f"cross-origin handle has no backend id: {link}")
        # the drawn box must sit inside the iframe's own box on screen — this
        # is the invariant that a frame-local number would break by ~(60,90).
        _, iframe = _handle_for(see, "Iframe", "")
        il, it, ir, ib = _bounds(iframe)
        cx, cy = see["coords"][str(idx)]["x"], see["coords"][str(idx)]["y"]
        self.assertTrue(il <= cx <= ir and it <= cy <= ib,
                        f"cross-origin node drawn at ({cx},{cy}), outside the "
                        f"iframe box {(il, it, ir, ib)} — frame-local leaked")

    def test_the_note_does_not_claim_unaddressable_lines(self):
        self.tab = _open_fixture("/origins-xor-parent")
        see = _see()
        hint = see.get("hint") or ""
        self.assertIn("merged", hint)
        self.assertNotIn("no backend id", hint,
                         f"note claims unaddressable lines on a page whose "
                         f"every frame line is addressable: {hint}")
        for h in (see.get("handles") or {}).values():
            if h.get("frame_id"):
                self.assertTrue(h.get("backend_node_id"),
                                f"frame line without a backend id: {h}")

    def test_click_reaches_the_other_origin(self):
        self.tab = _open_fixture("/origins-xor-parent")
        see, (idx, _) = _wait_for_handle("link", "cross-origin link")
        self.assertEqual(_frame_title("/origins-xor-child"), "xor child")
        r = cdp_click_handle(f"[{idx}]")
        self.assertTrue(r.get("verified"), r)
        self.assertEqual(list((r.get("evidence") or {}).get("dispatched") or []),
                         [round(see["coords"][str(idx)]["x"]),
                          round(see["coords"][str(idx)]["y"])],
                         f"dispatch disagrees with see's centre: {r.get('evidence')}")
        self.assertEqual(_frame_title("/origins-xor-child"), "xor clicked",
                         "click did not reach the cross-origin document")


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class NestedFrame(unittest.TestCase):
    """Frame inside frame: the inner document is two layers down."""

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

    def test_inner_frame_button_is_addressable(self):
        self.tab = _open_fixture("/origins-nest-outer")
        see, (idx, button) = _wait_for_handle("button", "nested button")
        self.assertTrue(button.get("backend_node_id"),
                        f"inner-frame node lost its backend id: {button}")
        self.assertTrue(button.get("frame_id"),
                        f"inner-frame node lost its frame id: {button}")
        hint = see.get("hint") or ""
        self.assertNotIn("no backend id", hint,
                         f"note claims unaddressable lines on a page whose "
                         f"inner button is addressable: {hint}")

    def test_click_two_layers_down_lands(self):
        self.tab = _open_fixture("/origins-nest-outer")
        see, (idx, _) = _wait_for_handle("button", "nested button")
        self.assertEqual(_frame_title("/origins-nest-inner"), "nest inner")
        r = cdp_click_handle(f"[{idx}]")
        self.assertTrue(r.get("verified"), r)
        # one lookup, not a sum of levels: the receipt's origin must be the
        # inner frame's position in the TOP-LEVEL viewport (100+20, 50+30).
        origin = (r.get("evidence") or {}).get("frame", {}).get("origin") or {}
        self.assertAlmostEqual(origin.get("x", -1), 120.0, delta=1.0,
                               msg=f"frame origin x wrong: {origin}")
        self.assertAlmostEqual(origin.get("y", -1), 80.0, delta=1.0,
                               msg=f"frame origin y wrong: {origin}")
        self.assertEqual(_frame_title("/origins-nest-inner"), "inner clicked",
                         "click did not reach the two-levels-down document")


class HintCountsLines(unittest.TestCase):
    """The note's number must be about what the reader can see.

    Hermetic (no browser): raw AX nodes are handed to serialize() directly,
    including bidless nodes that never become a line. Counting those was the
    0.13.3 behaviour and the reason the note overstated the damage.
    """

    def _node(self, nid, role, name, bid=None, parent=None):
        n = {"nodeId": nid, "role": {"type": "role", "value": role},
             "name": {"type": "value", "value": name}}
        if bid is not None:
            n["backendDOMNodeId"] = bid
        if parent is not None:
            n["parentId"] = parent
        return n

    def test_only_printed_lines_are_counted(self):
        nodes = [
            self._node("1", "RootWebArea", "top", bid=1),
            # a structural node inside the frame that never becomes a line
            dict(self._node("2", "none", "", bid=None, parent="1"), ignored=True),
            # a visible line inside the frame with no backend id
            self._node("3", "StaticText", "orphan text", bid=None, parent="1"),
            # a visible, addressable line inside the frame
            self._node("4", "link", "ok link", bid=9, parent="1"),
        ]
        ser = ax_tree.serialize(nodes, frame_nodeids={"2", "3", "4"})
        self.assertEqual(len(ser["lines"]), 3)          # ignored node never prints
        self.assertEqual(ser["frame_lines_without_handle"], 1,
                         "the count must be over printed lines: one line "
                         "('orphan text') lacks a backend id, the bidless "
                         "structural node never becomes a line")

    def test_main_frame_lines_are_not_counted_as_frame_lines(self):
        nodes = [self._node("1", "RootWebArea", "top", bid=1),
                 self._node("2", "StaticText", "main text", bid=None, parent="1")]
        self.assertEqual(ax_tree.serialize(nodes)["frame_lines_without_handle"], 0)
        self.assertEqual(
            ax_tree.serialize(nodes, frame_nodeids={"2"})["frame_lines_without_handle"], 1)

    def test_internal_node_id_does_not_leak(self):
        nodes = [self._node("1", "RootWebArea", "top", bid=1)]
        ser = ax_tree.serialize(nodes)
        self.assertNotIn("_node_id", ser["nodes"][0])
        self.assertEqual(ser["sha256"], ax_tree.serialize(nodes)["sha256"])


if __name__ == "__main__":
    unittest.main()
