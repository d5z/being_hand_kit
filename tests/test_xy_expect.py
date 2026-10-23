"""L2 (real Chrome) for hand 0.13.7 — xy with a declared target, and no
verdict when the document changes under the point.

Before 0.13.7 a coordinate click could not be wrong: `landed` was set from the
*pre-dispatch* reading of "who is under this point", which answers a different
question from "who received the event", and says nothing at all once the page
navigated.

What is pinned here, on a real page:

  * `@expect=<selector>` turns a coordinate into a judgeable click:
    self/descendant → landed true; other/ancestor → landed false
  * a bare `xy:` (no declared target) reports the receiver and never invents a
    hit/miss
  * the point-owner is read again *after* dispatch
  * a navigation during dispatch yields landed=None with `navigated: true` —
    not a true, not a false
  * an out-of-viewport point is refused before anything is dispatched

Skipped (never red) when no browser can be brought up.
"""

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action.cdp_act import cdp_click_do
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains,
    _write_last, _element_info, CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

FIXTURE_HTML = """<!doctype html><html><head><title>xy expect</title></head>
<body style="margin:0">
  <div id="other" style="position:absolute;left:0;top:0;width:400px;height:80px;
       background:#eee" onclick="record('other')">other area</div>
  <button id="target" style="position:absolute;left:0;top:100px;width:200px;
       height:60px" onclick="record('target')">Target Button</button>
  <a id="nav" href="/xy-other" style="position:absolute;left:0;top:200px;
       width:200px;height:40px;display:block">go elsewhere</a>
  <script>window.clicks=[];function record(w){window.clicks.push(w);}</script>
</body></html>"""

OTHER_HTML = """<!doctype html><html><head><title>elsewhere</title></head>
<body><h1>Elsewhere</h1></body></html>"""

PATHS = {"/xy-expect": FIXTURE_HTML, "/xy-other": OTHER_HTML}

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
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])
            if _js("location.pathname") == path:
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


def _point(selector):
    """Physical-px centre of `selector`, the same space `xy:` speaks."""
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        info = _element_info(ws, selector)
    finally:
        ws.close()
    assert "error" not in info, info
    return int(round(info["x"])), int(round(info["y"]))


def _clicks():
    return json.loads(_js("JSON.stringify(window.clicks||[])"))


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class XYExpect(unittest.TestCase):

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

    def test_declared_target_hit_is_true(self):
        self.tab = _open_fixture("/xy-expect")
        x, y = _point("#target")
        r = cdp_click_do("xy:%d,%d @expect=#target" % (x, y))
        self.assertEqual(r["landed"], True, r)
        self.assertEqual(r["hit_relation"], "self", r)
        self.assertIn("declared target", r["landed_source"])
        self.assertEqual(_clicks(), ["target"], "receipt says hit, page disagrees")

    def test_declared_target_miss_is_false(self):
        """Point over another element while claiming #target: a real negative."""
        self.tab = _open_fixture("/xy-expect")
        x, y = _point("#other")
        r = cdp_click_do("xy:%d,%d @expect=#target" % (x, y))
        self.assertEqual(r["landed"], False, r)
        self.assertIn(r["hit_relation"], ("other", "ancestor"), r)
        self.assertEqual(_clicks(), ["other"], _clicks())

    def test_bare_coordinate_reports_receiver_and_invents_nothing(self):
        self.tab = _open_fixture("/xy-expect")
        x, y = _point("#target")
        r = cdp_click_do("xy:%d,%d" % (x, y))
        self.assertIsNone(r["hit_relation"], r)
        self.assertEqual(r["landed"], True, r)
        self.assertIn("post-dispatch", r["landed_source"])
        self.assertEqual((r["element_at_point_after"] or {}).get("tag"), "BUTTON", r)
        self.assertEqual(_clicks(), ["target"])

    def test_navigation_during_dispatch_has_no_verdict(self):
        """点链接跳走：同一坐标在新文档里指别的东西——不给 true 也不给 false。"""
        self.tab = _open_fixture("/xy-expect")
        x, y = _point("#nav")
        r = cdp_click_do("xy:%d,%d @expect=#nav" % (x, y))
        self.assertIs(r["navigated"], True, r)
        self.assertIsNone(r["landed"], r)
        self.assertIn("navigated", r["landed_source"])
        self.assertTrue(_js("location.pathname").endswith("/xy-other"))

    def test_out_of_viewport_is_refused(self):
        self.tab = _open_fixture("/xy-expect")
        r = cdp_click_do("xy:99999,99999 @expect=#target")
        self.assertFalse(r["verified"], r)
        self.assertIn("outside viewport", r["error"])
        self.assertEqual(_clicks(), [], "a refused point still dispatched")

    def test_unknown_declared_target_dispatches_nothing(self):
        self.tab = _open_fixture("/xy-expect")
        x, y = _point("#target")
        r = cdp_click_do("xy:%d,%d @expect=#does-not-exist" % (x, y))
        self.assertFalse(r["verified"], r)
        self.assertIn("not found", r["error"])
        self.assertEqual(_clicks(), [], "resolved the target after dispatching")

    def test_xy_at_img_prefix_is_accepted(self):
        """0.11.0 wrote the syntax down; 0.13.7 makes it parse."""
        self.tab = _open_fixture("/xy-expect")
        x, y = _point("#target")
        r = cdp_click_do("xy@img:deadbeef:%d,%d @expect=#target" % (x, y))
        self.assertEqual(r["xy"], [x, y], r)
        self.assertEqual(r["landed"], True, r)
        self.assertIn("deadbeef", r["evidence"]["frame_ref"])


if __name__ == "__main__":
    unittest.main()
