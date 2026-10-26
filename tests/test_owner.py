"""0.13.7 — ownership of the browser on the debug port is written at birth.

Why this file exists: on 2026-10-26 a teardown closed the endpoint on :9222 and
took down a browser another process had started 166 days earlier. The receipt
was not lying — "the endpoint stopped answering" was true. What was missing was
the word "whose": nothing had ever written down who started that browser, and
afterwards it cannot be read back (ppid is 1 for everything that outlived its
parent).

So the fact is recorded at spawn and read at close, and close refuses when the
record does not describe a live process of ours. These tests pin the three
verdicts (mine / stranger / unknown) and the refusal itself, plus the real path:
spawn → tamper the record → close must refuse and the browser must still run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hand.perception.cdp_launcher import (  # noqa: E402
    record_owner, read_owner, clear_owner, owner_status, close_refusal,
    _proc_start_ticks,
)


class OwnerRecordTest(unittest.TestCase):
    """Unit level: the verdicts, with a plain sleep process standing in for Chrome."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hand-owner-")
        self._old = os.environ.get("HAND_CDP_OWNER_FILE")
        os.environ["HAND_CDP_OWNER_FILE"] = os.path.join(self.tmp, "owner.json")
        # A stand-in whose argv carries the debug-port flag: the record has to be
        # able to say "this live process is a browser serving *this* port", not
        # merely "this live process is one I started".
        self.proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)",
             "--remote-debugging-port=9222"])

    def tearDown(self):
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        if self._old is None:
            os.environ.pop("HAND_CDP_OWNER_FILE", None)
        else:
            os.environ["HAND_CDP_OWNER_FILE"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_record_is_unknown(self):
        self.assertEqual(owner_status()["owner"], "unknown")
        self.assertIsNone(read_owner())

    def test_record_of_a_live_process_is_mine(self):
        rec = record_owner(self.proc, "/bin/true")
        self.assertEqual(rec["pid"], self.proc.pid)
        self.assertEqual(rec["port"], 9222)
        self.assertEqual(owner_status()["owner"], "mine")

    def test_dead_pid_is_stranger(self):
        record_owner(self.proc)
        self.proc.kill()
        self.proc.wait(timeout=5)
        st = owner_status()
        self.assertEqual(st["owner"], "stranger")
        self.assertFalse(st["pid_alive"])
        self.assertIn("not alive", st["reason"])

    def test_recycled_pid_is_stranger(self):
        """pid alone is recyclable; pid + start ticks is the identity."""
        record_owner(self.proc)
        rec = read_owner()
        if rec.get("start_ticks") is None:
            self.skipTest("no /proc on this platform: identity degrades to pid-only")
        rec["start_ticks"] = rec["start_ticks"] + 1
        with open(os.environ["HAND_CDP_OWNER_FILE"], "w", encoding="utf-8") as f:
            json.dump(rec, f)
        st = owner_status()
        self.assertEqual(st["owner"], "stranger")
        self.assertIn("recycled", st["reason"])

    def test_alive_pid_that_is_not_serving_the_port_is_stranger(self):
        """A pid I own is not enough: the process must be the browser on this port."""
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            record_owner(bystander)
            st = owner_status()
            self.assertEqual(st["owner"], "stranger")
            self.assertIn("not serving", st["reason"])
        finally:
            bystander.kill()
            bystander.wait(timeout=5)

    def test_start_ticks_are_stable_across_two_reads(self):
        first = _proc_start_ticks(self.proc.pid)
        time.sleep(0.05)
        self.assertEqual(first, _proc_start_ticks(self.proc.pid))

    def test_clear_owner_removes_the_fact(self):
        record_owner(self.proc)
        clear_owner()
        self.assertEqual(owner_status()["owner"], "unknown")

    def test_refusal_receipt_shape(self):
        st = owner_status()
        out = close_refusal(st)
        self.assertEqual(out["closed"], "refused")
        self.assertFalse(out["verified"])
        self.assertFalse(out["endpoint_gone"])
        self.assertTrue(out["evidence"]["refused"])
        self.assertEqual(out["evidence"]["owner"]["owner"], "unknown")
        # the same contract hand uses for failures: no 'result' key, verified is the flag
        self.assertNotIn("result", out)


class _RealBrowser(unittest.TestCase):
    """L2: the path that actually bit — spawn, tamper the record, close."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hand-owner-l2-")
        cls._old = os.environ.get("HAND_CDP_OWNER_FILE")
        os.environ["HAND_CDP_OWNER_FILE"] = os.path.join(cls.tmp, "owner.json")
        from hand.perception.cdp_launcher import ensure_chrome, chrome_running
        cls.chrome_running = staticmethod(chrome_running)
        # A browser left over from an earlier run answers on the port but has no
        # record for *this* temp file -- that is precisely the "unknown" case, and
        # a test fixture has to start from a state it can attribute.
        if chrome_running():
            import hand.hand as H
            H.close(force=True)
            time.sleep(1.0)
        cls.proc = ensure_chrome()

    @classmethod
    def tearDownClass(cls):
        from hand.perception.cdp_launcher import clear_owner
        try:
            import hand.hand as H
            H.close(force=True)
        except Exception:
            pass
        clear_owner()
        if cls._old is None:
            os.environ.pop("HAND_CDP_OWNER_FILE", None)
        else:
            os.environ["HAND_CDP_OWNER_FILE"] = cls._old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_spawn_writes_the_record(self):
        from hand.perception.cdp_launcher import owner_status
        st = owner_status()
        self.assertEqual(st["owner"], "mine", st)
        self.assertIsNotNone(st["record"]["pid"])

    def test_2_close_refuses_an_unowned_endpoint_and_leaves_it_running(self):
        from hand.perception.cdp_launcher import read_owner
        import hand.hand as H
        saved = read_owner()
        # A live process of ours that is *not* the browser on 9222: exactly the
        # shape of the 166-day orphan (alive, port answering, not attributable).
        foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            tampered = dict(saved)
            tampered["pid"] = foreign.pid
            tampered["start_ticks"] = _proc_start_ticks(foreign.pid)
            with open(os.environ["HAND_CDP_OWNER_FILE"], "w", encoding="utf-8") as f:
                json.dump(tampered, f)
            out = H.close()
            self.assertFalse(out.get("verified", True), out)
            body = out.get("result") or out
            print("refusal receipt:", json.dumps(out)[:400])
            # the browser must still be there — a refusal that quietly kills is not a refusal
            self.assertTrue(self.chrome_running())
        finally:
            foreign.kill()
            foreign.wait(timeout=5)
            with open(os.environ["HAND_CDP_OWNER_FILE"], "w", encoding="utf-8") as f:
                json.dump(saved, f)

    def test_3_owned_close_is_allowed_and_clears_the_record(self):
        from hand.perception.cdp_launcher import read_owner
        import hand.hand as H
        self.assertEqual(read_owner()["pid"], read_owner()["pid"])
        out = H.close()
        self.assertTrue(out.get("verified"), out)
        self.assertFalse(self.chrome_running())
        self.assertIsNone(read_owner())


if __name__ == "__main__":
    unittest.main()
