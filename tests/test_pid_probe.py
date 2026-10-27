"""Does the pid exist? Three answers, because the probe fails in three ways (2026-10-27).

`os.kill(pid, 0)` was wrapped as

    try: os.kill(int(pid), 0); return True
    except Exception: return False

so **EPERM read as "not alive"**. EPERM is the kernel refusing the *signal*, not
refusing the *enumeration* — it is positive evidence that the pid exists. On any
machine where sync once ran as root, or where another user's chrome sits on the
profile, `owner_status()` reported `pid_alive: False` about a live browser: the
receipt claiming a fact it did not have.

Same shape Neuromancer was forced to split into gone/exited/eperm/unknown on his
installer tonight. The difference between his defect and mine is only the layer
the collapse lives at — and which side the collapsed value lands on.

Cells: EPERM → exists (was: gone); ESRCH → gone; other failure → unknown, and
"unknown" must not be reported as "gone" downstream.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hand.perception import cdp_launcher as L  # noqa: E402


class PidProbeTest(unittest.TestCase):
    def _probe(self, exc):
        kill = mock.Mock(side_effect=exc)
        with mock.patch.object(L.os, "kill", kill):
            return L._pid_state(4242), L._pid_alive(4242)

    def test_eperm_is_positive_evidence_of_existence(self):
        # ★ 有分辨力的那一格：修前这里返回 False（= 不在），现在返回 eperm/True。
        st, alive = self._probe(PermissionError(1, "Operation not permitted"))
        self.assertEqual(st, "eperm")
        self.assertIs(alive, True, "EPERM 被读成了「不在」—— 回执会说一件它没有的事")

    def test_esrch_is_gone(self):
        st, alive = self._probe(ProcessLookupError(3, "No such process"))
        self.assertEqual(st, "gone")
        self.assertIs(alive, False)

    def test_another_failure_is_unknown_not_gone(self):
        # 探针自己出错，不等于对象不在。OSError 之外的类型（int() 抛的异常）也算。
        st, alive = self._probe(OSError(5, "Input/output error"))
        self.assertEqual(st, "unknown")
        self.assertIs(alive, None, "判不了被读成「不在」= 同一个错换了个异常类")

    def test_success_is_alive(self):
        st, alive = self._probe(None)
        self.assertEqual(st, "alive")
        self.assertIs(alive, True)


class OwnerStatusThreeWayTest(unittest.TestCase):
    """判不了不许落进「不在」那一支。"""

    REC = {"pid": 4242, "profile": "/tmp/prof", "start_ticks": 12345}

    def _status(self, alive, reclaim):
        with mock.patch.object(L, "read_owner", return_value=dict(self.REC)), \
             mock.patch.object(L, "_pid_alive", return_value=alive), \
             mock.patch.object(L, "_reclaim_by_profile", return_value=reclaim):
            return L.owner_status()

    def test_indeterminate_probe_does_not_become_stranger(self):
        st = self._status(None, (None, None, "no-listener"))
        self.assertEqual(st["owner"], "unknown")
        self.assertIsNone(st["pid_alive"])
        self.assertIn("no evidence", st["reason"])
        self.assertNotIn("not alive", st["reason"])

    def test_indeterminate_probe_still_accepts_our_listener(self):
        st = self._status(None, (5150, "ss", None))
        self.assertEqual(st["owner"], "mine")
        self.assertEqual(st["listener_pid"], 5150)
        self.assertEqual(st["pid_state"], "unknown")

    def test_really_gone_still_says_gone(self):
        st = self._status(False, (None, None, "no-listener"))
        self.assertEqual(st["owner"], "stranger")
        self.assertIn("not alive", st["reason"])


if __name__ == "__main__":
    unittest.main()
