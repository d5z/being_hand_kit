"""L2-hermetic: the session page is resolved by identity, not by index.

Why this file exists — a real failure, not a hypothesis. A full-suite run
reported `no text field in the handle map` while the code was actually talking
to a different page that another test had left behind. The session page was
recorded as a bare list index; closing one tab shifted every later index by one,
so the recorded index silently named someone else's tab. The reading stayed
green-shaped and the target was wrong.

Three behaviours are locked here:
  1. a recorded page is found by id even after the list has been reordered
  2. a recorded page that is gone RAISES — it never falls back to pages[0]
  3. a record written by an older build (bare index) is still usable

A fourth followed the 2026-10-26 blackout:
  4. if the record is stale but exactly ONE page is open, it heals in place
     (and keeps `healed_from`), because with a single page nothing can be
     silently substituted — while raising there was a dead end: every cdp_*
     call failed and the suggested recoveries needed the same call to work.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from hand.perception import cdp_core as core


def _page(pid, url="https://example.test/x"):
    return {"id": pid, "url": url, "title": pid, "webSocketDebuggerUrl": "ws://" + pid}


class TestSessionPageIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "last")
        self._patch = mock.patch.object(core, "_state_file", return_value=self.path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _write_raw(self, obj):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_identity_survives_reordering(self):
        # Session page recorded while it sat at index 2.
        p = [_page("a"), _page("b"), _page("target")]
        self._write_raw({"idx": 2, "id": "target", "url": p[2]["url"]})
        # A tab ahead of it closes: the same page is now at index 1.
        reordered = [_page("b"), _page("target"), _page("a")]
        idx, page = core.resolve_page(None, reordered)
        self.assertEqual(page["id"], "target")
        self.assertEqual(idx, 1)

    def test_missing_page_raises_instead_of_falling_back(self):
        self._write_raw({"idx": 1, "id": "gone", "url": "https://gone.test/"})
        pages = [_page("a"), _page("b")]
        with self.assertRaises(RuntimeError) as ctx:
            core.resolve_page(None, pages)
        msg = str(ctx.exception)
        self.assertIn("gone", msg)          # names the lost page
        self.assertIn("2 page(s)", msg)     # says what is there now

    def test_missing_page_never_returns_first_page(self):
        # The specific bug shape: index still in range, but it is a DIFFERENT tab.
        self._write_raw({"idx": 0, "id": "gone", "url": "https://gone.test/"})
        with self.assertRaises(RuntimeError):
            core.resolve_page(None, [_page("a"), _page("b")])

    def test_legacy_bare_index_still_works(self):
        self._write_raw("1")                # what an older build wrote
        idx, page = core.resolve_page(None, [_page("a"), _page("b")])
        self.assertEqual((idx, page["id"]), (1, "b"))

    def test_no_record_returns_first_page(self):
        idx, page = core.resolve_page(None, [_page("a"), _page("b")])
        self.assertEqual((idx, page["id"]), (0, "a"))

    def test_last_without_record_still_errors(self):
        with self.assertRaises(RuntimeError):
            core.resolve_page("last", [_page("a")])

    def test_write_last_records_identity(self):
        pages = [_page("a"), _page("b", "https://example.test/b")]
        with mock.patch.object(core, "list_pages", return_value=pages):
            core._write_last(1)
        st = json.loads(open(self.path, encoding="utf-8").read())
        self.assertEqual(st["id"], "b")
        self.assertEqual(st["idx"], 1)
        self.assertTrue(st["url"].startswith("https://example.test/b"))

    # ── 0.13.8: a stale record with exactly one page open heals instead of
    #    blacking out. Measured 2026-10-26: record named a page that had been
    #    closed, health stayed green, and EVERY cdp_* call raised — the message
    #    pointed at recoveries that need this same function to succeed first.
    def test_stale_record_heals_when_exactly_one_page_is_open(self):
        self._write_raw({"idx": 0, "id": "gone", "url": "https://gone.test/"})
        only = _page("only", "https://example.test/only")
        idx, page = core.resolve_page(None, [only])
        self.assertEqual((idx, page["id"]), (0, "only"))
        st = json.loads(open(self.path, encoding="utf-8").read())
        self.assertEqual(st["id"], "only")                     # record healed
        self.assertIn("example.test/only", st["url"])
        self.assertEqual(st["healed_from"]["id"], "gone")      # keeps the trace
        self.assertTrue(st["healed_from"]["url"].startswith("https://gone.test"))

    def test_healed_record_survives_a_second_call(self):
        self._write_raw({"idx": 0, "id": "gone", "url": "https://gone.test/"})
        core.resolve_page(None, [_page("only")])
        # Second call must read the healed record, not heal again.
        idx, page = core.resolve_page(None, [_page("only")])
        self.assertEqual((idx, page["id"]), (0, "only"))
        st = json.loads(open(self.path, encoding="utf-8").read())
        self.assertEqual(st["healed_from"]["id"], "gone")


if __name__ == "__main__":
    unittest.main()
