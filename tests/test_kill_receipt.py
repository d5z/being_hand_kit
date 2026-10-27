"""A dry run's receipt must not use the verb of the act (2026-10-27).

`kill_our_browsers(dry_run=True)` used to append candidates to `killed` and put no
`dry_run` key in the receipt, so the receipt read

    {"killed": [926864], ...}

about a browser that was never signalled. Tomorrow's reader — or a log-driven
script — cannot tell from that whether a browser died. The key was the verb of the
action; the value was a prediction.

Cells: dry_run ⇒ killed == [] and the pid lands in would_kill, dry_run echoed;
real signal ⇒ killed, would_kill empty. Mutant: put the pid back into `killed` on
the dry path ⇒ the first cell goes red, the second stays green (it never took that
branch — a cell that cannot distinguish is not evidence).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hand.perception import cdp_launcher as L  # noqa: E402

MARKER = "/tmp/hand-test-profile-xyz"


def _fake_world(pid=4242):
    """pgrep finds one pid, its argv carries MARKER, its identity is stable."""
    def run(argv, **kw):
        return mock.Mock(stdout=f"{pid}\n", returncode=0)
    return {
        "run": mock.patch.object(L.subprocess, "run", side_effect=run),
        "argv": mock.patch.object(L, "_argv_of",
                                  return_value=("ok", [f"--user-data-dir={MARKER}"])),
        "ticks": mock.patch.object(L, "_proc_start_ticks", return_value=111),
        "chain": mock.patch.object(L, "_ancestor_chain", return_value={
            "pids": [], "levels": 1, "reached_init": True,
            "truncated_at": None, "truncated_why": None}),
    }


class DryRunReceiptTest(unittest.TestCase):
    def _call(self, **kw):
        patches = _fake_world()
        with patches["run"], patches["argv"], patches["ticks"], patches["chain"]:
            kill = mock.Mock()
            with mock.patch.object(L.os, "kill", kill):
                r = L.kill_our_browsers(marker=MARKER, **kw)
        return r, kill

    def test_dry_run_never_reports_killed(self):
        r, kill = self._call(dry_run=True)
        self.assertIs(r["dry_run"], True)
        self.assertEqual(r["killed"], [], "预演报了 killed —— 回执在说一件没发生的事")
        self.assertEqual(r["would_kill"], [4242])
        self.assertEqual(r["would_kill_count"], 1)
        self.assertFalse(kill.called, "dry_run 却真的发了信号")

    def test_real_signal_reports_killed_not_would(self):
        r, kill = self._call(dry_run=False)
        self.assertIs(r["dry_run"], False)
        self.assertEqual(r["killed"], [4242])
        self.assertEqual(r["would_kill"], [])
        self.assertTrue(kill.called)


class SameKeysOnEveryPathTest(unittest.TestCase):
    """早退那条路的字段类型不能和正常路不同。"""

    def test_enumeration_failure_keeps_the_same_shape(self):
        with mock.patch.object(L.subprocess, "run", side_effect=OSError("no pgrep")):
            r = L.kill_our_browsers(marker=MARKER)
        for k in ("killed", "would_kill", "skipped", "unreadable", "gone", "reused", "excluded"):
            self.assertIsInstance(r[k], list, f"{k} 在早退路上不是列表")
        self.assertIs(r["enumerated"], False)
        self.assertIs(r["dry_run"], False)
        self.assertIn("no pgrep", r["why"])


if __name__ == "__main__":
    unittest.main()
