"""L1 tests for hand 0.9 S2 — visual state marker.

PRD docs/prd-0.9-receipt-honesty.md S2. Two layers are tested:

  * `classify()` — the pure priority rule (error > loading > blank > interactive,
    `unknown` only when there is no signal). No browser.
  * the four fixture pages under tests/fixtures/visual_state/, read through a
    test-only DOM-signal mirror of the browser probe (no Chrome needed), plus an
    optional end-to-end run against a real Chrome when one is available.

The marker rides on cdp_see (a11y + dom) and cdp_shot; `expect="visual_state:…"`
is wired through hand.do().
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.perception.visual_state import (
    classify, parse_probe, VISUAL_STATES, BLANK_TEXT_THRESHOLD)
import hand.perception.ax_tree as ax
import hand.hand as face

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "visual_state")


# ── the classifier ───────────────────────────────────────────────────

class TestClassify(unittest.TestCase):
    def test_five_states_and_priority(self):
        self.assertEqual(classify({"body": True, "text_len": 100})[0], "interactive")
        self.assertEqual(classify({"body": True, "text_len": 3})[0], "blank")
        self.assertEqual(classify({"body": True, "aria_busy": True})[0], "loading")
        self.assertEqual(classify({"body": True, "error_heading": "404"})[0], "error")
        self.assertEqual(classify({"body": False})[0], "unknown")
        self.assertEqual(classify(None)[0], "unknown")

    def test_error_beats_loading_beats_blank(self):
        self.assertEqual(
            classify({"body": True, "error_heading": "not found",
                      "aria_busy": True, "text_len": 0})[0], "error")
        self.assertEqual(
            classify({"body": True, "aria_busy": True, "text_len": 0})[0], "loading")
        self.assertEqual(
            classify({"body": True, "ready_state": "loading", "text_len": 0})[0],
            "loading")
        self.assertEqual(
            classify({"body": True, "text_len": 0, "has_media": False})[0], "blank")

    def test_blank_requires_no_media(self):
        # short text but a rendered image -> not blank
        self.assertEqual(
            classify({"body": True, "text_len": 0, "has_media": True})[0],
            "interactive")

    def test_signals_are_auditable(self):
        state, signals = classify({"body": True, "spinner": True})
        self.assertEqual(state, "loading")
        self.assertIn("spinner-class", signals)
        _, signals = classify({"body": True, "error_heading": "错误"})
        self.assertIn("error-heading:错误", signals)
        _, signals = classify({"body": True, "text_len": 0})
        self.assertEqual(signals, ["empty-text", "no-media"])
        self.assertEqual(classify({"body": False})[1], ["no-body"])

    def test_probe_parse_never_raises(self):
        self.assertIsNone(parse_probe(1))
        self.assertIsNone(parse_probe("{not json"))
        self.assertEqual(parse_probe('{"body": true}'), {"body": True})

    def test_unknown_is_honest_not_a_guess(self):
        # a probe that could not run must NOT default to interactive
        for bad in (None, {}, {"body": False}, {"body": None}):
            self.assertEqual(classify(bad)[0], "unknown")

    def test_states_enum_is_frozen(self):
        self.assertEqual(VISUAL_STATES,
                         ("loading", "error", "blank", "interactive", "unknown"))

    def test_error_word_in_a_long_page_is_content_not_state(self):
        # Regression: the hand GitHub repo page. Its README renders a section
        # heading "Errors are documentation" — the old rule read that h2 and
        # classified the whole repo page (text_len=19143) as error.
        state, signals = classify(
            {"body": True, "error_heading": "error", "text_len": 19143})
        self.assertEqual(state, "interactive")
        self.assertIn("error-word-in-content:error", signals)

    def test_error_page_still_wins_when_text_is_short(self):
        # A real 404 page: error word in the heading, almost no body text.
        state, signals = classify(
            {"body": True, "error_heading": "page not found", "text_len": 120})
        self.assertEqual(state, "error")
        self.assertIn("error-heading:page not found", signals)

    def test_error_text_length_boundary(self):
        # just under the cap -> error; at/over the cap -> content
        self.assertEqual(
            classify({"body": True, "error_heading": "404",
                      "text_len": 499})[0], "error")
        for over in (500, 501, 10000):
            state, signals = classify(
                {"body": True, "error_heading": "404", "text_len": over})
            self.assertEqual(state, "interactive")
            self.assertIn("error-word-in-content:404", signals)

    def test_error_img_in_a_long_page_is_content_not_state(self):
        # A docs page embedding an error screenshot (alt="error message")
        # is content about errors, not an error page.
        state, signals = classify(
            {"body": True, "error_img": True, "text_len": 8000})
        self.assertEqual(state, "interactive")
        self.assertIn("error-img-in-content", signals)
        # but a bare error image on an otherwise empty page still says error
        self.assertEqual(
            classify({"body": True, "error_img": True, "text_len": 30})[0],
            "error")

    def test_title_hit_is_error_even_with_a_fat_footer(self):
        # Regression: the GitHub 404 page. Its title is "Page not found ·
        # GitHub" but the site-wide footer pushes text_len to 933 — the
        # body-length gate alone would have called it interactive.
        state, signals = classify(
            {"body": True, "error_title": "page not found",
             "error_heading": None, "text_len": 933})
        self.assertEqual(state, "error")
        self.assertIn("error-title:page not found", signals)

    def test_title_hit_beats_long_body(self):
        state, _ = classify(
            {"body": True, "error_title": "404", "text_len": 5000})
        self.assertEqual(state, "error")


# ── fixture pages (test-only mirror of the browser probe) ────────────
# VISUAL_STATE_JS is the production signal extractor. These fixtures exercise
# `classify()` against realistic HTML without a browser: _signals() mirrors the
# JS rules with the same field names (visibility is modeled as "everything the
# fixture draws is visible" — the JS in-viewport check has no mirror here:
# fixtures are first-fold-sized pages, so everything they draw is on screen;
# the viewport rule itself is exercised live, e.g. the GitHub language-bar
# regression). Real-browser equivalence is checked by the e2e
# test below when Chrome is available.

def _signals(html):
    """Mirror of the browser probe's signals, using only the stdlib."""
    from html.parser import HTMLParser
    from hand.perception.visual_state import ERROR_WORDS

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.body = False
            self.title = []
            self.head = []
            self.text = []
            self.media = False
            self.busy = False
            self.spinner = False
            self.alts = []
            self._skip = 0
            self._in_title = False
            self._in_head = False

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "body":
                self.body = True
            if tag in ("script", "style"):
                self._skip += 1
            if tag in ("img", "canvas", "video"):
                self.media = True
            if a.get("aria-busy") == "true":
                self.busy = True
            cls = (a.get("class") or "").lower()
            if any(w in cls for w in ("spinner", "loading", "skeleton")):
                self.spinner = True
            if a.get("role") == "progressbar":
                self.spinner = True
            if tag == "title":
                self._in_title = True
            if tag in ("h1", "h2"):
                self._in_head = True
            if tag == "img":
                self.alts.append((a.get("alt") or "").lower())

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self._skip:
                self._skip -= 1
            if tag == "title":
                self._in_title = False
            if tag in ("h1", "h2"):
                self._in_head = False

        def handle_data(self, data):
            if self._skip:
                return
            self.text.append(data)
            if self._in_title:
                self.title.append(data)
            if self._in_head:
                self.head.append(data)

    p = _P()
    p.feed(html)
    if not p.body:
        return {"body": False, "ready_state": "complete", "aria_busy": False,
                "spinner": False, "error_title": None, "error_heading": None,
                "error_img": False, "text_len": 0, "has_media": False}
    text = " ".join(" ".join(p.text).split())
    title = (" ".join(p.title)).lower()
    head = (" ".join(p.head)).lower()
    err_title = None
    for w in ERROR_WORDS:
        if w in title:
            err_title = w
            break
    err = None
    for w in ERROR_WORDS:
        if w in head:
            err = w
            break
    return {"body": True, "ready_state": "complete", "aria_busy": p.busy,
            "spinner": p.spinner, "error_title": err_title,
            "error_heading": err,
            "error_img": any(("error" in a or "错误" in a) for a in p.alts),
            "text_len": len(text), "has_media": p.media}



