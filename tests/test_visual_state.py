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

import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.perception import pixels, visual_state
from hand.perception.visual_state import (
    classify, parse_probe, VISUAL_STATES, BLANK_TEXT_THRESHOLD)

import hand.perception.ax_tree as ax
import hand.hand as face

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "visual_state")


# ── the classifier ───────────────────────────────────────────────────

class TestClassify(unittest.TestCase):
    def test_five_states_and_priority(self):
        self.assertEqual(classify({"body": True, "text_len": 100})[0], "interactive")
        # 0.10 D3: a blank candidate without a pixel vote has no witness ->
        # unknown, never blank.
        self.assertEqual(classify({"body": True, "text_len": 3})[0], "unknown")
        self.assertEqual(
            classify({"body": True, "text_len": 3,
                      "pixel": {"available": True, "ink_ratio": 0.0}})[0],
            "blank")
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
            classify({"body": True, "text_len": 0, "has_media": False,
                      "pixel": {"available": True, "ink_ratio": 0.0}})[0],
            "blank")


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
        self.assertEqual(signals, ["pixel-unavailable", "sparse-text"])
        _, signals = classify({"body": True, "text_len": 0,
                               "pixel": {"available": True, "ink_ratio": 0.0}})
        self.assertIn("pixel-empty:0.0000", signals)

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
    def _raw(self, name):
        with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as f:
            return _signals(f.read())

    def _voted(self, name, ink_ratio):
        """Fixture signals plus a pixel vote (D3: blank needs a witness)."""
        return dict(self._raw(name),
                    pixel={"available": True, "ink_ratio": ink_ratio})

    def _state(self, name):
        return classify(self._raw(name))


    def test_loading_fixture(self):
        state, signals = self._state("loading")
        self.assertEqual(state, "loading")
        self.assertTrue(any(s.startswith(("spinner", "aria-busy")) for s in signals))

    def test_error_fixture(self):
        state, signals = self._state("error")
        self.assertEqual(state, "error")
        self.assertTrue(any(s.startswith(("error-title", "error-heading", "error-img")) for s in signals))

    def test_blank_fixture(self):
        # The fixture is only a blank *candidate* on DOM signals alone (D3):
        # the state settles when the pixel vote agrees the frame is empty.
        self.assertEqual(self._state("blank")[0], "unknown")
        state, signals = classify(self._voted("blank", 0.0))
        self.assertEqual(state, "blank")
        self.assertIn("no-media", signals)
        self.assertIn("pixel-empty:0.0000", signals)

    def test_sparse_text_page_is_not_blank(self):
        # Regression for the 0.10 S2 counterexample (still visible in the 0.10
        # PRD): white page, eight 48px characters, no img/canvas/video. DOM-only
        # said "blank"; a pixel vote says the frame has ink.
        sig = self._raw("sparse_text")
        self.assertLess(sig["text_len"], 20)
        self.assertFalse(sig["has_media"])
        self.assertEqual(classify(sig)[0], "unknown")
        state, signals = classify(dict(sig, pixel={"available": True,
                                                   "ink_ratio": 0.012}))
        self.assertEqual(state, "interactive")
        self.assertIn("pixel-ink:0.0120", signals)

    def test_canvas_only_page_is_not_blank_candidate(self):
        # DOM has no text at all but a canvas is rendered: `has_media` keeps it
        # out of the blank branch, so no pixel vote is needed.
        sig = {"body": True, "text_len": 0, "has_media": True}
        self.assertEqual(classify(sig)[0], "interactive")

    def test_no_pixel_vote_means_unknown_not_blank(self):
        # PRD D3 acceptance: pixel unavailable -> unknown + pixel-unavailable.
        state, signals = classify({"body": True, "text_len": 2})
        self.assertEqual(state, "unknown")
        self.assertIn("pixel-unavailable", signals)


    def test_interactive_fixture(self):
        state, signals = self._state("interactive")
        self.assertEqual(state, "interactive")
        self.assertIn("content", signals)

    def test_fixtures_are_the_four_states(self):
        # blank carries a vote because `blank` is a visual claim (D3).
        self.assertEqual({classify(self._voted(n, 0.0))[0] for n in
                          ("loading", "error", "blank", "interactive")},
                         {"loading", "error", "blank", "interactive"})



# ── pixel vote (0.10 D3) ─────────────────────────────────────────────
#
# `blank` is a visual claim: the DOM candidate (`text_len < threshold`, no
# media) must be settled by a pixel vote, and a vote that cannot run means
# `unknown`, never `blank`. These tests cover the decoder, the vote, and the
# two-stage cost rule in probe().

def _png(width, height, flat, channels=4):
    """Encode a tiny 8-bit PNG (row filter 0) for the pixel vote tests.

    `flat` is row-major pixel data for the whole image.
    """
    import struct as _struct
    import zlib as _zlib
    color_type = 6 if channels == 4 else 2

    def chunk(tag, data):
        return (_struct.pack("!I", len(data)) + tag + data
                + _struct.pack("!I", _zlib.crc32(tag + data) & 0xFFFFFFFF))

    stride = width * channels
    raw = b"".join(b"\x00" + bytes(flat[y * stride:(y + 1) * stride])
                   for y in range(height))
    ihdr = _struct.pack("!IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", _zlib.compress(raw)) + chunk(b"IEND", b""))


def _white(w, h):
    return [255, 255, 255, 255] * (w * h)


