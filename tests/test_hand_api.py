"""L1 tests for hand 0.8.0 S1 — the Python face (code mode).

PRD docs/prd-0.8-code-mode.md S1. No browser: the router seam is mocked, so
these tests pin the *face contract* (shape, field order, teaching errors,
singleton persistence), not the CDP behaviour underneath it (that is L2/L3).

Covers:
  - top-level exports: `import hand; hand.open/see/do` and `from hand import hand`
  - global singleton Browser: lazy, survives across calls, resettable
  - receipt normalization: every call answers {"ok": bool, ...} in one shape
  - deterministic serialization: fixed field order, stable across runs
  - teaching errors: a failure says what to do next ([idx] / selector= forms)
  - [idx] handles stay resolvable across calls
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand
from hand import hand as face


def _a11y_receipt(**over):
    r = {
        "method": "cdp_a11y", "format": "a11y-v2", "page_index": 0,
        "header": "#p0 r:1 Beings | https://beings.town/",
        "url": "https://beings.town/", "page_title": "Beings Town",
        "tree": '- RootWebArea "Beings Town" [1]\n  - link "Sign in" [2]',
        "nodes": [{"idx": 1, "role": "RootWebArea", "name": "Beings Town"},
                  {"idx": 2, "role": "link", "name": "Sign in",
                   "backend_node_id": 105, "interactive": True}],
        "handles": {"2": {"role": "link", "name": "Sign in", "backend_node_id": 105,
                          "interactive": True, "x": 10, "y": 20}},
        "coords": {"2": {"x": 10, "y": 20}}, "hint": None,
        "root_role": "RootWebArea", "node_count": 2, "raw_node_count": 15,
        "curated_node_count": 13, "line_count": 2, "serialized_bytes": 45,
        "max_lines": 600, "truncated": False, "nodes_omitted": 0, "sha256": "abc",
        "ax_version": {"product": "Chrome/141.0.0", "protocol": "1.3"},
        "verified": True, "evidence": {"backend": "cdp_a11y", "verified": True,
                                       "node_count": 2},
    }
    r.update(over)
    return r


class TestExports(unittest.TestCase):
    def setUp(self):
        face.reset()

    def test_package_level_exports(self):
        for name in ("open", "see", "do"):
            self.assertTrue(callable(getattr(hand, name)), name)

    def test_submodule_face_is_importable(self):
        from hand import hand as f
        self.assertTrue(callable(f.open))
        self.assertTrue(callable(f.see))
        self.assertTrue(callable(f.do))

    def test_face_browser_is_lazy_and_singleton(self):
        b1 = face.browser()
        b2 = face.browser()
        self.assertIs(b1, b2)
        self.assertFalse(b1.opened)          # lazy: no browser touched yet

    def test_reset_gives_a_fresh_singleton(self):
        b1 = face.browser()
        face.reset()
        self.assertIsNot(face.browser(), b1)

    def test_exports_route_through_the_singleton(self):
        b = face.browser()
        with mock.patch.object(b, "do", return_value={"ok": True}) as m:
            hand.do("click [2]")
        m.assert_called_once()
        self.assertEqual(m.call_args[0][0], "click [2]")


class TestOpen(unittest.TestCase):
    def setUp(self):
        face.reset()

    def test_open_normalizes_to_ok_true(self):
        raw = {"open": "ok", "place": {"type": "browser", "identifier": "https://beings.town/"},
               "verified": True,
               "evidence": {"level": "navigate_confirmed", "detail": "hit host",
                            "browser": "HeadlessChrome/151"}}
        with mock.patch("hand.router.route_open", return_value=raw):
            r = face.open("https://beings.town/")
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "open")
        self.assertNotIn("open", r)                  # 归一：no more "open": "ok"
        self.assertEqual(r["place"]["type"], "browser")
        self.assertTrue(r["verified"])
        self.assertIsNone(r["error"])
        self.assertEqual(r["evidence"]["level"], "navigate_confirmed")

    def test_open_marks_unverified_navigation_with_a_hint(self):
        raw = {"open": "ok", "place": {"type": "browser", "identifier": "x"},
               "verified": False,
               "evidence": {"level": "endpoint_alive", "detail": "nav not confirmed"}}
        with mock.patch("hand.router.route_open", return_value=raw):
            r = face.open("https://beings.town/")
        self.assertTrue(r["ok"])
        self.assertFalse(r["verified"])
        self.assertIn("endpoint_alive", r["hint"])

    def test_open_failure_is_a_receipt_not_an_exception(self):
        with mock.patch("hand.router.route_open",
                        side_effect=RuntimeError("no chrome binary found — set $CHROME")):
            r = face.open("https://beings.town/")
        self.assertFalse(r["ok"])
        self.assertIn("no chrome binary", r["error"])
        self.assertIn("$CHROME", r["hint"])

    def test_open_without_url_teaches(self):
        r = face.open()
        self.assertFalse(r["ok"])
        self.assertIn("hand.open(url)", r["hint"])


class TestSee(unittest.TestCase):
    def setUp(self):
        face.reset()

    def test_see_returns_the_tree_and_handles(self):
        with mock.patch("hand.router.route_see", return_value=_a11y_receipt()):
            r = face.see()
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "see")
        self.assertEqual(r["kind"], "a11y")          # actual channel, not the arg
        self.assertEqual(r["method"], "cdp_a11y")
        self.assertIn("RootWebArea", r["tree"])
        self.assertEqual(r["handles"]["2"]["name"], "Sign in")
        self.assertFalse(r["truncated"])
        self.assertEqual(r["nodes_omitted"], 0)

    def test_see_kind_is_passed_through_and_reported(self):
        dom = {"method": "cdp_snapshot", "url": "https://x/", "page_title": "X",
               "text": "hi", "chars": 2, "verified": True,
               "evidence": {"backend": "cdp_snapshot", "verified": True}}
        with mock.patch("hand.router.route_see", return_value=dom) as m:
            r = face.see(kind="dom")
        self.assertEqual(m.call_args[1].get("kind"), "dom")
        self.assertEqual(r["kind"], "dom")

    def test_see_failure_is_a_receipt_with_a_hint(self):
        raw = {"error": "cdp_a11y failed: RuntimeError: no pages", "verified": False,
               "evidence": {"verified": False, "reason": "no pages"}}
        with mock.patch("hand.router.route_see", return_value=raw):
            r = face.see()
        self.assertFalse(r["ok"])
        self.assertIn("no pages", r["error"])
        self.assertIn("hand.open", r["hint"])

    def test_handles_survive_across_calls(self):
        # The disk handle map is pinned empty: a real snapshot on the dev box
        # must not decide this test.
        with mock.patch("hand.router.route_see", return_value=_a11y_receipt()), \
             mock.patch("hand.perception.ax_tree.load_handle_map", return_value={}):
            face.see()
            self.assertEqual(face.handles()["2"]["name"], "Sign in")
            entry = face.resolve("[2]")
            self.assertEqual(entry["backend_node_id"], 105)
            self.assertIn("error", face.resolve("[99]"))

    def test_truncation_is_declared_in_the_face_receipt(self):
        with mock.patch("hand.router.route_see",
                        return_value=_a11y_receipt(truncated=True, nodes_omitted=57)):
            r = face.see()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["nodes_omitted"], 57)


class TestDoGrammar(unittest.TestCase):
    """The action grammar is the protocol: one table, no surprises.

    click/scroll go through the router (same path as MCP cdp_click/cdp_scroll);
    type goes straight to the focus backends (same path as MCP cdp_type).
    """

    def setUp(self):
        face.reset()

    def _do(self, action, raw=None, **kw):
        raw = raw if raw is not None else {"method": "cdp_click", "result": "ok",
                                           "verified": True, "evidence": {}}
        with mock.patch("hand.router.route_do", return_value=raw) as routed, \
             mock.patch("hand.action.cdp_act.cdp_type_focused", return_value=raw) as typed, \
             mock.patch("hand.action.cdp_act.cdp_type_handle", return_value=raw) as typed_h:
            r = face.do(action, **kw)
        return r, routed, typed, typed_h

    def test_handle_click_goes_through_the_router(self):
        _, routed, _, _ = self._do("click [15]")
        self.assertEqual(routed.call_args[0][0], "[15]")

    def test_selector_prefix_is_stripped_for_the_router(self):
        _, routed, _, _ = self._do("click selector=a.login")
        self.assertEqual(routed.call_args[0][0], "a.login")

    def test_text_prefix_is_passed_through(self):
        _, routed, _, _ = self._do("click text=Sign in")
        self.assertEqual(routed.call_args[0][0], "text=Sign in")

    def test_xy_equals_becomes_the_router_syntax(self):
        _, routed, _, _ = self._do("click xy=100,200")
        self.assertEqual(routed.call_args[0][0], "xy:100,200")

    def test_bare_target_is_a_click(self):
        _, routed, _, _ = self._do("[15]")
        self.assertEqual(routed.call_args[0][0], "[15]")

    def test_bare_target_with_spaces_stays_a_selector(self):
        _, routed, _, _ = self._do("div.card > a.more")
        self.assertEqual(routed.call_args[0][0], "div.card > a.more")

    def test_type_without_handle_types_into_focus(self):
        _, routed, typed, typed_h = self._do("type hello world")
        self.assertFalse(routed.called)
        self.assertFalse(typed_h.called)
        self.assertEqual(typed.call_args[0][0], "hello world")

    def test_type_with_handle_focuses_then_types(self):
        _, _, typed, typed_h = self._do("type [3] hello")
        self.assertFalse(typed.called)
        self.assertEqual(typed_h.call_args[0], ("[3]", "hello"))

    def test_scroll_routes_to_the_router(self):
        _, routed, _, _ = self._do("scroll down")
        self.assertEqual(routed.call_args[0][0], "scroll down")

    def test_receipt_reports_verb_and_target(self):
        r, _, _, _ = self._do("click [15]")
        self.assertEqual(r["verb"], "click")
        self.assertEqual(r["target"], "[15]")

    def test_type_receipt_reports_its_target(self):
        r, _, _, _ = self._do("type [3] hello")
        self.assertEqual(r["verb"], "type")
        self.assertEqual(r["target"], "[3]")
        self.assertIsNone(r["expect"])

    def test_empty_action_is_rejected_with_the_table(self):
        r, routed, _, _ = self._do("")
        self.assertFalse(r["ok"])
        self.assertIn("click [15]", r["hint"])
        self.assertFalse(routed.called)

    def test_click_without_a_target_is_rejected(self):
        r, routed, _, _ = self._do("click")
        self.assertFalse(r["ok"])
        self.assertIn("target", r["error"].lower())
        self.assertFalse(routed.called)

    def test_type_without_text_is_rejected(self):
        r, _, typed, _ = self._do("type")
        self.assertFalse(r["ok"])
        self.assertIn("click", r["hint"].lower())
        self.assertFalse(typed.called)

    def test_scroll_without_direction_is_rejected(self):
        r, routed, _, _ = self._do("scroll sideways")
        self.assertFalse(r["ok"])
        self.assertIn("scroll", r["hint"])
        self.assertFalse(routed.called)


class TestTeachingErrors(unittest.TestCase):
    """错误消息即文档: a failure must name the next move."""

    def setUp(self):
        face.reset()

    def _do_failing(self, raw):
        with mock.patch("hand.router.route_do", return_value=raw), \
             mock.patch("hand.action.cdp_act.cdp_click_do", return_value=raw):
            return face.do("click selector=a.foo")

    def test_selector_miss_points_at_idx_handles(self):
        r = self._do_failing({"error": "selector did not match any element: 'a.foo'",
                              "verified": False, "selector": "a.foo",
                              "evidence": {"verified": False,
                                           "reason": "selector did not match any element"}})
        self.assertFalse(r["ok"])
        self.assertIn("[idx]", r["hint"])
        self.assertIn("selector=", r["hint"])
        self.assertIn("a.foo", r["error"])

    def test_stale_handle_points_at_see_again(self):
        r = self._do_failing({"error": "handle [99] not in the last AX snapshot (3 handles)",
                              "verified": False, "handle": "[99]",
                              "evidence": {"verified": False, "reason": "stale handle"}})
        self.assertIn("see()", r["hint"])

    def test_no_focus_points_at_clicking_the_field_first(self):
        r = self._do_failing({"error": "no focused element (activeElement is BODY)",
                              "verified": False, "text": "hi",
                              "evidence": {"verified": False, "reason": "no focus"}})
        self.assertIn("click", r["hint"].lower())

    def test_no_place_points_at_open(self):
        r = self._do_failing({"error": "no place — call route_open first"})
        self.assertIn("hand.open", r["hint"])

    def test_hint_is_none_when_the_action_succeeded(self):
        raw = {"method": "cdp_click", "result": "ok", "verified": True,
               "evidence": {"element": 'A "Sign in"'}}
        with mock.patch("hand.router.route_do", return_value=raw):
            r = face.do("click [2]")
        self.assertTrue(r["ok"])
        self.assertIsNone(r["hint"])


class TestSerializationContract(unittest.TestCase):
    """The face is the future protocol boundary: stable shape, stable order."""

    def setUp(self):
        face.reset()

    def test_field_order_is_fixed(self):
        with mock.patch("hand.router.route_see", return_value=_a11y_receipt()):
            r = face.see()
        keys = list(r)
        self.assertEqual(keys[:5], ["ok", "action", "kind", "method", "url"])

    def test_dumps_are_byte_identical_across_calls(self):
        with mock.patch("hand.router.route_see", return_value=_a11y_receipt()):
            a = face.see()
            b = face.see()
        self.assertEqual(json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False))

    def test_every_action_answers_the_same_skeleton(self):
        with mock.patch("hand.router.route_open",
                        return_value={"open": "ok", "place": {"type": "browser",
                                                              "identifier": "u"},
                                      "verified": True, "evidence": {"level": "x"}}), \
             mock.patch("hand.router.route_see", return_value=_a11y_receipt()), \
             mock.patch("hand.router.route_do",
                        return_value={"method": "cdp_click", "result": "ok",
                                      "verified": True, "evidence": {}}):
            receipts = [face.open("https://beings.town/"), face.see(), face.do("click [2]")]
        for r in receipts:
            for key in ("ok", "action", "error", "hint", "verified", "evidence"):
                self.assertIn(key, r)
            self.assertIsInstance(r["ok"], bool)

    def test_no_timestamps_in_the_payload(self):
        with mock.patch("hand.router.route_see", return_value=_a11y_receipt()):
            r = face.see()
        self.assertNotIn("ts", r)
        self.assertNotIn("timestamp", r)


class TestHelp(unittest.TestCase):
    def test_help_documents_the_action_table(self):
        text = face.help()
        for token in ("click [15]", "selector=", "text=", "xy=", "type", "scroll",
                      "expect="):
            self.assertIn(token, text, token)

    def test_help_is_also_a_receipt_shape(self):
        r = face.help(as_receipt=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "help")
        self.assertIn("actions", r)


class TestClose(unittest.TestCase):
    def setUp(self):
        face.reset()

    def test_close_reports_the_visible_pages(self):
        # chrome_running is pinned: a live Chrome on the dev box must not decide
        # this test (0.7 lesson — test hygiene beats environment luck).
        with mock.patch("hand.perception.cdp_core.list_pages",
                        return_value=[{"id": "1", "type": "page", "url": "u",
                                       "title": "t", "webSocketDebuggerUrl": "ws://x"}]), \
             mock.patch("hand.perception.cdp_core.cdp_connect",
                        side_effect=RuntimeError("no socket in a unit test")), \
             mock.patch("hand.perception.cdp_launcher.chrome_running",
                        return_value=False):
            r = face.close(timeout=0.1)
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "close")

    def test_close_is_safe_when_no_browser_is_running(self):
        with mock.patch("hand.perception.cdp_core.list_pages",
                        side_effect=RuntimeError("connection refused")), \
             mock.patch("hand.perception.cdp_launcher.chrome_running",
                        return_value=False):
            r = face.close(timeout=0.1)
        self.assertFalse(r["ok"])
        self.assertIn("error", r)


class TestExpect(unittest.TestCase):
    """S2: `expect=` — bounded wait on world state, reported separately.

    The action verdict (verified/evidence) and the world verdict (expect.met)
    are two different claims; these tests pin both, and pin that neither
    collapses into the other.
    """

    def setUp(self):
        face.reset()
        self._interval = mock.patch("hand.hand.EXPECT_POLL_INTERVAL", 0.02)
        self._interval.start()
        self.addCleanup(self._interval.stop)

    def _do(self, action="click [15]", raw=None, states=None, **kw):
        """states: list of page states returned by successive polls."""
        raw = raw if raw is not None else {"method": "cdp_click", "result": "ok",
                                           "verified": True, "evidence": {}}
        seen = []
        queue = list(states or [])

        def fake_state(need_text=False):
            seen.append(need_text)
            if len(queue) > 1:
                return queue.pop(0)
            return queue[0] if queue else {"url": "https://x/", "title": "X"}

        with mock.patch("hand.router.route_do", return_value=raw), \
             mock.patch("hand.hand._page_state", side_effect=fake_state) as state:
            r = face.do(action, **kw)
        return r, state, seen

    def test_expect_met_immediately(self):
        r, state, _ = self._do(expect="url:/issues",
                               states=[{"url": "https://github.com/o/r/issues",
                                        "title": "Issues"}])
        self.assertTrue(r["ok"])
        self.assertEqual(r["expect"]["met"], True)
        self.assertEqual(r["expect"]["spec"], "url:/issues")
        self.assertEqual(r["expect"]["kind"], "url")
        self.assertEqual(r["expect"]["checks"], 1)
        self.assertIn("issues", r["expect"]["evidence"]["url"])
        self.assertEqual(r["expect"]["evidence"]["title"], "Issues")

    def test_expect_met_after_polling(self):
        r, _, _ = self._do(expect="url:/issues",
                           states=[{"url": "https://github.com/o/r", "title": "R"},
                                   {"url": "https://github.com/o/r", "title": "R"},
                                   {"url": "https://github.com/o/r/issues",
                                    "title": "Issues"}])
        self.assertEqual(r["expect"]["met"], True)
        self.assertEqual(r["expect"]["checks"], 3)

    def test_expect_timeout_is_reported_not_raised(self):
        r, _, _ = self._do(expect="url:/issues", timeout=0.2,
                           states=[{"url": "https://github.com/o/r", "title": "Repo"}])
        self.assertTrue(r["ok"])                      # the action did happen
        self.assertFalse(r["expect"]["met"])
        self.assertIn("issues", r["expect"]["reason"])
        self.assertEqual(r["expect"]["evidence"]["url"], "https://github.com/o/r")
        self.assertEqual(r["expect"]["evidence"]["title"], "Repo")
        self.assertLess(r["expect"]["waited_ms"], 1500)

    def test_timeout_is_bounded_by_the_parameter(self):
        r, _, _ = self._do(expect="url:/nope", timeout=0.3,
                           states=[{"url": "https://x/", "title": "X"}])
        self.assertGreaterEqual(r["expect"]["waited_ms"], 250)
        self.assertLess(r["expect"]["waited_ms"], 1500)
        self.assertEqual(r["expect"]["timeout_s"], 0.3)

    def test_no_expect_returns_immediately_and_never_reads_the_world(self):
        r, state, _ = self._do()
        self.assertIsNone(r["expect"])
        self.assertFalse(state.called)

    def test_action_verdict_and_world_verdict_are_separate(self):
        """A dispatched-but-unverified action can still meet the world state."""
        raw = {"method": "cdp_click", "result": "ok", "verified": False,
               "evidence": {"verified": False, "reason": "coordinate click: "
                                                         "dispatch-only"}}
        r, _, _ = self._do(raw=raw, expect="url:/issues",
                           states=[{"url": "https://x/issues", "title": "I"}])
        self.assertFalse(r["verified"])               # action: unconfirmed
        self.assertTrue(r["expect"]["met"])           # world: confirmed
        self.assertIn("dispatch-only", r["hint"])

    def test_failed_action_skips_the_wait(self):
        raw = {"error": "selector did not match any element: 'a.x'",
               "verified": False, "evidence": {"verified": False}}
        r, state, _ = self._do(raw=raw, expect="url:/issues")
        self.assertFalse(r["ok"])
        self.assertFalse(r["expect"]["met"])
        self.assertTrue(r["expect"]["skipped"])
        self.assertIn("action failed", r["expect"]["reason"])
        self.assertFalse(state.called)                # no 5s stall on a failed click

    def test_malformed_expect_is_a_caller_error(self):
        r, _, _ = self._do(expect="issues")           # no url:/title:/text: form
        self.assertFalse(r["ok"])
        self.assertIn("expect", r["error"])
        self.assertTrue(r["expect"]["skipped"])
        self.assertIn("url:", r["expect"]["hint"])

    def test_unknown_expect_kind_is_named(self):
        r, _, _ = self._do(expect="href:foo")
        self.assertFalse(r["ok"])
        for kind in ("url", "title", "text"):
            self.assertIn(kind, r["expect"]["hint"])

    def test_empty_expect_value_is_rejected(self):
        r, _, _ = self._do(expect="url:")
        self.assertFalse(r["ok"])
        self.assertIn("empty", r["expect"]["reason"])

    def test_url_matching_is_case_sensitive(self):
        r, _, _ = self._do(expect="url:/ISSUES",
                           states=[{"url": "https://x/issues", "title": "I"}],
                           timeout=0.1)
        self.assertFalse(r["expect"]["met"])

    def test_title_and_text_matching_ignore_case(self):
        r, _, _ = self._do(expect="title:issues",
                           states=[{"url": "https://x/", "title": "Open Issues"}])
        self.assertTrue(r["expect"]["met"])

    def test_text_expect_reads_the_page_text(self):
        r, state, seen = self._do(expect="text:Welcome",
                                  states=[{"url": "https://x/", "title": "X",
                                           "text": "Welcome aboard"}])
        self.assertTrue(r["expect"]["met"])
        self.assertEqual(seen, [True])                # need_text=True

    def test_expect_on_type_actions(self):
        raw = {"method": "cdp_type", "result": "ok", "verified": True,
               "evidence": {"focus": "INPUT#q"}}
        with mock.patch("hand.action.cdp_act.cdp_type_focused", return_value=raw), \
             mock.patch("hand.hand._page_state",
                        return_value={"url": "https://x/?q=hello", "title": "X"}):
            r = face.do("type hello", expect="url:q=hello")
        self.assertTrue(r["expect"]["met"])
        self.assertEqual(r["verb"], "type")

    def test_expect_field_is_always_in_the_skeleton(self):
        r, _, _ = self._do()
        self.assertIn("expect", r)
        self.assertIsNone(r["expect"])

    def test_help_documents_expect(self):
        text = face.help()
        self.assertIn("expect=", text)
        self.assertIn("met", text)


if __name__ == "__main__":
    unittest.main()
