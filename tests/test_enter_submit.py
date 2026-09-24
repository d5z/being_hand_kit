"""L2 tests for hand 0.9.4-P3 — Enter submits (keyboard event vs text insert).

Spec: docs/spec-0.9.4-p3-enter-submit.md. Regression covered:

  * the type loops inserted every character with `Input.insertText`, which is a
    *text insertion* and produces no KeyboardEvent. A "\n" in a single-line
    input was therefore swallowed as text and never became keydown(13), so
    reactive search/submit handlers (React onKeyDown) never fired: measured on
    2026-09-24 against the GitHub issues search box, `insertText("NVDA")` left
    the URL unchanged while `dispatchKeyEvent` keyDown+keyUp (13) changed it to
    `?q=NVDA` immediately.

The fix forks "\n" by element type — a real Enter key press for a single-line
field, a literal newline for a multiline one (textarea / role contains
multiline) — and reports the fork as `evidence.enter_mode`.

Each fixture records the events it receives — the keyCode-13 keydown the page's
own handler sees (the submission signal a search box like GitHub's reacts to),
the native implicit form submission, and the field value — so a receipt
claiming "submitted" can be checked against the page itself, and the old
behaviour is proven *not* to submit before the new one is proven to.

Measured boundary of the spec's pinned dispatch payload (2026-09-24, Chrome
headless, this fixture — see `_scratch`-style probe in the round-1 report):
the pinned keyDown+keyUp pair (no `text`) makes the page see keydown(13) but
does *not* trigger Chrome's *native* implicit form submission, whereas
`Input.insertText("\\n")` triggers the native path (native=1) while producing
no keydown at all (keydown(13)=0) — which is exactly why the JS-driven GitHub
search box never submitted. Adding `text: "\\r"` to the keyDown would light
both; the spec pins the payload without it, so this suite asserts the keydown
channel (the root cause it names) and does not lock in either behaviour of the
native channel.

Real headless Chrome against fixture pages served by the repo's own fixture
server, on the shared localhost:9222 CDP endpoint. Skipped (never red) when no
browser can be brought up.
"""

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action.cdp_act import cdp_type, cdp_type_focused, cdp_type_handle
from hand.action.cdp_act import ENTER_MODE_KEYBOARD, ENTER_MODE_TEXT
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixture pages ────────────────────────────────────────────────────
# Fixture A: a single-line input in a form. Enter must reach the page as a real
# keydown(13) *and* run the form's implicit submission.
# Fixture B: a textarea where "\n" is a newline, not a submit.

# The input's handler is the spec's fixture A ("if keyCode 13 → submitted"):
# it is the submission signal a JS-driven search box produces. The form's own
# onsubmit is kept as a second, independent instrument for the *native* channel.
SUBMIT_JS = "window.native=(window.native||0)+1;document.title='native';return false;"

INPUT_HTML = """<!doctype html><html><head><title>Enter Input</title></head>
<body style="margin:0">
  <form id="f" onsubmit="%s">
    <input id="q" type="text" name="q" aria-label="Query" value=""
           onkeydown="if(event.keyCode===13){window.keydowns=(window.keydowns||0)+1;window.submits=(window.submits||0)+1;window.lastValue=this.value;document.title='submitted';}">
    <button id="go" type="submit">Go</button>
  </form>
</body></html>""" % SUBMIT_JS

TEXTAREA_HTML = """<!doctype html><html><head><title>Enter Textarea</title></head>
<body style="margin:0">
  <textarea id="t" name="t" aria-label="Notes" rows="4" cols="20"
            onkeydown="window.keydowns=(window.keydowns||0)+1;"></textarea>
</body></html>"""

PATHS = {"/enter-input": INPUT_HTML, "/enter-textarea": TEXTAREA_HTML}

_FX = None
_CHROME = runner.chrome_available()
if not _CHROME:          # same launcher path the kit uses; missing = SKIP
    try:
        from hand.perception.cdp_launcher import ensure_chrome
        ensure_chrome()
    except Exception:
        pass
    _CHROME = runner.chrome_available()


def setUpModule():
    global _FX
    if _CHROME:
        _FX = FixtureServer(extra_pages=PATHS)


def tearDownModule():
    if _FX:
        _FX.close()


# ── helpers ──────────────────────────────────────────────────────────

def _open_fixture(path):
    """Open `path` in its own tab and make it the session page (resolve_page(None))."""
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    pages, idx = [], None
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            idx = match[0]
            _write_last(idx)
            if _js("location.pathname") == path:
                break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{path} never loaded in tab {tab['id']}")
    time.sleep(0.2)
    return tab


