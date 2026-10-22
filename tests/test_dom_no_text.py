"""0.13.3 — an empty top-level body is not a blank page.

Measured 2026-10-22 on a page whose whole content lives in an <iframe>:
cdp_see(kind=dom) returned

    {"error": "empty page (CSR?)", "hint": "try render-wait", verified: false,
     evidence: {"reason": "cdp_dom returned neither url nor title"}}

i.e. it dropped url/title it could have read and blamed the page ("CSR?") for
hand's own not looking inside the frame. The a11y backend on the same page read
the frame content fine.

The fix keeps the receipt honest in three places:
  · url / title are always reported — they were readable
  · `reason` names the real cause, including the child-frame count
  · emitted.dom says emitted:false with reason "no_text", not "not_requested"
    (nobody asked vs. there is nothing at this level are different statements)
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.receipt import text_channel
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

_PARENT = """<!doctype html><html><head><title>Frame Only</title></head>
<body style="margin:0">
  <iframe src="/domframe-inner" style="width:600px;height:300px;border:0"></iframe>
</body></html>"""

_INNER = """<!doctype html><html><head><title>Inner Text</title></head>
<body style="margin:0;padding:8px"><p>text that lives inside the frame</p></body></html>"""

PATHS = {"/domframe-parent": _PARENT, "/domframe-inner": _INNER}

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
            if _js("location.pathname") == path:
                break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{path} never loaded in tab {tab['id']}")
    return tab


class EmptyTextChannelReason(unittest.TestCase):
    """The receipt layer must be able to say 'there is nothing here' — a state
    distinct from 'you did not ask for it'."""

    def test_no_text_is_its_own_reason(self):
        ch = text_channel(None, reason="no_text")
        self.assertFalse(ch["emitted"])
        self.assertEqual(ch["reason"], "no_text")

    def test_default_stays_not_requested(self):
        self.assertEqual(text_channel(None)["reason"], "not_requested")

    def test_router_maps_snapshot_reason_into_the_channel(self):
        from hand.router import _emitted_for
        blk = _emitted_for("cdp_snapshot", {"reason": "no text at the top level"})
        self.assertEqual(blk["dom"]["reason"], "no_text")
        ok = _emitted_for("cdp_snapshot", {"text": "hi", "chars": 2})
        self.assertTrue(ok["dom"]["emitted"])
        self.assertEqual(ok["dom"]["count"], 2)


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class DomOnFrameOnlyPage(unittest.TestCase):
    def setUp(self):
        self.tab = None

    def tearDown(self):
        if not self.tab:
            return
        try:
            if len(list_pages()) > 1:
                import urllib.request
                from hand.perception.cdp_core import CDP_HOST
                req = urllib.request.Request(
                    f'{CDP_HOST}/json/close/{self.tab["id"]}', method="PUT")
                urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass

    def test_dom_names_the_frame_instead_of_blaming_the_page(self):
        self.tab = _open_fixture("/domframe-parent")
        r = router.route_see(kind="dom")

        self.assertNotIn("empty page (CSR?)", repr(r),
                         f"the old misdiagnosis is back: {r}")
        self.assertEqual(r.get("url"), _FX.url("/domframe-parent"), r)
        self.assertEqual(r.get("page_title"), "Frame Only", r)
        self.assertTrue(r.get("verified"), r)
        self.assertEqual(r.get("text_chars"), 0, r)
        self.assertEqual(r.get("frames"), 1, r)
        self.assertIn("child frame", r.get("reason") or "", r)
        self.assertEqual((r.get("emitted") or {}).get("channels", {})
                         .get("dom", {}).get("reason"), "no_text", r)

    def test_a11y_still_reads_the_frame_content_on_the_same_page(self):
        """The point of the fix: dom says 'it is in a frame', a11y shows it."""
        self.tab = _open_fixture("/domframe-parent")
        a = router.route_see(kind="a11y")
        self.assertTrue(a.get("verified"), a)
        self.assertIn("text that lives insi", a.get("tree") or "")


if __name__ == "__main__":
    unittest.main()
