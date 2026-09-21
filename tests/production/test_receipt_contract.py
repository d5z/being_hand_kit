"""L4 contract — full receipt scan + anti-fake-ok detection.

PRD L4: every receipt's required fields, evidence truthfulness, three-state
honesty, and — the soul of this layer — deliberately broken scenarios whose
receipts must NOT claim ok (feedback-ledger 3339b7f institutionalised).

Broken scenarios: bad DNS domain, missing element, missing [idx] handle,
never-answering page (timeout), and a CDP failure with no browser.
"""

import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, "/home/alice/Hand")

from hand import router
from hand.perception import cdp_core
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains,
)

from tests.harness import judge as J
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

_FX = None
_SKIP = None

# Fields the implemented F14 receipt contract guarantees (docs/prd-receipt-contract.md S3).
OUTCOME_KEYS = ("open", "method", "closed")


def setUpModule():
    global _FX, _SKIP
    if not runner.chrome_available():
        _SKIP = "Chrome CDP endpoint not reachable"
        return
    _FX = FixtureServer()


def tearDownModule():
    if _FX:
        _FX.close()


def _receipt_ok_shape(r):
    """(ok, problem) for the implemented receipt contract."""
    if not isinstance(r, dict):
        return False, f"not a dict: {type(r).__name__}"
    if not any(k in r for k in OUTCOME_KEYS):
        return False, f"no outcome field {OUTCOME_KEYS}: keys={sorted(r)[:8]}"
    if "verified" not in r or not isinstance(r["verified"], bool):
        return False, f"verified missing/non-bool: {r.get('verified')!r}"
    ev = r.get("evidence")
    if not isinstance(ev, dict):
        return False, f"evidence missing/not-dict: {ev!r}"
    if not isinstance(ev.get("verified"), bool):
        return False, f"evidence.verified missing/non-bool: {ev.get('verified')!r}"
    if r["verified"] is False and not (ev.get("reason") or r.get("error") or ev.get("detail")):
        return False, "verified=False with no reason/error/detail (silent failure)"
    return True, ""


def _eval(expr):
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        return cdp_call(ws, "Runtime.evaluate",
                        {"expression": expr, "returnByValue": True},
                        msg_id=91).get("result", {}).get("value")
    finally:
        ws.close()