def _ws():
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    _init_domains(ws, "Runtime")
    return ws


def _js(expr):
    """Evaluate `expr` in the session page; return its value."""
    ws = _ws()
    try:
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, msg_id=91)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def _reset():
    """Fresh measurement conditions: no counters, no stale field content."""
    return _js("(function(){window.clicked=0;window.keydowns=0;window.submits=0;"
               "window.native=0;"
               "window.lastValue=null;document.title='reset';"
               "var q=document.getElementById('q');if(q)q.value='';"
               "var t=document.getElementById('t');if(t)t.value='';"
               "return true;})()")


def _counters():
    return _js("JSON.stringify({keydowns:window.keydowns||0,"
               "submits:window.submits||0,native:window.native||0,"
               "title:document.title,"
               "q:(document.getElementById('q')||{}).value||null,"
               "t:(document.getElementById('t')||{}).value||null})")


def _focus(selector):
    """Focus `selector` the way a click would (JS focus, no mouse event)."""
    return _js("(function(){var el=document.querySelector(%s);el.focus();"
               "return document.activeElement===el;})()" % json.dumps(selector))


def _raw_type(selector, text):
    """The pre-fix loop, verbatim in effect:每 char via Input.insertText.

    This is the control experiment — it must NOT submit, which is what makes
    the fixture's submit counter a real instrument.
    """
    assert _focus(selector), f"{selector} did not take focus"
    ws = _ws()
    try:
        for char in text:
            cdp_call(ws, "Input.insertText", {"text": char}, msg_id=80)
    finally:
        ws.close()


