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
from hand.session import Place, get_session, reset_session


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


# ── S3: unified receipt evidence for actions / see ───────────────────

def _page():
    return [_fake_page()]


class TestActionReceipts(unittest.TestCase):
    """S3: no action may return a success-shaped receipt it cannot back."""

    def _run(self, dispatcher, fn, *args, **kwargs):
        calls = []

        def fake_cdp_call(ws, method, params=None, msg_id=1, timeout=30):
            calls.append((method, params or {}))
            return dispatcher(method, params or {})

        with mock.patch("hand.action.cdp_act.list_pages", return_value=_page()), \
             mock.patch("hand.action.cdp_act.resolve_page", return_value=(0, _fake_page())), \
             mock.patch("hand.action.cdp_act.cdp_connect", return_value=_FakeWS()), \
             mock.patch("hand.action.cdp_act._init_domains"), \
             mock.patch("hand.action.cdp_act._write_last"), \
             mock.patch("hand.action.cdp_act.cdp_call", side_effect=fake_cdp_call), \
             mock.patch("hand.perception.cdp_core.cdp_call", side_effect=fake_cdp_call):
            result = fn(*args, **kwargs)
        return result, calls

    # ── cdp_click ───────────────────────────────────────────────────

    def test_click_verified_element_evidence(self):
        def dispatcher(method, params):
            expr = params.get("expression", "")
            if "getBoundingClientRect" in expr:
                return {"result": {"value": '{"x":10,"y":20,"w":4,"h":4,"visible":true,"tag":"BUTTON","text":"Sign in"}'}}
            if "querySelector" in expr and "found" in expr:
                return {"result": {"value": '{"found":true,"tag":"BUTTON","text":"Sign in"}'}}
            return {}

        from hand.action.cdp_act import cdp_click
        r, calls = self._run(dispatcher, cdp_click, "#go")
        self.assertTrue(r["verified"])
        self.assertEqual(r["result"], "ok")
        self.assertIn("BUTTON", r["evidence"]["element"])
        self.assertIn("Sign in", r["evidence"]["element"])

    def test_click_selector_miss_errors_without_clicking(self):
        def dispatcher(method, params):
            if "found" in params.get("expression", ""):
                return {"result": {"value": '{"found":false}'}}
            return {}

        from hand.action.cdp_act import cdp_click
        r, calls = self._run(dispatcher, cdp_click, "#ghost")
        self.assertFalse(r["verified"])
        self.assertIn("selector", r["error"])
        self.assertIn("did not match", r["evidence"]["reason"])
        dispatched = [c for c in calls if c[0] == "Input.dispatchMouseEvent"]
        self.assertEqual(dispatched, [])  # no blind click

    def test_click_do_text_match_verified(self):
        def dispatcher(method, params):
            if "XPathResult" in params.get("expression", ""):
                return {"result": {"value": '{"x":5,"y":5,"tag":"A","text":"Learn more"}'}}
            return {}

        from hand.action.cdp_act import cdp_click_do
        r, _ = self._run(dispatcher, cdp_click_do, "text=Learn more")
        self.assertTrue(r["verified"])
        self.assertIn("A", r["evidence"]["element"])

    def test_click_do_xy_is_dispatch_only(self):
        from hand.action.cdp_act import cdp_click_do
        r, _ = self._run(lambda m, p: {}, cdp_click_do, "xy:412,188")
        self.assertFalse(r["verified"])
        self.assertIn("dispatch", r["evidence"]["reason"])
        self.assertEqual(r["xy"], [412, 188])

    def test_click_do_bad_xy_is_unverified(self):
        from hand.action.cdp_act import cdp_click_do
        r, _ = self._run(lambda m, p: {}, cdp_click_do, "xy:abc")
        self.assertFalse(r["verified"])
        self.assertIn("reason", r["evidence"])

    # ── cdp_type ────────────────────────────────────────────────────

    def test_type_focused_without_focus_errors(self):
        def dispatcher(method, params):
            if "activeElement" in params.get("expression", ""):
                return {"result": {"value": '{"tag":"BODY"}'}}
            return {}

        from hand.action.cdp_act import cdp_type_focused
        r, calls = self._run(dispatcher, cdp_type_focused, "hello")
        self.assertFalse(r["verified"])
        self.assertIn("no focused element", r["error"])
        inserted = [c for c in calls if c[0] == "Input.insertText"]
        self.assertEqual(inserted, [])  # nothing typed into the void

    def test_type_focused_verified_reports_target(self):
        def dispatcher(method, params):
            if "activeElement" in params.get("expression", ""):
                return {"result": {"value": '{"tag":"INPUT","id":"q","type":"search"}'}}
            return {}

        from hand.action.cdp_act import cdp_type_focused
        r, calls = self._run(dispatcher, cdp_type_focused, "hi")
        self.assertTrue(r["verified"])
        self.assertIn("INPUT", r["evidence"]["focus"])
        self.assertTrue([c for c in calls if c[0] == "Input.insertText"])

    def test_type_selector_miss_errors(self):
        def dispatcher(method, params):
            if "found" in params.get("expression", ""):
                return {"result": {"value": '{"found":false}'}}
            return {}

        from hand.action.cdp_act import cdp_type
        r, calls = self._run(dispatcher, cdp_type, "input#nope", "hi")
        self.assertFalse(r["verified"])
        self.assertEqual([c for c in calls if c[0] == "Input.insertText"], [])

    # ── cdp_scroll ──────────────────────────────────────────────────

    def test_scroll_evidence_reads_back(self):
        state = {"y": 0}

        def dispatcher(method, params):
            expr = params.get("expression", "")
            if expr == "window.scrollY || 0":
                return {"result": {"value": state["y"]}}
            if "innerHeight" in expr:
                return {"result": {"value": 800}}
            if "scrollBy" in expr or "scrollTo" in expr:
                state["y"] = 300
                return {}
            if "mouseWheel" in str(params.get("type", "")):
                state["y"] = 300
                return {}
            return {}

        from hand.action.cdp_act import cdp_scroll
        r, _ = self._run(dispatcher, cdp_scroll, "down")
        self.assertTrue(r["verified"])
        self.assertEqual(r["evidence"]["scrollY_before"], 0)
        self.assertEqual(r["evidence"]["scrollY_after"], 300)
        self.assertTrue(r["evidence"]["moved"])


