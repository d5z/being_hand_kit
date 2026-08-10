"""Tests for Tier 2 (streaming) and Tier 3 (recovery).

Run with: python3 tests/run_tests.py
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hand.plan.parser import Step
from hand.plan.stream_engine import StreamingEngine
from hand.plan.recovery import build_recovery_prompt, RECOVERY_SYSTEM_PROMPT
from hand.plan.tier2_prompts import build_stream_prompt, HAND_PLANNER_STREAM_PROMPT


# ── Tier 2: tier2_prompts ──────────────────────────────────────────

class TestBuildStreamPrompt(unittest.TestCase):

    def test_includes_goal(self):
        p = build_stream_prompt('open mail')
        self.assertIn('open mail', p)
        self.assertIn('Output your first step:', p)

    def test_includes_context(self):
        p = build_stream_prompt('do x', context={'app': 'Notes'})
        self.assertIn('app: Notes', p)


# ── Tier 2: StreamingEngine parse ──────────────────────────────────

class TestStreamingParse(unittest.TestCase):

    def setUp(self):
        self.engine = StreamingEngine(opencode_bin='/fake/opencode')

    def test_extract_step_json(self):
        s = self.engine._extract_step('{"step":"open","target":"Notes"}')
        self.assertEqual(s.kind, 'open')
        self.assertEqual(s.action, 'Notes')

    def test_extract_step_ignores_non_kind(self):
        s = self.engine._extract_step('{"step":"bogus","action":"x"}')
        self.assertIsNone(s)

    def test_extract_see_action_default(self):
        s = self.engine._extract_step('{"step":"see"}')
        self.assertEqual(s.kind, 'see')
        self.assertEqual(s.action, '')

    def test_parse_response_text_event(self):
        out = json.dumps({'type': 'text', 'part': {'text': '{"step":"see"}'}})
        step, sid = self.engine._parse_response(out)
        self.assertEqual(step.kind, 'see')
        self.assertIsNone(sid)

    def test_parse_response_with_session_id(self):
        ev1 = json.dumps({'type': 'text', 'sessionID': 'abc123',
                          'part': {'text': '{"step":"do","action":"Cmd+N"}'}})
        step, sid = self.engine._parse_response(ev1)
        self.assertEqual(step.kind, 'do')
        self.assertEqual(step.action, 'Cmd+N')
        self.assertEqual(sid, 'abc123')

    def test_parse_response_no_step_returns_none(self):
        out = json.dumps({'type': 'text', 'part': {'text': 'hello world'}})
        self.assertIsNone(self.engine._parse_response(out))


# ── Tier 2: StreamingEngine plan_stream (mocked execution) ─────────

class TestStreamingPlanFlow(unittest.TestCase):

    def setUp(self):
        self.engine = StreamingEngine(opencode_bin='/fake/opencode')
        self.engine._base_url = 'http://127.0.0.1:14096'

    def test_plan_stream_done_immediately(self):
        self.engine._send_message = mock.Mock(return_value=(
            Step(kind='done', action='all good', raw={'step': 'done', 'summary': 'all good'}),
            'sid1'))
        trace = self.engine.plan_stream('goal')
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0].step.kind, 'done')
        self.assertEqual(trace[0].result['summary'], 'all good')

    def test_plan_stream_open_see(self):
        """Mock the router methods that _execute_step calls internally."""
        responses = [
            (Step(kind='open', action='Notes', raw={'step': 'open', 'target': 'Notes'}), 'sid1'),
            (Step(kind='done', action='done', raw={'step': 'done', 'summary': 'opened'}), 'sid1'),
        ]
        self.engine._send_message = mock.Mock(side_effect=responses)
        # _execute_step imports route_open from hand.router at call time
        with mock.patch('hand.router.route_open', return_value={'ok': True, 'method': 'open'}) as m_open:
            trace = self.engine.plan_stream('open notes')
            m_open.assert_called_once_with('Notes')
        self.assertEqual([t.step.kind for t in trace], ['open', 'done'])

    def test_plan_stream_error_breaks(self):
        self.engine._send_message = mock.Mock(return_value=(
            Step(kind='error', action='boom', raw={'step': 'error', 'action': 'boom'}), 'sid1'))
        trace = self.engine.plan_stream('goal')
        self.assertEqual(trace[0].step.kind, 'error')
        self.assertEqual(trace[0].error, 'boom')

    def test_plan_stream_no_binary(self):
        e = StreamingEngine(opencode_bin=None)
        trace = e.plan_stream('goal')
        self.assertEqual(trace[0].step.kind, 'error')
        self.assertIn('binary', trace[0].error)

    def test_plan_stream_server_not_start(self):
        e = StreamingEngine(opencode_bin='/fake/opencode')
        e._base_url = None
        e.start_server = mock.Mock(return_value=False)
        trace = e.plan_stream('goal')
        self.assertEqual(trace[0].step.kind, 'error')


# ── Tier 3: build_recovery_prompt ──────────────────────────────────

class TestBuildRecoveryPrompt(unittest.TestCase):

    def test_includes_failed_step_and_goal(self):
        failed = {'kind': 'open', 'action': '/bad/path', 'raw': {'step': 'open'},
                  'result': {'error': 'no such file'}}
        trace = [
            {'kind': 'open', 'action': '/bad/path', 'result': {'error': 'no such file'}},
        ]
        p = build_recovery_prompt('open the file', failed, trace)
        self.assertIn('open the file', p)
        self.assertIn('no such file', p)
        # system prompt says 
class TestTier5Healing(unittest.TestCase):
    """Tier 5 - Proactive Self-Healing tests."""

    def setUp(self):
        from hand.session import reset_session
        reset_session()

    def test_failure_predictor_no_place(self):
        """do without place -> high risk + insert_open."""
        from hand.plan.healing import FailurePredictor
        p = FailurePredictor()
        pred = p.predict("do", "Cmd+N", place_set=False, trace=[])
        self.assertEqual(pred.risk, "high")
        self.assertEqual(pred.signal, "no_place")
        self.assertEqual(pred.healing, "insert_open")

    def test_failure_predictor_with_place(self):
        from hand.plan.healing import FailurePredictor
        p = FailurePredictor()
        pred = p.predict("do", "Cmd+N", place_set=True, trace=[])
        self.assertEqual(pred.risk, "low")

    def test_failure_predictor_unknown_kind(self):
        from hand.plan.healing import FailurePredictor
        p = FailurePredictor()
        pred = p.predict("bogus", "x", place_set=True, trace=[])
        self.assertEqual(pred.risk, "high")
        self.assertEqual(pred.signal, "unknown_kind")
        self.assertEqual(pred.healing, "skip_step")

    def test_failure_predictor_repeated_failure(self):
        from hand.plan.healing import FailurePredictor
        p = FailurePredictor()
        trace = [{"kind": "do", "action": "Cmd+N", "result": {"error": "failed"}}]
        pred = p.predict("do", "Cmd+N", place_set=True, trace=trace)
        self.assertEqual(pred.risk, "high")
        self.assertEqual(pred.signal, "repeated_failure")

    def test_healing_engine_normal_flow(self):
        from hand.plan.healing import HealingEngine
        engine = HealingEngine()
        def fe(kind, action): return {"ok": True}
        steps = [("open", "Notes", None), ("do", "Cmd+N", None), ("done", "", {})]
        r = engine.heal("test", steps, fe)
        self.assertEqual(r["plan"], "healed")
        self.assertGreaterEqual(r["heal_count"], 0)

    def test_healing_engine_skips_unknown(self):
        from hand.plan.healing import HealingEngine
        engine = HealingEngine()
        def fe(kind, action): return {"ok": True}
        steps = [("open", "Notes", None), ("bogus", "x", None), ("done", "", {})]
        r = engine.heal("test", steps, fe)
        self.assertGreaterEqual(r["heal_count"], 1)
        for p in r["predictions"]:
            if p["kind"] == "bogus":
                self.assertTrue(p["healed"])

    def test_route_plan_healing_importable(self):
        from hand.router import route_plan_healing
        self.assertTrue(callable(route_plan_healing))
        import inspect
        sig = inspect.signature(route_plan_healing)
        self.assertIn("goal", sig.parameters)

    def test_healing_engine_see_without_place(self):
        from hand.plan.healing import FailurePredictor
        p = FailurePredictor()
        pred = p.predict("see", "", place_set=False, trace=[])
        self.assertEqual(pred.risk, "high")
        self.assertEqual(pred.signal, "no_place")

if __name__ == "__main__":
    unittest.main()
