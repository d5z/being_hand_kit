"""L2 (real Chrome) — the dpr *tiers* nobody had exercised: 1.5 / 2.625 / 3.

Why this file exists: every dpr=2 sample the coordinate work has produced came
from one retina machine on one page. A constant 2 and the variable
`devicePixelRatio` are collinear there, so those samples prove "divided by 2",
not "divided by dpr". This file separates them by *changing the variable*:
`Emulation.setDeviceMetricsOverride(deviceScaleFactor=n)` makes the same page
report 1.5 / 2.625 / 3 without touching zoom or the machine.

Three things get pinned, and the first is the one that can hurt:

  * a coordinate computed under one dpr, dispatched under another, still
    reports success (the receipt is self-consistent and therefore blind) —
    `@expect` is what turns that into a `landed: false`
  * a declared fractional dpr that matches dispatches; that mismatches refuses
    *before* dispatch
  * rounding: physical px are rounded to integers, so the CSS error is
    0.5/dpr — largest at dpr=1, *smaller* at 1.5 / 2.625. The intuition
    "fractional ratios round worse" is backwards.

Skipped (never red) when no browser can be brought up.
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action.cdp_act import cdp_click_do
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains,
    _write_last, _element_info,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner

_CHROME = runner.chrome_available()
if not _CHROME:
    try:
        from hand.perception.cdp_launcher import ensure_chrome
        ensure_chrome()
    except Exception:
        pass
    _CHROME = runner.chrome_available()

# 100px box: a wrong-tier click usually still lands *in* it.
BIG = "big"
# 20px box far to the right: a wrong-tier click leaves it entirely.
SMALL = "small"

PAGE = (
    "data:text/html,<body style='margin:0'>"
    "<div id=big style='position:absolute;left:100.5px;top:100.5px;width:100px;"
    "height:100px;background:%23ddd' onclick=\"hit('big')\">b</div>"
    "<div id=small style='position:absolute;left:400px;top:300px;width:20px;"
    "height:20px;background:%23a00' onclick=\"hit('small')\">s</div>"
    "<script>window.hits=[];function hit(w){window.hits.push(w)}</script>"
    "</body>"
)


def _open():
    tab = open_new_tab(PAGE)
    deadline = time.time() + 10
    while time.time() < deadline:
        pages = list_pages()
        match = [i for i, p in enumerate(pages) if p.get("id") == tab["id"]]
        if match:
            _write_last(match[0])
            time.sleep(0.3)
            return tab
        time.sleep(0.2)
    raise AssertionError("fixture tab never appeared")


def _ws():
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    _init_domains(ws, "Runtime")
    return ws


def _ev(ws, expr):
    raw = cdp_call(ws, "Runtime.evaluate",
                   {"expression": expr, "returnByValue": True}, msg_id=91)
    return raw.get("result", {}).get("value")


def _set_dpr(ws, ratio):
    cdp_call(ws, "Emulation.setDeviceMetricsOverride",
             {"width": 800, "height": 600, "deviceScaleFactor": ratio,
              "mobile": False}, msg_id=90)
    deadline = time.time() + 5
    while time.time() < deadline:
        if _ev(ws, "window.devicePixelRatio") == ratio:
            return True
        time.sleep(0.1)
    return False


def _clear(ws):
    try:
        cdp_call(ws, "Emulation.clearDeviceMetricsOverride", {}, msg_id=90)
    except Exception:
        pass


def _hits(ws):
    return json.loads(_ev(ws, "JSON.stringify(window.hits||[])"))


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class DprTiers(unittest.TestCase):

    def setUp(self):
        self.tab = None
        self.ws = None

    def tearDown(self):
        if self.ws:
            try:
                _clear(self.ws)
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.tab:
            try:
                import urllib.request
                from hand.perception.cdp_core import CDP_HOST
                if len(list_pages()) > 1:
                    req = urllib.request.Request(
                        f'{CDP_HOST}/json/close/{self.tab["id"]}', method="PUT")
                    urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass
            self.tab = None

    def _page_at(self, ratio):
        self.tab = _open()
        self.ws = _ws()
        self.assertTrue(_set_dpr(self.ws, ratio),
                        "page refuses deviceScaleFactor=%r" % (ratio,))
        return self.ws

    # -- 1. the tiers are real -------------------------------------------------

    def test_fractional_ratios_are_honoured_by_the_page(self):
        """If Chrome clamped 1.5 -> 1 or 2, every test below would be vacuous."""
        for ratio in (1.5, 2.625):
            with self.subTest(ratio=ratio):
                ws = self._page_at(ratio)
                self.assertEqual(_ev(ws, "window.devicePixelRatio"), ratio)
                self.tearDown()

    def test_coordinate_from_the_same_tier_lands(self):
        for ratio in (1.5, 2.625):
            with self.subTest(ratio=ratio):
                ws = self._page_at(ratio)
                info = _element_info(ws, "#big")
                self.assertNotIn("error", info)
                r = cdp_click_do("xy:%d,%d@dpr=%s@expect=#big"
                                 % (round(info["x"]), round(info["y"]), ratio))
                self.assertEqual(r.get("landed"), True, r)
                self.assertEqual(r.get("hit_relation"), "self", r)
                self.assertEqual(_hits(ws), ["big"],
                                 "receipt says hit, page disagrees")
                self.tearDown()

    # -- 2. mixed tiers: self-consistent and wrong -----------------------------

    def test_mixed_tier_reports_success_while_missing_the_target(self):
        """Read at 1.5, dispatch at 2.625 — the receipt cannot see the pairing."""
        ws = self._page_at(1.5)
        info = _element_info(ws, "#small")
        physical = (round(info["x"]), round(info["y"]))
        self.assertTrue(_set_dpr(ws, 2.625))
        r = cdp_click_do("xy:%d,%d" % physical)
        self.assertEqual(r.get("result"), "ok", r)
        self.assertEqual(_hits(ws), [],
                         "wrong-tier click reached the target: the pairing is "
                         "not observable here")

        # Same physical point, now with the assumption handed over: refused,
        # and nothing is dispatched.
        r2 = cdp_click_do("xy:%d,%d@dpr=1.5" % physical)
        self.assertFalse(r2.get("verified", True), r2)
        self.assertIn("dpr mismatch", repr(r2))
        self.assertEqual(_hits(ws), [], "a refusal must not click")

    def test_matching_fractional_declaration_is_not_a_rounding_mismatch(self):
        """1.5 declared vs 1.5 read: equality must survive the float round-trip."""
        ws = self._page_at(1.5)
        info = _element_info(ws, "#big")
        r = cdp_click_do("xy:%d,%d@dpr=1.5"
                         % (round(info["x"]), round(info["y"])))
        self.assertNotIn("dpr mismatch", repr(r))
        self.assertEqual(_hits(ws), ["big"], r)

    # -- 3. rounding is worst at dpr=1, not at the fractional tiers ------------

    def test_rounding_error_shrinks_as_dpr_grows(self):
        """integer physical px => CSS error = up to 0.5/dpr."""
        errors = {}
        for ratio in (1, 1.5, 2.625):
            ws = self._page_at(ratio)
            raw = _ev(ws, "(()=>{const r=document.getElementById('big')"
                          ".getBoundingClientRect();return r.left+r.width/2})()")
            phys = raw * ratio
            back = round(phys) / ratio
            errors[ratio] = abs(back - raw)
            self.tearDown()
        self.assertLessEqual(errors[1], 0.5 + 1e-9)
        self.assertLess(errors[2.625], errors[1],
                        "fractional dpr must round *better* than dpr=1: %r"
                        % (errors,))