class TestSeeAndShotReceipts(unittest.TestCase):
    """S3: perception receipts carry the evidence that backs them."""

    def test_see_dom_receipt_verified(self):
        reset_session()
        with mock.patch("hand.perception.cdp_snapshot.cdp_snapshot_see",
                        return_value={"method": "cdp_snapshot", "page_title": "Example",
                                      "url": "https://example.com/", "text": "hi"}):
            r = router.route_see(place=Place(type="browser", identifier="https://example.com/"))
        self.assertTrue(r["verified"])
        self.assertEqual(r["evidence"]["backend"], "cdp_snapshot")
        self.assertEqual(r["evidence"]["url"], "https://example.com/")

    def test_see_interactive_empty_map_is_unverified(self):
        reset_session()
        with mock.patch("hand.perception.cdp_snapshot.interactive_map",
                        return_value={"method": "cdp_interactive", "count": 0, "elems": []}):
            r = router.route_see(kind="interactive")
        self.assertFalse(r["verified"])
        self.assertEqual(r["evidence"]["backend"], "cdp_interactive")
        self.assertIn("0", r["evidence"]["reason"])

    def test_see_receipt_additive(self):
        reset_session()
        with mock.patch("hand.perception.cdp_network.network_snapshot",
                        return_value={"method": "cdp_network", "total_requests": 3, "requests": []}):
            r = router.route_see(kind="network")
        self.assertTrue(r["verified"])
        self.assertEqual(r["method"], "cdp_network")
        self.assertEqual(r["evidence"]["total_requests"], 3)

    def test_shot_receipt_carries_source_and_length(self):
        reset_session()
        with mock.patch("hand.perception.cdp_core.list_pages", return_value=_page()), \
             mock.patch("hand.perception.cdp_core.cdp_screenshot",
                        return_value={"data": "AAAA", "format": "png"}):
            r = router.route_screenshot(with_data=True)
        self.assertTrue(r["verified"])
        self.assertEqual(r["evidence"]["source"], "cdp")
        self.assertEqual(r["evidence"]["data_length"], 4)


