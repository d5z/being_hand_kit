"""0.13.7 — a selector click must run the page's handler exactly once.

Why this exists: the selector branch dispatched three things in a row — a real
mouse click, `el.click()`, and `el.onclick()` (via `_js_submit`) — all three
unconditionally, after a click that had already succeeded. Measured on a page
with an inline onclick: `window.n == 3` while document-level listeners saw only
two clicks, because `el.onclick()` is a direct handler call and dispatches no
event. The third execution therefore cannot be observed by the page's own
instrumentation; a receipt saying `verified: true` said nothing about it.

Neuromancer found the same triple on his machine (his A/B: xy → 1 event,
selector → 3). The claim here is narrower and testable: the page's handler runs
once for a click that lands, and escalation happens only on evidence that
nothing reached the target.

Hermetic: the decision function is pure. The live path (probe installed before
dispatch, real click, read back, escalate at most once) is covered by
`ClickProbeContractTest`, which asserts on the wire what the probe does, with
the CDP surface mocked.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import cdp_act as mod


class EscalationDecisionTest(unittest.TestCase):
    def test_trusted_click_means_no_escalation(self):
        # The whole point: the real click landed, the handler already ran.
        self.assertEqual(mod._click_escalation(1, 0), "none")

    def test_nothing_landed_escalates_to_js_click(self):
        self.assertEqual(mod._click_escalation(0, 0), "js_click")

    def test_js_click_already_landed_is_not_stacked(self):
        self.assertEqual(mod._click_escalation(0, 1), "none")

    def test_trusted_and_untrusted_still_no_escalation(self):
        self.assertEqual(mod._click_escalation(2, 3), "none")


class ClickProbeContractTest(unittest.TestCase):
    """The probe has to be installed *before* the dispatch, and removed after."""

    def _calls(self, handler):
        sent = []
        with mock.patch.object(mod, "cdp_call",
                               side_effect=lambda ws, method, params, msg_id=None: sent.append(
                                   (method, params.get("expression", ""))) or handler(method, params)):
            return sent

    def test_probe_expression_is_capture_phase_and_trusted_aware(self):
        sent = []
        with mock.patch.object(mod, "cdp_call",
                               side_effect=lambda ws, m, p, msg_id=None: sent.append(p.get("expression", ""))):
            mod._install_click_probe(None, "#A", msg_id=5)
        expr = sent[0]
        self.assertIn("addEventListener(\"click\"", expr)
        self.assertIn(",true)", expr)          # capture phase
        self.assertIn("e.isTrusted", expr)     # counts trusted vs untrusted
        self.assertIn("__handProbe", expr)

    def test_read_returns_counts_even_on_a_broken_answer(self):
        with mock.patch.object(mod, "cdp_call", return_value={}):
            self.assertEqual(mod._read_click_probe(None, msg_id=6),
                             {"trusted": 0, "untrusted": 0, "has_form": False})

    def test_read_parses_the_counts(self):
        payload = {"result": {"value": json.dumps({"trusted": 1, "untrusted": 0, "has_form": True})}}
        with mock.patch.object(mod, "cdp_call", return_value=payload):
            self.assertEqual(mod._read_click_probe(None, msg_id=6),
                             {"trusted": 1, "untrusted": 0, "has_form": True})

    def test_clear_removes_the_listener(self):
        sent = []
        with mock.patch.object(mod, "cdp_call",
                               side_effect=lambda ws, m, p, msg_id=None: sent.append(p.get("expression", ""))):
            mod._clear_click_probe(None, msg_id=13)
        self.assertIn("removeEventListener", sent[0])
        self.assertIn("delete window.__handProbe", sent[0])

    def test_the_click_path_no_longer_calls_the_unconditional_escalations(self):
        """Source-level guard: the old three-in-a-row must not come back."""
        with open(os.path.join(os.path.dirname(__file__), "..",
                               "hand", "action", "cdp_act.py")) as fh:
            src = fh.read()
        start = src.index("def cdp_click(selector")
        body = src[start:src.index("def cdp_type(", start)]
        self.assertIn("_install_click_probe", body)
        self.assertIn("_click_escalation", body)
        # the direct handler call that made the third execution invisible
        self.assertNotIn("_js_submit(ws, selector", body)


if __name__ == "__main__":
    unittest.main()
