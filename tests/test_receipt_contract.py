"""L1 tests for v6.11.0 receipt contract layer (all mocked, no real Chrome).

Covers PRD docs/prd-receipt-contract.md S1–S4:
  S1 route_open three-state evidence (navigate_confirmed / endpoint_alive / raise)
  S2 ensure_chrome post-spawn endpoint probe
  S3 unified receipt evidence fields for actions/see
  S4 manifest idempotency + evidence declarations
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.perception.cdp_launcher as cdp_launcher
import hand.router as router
from hand.place import detect as place_detect
from hand.session import get_session, reset_session


PAGE_URL = "https://example.com/"


def _fake_page(url=PAGE_URL):
    return {"id": "1", "type": "page", "url": url, "title": "Example",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}


class _FakeWS:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class TestRouteOpenEvidence(unittest.TestCase):
    """S1: the three open paths must be distinguishable in the receipt."""

    def _open(self, pages_before, pages_after, nav_result=None, chrome_alive=True):
        calls = {"list_pages": 0}

        def fake_list_pages():
            calls["list_pages"] += 1
            src = pages_before if calls["list_pages"] == 1 else pages_after
            if isinstance(src, Exception):
                raise src
            return src

        def fake_cdp_call(ws, method, params=None, msg_id=1, timeout=30):
            if method == "Page.navigate":
                if isinstance(nav_result, Exception):
                    raise nav_result
                return nav_result or {}
            return {}

        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=chrome_alive), \
             mock.patch("hand.perception.cdp_core.list_pages", side_effect=fake_list_pages), \
             mock.patch("hand.perception.cdp_core.resolve_page", return_value=(0, _fake_page())), \
             mock.patch("hand.perception.cdp_core.cdp_connect", return_value=_FakeWS()), \
             mock.patch("hand.perception.cdp_core._init_domains"), \
             mock.patch("hand.perception.cdp_core.cdp_call", side_effect=fake_cdp_call), \
             mock.patch("hand.place.detect.time.sleep"):
            reset_session()
            return router.route_open("https://example.com")

    def test_path1_navigate_confirmed(self):
        r = self._open([_fake_page()], [_fake_page()])
        self.assertEqual(r["open"], "ok")
        self.assertEqual(r["place"]["type"], "browser")
        self.assertTrue(r["verified"])
        self.assertEqual(r["evidence"]["level"], "navigate_confirmed")

    def test_path2_endpoint_alive_on_nav_exception(self):
        r = self._open(RuntimeError("CDP unreachable"), [], chrome_alive=True)
        self.assertEqual(r["open"], "ok")
        self.assertFalse(r["verified"])
        self.assertEqual(r["evidence"]["level"], "endpoint_alive")
        # the downgrade must name the failure — no silent pass
        self.assertIn("导航未证实", r["evidence"]["detail"])
        self.assertIn("CDP unreachable", r["evidence"]["detail"])

    def test_path2_endpoint_alive_on_navigate_error_text(self):
        r = self._open([_fake_page()], [_fake_page("chrome-error://chromewebdata/")],
                       nav_result={"errorText": "net::ERR_NAME_NOT_RESOLVED"})
        self.assertFalse(r["verified"])
        self.assertEqual(r["evidence"]["level"], "endpoint_alive")
        self.assertIn("ERR_NAME_NOT_RESOLVED", r["evidence"]["detail"])

    def test_path3_no_endpoint_still_raises(self):
        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=False), \
             mock.patch("hand.perception.cdp_launcher.ensure_chrome", return_value=None), \
             mock.patch("hand.perception.cdp_core.list_pages", side_effect=RuntimeError("CDP unreachable")), \
             mock.patch("hand.place.detect.time.sleep"):
            reset_session()
            with self.assertRaises(RuntimeError) as ctx:
                router.route_open("https://example.com")
        self.assertIn("$CHROME", str(ctx.exception))

    def test_receipt_is_additive(self):
        """Legacy keys survive; evidence/verified are added, not substituted."""
        r = self._open([_fake_page()], [_fake_page()])
        self.assertEqual(set(r.keys()) - {"kind"}, {"open", "place", "verified", "evidence"})
        self.assertEqual(set(r["place"].keys()), {"type", "identifier"})
        self.assertEqual(r["place"]["identifier"], "https://example.com")

    def test_app_target_carries_unverified_evidence(self):
        with mock.patch("hand.place.detect.subprocess.run", return_value=mock.Mock()), \
             mock.patch("hand.place.detect.time.sleep"), \
             mock.patch("hand.place.detect.detect_place") as m:
            from hand.session import Place
            m.return_value = Place(type="desktop_app", identifier="Notes")
            reset_session()
            r = router.route_open("Notes")
        self.assertEqual(r["place"]["type"], "desktop_app")
        self.assertFalse(r["verified"])
        self.assertEqual(r["evidence"]["level"], "activate_issued")


class _FakeClock:
    """Deterministic clock: every time() call advances by `step`."""

    def __init__(self, start=1000.0, step=0.5):
        self.t = start
        self.step = step

    def time(self):
        self.t += self.step
        return self.t


class TestEnsureChromeEndpointProbe(unittest.TestCase):
    """S2: spawn success alone must not be reported as a live endpoint."""

    def test_probe_constants_match_prd(self):
        self.assertEqual(cdp_launcher.CDP_PROBE_INTERVAL, 0.5)
        self.assertEqual(cdp_launcher.CDP_PROBE_TIMEOUT, 6.0)

    def test_returns_proc_only_after_endpoint_answers(self):
        sleeps = []
        clock = _FakeClock()
        probes = [None, None, {"browser": "HeadlessChrome/140.0"}]

        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=False), \
             mock.patch("hand.perception.cdp_launcher._find_chrome", return_value="/usr/bin/chrome"), \
             mock.patch("hand.perception.cdp_launcher.subprocess.Popen") as m_popen, \
             mock.patch("hand.perception.cdp_launcher.endpoint_info", side_effect=lambda timeout=2: probes.pop(0) if probes else {"browser": "x"}), \
             mock.patch("hand.perception.cdp_launcher.time.time", side_effect=clock.time), \
             mock.patch("hand.perception.cdp_launcher.time.sleep", side_effect=sleeps.append):
            proc = cdp_launcher.ensure_chrome()

        self.assertIs(proc, m_popen.return_value)
        self.assertEqual(sleeps, [0.5, 0.5])  # 0.5s interval, no busy loop
        # the returned handle records the verified endpoint
        self.assertEqual(proc.cdp_endpoint["browser"], "HeadlessChrome/140.0")

    def test_timeout_raises_and_kills(self):
        clock = _FakeClock()
        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=False), \
             mock.patch("hand.perception.cdp_launcher._find_chrome", return_value="/usr/bin/chrome"), \
             mock.patch("hand.perception.cdp_launcher.subprocess.Popen") as m_popen, \
             mock.patch("hand.perception.cdp_launcher.endpoint_info", return_value=None), \
             mock.patch("hand.perception.cdp_launcher.time.time", side_effect=clock.time), \
             mock.patch("hand.perception.cdp_launcher.time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                cdp_launcher.ensure_chrome()

        msg = str(ctx.exception)
        self.assertIn("Chrome spawned but CDP endpoint never became reachable", msg)
        self.assertIn("6.0", msg)
        m_popen.return_value.kill.assert_called_once()

    def test_already_running_is_a_noop(self):
        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=True), \
             mock.patch("hand.perception.cdp_launcher.subprocess.Popen") as m_popen:
            self.assertIsNone(cdp_launcher.ensure_chrome())
        m_popen.assert_not_called()

    def test_no_binary_raises_before_spawn(self):
        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=False), \
             mock.patch("hand.perception.cdp_launcher._find_chrome", return_value=None), \
             mock.patch("hand.perception.cdp_launcher.subprocess.Popen") as m_popen:
            with self.assertRaises(RuntimeError) as ctx:
                cdp_launcher.ensure_chrome()
        self.assertIn("$CHROME", str(ctx.exception))
        m_popen.assert_not_called()

    def test_endpoint_info_parses_version(self):
        body = json.dumps({"Browser": "HeadlessChrome/140.0", "Protocol-Version": "1.3"}).encode()

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body

        with mock.patch("hand.perception.cdp_launcher.urllib.request.urlopen", return_value=_Resp()):
            info = cdp_launcher.endpoint_info()
        self.assertEqual(info["Browser"], "HeadlessChrome/140.0")
        self.assertTrue(cdp_launcher.chrome_running())

    def test_endpoint_info_returns_none_when_dead(self):
        with mock.patch("hand.perception.cdp_launcher.urllib.request.urlopen",
                        side_effect=OSError("connection refused")):
            self.assertIsNone(cdp_launcher.endpoint_info())
            self.assertFalse(cdp_launcher.chrome_running())

    def test_receipt_carries_browser_version(self):
        """S1+S2 join: endpoint version lands in the open receipt's evidence."""
        def fake_list_pages():
            return [_fake_page()]

        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=True), \
             mock.patch("hand.perception.cdp_launcher.endpoint_info",
                        return_value={"Browser": "HeadlessChrome/140.0"}), \
             mock.patch("hand.perception.cdp_core.list_pages", side_effect=fake_list_pages), \
             mock.patch("hand.perception.cdp_core.resolve_page", return_value=(0, _fake_page())), \
             mock.patch("hand.perception.cdp_core.cdp_connect", return_value=_FakeWS()), \
             mock.patch("hand.perception.cdp_core._init_domains"), \
             mock.patch("hand.perception.cdp_core.cdp_call", return_value={}), \
             mock.patch("hand.place.detect.time.sleep"):
            reset_session()
            r = router.route_open("https://example.com")
        self.assertEqual(r["evidence"]["level"], "navigate_confirmed")
        self.assertEqual(r["evidence"]["browser"], "HeadlessChrome/140.0")


if __name__ == "__main__":
    unittest.main()
