"""L2 tests for hand 0.13.5 — 一条通道的空不是世界的空。

Regression covered (measured live 2026-10-22, hand 0.13.4):

  * A click that only changes `document.title` inside a child frame really
    happened — the a11y tree shows the new name — yet `effected` came back
    `no_change`, whole-frame change ratio 0.000. Pixels cannot see a title:
    it never becomes ink.
  * The mirror case exists too: a colour change is real to a person and
    invisible to the a11y tree. A single-channel judge calls one of these two
    "nothing happened".

What this pins:
  1. title-only change (inside a frame)  → effected=changed, seen by document
  2. ink-only change (background colour) → effected=changed, seen by pixel
  3. neither moves                       → no_change, and the receipt says
     both channels looked
  4. every receipt declares, per channel, what that channel is blind to —
     so a downstream reader can tell "looked and saw nothing" from "could not
     look". A blind channel's silence is never reported as a negative.

Real headless Chrome against the repo's own fixture server; skipped (never red)
when no browser can be brought up.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action.effect import probe_action
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# The button lives in a child frame on purpose: the top document's title stays
# put, only the frame's own RootWebArea name changes. A channel that reads only
# the top document cannot see this — and that was the first cut of this fix.
FRAME_LEFT, FRAME_TOP = 60, 60
FRAME_W, FRAME_H = 360, 160

PARENT_HTML = """<!doctype html><html><head><title>chan parent</title></head>
<body style="margin:0">
  <iframe src="/chan-inner"
          style="position:absolute;left:%dpx;top:%dpx;width:%dpx;height:%dpx;border:1px solid #888">
  </iframe>
</body></html>""" % (FRAME_LEFT, FRAME_TOP, FRAME_W, FRAME_H)

INNER_HTML = """<!doctype html><html><head><title>chan inner</title></head>
<body style="margin:0;padding:20px">
  <button id="t" onclick="document.title='INNER CLICKED'"
          style="font-size:18px;padding:10px 16px">retitle me</button>
</body></html>"""

# Ink only: the background flips, nothing in the a11y tree moves.
INK_HTML = """<!doctype html><html><head><title>ink page</title></head>
<body style="margin:0">
  <div id="swatch" role="button" aria-label="swatch"
       onclick="this.style.background='#c00'"
       style="position:absolute;left:40px;top:40px;width:200px;height:120px;background:#0a0">
  </div>
  <button id="still" style="position:absolute;left:40px;top:200px">do nothing</button>
</body></html>"""

PATHS = {"/chan-parent": PARENT_HTML,
         "/chan-inner": INNER_HTML,
         "/chan-ink": INK_HTML}

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


def _open_fixture(path):
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
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
        raise AssertionError("%s never loaded in tab %s" % (path, tab["id"]))
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


def _click_idx(idx):
    """Click an [idx] handle exactly the way the cdp_click tool does."""
    return probe_action('click', lambda: router.route_do("[%d]" % idx),
                        verify=True)


class ChannelsOnRealPages(unittest.TestCase):

    def setUp(self):
        if not _CHROME:
            self.skipTest("no headless chrome available")

    def test_title_only_change_is_seen_by_the_document_channel(self):
        _open_fixture("/chan-parent")
        see = router.route_see(kind="a11y")
        btn = [n for n in see["nodes"] if n.get("role") == "button"]
        self.assertEqual(len(btn), 1, "fixture should expose exactly one button")
        self.assertEqual(btn[0]["name"], "retitle me")

        out = _click_idx(btn[0]["idx"])
        self.assertEqual(out["resolved"], True)
        self.assertEqual(out["landed"], True)

        # The click really happened — the frame's own document says so.
        self.assertEqual(_js("document.title"), "chan parent")
        ch = out["change"]["channels"]
        self.assertEqual(
            ch["document"]["verdict"], "changed",
            "the a11y tree carries the frame's new name; the document channel "
            "must see it (0.13.4 said no_change here)")
        self.assertIn("content", ch["document"]["moved"])
        # Pixels cannot see a title. That is not an error, it is a blind spot
        # the receipt is required to name.
        self.assertEqual(ch["pixel"]["verdict"], "no_change")
        self.assertEqual(out["effected"], "changed")

    def test_ink_only_change_is_seen_by_the_pixel_channel(self):
        _open_fixture("/chan-ink")
        see = router.route_see(kind="a11y")
        swatch = [n for n in see["nodes"] if n.get("name") == "swatch"]
        self.assertTrue(swatch, "fixture should expose the swatch container")
        out = _click_idx(swatch[0]["idx"])
        ch = out["change"]["channels"]
        self.assertEqual(ch["pixel"]["verdict"], "changed")
        self.assertEqual(ch["document"]["verdict"], "no_change")
        self.assertEqual(out["effected"], "changed")

    def test_click_that_changes_nothing_says_both_channels_looked(self):
        """第一次点会亮起 focus（那是真的墨迹变化），第二次什么都没有。

        拿第二次当「都看了、都没看见」的样本：同一个按钮、同一位置、
        世界确实没动。
        """
        _open_fixture("/chan-ink")
        see = router.route_see(kind="a11y")
        btn = [n for n in see["nodes"] if n.get("name") == "do nothing"]
        self.assertTrue(btn)
        _click_idx(btn[0]["idx"])          # settles focus / hover ink
        out = _click_idx(btn[0]["idx"])
        self.assertEqual(out["effected"], "no_change")
        ch = out["change"]["channels"]
        self.assertEqual(ch["pixel"]["verdict"], "no_change")
        self.assertEqual(ch["document"]["verdict"], "no_change")
        self.assertIn("both channels looked", out["change"]["reason"])

    def test_every_channel_declares_what_it_cannot_see(self):
        _open_fixture("/chan-ink")
        see = router.route_see(kind="a11y")
        btn = [n for n in see["nodes"] if n.get("role") == "button"]
        out = _click_idx(btn[0]["idx"])
        ch = out["change"]["channels"]
        self.assertIn("title", ch["pixel"]["blind_to"])
        self.assertIn("ink", ch["document"]["blind_to"])


if __name__ == "__main__":
    unittest.main()
