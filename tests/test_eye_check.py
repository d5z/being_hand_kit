"""L1 tests for hand 0.10 D4 — hand_eye_check (being-side self-proof).

PRD docs/prd-delivery-honesty.md §D4. The tool answers a question no outside
layer can: did the rendered frame actually reach the caller?

These tests guard the three constraints that make it a proof:

  1. the string never enters the receipt / the page source / the title,
  2. challenge and verify are separated (the tool never answers itself),
  3. strict matching — a near-miss fails, and a pass is single use.

No browser needed: `route_open` and the CDP evaluate are both mocked. The
real-browser run (canvas pixels, DOM has no text node) is done by hand and
recorded in the PRD acceptance table.
"""

import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.perception import eye_check


class _FakePage:
    """Stands in for route_open + the CDP evaluate, capturing the page source."""

    def __init__(self):
        self.html = None
        self.expressions = []
        self.draw_returned = True
        self.ink_ratio = 0.12

    def open(self, url):
        if url.startswith("file://"):
            try:
                with open(url[len("file://"):], encoding="utf-8") as f:
                    self.html = f.read()
            except OSError:
                self.html = None
        return {"verified": True}

    def evaluate(self, expr, timeout=10):
        self.expressions.append(expr)
        if "drawEye" in expr:
            return {"value": {"drawn": self.draw_returned,
                              "w": 640, "h": 160, "chars": 8}}
        if "eyeStats" in expr:
            return {"value": {"samples": 1200, "ink": 120,
                              "ink_ratio": self.ink_ratio}}
        return {"value": {}}

    def __enter__(self):
        self._patches = [
            mock.patch.object(eye_check, "_evaluate", self.evaluate),
            mock.patch("hand.router.route_open", self.open),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _clean_challenges():
    for info in list(eye_check._CHALLENGES.values()):
        eye_check._cleanup(info["place_path"])
    eye_check._CHALLENGES.clear()


class TestAlphabet(unittest.TestCase):
    def test_ambiguous_glyphs_are_excluded(self):
        # O/0/I/1/L are missing on purpose: the question is "did the pixels
        # arrive", not "is the font legible".
        for bad in "O0I1Ll":
            self.assertNotIn(bad, eye_check.ALPHABET)

    def test_answer_shape(self):
        a = eye_check._new_answer(8)
        self.assertEqual(len(a), 8)
        self.assertTrue(set(a) <= set(eye_check.ALPHABET))

    def test_answers_differ(self):
        self.assertNotEqual(eye_check._new_answer(12), eye_check._new_answer(12))


class TestChallengeReceipt(unittest.TestCase):
    def tearDown(self):
        _clean_challenges()

    def test_receipt_and_page_source_never_carry_the_string(self):
        page = _FakePage()
        with page:
            out = eye_check.challenge()
        self.assertTrue(out["verified"])
        cid = out["challenge_id"]
        answer = eye_check._CHALLENGES[cid]["answer"]

        # 1. the receipt is safe to print / log / show to the model
        self.assertNotIn(answer, json.dumps(out))
        # 2. the page *source* never held it either (injected after load)
        self.assertIsNotNone(page.html)
        self.assertNotIn(answer, page.html)
        # 3. no text container in the template that could expose it
        for tag in ("<p", "<div", "<span"):
            self.assertNotIn(tag, eye_check._TEMPLATE)
        # 4. the only place it exists is the draw call
        self.assertTrue(any(answer in e for e in page.expressions))

    def test_renders_on_a_canvas(self):
        page = _FakePage()
        with page:
            out = eye_check.challenge()
        self.assertIn("<canvas", eye_check._TEMPLATE)
        self.assertTrue(out["evidence"]["rendered"])
        self.assertGreater(out["evidence"]["ink_ratio"], 0)

    def test_refuses_to_issue_a_challenge_that_did_not_render(self):
        # Same discipline as D3: no evidence, no claim.
        page = _FakePage()
        page.ink_ratio = 0.0
        with page:
            out = eye_check.challenge()
        self.assertIn("error", out)
        self.assertEqual(eye_check.active_challenges()["count"], 0)

    def test_out_of_range_arguments(self):
        for kwargs in ({"chars": 3}, {"chars": 17}, {"font_px": 10},
                       {"font_px": 200}, {"ttl_s": 1}, {"ttl_s": 99999}):
            self.assertIn("error", eye_check.challenge(**kwargs))

    def test_place_is_a_local_file_url(self):
        page = _FakePage()
        with page:
            out = eye_check.challenge()
        self.assertTrue(out["place"].startswith("file://"))
        self.assertTrue(os.path.exists(out["place"][len("file://"):]))


class TestVerify(unittest.TestCase):
    def setUp(self):
        _clean_challenges()
        self.page = _FakePage()
        self.page.__enter__()
        self.receipt = eye_check.challenge()
        self.answer = eye_check._CHALLENGES[self.receipt["challenge_id"]]["answer"]

    def tearDown(self):
        self.page.__exit__(None, None, None)
        _clean_challenges()

    def test_correct_answer_passes(self):
        out = eye_check.verify(self.receipt["challenge_id"], self.answer)
        self.assertTrue(out["pass"])
        self.assertNotIn("reason", out)

    def test_receipt_of_verify_never_echoes_the_string(self):
        out = eye_check.verify(self.receipt["challenge_id"], "WRONGANS")
        self.assertNotIn(self.answer, json.dumps(out))
        self.assertEqual(out["answer_len_expected"], len(self.answer))

    def test_near_miss_fails(self):
        # Substitutions that a half-read frame would produce.
        swaps = {"B": "8", "S": "5", "G": "6", "Z": "2", "Q": "9"}
        mutated = "".join(swaps.get(c, c) for c in self.answer)
        if mutated == self.answer:  # answer had no swappable glyph
            mutated = self.answer[:-1] + ("A" if self.answer[-1] != "A" else "B")
        out = eye_check.verify(self.receipt["challenge_id"], mutated)
        self.assertFalse(out["pass"])
        self.assertEqual(out["reason"], "mismatch")

    def test_case_insensitive_but_nothing_else(self):
        # Reading a lower-case glyph off a screen is not a delivery failure.
        out = eye_check.verify(self.receipt["challenge_id"], self.answer.lower())
        self.assertTrue(out["pass"])

    def test_single_use(self):
        cid = self.receipt["challenge_id"]
        eye_check.verify(cid, self.answer)
        again = eye_check.verify(cid, self.answer)
        self.assertFalse(again["pass"])
        self.assertEqual(again["reason"], "unknown-challenge")

    def test_unknown_challenge(self):
        out = eye_check.verify("ec_deadbeefdeadbeef", self.answer)
        self.assertFalse(out["pass"])
        self.assertEqual(out["reason"], "unknown-challenge")

    def test_expired_challenge_fails(self):
        cid = self.receipt["challenge_id"]
        eye_check._CHALLENGES[cid]["expires_at"] = time.time() - 1
        out = eye_check.verify(cid, self.answer)
        self.assertFalse(out["pass"])
        self.assertEqual(out["reason"], "expired")

    def test_missing_arguments(self):
        self.assertIn("error", eye_check.verify(None, "X"))
        self.assertIn("error", eye_check.verify("ec_x", None))


class TestListSafety(unittest.TestCase):
    def tearDown(self):
        _clean_challenges()

    def test_list_never_prints_strings(self):
        page = _FakePage()
        with page:
            out = eye_check.challenge()
        answer = eye_check._CHALLENGES[out["challenge_id"]]["answer"]
        listing = json.dumps(eye_check.active_challenges())
        self.assertNotIn(answer, listing)
        self.assertIn(out["challenge_id"], listing)


if __name__ == "__main__":
    unittest.main()