@unittest.skipIf(_SKIP is not None, "Chrome unavailable")
class L4ReceiptContract(unittest.TestCase):

    # ── A. field completeness over a real call sweep ────────────────
    def test_receipt_field_completeness_sweep(self):
        router.route_open(_FX.url("/basic"))
        receipts = {}
        receipts["open"] = router.route_open(_FX.url("/basic"))
        receipts["see.a11y"] = router.route_see(kind="a11y")
        receipts["see.dom"] = router.route_see(kind="dom")
        receipts["see.interactive"] = router.route_see(kind="interactive")
        receipts["scroll"] = router.route_do("scroll down")
        receipts["shot"] = router.route_screenshot()
        see = receipts["see.a11y"]
        idx = next(k for k, h in see["handles"].items() if h["role"] == "button")
        receipts["click"] = router.route_do(f"[{idx}]")
        receipts["type"] = router.route_do(f"[{idx}]|sweep-text")
        bad = []
        for name, r in receipts.items():
            ok, problem = _receipt_ok_shape(r)
            if not ok:
                bad.append(f"{name}: {problem}")
        self.assertEqual(bad, [], "receipts violating the field contract:\n" + "\n".join(bad))

    def test_open_evidence_url_is_the_live_document(self):
        url = _FX.url("/form")
        r = router.route_open(url)
        self.assertTrue(r["verified"])
        live = _eval("location.href")
        self.assertIn("127.0.0.1", live, "open claimed verified but live doc is elsewhere")
        self.assertIn(_FX.url("/form"), live)

    def test_click_evidence_backend_node_resolves(self):
        router.route_open(_FX.url("/basic"))
        see = router.route_see(kind="a11y")
        idx = next(k for k, h in see["handles"].items() if h["role"] == "button")
        r = router.route_do(f"[{idx}]")
        self.assertTrue(r["verified"])
        bid = r["evidence"]["backend_node_id"]
        pages = list_pages()
        _, page = resolve_page(None, pages)
        ws = cdp_connect(page["webSocketDebuggerUrl"])
        try:
            _init_domains(ws, "Runtime")
            cdp_call(ws, "DOM.getDocument", {"depth": 0}, msg_id=94)
            res = cdp_call(ws, "DOM.resolveNode", {"backendNodeId": bid}, msg_id=95)
            self.assertTrue(res.get("object", {}).get("objectId"),
                            "click evidence names a backendNodeId that does not resolve")
        finally:
            ws.close()

    def test_selector_click_evidence_matches_a_real_element(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_do("#mark")
        self.assertTrue(r["verified"])
        tag = _eval("document.querySelector('#mark').tagName")
        self.assertEqual(tag.upper(), "BUTTON")

    # ── B. anti-fake-ok: deliberately broken scenarios ──────────────
    def test_bad_domain_open_is_not_fake_ok(self):
        r = router.route_open("https://nonexistent-xyz-123.invalid")
        J.assert_verdict(self, J.judge_honest_failure(
            r, expect_reason="NOT_RESOLVED", task="open(bad-domain)"))
        self.assertEqual(r["evidence"]["level"], "endpoint_alive")

    def test_missing_element_click_is_not_fake_ok(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_do("#definitely-not-here-xyz-123")
        J.assert_verdict(self, J.judge_honest_failure(
            r, expect_reason="did not match", task="click(missing-element)"))

    def test_missing_handle_click_is_not_fake_ok(self):
        router.route_open(_FX.url("/basic"))
        router.route_see(kind="a11y")
        r = router.route_do("[999999]")
        J.assert_verdict(self, J.judge_honest_failure(
            r, expect_reason="not in the last AX snapshot", task="click(missing-handle)"))

    def test_type_without_focus_is_not_fake_ok(self):
        from hand.action.cdp_act import cdp_type_focused
        router.route_open(_FX.url("/form"))   # nothing focused on load
        r = cdp_type_focused("should-not-land")
        J.assert_verdict(self, J.judge_honest_failure(
            r, expect_reason="no focused element", task="type(no-focus)"))

    def test_hanging_page_open_is_not_fake_ok(self):
        """A never-answering server: Page.navigate times out; receipt honest."""
        router.route_open(_FX.url("/basic"))
        orig = cdp_core.cdp_call

        def fast_call(ws, method, params=None, msg_id=1, timeout=None):
            return orig(ws, method, params if params is not None else {}, msg_id,
                        timeout=6)

        try:
            with mock.patch.object(cdp_core, "cdp_call", fast_call):
                t0 = time.time()
                r = router.route_open(_FX.blackhole_url("/slow"))
                elapsed = time.time() - t0
            J.assert_verdict(self, J.judge_honest_failure(
                r, expect_reason="timed out", task="open(hanging-page)"))
            self.assertLess(elapsed, 20, f"open of a hanging page took {elapsed:.1f}s")
        finally:
            _FX.release_held()
            router.route_open(_FX.url("/basic"))   # recover the browser

    def test_see_without_browser_is_error_receipt(self):
        """CDP dead -> route_see must return an error receipt, not a fake tree.

        The a11y channel resolves `list_pages` inside hand.perception.ax_tree,
        so the dead-CDP condition is injected there (the transport symbol), and
        the no-kind fallback chain is injected at every browser backend.
        """
        import hand.perception.ax_tree as ax_tree
        import hand.perception.cdp_snapshot as cdp_snapshot
        import hand.perception.cdp_network as cdp_network
        boom = RuntimeError("CDP unreachable")
        with mock.patch.object(ax_tree, "list_pages", side_effect=boom), \
             mock.patch.object(cdp_snapshot, "list_pages", side_effect=boom), \
             mock.patch.object(cdp_network, "list_pages", side_effect=boom):
            r_a11y = router.route_see(kind="a11y")
            router.route_open(_FX.url("/basic"))
            with mock.patch.object(ax_tree, "list_pages", side_effect=boom), \
                 mock.patch.object(cdp_snapshot, "list_pages", side_effect=boom), \
                 mock.patch.object(cdp_network, "list_pages", side_effect=boom):
                r_auto = router.route_see()
        J.assert_verdict(self, J.judge_error_receipt(r_a11y, task="see(a11y,no-browser)"))
        self.assertFalse(r_a11y["verified"])
        J.assert_verdict(self, J.judge_honest_failure(r_auto, task="see(auto,no-browser)"))

    def test_route_do_with_text_form_never_silently_passes(self):
        """Regression guard: route_do('[idx]|text') must type OR fail loudly —
        never return a bare ok while doing nothing (the 3339b7f fake-ok shape).

        KNOWN GAP (see REPORT-production.md): route_do does not fall through
        from a failing cdp_click to cdp_type, so today this returns an honest
        failure receipt. The public flow (click to focus, then type) works.
        """
        extras = []
        fx = _FX
        router.route_open(fx.url("/form"))
        see = router.route_see(kind="a11y")
        idx = next(k for k, h in see["handles"].items() if h["role"] == "textbox")
        r = router.route_do(f"[{idx}]|loud-failure")
        if r.get("verified") is True:
            v = J.judge_type(r, "loud-failure", read_back=_eval("document.querySelector('#q').value"),
                             task="route_do(text-form)")
            J.assert_verdict(self, v)
        else:
            J.assert_verdict(self, J.judge_honest_failure(r, task="route_do(text-form)"))


if __name__ == "__main__":
    unittest.main()