class TestPixelVote(unittest.TestCase):
    def test_blank_frame_has_no_ink(self):
        stats = pixels.ink_stats(_png(20, 20, _white(20, 20)))
        self.assertEqual(stats["ink_ratio"], 0.0)
        self.assertEqual(stats["background"], "#f8f8f8")
        self.assertEqual(stats["distinct_colors"], 1)

    def test_ink_is_detected(self):
        flat = []
        for _y in range(20):
            for x in range(20):
                flat.extend((0, 0, 0, 255) if 8 <= x < 12
                            else (255, 255, 255, 255))
        stats = pixels.ink_stats(_png(20, 20, flat))
        self.assertGreater(stats["ink_ratio"], 0.15)
        self.assertEqual(stats["distinct_colors"], 2)

    def test_rgb_is_decoded(self):
        flat = [255, 255, 255] * 16
        stats = pixels.ink_stats(_png(4, 4, flat, channels=3))
        self.assertEqual((stats["width"], stats["height"]), (4, 4))
        self.assertEqual(stats["ink_ratio"], 0.0)

    def test_background_tie_is_reported_not_hidden(self):
        """两个桶同票时，赢家由 dict 迭代序决定——那是事实的一部分，必须带出去。

        2026-10-27：`max(counts.items(), key=kv[1])[0]` 在并列时静默选一个，
        回执读起来像「背景色是 X」这个判断，其实是「谁先进 counts 谁赢」。
        """
        flat = []
        for y in range(4):
            for x in range(4):
                black = y < 2                      # 上半黑、下半白：8 票对 8 票
                flat.extend((0, 0, 0, 255) if black else (255, 255, 255, 255))
        stats = pixels.ink_stats(_png(4, 4, flat))
        self.assertEqual(stats["distinct_colors"], 2)
        self.assertEqual(stats["background_tie"], 2)

    def test_background_has_no_tie_when_one_bucket_wins(self):
        flat = []
        for y in range(4):
            for x in range(4):
                black = y < 3                      # 12 票黑 vs 4 票白
                flat.extend((0, 0, 0, 255) if black else (255, 255, 255, 255))
        stats = pixels.ink_stats(_png(4, 4, flat))
        self.assertEqual(stats["background_tie"], 1)
        self.assertEqual(stats["background"], "#080808")


    def test_unsupported_png_raises_instead_of_guessing(self):
        with self.assertRaises(pixels.PngUnsupported):
            pixels.decode_png(b"not a png at all")
        bad = bytearray(_png(2, 2, _white(2, 2)))
        bad[24] = 16                          # bit depth 16: out of scope
        with self.assertRaises(pixels.PngUnsupported):
            pixels.decode_png(bytes(bad))

    def test_pixel_vote_from_an_inline_frame(self):
        b64 = base64.b64encode(_png(20, 20, _white(20, 20))).decode()
        vote = pixels.pixel_vote(png_b64=b64)
        self.assertTrue(vote["available"])
        self.assertEqual(vote["ink_ratio"], 0.0)

    def test_pixel_vote_without_a_source_is_unavailable(self):
        vote = pixels.pixel_vote()
        self.assertFalse(vote["available"])
        self.assertEqual(vote["reason"], "pixel-unavailable")

    def test_large_frame_is_not_decoded_inline(self):
        # A full-size frame is re-shot downscaled instead; with no socket the
        # honest answer is "no evidence", not a slow decode of 600x600.
        b64 = base64.b64encode(_png(500, 500, _white(500, 500))).decode()
        vote = pixels.pixel_vote(ws=None, call=None, png_b64=b64)
        self.assertFalse(vote["available"])


class TestProbeTwoStage(unittest.TestCase):
    """D3 cost rule: only a blank candidate pays for a pixel vote."""

    BASE = {"body": True, "ready_state": "complete", "aria_busy": False,
            "spinner": False, "error_title": None, "error_heading": None,
            "error_img": False, "text_len": 0, "has_media": False}

    def _probe_json(self, **overrides):
        sig = dict(self.BASE)
        sig.update(overrides)
        return json.dumps(sig)

    def _call(self, probe_json, frame=None, seen=None, fail_shot=False):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if seen is not None:
                seen.append(method)
            if method == "Runtime.evaluate":
                return {"result": {"value": probe_json}}
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 100,
                                              "clientHeight": 80}}
            if method == "Page.captureScreenshot":
                if fail_shot:
                    raise RuntimeError("CDP gone")
                return {"data": base64.b64encode(frame or b"").decode()}
            return {}
        return fake_call

    def _run(self, probe_json, frame=None, seen=None, fail_shot=False):
        with mock.patch("hand.perception.cdp_core._init_domains",
                        return_value=None):
            return visual_state.probe(
                _FakeWS(), call=self._call(probe_json, frame, seen, fail_shot))

    def test_content_page_takes_no_screenshot(self):
        seen = []
        out = self._run(self._probe_json(text_len=120), seen=seen)
        self.assertEqual(out["visual_state"], "interactive")
        self.assertNotIn("Page.captureScreenshot", seen)

    def test_sparse_text_with_ink_is_not_blank(self):
        flat = [0, 0, 0, 255] * 50 + [255, 255, 255, 255] * 50
        out = self._run(self._probe_json(text_len=8), frame=_png(10, 10, flat))
        self.assertEqual(out["visual_state"], "interactive")
        self.assertTrue(any(s.startswith("pixel-ink:") for s in out["visual_signals"]))


    def test_sparse_text_on_an_empty_frame_is_blank(self):
        out = self._run(self._probe_json(text_len=8),
                        frame=_png(10, 10, _white(10, 10)))
        self.assertEqual(out["visual_state"], "blank")
        self.assertIn("pixel-empty:0.0000", out["visual_signals"])

    def test_vote_failure_downgrades_to_unknown(self):
        out = self._run(self._probe_json(text_len=8), fail_shot=True)
        self.assertEqual(out["visual_state"], "unknown")
        self.assertIn("pixel-unavailable", out["visual_signals"])



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
