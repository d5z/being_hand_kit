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


# ── Read side: the open receipt must carry "whose", not only "how much" ──────
#
# 2026-10-27. `open` already reported how much it had proved (level) but never
# whose endpoint it proved it on, so "I spawned this browser" and "an endpoint
# was already answering and I attached to it" produced the same receipt. That is
# the same shape as the close-side bug this file was written for, one door over:
# the fact about ownership existed (written at birth) but was not read at the
# reuse point, so the reading could not name the object it was reading.

import unittest.mock as mock  # noqa: E402

from hand.place.detect import open_place, get_open_evidence  # noqa: E402
from hand.perception import cdp_launcher, cdp_core  # noqa: E402


class OpenOriginTest(unittest.TestCase):
    """origin (spawned/attached) and owner (mine/stranger/unknown) reach the receipt."""

    def _open(self, running, owner, url="https://example.test/"):
        # `running` is either a fixed answer or a sequence (spawn path: nothing
        # answers first, the spawn answers afterwards).
        if isinstance(running, list):
            cm = mock.patch.object(cdp_launcher, "chrome_running",
                                   side_effect=list(running))
        else:
            cm = mock.patch.object(cdp_launcher, "chrome_running",
                                   return_value=running)
        with cm, \
             mock.patch.object(cdp_launcher, "ensure_chrome", return_value=None), \
             mock.patch.object(cdp_launcher, "owner_status", return_value=owner), \
             mock.patch.object(cdp_core, "list_pages",
                               side_effect=RuntimeError("no pages to navigate")):
            return open_place(url)

    def test_attaching_to_an_unrecorded_endpoint_is_named_as_such(self):
        place = self._open(True, {"owner": "unknown", "reason": "no spawn record",
                                  "record": None})
        ev = get_open_evidence(place)
        self.assertEqual(ev.get("origin"), "attached")
        self.assertEqual(ev.get("owner", {}).get("state"), "unknown")
        self.assertEqual(ev.get("owner", {}).get("reason"), "no spawn record")
        # Naming the stranger must not upgrade the verdict: navigation still
        # failed, so the level is still the downgrade.
        self.assertEqual(ev.get("level"), "endpoint_alive")
        self.assertFalse(ev.get("verified"))

    def test_attaching_to_a_recycled_owner_is_named_stranger(self):
        place = self._open(True, {"owner": "stranger",
                                  "reason": "pid was recycled (start time differs)",
                                  "record": {"pid": 4242}})
        ev = get_open_evidence(place)
        self.assertEqual(ev.get("origin"), "attached")
        self.assertEqual(ev.get("owner", {}).get("state"), "stranger")
        self.assertEqual(ev.get("owner", {}).get("pid"), 4242)

    def test_spawning_reads_back_mine(self):
        # First call: nothing answers → we spawn. Second: the spawn is up.
        place = self._open([False, True], {"owner": "mine", "record": {"pid": 99},
                                           "cmdline_checked": True})
        ev = get_open_evidence(place)
        self.assertEqual(ev.get("origin"), "spawned")
        self.assertEqual(ev.get("owner", {}).get("state"), "mine")
        self.assertTrue(ev.get("owner", {}).get("cmdline_checked"))

    def test_route_open_surfaces_origin_without_a_new_top_level_field(self):
        from hand.router import route_open
        with mock.patch.object(cdp_launcher, "chrome_running", return_value=True), \
             mock.patch.object(cdp_launcher, "owner_status",
                               return_value={"owner": "unknown", "record": None}), \
             mock.patch.object(cdp_core, "list_pages",
                               side_effect=RuntimeError("no pages to navigate")):
            receipt = route_open("https://example.test/")
        self.assertEqual(receipt.get("open"), "ok")
        self.assertEqual(receipt.get("evidence", {}).get("origin"), "attached")
        self.assertEqual(receipt.get("evidence", {}).get("owner", {}).get("state"),
                         "unknown")


# ── The machine's ownership fact must not be a test's side effect ───────────
#
# 2026-10-27. The record written by `record_owner()` is what a later close reads
# to decide whether the browser on :9222 is ours — it is a production fact, and
# it cannot be reconstructed afterwards. Two tests that fake a spawn (a stub
# Popen with pid=4242) were writing that fake record into the real file, so this
# machine came to hold a spawn record for a browser nobody ever started. These
# tests pin the isolation at the only place that cannot be forgotten: the
# package import (tests/__init__.py).

class MachineRecordIsolationTest(unittest.TestCase):

    def test_owner_file_is_redirected_under_test(self):
        from hand.perception.cdp_launcher import _owner_file, OWNER_FILE
        self.assertNotEqual(_owner_file(), OWNER_FILE,
                            "a test run must not answer to the machine's real "
                            "spawn history")
        self.assertIn("hand-test-owner-", _owner_file())

    def test_record_owner_does_not_touch_the_machine_file(self):
        from hand.perception.cdp_launcher import (record_owner, _owner_file,
                                                  OWNER_FILE)

        class _Proc:
            pid = os.getpid()

        before = os.path.exists(OWNER_FILE)
        record_owner(_Proc(), "/usr/bin/true")
        self.assertTrue(os.path.exists(_owner_file()))
        self.assertEqual(os.path.exists(OWNER_FILE), before,
                         "record_owner() wrote the real ~/.hand-cdp-owner.json")

    def test_a_faked_spawn_leaves_the_machine_file_alone(self):
        """The exact shape that leaked: fake Popen + real ensure_chrome()."""
        from hand.perception import cdp_launcher
        before = os.path.exists(cdp_launcher.OWNER_FILE)

        class _Proc:
            pid = 4242

            def kill(self):
                pass

        with mock.patch.object(cdp_launcher, "chrome_running", return_value=False), \
             mock.patch.object(cdp_launcher, "_find_chrome", return_value="/usr/bin/google-chrome"), \
             mock.patch.object(cdp_launcher, "endpoint_info",
                               return_value={"Browser": "Chrome/141.0.0"}), \
             mock.patch.object(cdp_launcher.subprocess, "Popen",
                               return_value=_Proc()):
            cdp_launcher.ensure_chrome()

        self.assertEqual(os.path.exists(cdp_launcher.OWNER_FILE), before,
                         "a faked spawn wrote a spawn record for the real machine")