def _raw_dispatch_enter():
    """A real Enter press (what the fix must do) — proves the counter works."""
    ws = _ws()
    try:
        for kind in ("keyDown", "keyUp"):
            cdp_call(ws, "Input.dispatchKeyEvent",
                     {"type": kind, "key": "Enter", "code": "Enter",
                      "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13},
                     msg_id=81)
    finally:
        ws.close()


def _input_handle():
    """[idx] of the fixture's text field from a fresh a11y snapshot."""
    see = router.route_see(kind="a11y")
    if not see.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {see}")
    for idx, h in (see.get("handles") or {}).items():
        if "Query" in (h.get("name") or ""):
            return idx
    for idx, h in (see.get("handles") or {}).items():
        if (h.get("role") or "").lower() in ("textbox", "searchbox", "combobox"):
            return idx
    raise AssertionError(f"no text field in the a11y handle map: {see.get('handles')}")


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class EnterSubmit(unittest.TestCase):
    """Spec 0.9.4-P3: "\n" in a single-line field is a submit intent."""

    def setUp(self):
        self.tabs = []

    def tearDown(self):
        """Close the tabs this test opened (never the last remaining page)."""
        for tab in self.tabs:
            try:
                if len(list_pages()) > 1:
                    req = urllib.request.Request(
                        f'{CDP_HOST}/json/close/{tab["id"]}', method="PUT")
                    urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass

    # ── 1 ───────────────────────────────────────────────────────────
    def test_enter_submits_input(self):
        """Core regression: "\n" typed into an input must submit, not vanish.

        The fixture is proven dangerous first: the pre-fix char-by-char
        insertText path leaves both the keydown counter and the form's submit
        counter at zero.
        """
        self.tabs.append(_open_fixture("/enter-input"))
        self.assertTrue(_reset())
        _raw_type("#q", "screen reader\n")
        control = json.loads(_counters())
        self.assertEqual(control["q"], "screen reader",
                         "fixture is wrong: the text never reached the input")
        self.assertEqual(control["keydowns"], 0,
                         "fixture is wrong: insertText produced a keydown")
        self.assertEqual(control["submits"], 0,
                         "fixture is wrong: the pre-fix path already submitted")
        # the measured nuance behind the root cause: insertText("\n") does reach
        # Chrome's *native* implicit submission, but it produces no keydown at
        # all — which is why the JS-driven GitHub box never submitted.
        self.assertGreaterEqual(control["native"], 1,
                                "insertText(\\n) no longer reaches the native path")

        # the fix
        self.assertTrue(_reset())
        r = cdp_type("#q", "screen reader\n")
        self.assertTrue(r["verified"], r)
        after = json.loads(_counters())
        self.assertGreaterEqual(after["keydowns"], 1,
                                "no keydown(13) reached the page")
        self.assertGreaterEqual(after["submits"], 1,
                                "receipt claimed ok but the form never submitted")
        self.assertEqual(after["title"], "submitted")
        self.assertEqual(after["q"], "screen reader", after)

    # ── 2 ───────────────────────────────────────────────────────────
    def test_enter_newline_in_textarea(self):
        """The same "\n" in a textarea is a real newline, with no key side effect."""
        self.tabs.append(_open_fixture("/enter-textarea"))
        self.assertTrue(_reset())
        # the instrument is real: a dispatched Enter *does* light the counter
        self.assertTrue(_focus("#t"))
        _raw_dispatch_enter()
        probed = json.loads(_counters())
        self.assertGreaterEqual(probed["keydowns"], 1,
                                "fixture is wrong: it cannot see a real Enter")
        self.assertNotIn("\n", probed["t"] or "",
                         "fixture is wrong: Enter inserted a newline by itself")

        self.assertTrue(_reset())
        r = cdp_type("#t", "line1\nline2")
        self.assertTrue(r["verified"], r)
        after = json.loads(_counters())
        self.assertIn("\n", after["t"] or "",
                      "the newline was not inserted as text into the textarea")
        self.assertEqual(after["t"], "line1\nline2", after)
        self.assertEqual(after["keydowns"], 0,
                         "a keyboard event leaked into a multiline field")
        self.assertEqual(after["submits"], 0)

    # ── 3 ───────────────────────────────────────────────────────────
    def test_enter_receipt_has_mode(self):
        """evidence.enter_mode declares the fork the receipt actually took."""
        self.tabs.append(_open_fixture("/enter-input"))
        r = cdp_type("#q", "no newline here")
        self.assertTrue(r["verified"], r)
        self.assertIsNone(r["evidence"]["enter_mode"],
                          "no \n → nothing was forked, so the mode must be null")

        r2 = cdp_type("#q", "submit me\n")
        self.assertTrue(r2["verified"], r2)
        self.assertEqual(r2["evidence"]["enter_mode"], ENTER_MODE_KEYBOARD, r2)

        self.tabs.append(_open_fixture("/enter-textarea"))
        r3 = cdp_type("#t", "a\nb")
        self.assertTrue(r3["verified"], r3)
        self.assertEqual(r3["evidence"]["enter_mode"], ENTER_MODE_TEXT, r3)

        r4 = cdp_type("#t", "single line")
        self.assertTrue(r4["verified"], r4)
        self.assertIsNone(r4["evidence"]["enter_mode"], r4)

    # ── 4 ───────────────────────────────────────────────────────────
    def test_enter_focused_path(self):
        """cdp_type_focused takes the same fork (focus pre-flight already read it)."""
        self.tabs.append(_open_fixture("/enter-input"))
        self.assertTrue(_reset())
        self.assertTrue(_focus("#q"))
        r = cdp_type_focused("focused text\n")
        self.assertTrue(r["verified"], r)
        self.assertEqual(r["evidence"]["enter_mode"], ENTER_MODE_KEYBOARD, r)
        after = json.loads(_counters())
        self.assertGreaterEqual(after["submits"], 1,
                                "focused path typed but never submitted")
        self.assertEqual(after["q"], "focused text", after)

        # and the multiline fork is taken here too
        self.tabs.append(_open_fixture("/enter-textarea"))
        self.assertTrue(_reset())
        self.assertTrue(_focus("#t"))
        r2 = cdp_type_focused("one\ntwo")
        self.assertTrue(r2["verified"], r2)
        self.assertEqual(r2["evidence"]["enter_mode"], ENTER_MODE_TEXT, r2)
        self.assertIn("\n", json.loads(_counters())["t"] or "")

    # ── 5 ───────────────────────────────────────────────────────────
    def test_enter_handle_path(self):
        """cdp_type_handle takes the same fork (spec names all three落点)."""
        self.tabs.append(_open_fixture("/enter-input"))
        self.assertTrue(_reset())
        idx = _input_handle()
        r = cdp_type_handle(f"[{idx}]", "via handle\n")
        self.assertTrue(r["verified"], r)
        self.assertEqual(r["evidence"]["enter_mode"], ENTER_MODE_KEYBOARD, r)
        after = json.loads(_counters())
        self.assertGreaterEqual(after["submits"], 1,
                                "handle path typed but never submitted")
        self.assertEqual(after["q"], "via handle", after)


if __name__ == "__main__":
    unittest.main()