# ── S4: manifest idempotency + evidence declarations ─────────────────

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "kit", "manifest.json")

# PRD S4 tables. Idempotency: what a retry does. Evidence: does the receipt
# carry a verification field at all (S3-covered = verified, rest = claimed).
EXPECTED_IDEMPOTENCY = {
    "cdp_open": "idempotent",
    "cdp_nav": "idempotent",
    "cdp_see": "idempotent",
    "cdp_shot": "idempotent",
    "cdp_scroll": "idempotent",
    "cdp_close": "idempotent",
    "cdp_type": "append",
    "cdp_click": "side_effect",
    "hand_plan": "side_effect",
    "hand_see_vlm": "idempotent",
    "health": "idempotent",
}

EXPECTED_EVIDENCE = {
    "cdp_open": "verified",
    "cdp_nav": "verified",
    "cdp_see": "verified",
    "cdp_shot": "verified",
    "cdp_scroll": "verified",
    "cdp_click": "verified",
    "cdp_type": "verified",
    "hand_plan": "claimed",
    "hand_see_vlm": "claimed",
    "cdp_close": "claimed",
    "health": "claimed",
}

IDEMPOTENCY_ENUM = {"idempotent", "append", "side_effect"}
EVIDENCE_ENUM = {"verified", "claimed"}


class TestManifestDeclarations(unittest.TestCase):
    """S4: idempotency shape must be declared, not guessed by the caller (F-4/F-5)."""

    def setUp(self):
        with open(MANIFEST_PATH) as f:
            self.manifest = json.load(f)
        self.tools = {t["name"]: t for t in self.manifest["tools"]}

    def test_every_tool_declares_idempotency_and_evidence(self):
        for name, tool in self.tools.items():
            self.assertIn("idempotency", tool, f"{name} missing idempotency")
            self.assertIn("evidence", tool, f"{name} missing evidence")
            self.assertIn(tool["idempotency"], IDEMPOTENCY_ENUM, name)
            self.assertIn(tool["evidence"], EVIDENCE_ENUM, name)

    def test_idempotency_values_match_prd(self):
        self.assertEqual({n: t["idempotency"] for n, t in self.tools.items()},
                         EXPECTED_IDEMPOTENCY)

    def test_evidence_values_match_prd(self):
        self.assertEqual({n: t["evidence"] for n, t in self.tools.items()},
                         EXPECTED_EVIDENCE)

    def test_description_declares_the_contract(self):
        self.assertIn("Receipts distinguish verified vs claimed; tools declare idempotency.",
                      self.manifest["description"])

    def test_no_tool_was_dropped_or_renamed(self):
        self.assertEqual(set(self.tools), set(EXPECTED_IDEMPOTENCY))

    def test_declared_verified_tools_actually_emit_evidence(self):
        """Cross-check: every tool declared 'verified' must have code emitting it."""
        sources = {
            "cdp_open": ("hand/router.py", "hand/place/detect.py"),
            "cdp_nav": ("hand/router.py", "hand/place/detect.py"),
            "cdp_see": ("hand/router.py",),
            "cdp_shot": ("hand/router.py",),
            "cdp_scroll": ("hand/action/cdp_act.py",),
            "cdp_click": ("hand/action/cdp_act.py",),
            "cdp_type": ("hand/action/cdp_act.py",),
        }
        root = os.path.join(os.path.dirname(__file__), "..")
        for name, files in sources.items():
            if self.tools[name]["evidence"] != "verified":
                continue
            blob = "".join(open(os.path.join(root, f)).read() for f in files)
            self.assertIn('"verified"', blob, f"{name} declared verified but no evidence field emitted")


if __name__ == "__main__":
    unittest.main()
