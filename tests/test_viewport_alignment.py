"""L2 tests for hand 0.9.3-P0 — click viewport alignment.

Spec: docs/spec-0.9.3-p0-viewport.md. Regression covered:

  * `scrollIntoView({block:'center'})` without `behavior` inherits a page's
    `html { scroll-behavior: smooth }` (GitHub) → the scroll animates
    asynchronously → the rect read in the same JS expression is still the
    pre-animation position → the mouse event is dispatched outside the viewport,
    where it has no target → the click is physically lost while the receipt
    claimed `verified: true`.

Real headless Chrome against deterministic fixture pages served by the repo's
own fixture server (tests/harness/scenarios.FixtureServer), on the shared
localhost:9222 CDP endpoint every other real-browser test uses. Skipped (never
red) when no browser can be brought up.
"""

import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action.cdp_act import cdp_click_handle
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixture pages ────────────────────────────────────────────────────
# The viewport is pinned through CDP (800×600 CSS px, dpr 1) so "outside the
# viewport" is a measured fact, not a guess. The target sits ~1500px down.

VIEWPORT_W, VIEWPORT_H = 800, 600
SPACER_PX = 1500
TARGET_LABEL = "Far Target"

_TEMPLATE = """<!doctype html><html><head><title>{title}</title>
<style>{html_style}</style></head>
<body style="margin:0">
  <div style="height:{spacer}px">top spacer</div>
  <button id="target" onclick="window.clicked=(window.clicked||0)+1">{label}</button>
  <div style="height:{spacer}px">bottom spacer</div>
</body></html>"""

PLAIN_HTML = _TEMPLATE.format(title="Viewport Plain", html_style="",
                              spacer=SPACER_PX, label=TARGET_LABEL)
# fixture B reproduces GitHub's condition exactly: the page animates scrolls.
SMOOTH_HTML = _TEMPLATE.format(title="Viewport Smooth",
                               html_style="html{scroll-behavior:smooth}",
                               spacer=SPACER_PX, label=TARGET_LABEL)
# fixture C: scrolling cannot succeed, so scrollIntoView can never bring the
# target in — the click point stays outside the viewport and must fail loudly.
# `html{overflow:hidden}` (the spec's suggestion) does NOT lock scrolling in
# current Chrome: overflow:hidden stays programmatically scrollable
# (measured: scrollIntoView moved scrollY 0 → 1211). The lock here is a
# non-scrollable clipped pane — the realistic "element inside a clipped
# container / virtualized list" case.
LOCKED_HTML = """<!doctype html><html><head><title>Viewport Locked</title></head>
<body style="margin:0">
  <div id="pane" style="position:relative;height:%dpx;overflow:clip">
    <div style="height:%dpx">top spacer</div>
    <button id="target" onclick="window.clicked=(window.clicked||0)+1">%s</button>
    <div style="height:%dpx">bottom spacer</div>
  </div>
</body></html>""" % (VIEWPORT_H, SPACER_PX, TARGET_LABEL, SPACER_PX)

PATHS = {"/viewport-plain": PLAIN_HTML,
         "/viewport-smooth": SMOOTH_HTML,
         "/viewport-locked": LOCKED_HTML}

_FX = None
_CHROME = runner.chrome_available()
if not _CHROME:  # same launcher path the kit uses; a missing binary is a SKIP
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
    """Open `path` in its own tab, pin the viewport, make it the session page.

    A fresh tab per test (the pattern tests/test_cdp_contract_real.py uses) means
    no other suite's leftover page state can leak in; the tab is closed again in
    tearDown.
    """
    tab = open_new_tab(_FX.url(path))
    deadline = time.time() + 10
    pages, idx = [], None
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            idx = match[0]
            _write_last(idx)      # resolve_page(None) == this tab for every call
            if _js("location.pathname") == path:
                break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{path} never loaded in tab {tab['id']}")
    ws = cdp_connect(pages[idx]["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        cdp_call(ws, "Emulation.setDeviceMetricsOverride",
                 {"width": VIEWPORT_W, "height": VIEWPORT_H,
                  "deviceScaleFactor": 1, "mobile": False}, msg_id=90)
    finally:
        ws.close()
    time.sleep(0.2)
    return tab


def _js(expr):
    """Evaluate `expr` in the session page; return its value."""
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, msg_id=91)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def _reset():
    """Fresh measurement conditions: top of the document, no recorded clicks.

    `behavior:'instant'` here too — on a smooth page a plain scrollTo(0,0) would
    merely start an animation.
    """
    return _js("(function(){window.scrollTo({top:0,behavior:'instant'});"
               "window.clicked=0;return window.scrollY;})()")


def _button_handle():
    """[idx] of the fixture's target button from a fresh a11y snapshot."""
    see = router.route_see(kind="a11y")
    if not see.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {see}")
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == "button" and TARGET_LABEL in (h.get("name") or ""):
            return idx
    raise AssertionError(f"button {TARGET_LABEL!r} not in the a11y handle map: "
                         f"{see.get('handles')}")


def _target_center_y():
    """Document-space y of the target's center — where a real scroll must land."""
    return _js("(function(){var r=document.getElementById('target')"
               ".getBoundingClientRect();return r.top+window.scrollY+r.height/2;})()")