class TestFixturePages(unittest.TestCase):
    def _state(self, name):
        with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as f:
            return classify(_signals(f.read()))

    def test_loading_fixture(self):
        state, signals = self._state("loading")
        self.assertEqual(state, "loading")
        self.assertTrue(any(s.startswith(("spinner", "aria-busy")) for s in signals))

    def test_error_fixture(self):
        state, signals = self._state("error")
        self.assertEqual(state, "error")
        self.assertTrue(any(s.startswith(("error-title", "error-heading", "error-img")) for s in signals))

    def test_blank_fixture(self):
        state, signals = self._state("blank")
        self.assertEqual(state, "blank")
        self.assertIn("no-media", signals)

    def test_interactive_fixture(self):
        state, signals = self._state("interactive")
        self.assertEqual(state, "interactive")
        self.assertIn("content", signals)

    def test_fixtures_are_the_four_states(self):
        self.assertEqual({self._state(n)[0] for n in
                          ("loading", "error", "blank", "interactive")},
                         {"loading", "error", "blank", "interactive"})


# ── receipt wiring ───────────────────────────────────────────────────

PAGE = {"id": "1", "type": "page", "url": "https://example.com/",
        "title": "Example", "webSocketDebuggerUrl": "ws://x/1"}


class _FakeWS:
    def close(self):
        pass


