"""Unit tests for the hand/plan module: parser, engine, prompts, session, router.

Run with: python3 tests/run_tests.py
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hand.plan.parser import parse_events, Step
from hand.plan.engine import PlanningEngine
from hand.plan.prompts import (
    _build_prompt, _goal_met, _last_summary,
    HAND_PLANNER_SYSTEM_PROMPT,
)
from hand.session import Session, get_session, reset_session


# ── Parser ──────────────────────────────────────────────────────────

class TestParseEvents(unittest.TestCase):

    def test_parse_empty(self):
        self.assertEqual(parse_events(''), [])

    def test_parse_single_see(self):
        steps = parse_events('{"step": "see"}')
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].kind, 'see')

    def test_parse_open_do_see_done_sequence(self):
        lines = [
            '{"step": "open", "action": "Notes"}',
            '{"step": "see"}',
            '{"step": "do", "action": "Cmd+N"}',
            '{"step": "see"}',
            '{"step": "done", "summary": "Created a new note."}',
            '{"step": "do", "action": "ignored"}',
        ]
        steps = parse_events('\n'.join(lines))
        self.assertEqual(len(steps), 5)
        self.assertEqual(steps[0].kind, 'open')
        self.assertEqual(steps[0].action, 'Notes')
        self.assertEqual(steps[4].kind, 'done')
        # nothing after "done" matters
        self.assertNotIn('ignored', [s.action for s in steps])

    def test_parse_skips_non_json_lines(self):
        lines = [
            "opencode 1.18.13",
            '{"step": "see"}',
            "some stray log line",
        ]
        steps = parse_events('\n'.join(lines))
        self.assertEqual([s.kind for s in steps], ['see'])

    def test_parse_from_opencode_data_text_event(self):
        ev = {'type': 'text', 'data': {'text': '{"step": "do", "action": "type hello"}'}}
        steps = parse_events(json.dumps(ev))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].kind, 'do')
        self.assertEqual(steps[0].action, 'type hello')

    def test_parse_from_assistant_message_part(self):
        ev = {'type': 'assistant_message', 'part': {
            'type': 'text', 'text': '{"step": "open", "action": "https://example.com"}'}}
        steps = parse_events(json.dumps(ev))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].action, 'https://example.com')

    def test_parse_error_step(self):
        steps = parse_events('{"step": "error", "action": "boom"}')
        self.assertEqual(steps[0].kind, 'error')
        self.assertEqual(steps[0].action, 'boom')

    def test_step_dataclass(self):
        s = Step(kind='see', raw={'source': 'test'})
        self.assertEqual(s.kind, 'see')
        self.assertEqual(s.raw['source'], 'test')
        self.assertEqual(s.action, '')


# ── Engine ──────────────────────────────────────────────────────────

class TestPlanningEngine(unittest.TestCase):

    def test_engine_no_binary(self):
        engine = PlanningEngine(opencode_bin=None)
        result = engine.plan('test goal')
        self.assertFalse(result.ok)
        self.assertIn('opencode binary not found', result.error)

    def test_build_prompt_includes_system_goal_context(self):
        prompt = _build_prompt('写个笔记', {'text': 'hello'})
        self.assertIn('hand-planner', prompt)
        self.assertIn('写个笔记', prompt)
        self.assertIn('text: hello', prompt)

    def test_build_cmd_shape(self):
        engine = PlanningEngine(opencode_bin='/fake/opencode',
                                agent='hand-planner', model='opencode/deepseek-v4-flash')
        cmd = engine._build_cmd('goal here')
        self.assertEqual(cmd[0], '/fake/opencode')
        self.assertEqual(cmd[1], 'run')
        self.assertIn('--format', cmd)
        self.assertIn('json', cmd)
        self.assertIn('--agent', cmd)
        self.assertIn('hand-planner', cmd)
        self.assertIn('-m', cmd)
        self.assertIn('opencode/deepseek-v4-flash', cmd)
        self.assertIn('--auto', cmd)

    def test_build_cmd_uses_session_env(self):
        engine = PlanningEngine(opencode_bin='/fake/opencode')
        with mock.patch.dict(os.environ, {'OPENCODE_PLAN_SESSION': 'abc123'}):
            cmd = engine._build_cmd('x')
        self.assertIn('-s', cmd)
        self.assertIn('abc123', cmd)

    def test_goal_met(self):
        self.assertTrue(_goal_met([Step(kind='done')]))
        self.assertFalse(_goal_met([Step(kind='see'), Step(kind='do', action='x')]))

    def test_last_summary(self):
        steps = [
            Step(kind='see'),
            Step(kind='done', raw={'summary': 'all good'}),
        ]
        self.assertEqual(_last_summary(steps), 'all good')


# ── Session plan_trace ─────────────────────────────────────────────

class TestSessionPlanTrace(unittest.TestCase):

    def test_plan_trace_default(self):
        self.assertEqual(Session().plan_trace, [])

    def test_clear_plan_trace(self):
        s = Session()
        s.plan_trace.append({"kind": "see"})
        self.assertEqual(len(s.plan_trace), 1)
        s.clear_plan_trace()
        self.assertEqual(s.plan_trace, [])


# ── Route plan (stubbed routes, no engine / no screen) ─────────────

class TestRoutePlan(unittest.TestCase):

    def setUp(self):
        reset_session()

    def test_route_plan_done_only(self):
        from hand.router import route_plan
        steps = [("done", "", {"step": "done", "summary": "all good"})]
        result = route_plan("test goal", steps=steps)
        self.assertEqual(result["plan"], "ok")
        self.assertEqual(result["goal"], "test goal")
        self.assertEqual(len(result["trace"]), 1)
        self.assertEqual(result["trace"][0]["kind"], "done")
        self.assertEqual(result["trace"][0]["summary"], "all good")

    def test_route_plan_unknown_step(self):
        from hand.router import route_plan
        steps = [("bogus", "x", {"step": "bogus", "action": "x"})]
        result = route_plan("bogus goal", steps=steps)
        self.assertEqual(result["trace"][0]["result"]["error"],
                         "unknown step kind: bogus")

    def test_route_plan_dispatches_in_order_with_auto_see(self):
        from hand import router
        calls = []
        with mock.patch.object(router, 'route_open',
                               side_effect=lambda a: calls.append(('open', a)) or {"ok": True}), \
             mock.patch.object(router, 'route_see',
                               side_effect=lambda: calls.append(('see', None)) or {"ok": True}), \
             mock.patch.object(router, 'route_do',
                               side_effect=lambda a: calls.append(('do', a)) or {"ok": True}):
            steps = [
                ("open", "Notes", {"step": "open", "action": "Notes"}),
                ("see", "", {"step": "see"}),
                ("do", "Cmd+N", {"step": "do", "action": "Cmd+N"}),
                ("done", "", {"step": "done", "summary": "done!"}),
                ("do", "after-done", {"step": "do", "action": "after-done"}),
            ]
            result = router.route_plan("make a note", steps=steps)

        # open → see → do → auto-see → done (after-done dropped)
        self.assertEqual(calls, [
            ('open', 'Notes'),
            ('see', None),
            ('do', 'Cmd+N'),
            ('see', None),
        ])
        kinds = [e["kind"] for e in result["trace"]]
        self.assertEqual(kinds, ["open", "see", "do", "see", "done"])
        self.assertEqual(result["trace"][-1]["summary"], "done!")

    def test_route_plan_error_step_stops(self):
        from hand import router
        with mock.patch.object(router, 'route_open',
                               side_effect=lambda a: {"ok": True}), \
             mock.patch.object(router, 'route_do',
                               side_effect=lambda a: {"ok": True}):
            steps = [
                ("open", "Notes", {"step": "open", "action": "Notes"}),
                ("error", "boom", {"step": "error", "action": "boom"}),
                ("do", "never", {"step": "do", "action": "never"}),
            ]
            result = router.route_plan("goal", steps=steps)
        kinds = [e["kind"] for e in result["trace"]]
        self.assertEqual(kinds, ["open", "error"])
        self.assertEqual(result["trace"][-1]["result"]["error"], "boom")

    def test_route_plan_catches_route_exception(self):
        from hand import router
        with mock.patch.object(router, 'route_do',
                               side_effect=RuntimeError("screen locked")):
            steps = [("do", "Cmd+N", {"step": "do", "action": "Cmd+N"})]
            result = router.route_plan("goal", steps=steps)
        self.assertEqual(result["trace"][0]["result"]["error"], "screen locked")


# ── Version ─────────────────────────────────────────────────────────

class TestVersion(unittest.TestCase):

    def test_version(self):
        import hand
        self.assertEqual(hand.__version__, "6.1.0")


if __name__ == '__main__':
    unittest.main()