def _clicked():
    return _js("window.clicked||0")


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class ViewportAlignment(unittest.TestCase):
    """Spec M1/M2: the click point must be inside the viewport before dispatch."""

    def setUp(self):
        self.tab = None

    def tearDown(self):
        """Close the tab this test opened (never the last remaining page)."""
        if not self.tab:
            return
        try:
            if len(list_pages()) > 1:
                req = urllib.request.Request(
                    f'{CDP_HOST}/json/close/{self.tab["id"]}', method="PUT")
                urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass

    # ── 1 ───────────────────────────────────────────────────────────
    def test_click_handle_outside_viewport_plain(self):
        """Outside-viewport click on a plain page really lands (M1)."""
        self.tab = _open_fixture("/viewport-plain")
        self.assertEqual(_reset(), 0)
        self.assertGreater(_target_center_y(), VIEWPORT_H,
                           "fixture is wrong: the target is already in the viewport")
        idx = _button_handle()
        r = cdp_click_handle(f"[{idx}]")
        self.assertTrue(r["verified"], r)
        self.assertIs(r["evidence"]["in_viewport"], True, r["evidence"])
        self.assertEqual(_clicked(), 1,
                         "receipt claimed ok but the page never saw the click")

    # ── 2 ───────────────────────────────────────────────────────────
    def test_click_handle_outside_viewport_smooth(self):
        """Core regression: the same click on a `scroll-behavior: smooth` page.

        The fixture must be genuinely dangerous — a plain `scrollIntoView()` on
        this page leaves `scrollY` untouched at the synchronous read (the
        animation cannot advance inside one JS expression), while
        `behavior:'instant'` lands the scroll in that same expression. That is
        precisely why M1 passes `instant`.
        """
        self.tab = _open_fixture("/viewport-smooth")
        self.assertEqual(
            _js("getComputedStyle(document.documentElement).scrollBehavior"),
            "smooth", "fixture does not reproduce GitHub's condition")
        self.assertGreater(_target_center_y(), VIEWPORT_H)
        # root cause, measured (the dogfooding probe from the spec)
        self.assertEqual(
            _js("(function(){document.getElementById('target')"
                ".scrollIntoView({block:'center'});return window.scrollY;})()"),
            0, "smooth scroll advanced synchronously — fixture not dangerous")
        self.assertEqual(_reset(), 0)
        self.assertGreater(
            _js("(function(){document.getElementById('target')"
                ".scrollIntoView({block:'center',behavior:'instant'});"
                "return window.scrollY;})()"),
            100, "behavior:'instant' did not scroll synchronously")
        self.assertEqual(_reset(), 0)
        idx = _button_handle()
        r = cdp_click_handle(f"[{idx}]")
        self.assertTrue(r["verified"], r)
        self.assertIs(r["evidence"]["in_viewport"], True, r["evidence"])
        self.assertEqual(_clicked(), 1,
                         "receipt claimed ok but the page never saw the click")

    # ── 3 ───────────────────────────────────────────────────────────
    def test_click_receipt_has_viewport_fields(self):
        """A successful handle click declares the geometry it verified."""
        self.tab = _open_fixture("/viewport-smooth")
        self.assertEqual(_reset(), 0)
        idx = _button_handle()
        r = cdp_click_handle(f"[{idx}]")
        self.assertTrue(r["verified"], r)
        ev = r["evidence"]
        self.assertEqual(ev["viewport"], {"w": VIEWPORT_W, "h": VIEWPORT_H}, ev)
        self.assertIs(ev["in_viewport"], True, ev)
        # the declared box really is inside the declared viewport (CSS px)
        self.assertTrue(0 <= ev["box"]["x"] < ev["viewport"]["w"], ev)
        self.assertTrue(0 <= ev["box"]["y"] < ev["viewport"]["h"], ev)
        self.assertEqual(_clicked(), 1)

    # ── 4 ───────────────────────────────────────────────────────────
    def test_click_viewport_locked_fails_loudly(self):
        """Scroll-locked page: the click point stays outside → explicit failure."""
        self.tab = _open_fixture("/viewport-locked")
        self.assertEqual(_reset(), 0)
        # the lock is real: nothing in the document can scroll
        self.assertEqual(
            _js("document.scrollingElement.scrollHeight"),
            _js("document.scrollingElement.clientHeight"),
            "fixture is wrong: the page can still be scrolled")
        self.assertGreater(_target_center_y(), VIEWPORT_H,
                           "fixture is wrong: the locked target became reachable")
        idx = _button_handle()
        r = cdp_click_handle(f"[{idx}]")
        self.assertFalse(r["verified"], r)
        reason = r["evidence"]["reason"]
        self.assertIn("outside viewport", reason)
        self.assertIn(f"({VIEWPORT_W}x{VIEWPORT_H})", reason)
        self.assertNotIn("in_viewport", r["evidence"],
                         "a receipt must not claim a check it aborted on")
        self.assertEqual(_clicked(), 0,
                         "a click outside the viewport reached the page")


if __name__ == "__main__":
    unittest.main()