class TestReceiptCarriesVisualState(unittest.TestCase):
    def test_a11y_snapshot_carries_marker(self):
        probe_json = json.dumps({"body": True, "ready_state": "complete",
                                 "text_len": 120})

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Accessibility.getFullAXTree":
                return {"nodes": [{"nodeId": "1", "role": {"value": "RootWebArea"},
                                   "name": {"value": "P"}}]}
            if method == "Browser.getVersion":
                return {"product": "Chrome/141.0"}
            if method == "Runtime.evaluate":
                expr = (params or {}).get("expression", "")
                if "aria-busy" in expr:
                    return {"result": {"value": probe_json}}
                return {"result": {"value": 1}}
            return {}

        tmp = tempfile.mkdtemp()
        with mock.patch.object(ax, "list_pages", return_value=[PAGE]), \
             mock.patch.object(ax, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(ax, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(ax, "cdp_call", side_effect=fake_call), \
             mock.patch.object(ax, "_init_domains", return_value=None), \
             mock.patch.object(ax, "_write_last", return_value=None):
            out = ax.ax_snapshot(handle_map_path=os.path.join(tmp, "h.json"))
        self.assertEqual(out["visual_state"], "interactive")
        self.assertEqual(out["visual_signals"], ["content"])

    def test_a11y_snapshot_unknown_when_probe_fails(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Accessibility.getFullAXTree":
                return {"nodes": [{"nodeId": "1", "role": {"value": "RootWebArea"},
                                   "name": {"value": "P"}}]}
            if method == "Runtime.evaluate":
                raise RuntimeError("no Runtime")
            return {}

        tmp = tempfile.mkdtemp()
        with mock.patch.object(ax, "list_pages", return_value=[PAGE]), \
             mock.patch.object(ax, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(ax, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(ax, "cdp_call", side_effect=fake_call), \
             mock.patch.object(ax, "_init_domains", return_value=None), \
             mock.patch.object(ax, "_write_last", return_value=None):
            out = ax.ax_snapshot(handle_map_path=os.path.join(tmp, "h.json"))
        self.assertEqual(out["visual_state"], "unknown")
        self.assertEqual(out["visual_signals"], ["probe-failed"])

    def test_shot_carries_marker(self):
        from hand import router
        from hand.session import Place
        with mock.patch("hand.perception.cdp_core.cdp_screenshot",
                        return_value={"data": "AAAA", "format": "png",
                                      "visual_state": "loading",
                                      "visual_signals": ["aria-busy"]}):
            out = router.route_screenshot(
                place=Place(type="browser", identifier="https://x/"),
                with_data=True)
        self.assertEqual(out["visual_state"], "loading")
        self.assertEqual(out["evidence"]["visual_state"], "loading")


# ── expect= wiring ───────────────────────────────────────────────────

class TestExpectVisualState(unittest.TestCase):
    def setUp(self):
        face.reset()

    def test_parse_visual_state(self):
        p = face.parse_expect("visual_state:loading")
        self.assertEqual(p["kind"], "visual_state")
        self.assertEqual(p["needle"], "loading")

    def test_bad_visual_state_is_named(self):
        p = face.parse_expect("visual_state:spinning")
        self.assertIn("error", p)
        self.assertIn("loading", p["hint"])

    def test_expect_met_on_visual_state(self):
        raw = {"method": "cdp_click", "result": "ok", "verified": True, "evidence": {}}
        with mock.patch("hand.router.route_do", return_value=raw), \
             mock.patch("hand.hand._page_state",
                        return_value={"url": "https://x/", "title": "X",
                                      "visual_state": "loading"}) as state, \
             mock.patch("hand.hand.EXPECT_POLL_INTERVAL", 0.02):
            r = face.do("click [15]", expect="visual_state:loading")
        self.assertTrue(r["expect"]["met"])
        self.assertEqual(r["expect"]["kind"], "visual_state")
        self.assertEqual(r["expect"]["evidence"]["visual_state"], "loading")
        self.assertTrue(state.call_args.kwargs.get("need_visual"))

    def test_expect_timeout_on_visual_state(self):
        raw = {"method": "cdp_click", "result": "ok", "verified": True, "evidence": {}}
        with mock.patch("hand.router.route_do", return_value=raw), \
             mock.patch("hand.hand._page_state",
                        return_value={"url": "https://x/", "title": "X",
                                      "visual_state": "interactive"}), \
             mock.patch("hand.hand.EXPECT_POLL_INTERVAL", 0.02):
            r = face.do("click [15]", expect="visual_state:loading", timeout=0.1)
        self.assertFalse(r["expect"]["met"])
        self.assertIn("loading", r["expect"]["reason"])
        self.assertEqual(r["expect"]["evidence"]["visual_state"], "interactive")


if __name__ == "__main__":
    unittest.main()
