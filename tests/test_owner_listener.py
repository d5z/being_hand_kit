"""0.13.8 — the record names the *listener*, not the pid we spawned.

Why: Chrome re-execs. Neuromancer measured it on macOS (2026-10-27, hand 0.13.5):
the pid `Popen` returned was alive when written and gone seconds later, with the
port held by a different pid and the launcher reparented. A record built on the
spawn pid then describes a dead process, so every later check answers "not mine"
about our own browser — and close refuses, leaving a browser nobody can close.

Identity here is (port + profile directory), which survives a re-exec; the pid is
a clue about the birth. These tests pin: the listener is found, it is accepted
only when its argv names *this install's* profile, and a record whose pid died is
reclaimed from the listener rather than declared a stranger.

Hermetic — subprocess and the process table are mocked.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hand.perception import cdp_launcher as L  # noqa: E402


class ListenerDiscoveryTest(unittest.TestCase):
    def test_ss_output_yields_the_listening_pid(self):
        out = ('LISTEN 0 511 127.0.0.1:9222 0.0.0.0:* '
               'users:(("chrome",pid=4242,fd=99))\n')
        run = mock.Mock(return_value=mock.Mock(stdout=out))
        with mock.patch.object(L.subprocess, "run", run):
            pid, how = L._listener_pid(timeout=0)
        self.assertEqual((pid, how), (4242, "ss"))

    def test_lsof_is_the_fallback_when_ss_is_absent(self):
        def run(cmd, **kw):
            if cmd[0] == "ss":
                raise FileNotFoundError("no ss here")
            return mock.Mock(stdout="5150\n")
        with mock.patch.object(L.subprocess, "run", side_effect=run):
            pid, how = L._listener_pid(timeout=0)
        self.assertEqual((pid, how), (5150, "lsof"))

    def test_no_answer_is_not_nobody_listening(self):
        """(None, None) means 'could not find out' — the caller must not read it
        as 'the port is free'."""
        with mock.patch.object(L.subprocess, "run", return_value=mock.Mock(stdout="")):
            self.assertEqual(L._listener_pid(timeout=0), (None, None))

    def test_unreadable_argv_is_not_a_no(self):
        with mock.patch.object(L, "_proc_cmdline", return_value=None):
            self.assertIsNone(L._cmdline_has(1234, "/prof"))


class RecordNamesTheListenerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hand-owner-listener-")
        self._old = os.environ.get("HAND_CDP_OWNER_FILE")
        os.environ["HAND_CDP_OWNER_FILE"] = os.path.join(self.tmp, "owner.json")
        self.profile = "/tmp/hand-prof-ours"
        self._p = mock.patch.object(L, "profile_dir", return_value=self.profile)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        if self._old is None:
            os.environ.pop("HAND_CDP_OWNER_FILE", None)
        else:
            os.environ["HAND_CDP_OWNER_FILE"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spawn(self, pid=1000):
        return mock.Mock(pid=pid)

    def test_listener_with_our_profile_is_recorded_as_the_identity(self):
        argv = ["chrome", f"--user-data-dir={self.profile}",
                "--remote-debugging-port=9222"]
        with mock.patch.object(L, "_proc_cmdline", return_value=argv), \
             mock.patch.object(L, "_listener_pid", return_value=(4242, "ss")), \
             mock.patch.object(L, "_proc_start_ticks", return_value=77):
            rec = L.record_owner(self._spawn(1000), "/usr/bin/chrome")
        self.assertEqual(rec["pid"], 4242)
        self.assertEqual(rec["pid_source"], "listener")
        self.assertEqual(rec["spawn_pid"], 1000)
        self.assertEqual(rec["listener_via"], "ss")
        self.assertTrue(rec["listener_profile_match"])

    def test_listener_with_another_profile_is_not_ours(self):
        argv = ["chrome", "--user-data-dir=/tmp/somebody-else",
                "--remote-debugging-port=9222"]
        with mock.patch.object(L, "_proc_cmdline", return_value=argv), \
             mock.patch.object(L, "_listener_pid", return_value=(4242, "ss")), \
             mock.patch.object(L, "_proc_start_ticks", return_value=77):
            rec = L.record_owner(self._spawn(1000), "/usr/bin/chrome")
        self.assertEqual(rec["pid"], 1000)          # the spawn pid, unverified
        self.assertEqual(rec["pid_source"], "spawn")
        self.assertIs(rec["listener_profile_match"], False)

    def test_no_listener_falls_back_to_the_spawn_pid_and_says_so(self):
        with mock.patch.object(L, "_listener_pid", return_value=(None, None)), \
             mock.patch.object(L, "_proc_start_ticks", return_value=77):
            rec = L.record_owner(self._spawn(1000), "/usr/bin/chrome")
        self.assertEqual(rec["pid"], 1000)
        self.assertEqual(rec["pid_source"], "spawn")
        self.assertIsNone(rec["listener_via"])


class ReexecReclaimTest(unittest.TestCase):
    """The recorded pid is dead; the browser is alive under another pid."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hand-reclaim-")
        self._old = os.environ.get("HAND_CDP_OWNER_FILE")
        os.environ["HAND_CDP_OWNER_FILE"] = os.path.join(self.tmp, "owner.json")
        self.profile = "/tmp/hand-prof-ours"
        self._p = mock.patch.object(L, "profile_dir", return_value=self.profile)
        self._p.start()
        with mock.patch.object(L, "_proc_start_ticks", return_value=11):
            L.record_owner(mock.Mock(pid=1000), "/usr/bin/chrome",
                           claim_listener=False)

    def tearDown(self):
        self._p.stop()
        if self._old is None:
            os.environ.pop("HAND_CDP_OWNER_FILE", None)
        else:
            os.environ["HAND_CDP_OWNER_FILE"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _status(self, listener_argv, listener=(4242, "ss")):
        with mock.patch.object(L, "_pid_alive", return_value=False), \
             mock.patch.object(L, "_listener_pid", return_value=listener), \
             mock.patch.object(L, "_proc_cmdline", return_value=listener_argv):
            return L.owner_status()

    def test_dead_pid_with_our_listener_is_still_mine(self):
        st = self._status(["chrome", f"--user-data-dir={self.profile}",
                           "--remote-debugging-port=9222"])
        self.assertEqual(st["owner"], "mine")
        self.assertEqual(st["pid_source"], "listener")
        self.assertEqual(st["listener_pid"], 4242)
        self.assertIn("re-exec", st["reason"])

    def test_dead_pid_with_a_stranger_listener_stays_stranger(self):
        st = self._status(["chrome", "--user-data-dir=/tmp/somebody-else",
                           "--remote-debugging-port=9222"])
        self.assertEqual(st["owner"], "stranger")
        self.assertIn("not alive", st["reason"])

    def test_dead_pid_with_nobody_listening_stays_stranger(self):
        st = self._status(None, listener=(None, None))
        self.assertEqual(st["owner"], "stranger")

    def test_unreadable_listener_argv_does_not_claim_mine(self):
        """No evidence is not consent: an unreadable argv cannot make it ours."""
        st = self._status(None)
        self.assertEqual(st["owner"], "stranger")


if __name__ == "__main__":
    unittest.main()
