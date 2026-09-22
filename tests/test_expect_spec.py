"""Alignment tests for docs/expect-spec-v1.md (hand 0.9 S4).

The spec is a contract: every example in its machine-readable table is executed
here, and the verdict/failure shapes are pinned to what the document promises.
If the spec and the parser drift, these tests fail.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.hand as face

SPEC = os.path.join(os.path.dirname(__file__), "..", "docs", "expect-spec-v1.md")


def _read_spec():
    with open(SPEC, encoding="utf-8") as f:
        return f.read()


def _spec_examples():
    """Rows from the <!-- spec-examples --> table: (example, kind, value)."""
    rows = []
    inside = False
    for line in _read_spec().splitlines():
        if "spec-examples:start" in line:
            inside = True
            continue
        if "spec-examples:end" in line:
            break
        if not inside or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].startswith("---") or cells[0] == "example":
            continue
        rows.append((cells[0].strip("`").strip(),
                     cells[1].strip("`").strip(),
                     cells[2].strip("`").strip()))
    return rows


class TestSpecDocument(unittest.TestCase):
    def test_version_promise_is_written(self):
        self.assertEqual(face.EXPECT_SPEC_VERSION, "1.0")
        doc = _read_spec()
        self.assertIn("v1.0", doc)
        self.assertIn("frozen", doc.lower())
        self.assertIn("Breaking changes bump the major version", doc)

    def test_key_space_is_complete(self):
        doc = _read_spec()
        for key in ("url", "title", "text", "visual_state"):
            self.assertIn("`%s`" % key, doc)

    def test_all_five_visual_states_are_documented(self):
        doc = _read_spec()
        from hand.perception.visual_state import VISUAL_STATES
        for state in VISUAL_STATES:
            self.assertIn("visual_state:%s" % state, doc)

    def test_at_least_the_documented_examples_exist(self):
        self.assertGreaterEqual(len(_spec_examples()), 14)


class TestSpecExamplesAreExecuted(unittest.TestCase):
    """100% alignment: every documented example parses exactly as documented."""

    def test_every_example_matches_the_document(self):
        rows = _spec_examples()
        self.assertGreaterEqual(len(rows), 14)
        for example, kind, value in rows:
            parsed = face.parse_expect(example)
            if kind == "(error)":
                self.assertIn("error", parsed,
                              "spec example %r should be rejected" % example)
                continue
            self.assertNotIn("error", parsed,
                             "spec example %r should parse: %r" % (example, parsed))
            self.assertEqual(parsed["kind"], kind, example)
            self.assertEqual(parsed["needle"], value, example)


class TestVerdictShapes(unittest.TestCase):
    """The `expect` object fields pinned by §5 of the spec."""

    def setUp(self):
        face.reset()
        self._p = mock.patch("hand.hand.EXPECT_POLL_INTERVAL", 0.02)
        self._p.start()
        self.addCleanup(self._p.stop)

    def _do(self, expect, states, raw=None, **kw):
        raw = raw if raw is not None else {"method": "cdp_click", "result": "ok",
                                           "verified": True, "evidence": {}}
        queue = list(states)

        def fake_state(need_text=False, need_visual=False):
            return queue.pop(0) if len(queue) > 1 else queue[0]

        with mock.patch("hand.router.route_do", return_value=raw), \
             mock.patch("hand.hand._page_state", side_effect=fake_state):
            return face.do("click [15]", expect=expect, **kw)

    def test_met_shape(self):
        r = self._do("url:/issues",
                     [{"url": "https://x/issues", "title": "Issues"}])
        e = r["expect"]
        self.assertEqual(set(e), {"spec", "kind", "needle", "met", "waited_ms",
                                  "checks", "evidence"})
        self.assertTrue(e["met"])

    def test_timeout_shape_and_reason_template(self):
        r = self._do("url:/nope", [{"url": "https://x/", "title": "X"}], timeout=0.1)
        e = r["expect"]
        for key in ("spec", "kind", "needle", "met", "waited_ms", "checks",
                    "timeout_s", "evidence", "reason"):
            self.assertIn(key, e)
        self.assertEqual(e["reason"],
                         "url never contained '/nope' within 0.1s")

    def test_visual_state_timeout_reason_template(self):
        r = self._do("visual_state:loading",
                     [{"url": "https://x/", "title": "X",
                       "visual_state": "interactive"}], timeout=0.1)
        self.assertEqual(r["expect"]["reason"],
                         "'visual_state' was never 'loading' within 0.1s")

    def test_action_failed_shape(self):
        r = self._do("url:/issues", [{"url": "https://x/", "title": "X"}],
                     raw={"error": "selector did not match", "verified": False,
                          "evidence": {}})
        e = r["expect"]
        self.assertTrue(e["skipped"])
        self.assertFalse(e["met"])
        self.assertTrue(e["reason"].startswith("action failed:"))

    def test_spec_error_shape(self):
        r = self._do("href:foo", [{"url": "https://x/", "title": "X"}])
        e = r["expect"]
        self.assertTrue(e["spec_error"])
        self.assertTrue(e["skipped"])
        self.assertFalse(r["ok"])                       # the call as specified failed
        self.assertEqual(r["error"], e["reason"])
        self.assertIn("hint", e)

    def test_evidence_carries_the_observed_state(self):
        r = self._do("visual_state:loading",
                     [{"url": "https://x/", "title": "X",
                       "visual_state": "loading"}])
        self.assertEqual(r["expect"]["evidence"]["visual_state"], "loading")

    def test_url_case_sensitive_title_insensitive(self):
        r = self._do("url:/ISSUES", [{"url": "https://x/issues", "title": "I"}],
                     timeout=0.1)
        self.assertFalse(r["expect"]["met"])
        r = self._do("title:issues", [{"url": "https://x/", "title": "Open Issues"}])
        self.assertTrue(r["expect"]["met"])

    def test_visual_state_is_an_exact_enum(self):
        # "load" is a substring of "loading" but visual_state is not substring-matched
        r = self._do("visual_state:load",
                     [{"url": "https://x/", "title": "X",
                       "visual_state": "loading"}])
        self.assertTrue(r["expect"]["skipped"])         # rejected as a bad value
        self.assertFalse(r["expect"]["met"])


if __name__ == "__main__":
    unittest.main()
