"""L2 integration — real headless Chrome, one scenario per tool.

PRD docs/prd-test-framework.md L2: open / see(a11y) / see(interactive) /
see(dom) / click / type / shot / close, each verifying the receipt's evidence
chain rather than a bare "ok".

Deterministic fixtures (tests/harness/scenarios.FixtureServer) keep this layer
offline-safe: a throwaway HTTP server on 127.0.0.1.
"""

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, "/home/alice/Hand")

from hand import router
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab

from tests.harness import judge as J
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

_FX = None
_CHROME = runner.chrome_available()


def setUpModule():
    global _FX
    if _CHROME:
        _FX = FixtureServer()


def tearDownModule():
    if _FX:
        _FX.close()


def eval_js(expr):
    pages = list_pages()
    _, page = resolve_page(None, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, msg_id=77)
        return raw.get("result", {}).get("value")
    finally:
        ws.close()


def _find_handle(receipt, role=None, name=None):
    for idx, h in (receipt.get("handles") or {}).items():
        if role and h.get("role") != role:
            continue
        if name and name.lower() not in (h.get("name") or "").lower():
            continue
        return idx
    return None


@unittest.skipIf(not _CHROME, "Chrome unavailable")
class L2Tools(unittest.TestCase):

    # ── open ────────────────────────────────────────────────────────
    def test_open_navigate_confirmed(self):
        r = router.route_open(_FX.url("/basic"))
        J.assert_verdict(self, J.judge_open(r, expect_host="127.0.0.1", task="open"))

    def test_open_sets_place_and_session(self):
        r = router.route_open(_FX.url("/form"))
        self.assertEqual(r["place"]["type"], "browser")
        self.assertTrue(r["verified"])

    # ── see ─────────────────────────────────────────────────────────
    def test_see_a11y_tree_valid(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_see(kind="a11y")
        v = J.judge_a11y(r, task="see(a11y)")
        J.assert_verdict(self, v)
        # the tree must carry the fixture's heading as a real node
        self.assertIn("Fixture Basic", r["tree"])

    def test_see_interactive_legacy_format(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_see(kind="interactive")
        J.assert_verdict(self, J.judge_legacy_channel(r, "cdp_interactive",
                                                      task="see(interactive)"))

    def test_see_dom_legacy_format(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_see(kind="dom")
        J.assert_verdict(self, J.judge_legacy_channel(r, "cdp_snapshot", task="see(dom)"))
        self.assertIn("Fixture Basic", (r.get("text") or "") + (r.get("page_title") or ""))

    # ── click ───────────────────────────────────────────────────────
    def test_click_handle_hits_target(self):
        router.route_open(_FX.url("/basic"))
        see = router.route_see(kind="a11y")
        idx = _find_handle(see, role="button", name="Mark")
        self.assertIsNotNone(idx, "Mark button handle not found in a11y tree")
        # reset the counter so we can prove the click landed (not a fake ok)
        eval_js("window.clicked=0")
        r = router.route_do(f"[{idx}]")
        J.assert_verdict(self, J.judge_click(r, expect_name="Mark", task="click"))
        time.sleep(0.3)
        self.assertGreaterEqual(eval_js("window.clicked||0"), 1,
                                "click receipt claimed ok but the page never saw it")

    # ── type ────────────────────────────────────────────────────────
    def test_type_documented_flow_lands_text(self):
        """MCP flow: cdp_click('[idx]') to focus the field, then cdp_type(text)."""
        router.route_open(_FX.url("/form"))
        see = router.route_see(kind="a11y")
        idx = _find_handle(see, role="textbox")
        self.assertIsNotNone(idx, "Query textbox handle not found in a11y tree")
        focus = router.route_do(f"[{idx}]")
        J.assert_verdict(self, J.judge_click(focus, expect_name="Query", task="click-to-focus"))
        text = "hand-prod-test"
        from hand.action.cdp_act import cdp_type_focused
        r = cdp_type_focused(text)
        read_back = eval_js("document.querySelector('#q').value")
        J.assert_verdict(self, J.judge_type(r, text, read_back=read_back, task="type"))

    def test_type_handle_internal_path_lands_text(self):
        """Internal '[idx]|text' path (cdp_type_do) also focuses + verifies."""
        router.route_open(_FX.url("/form"))
        see = router.route_see(kind="a11y")
        idx = _find_handle(see, role="textbox")
        self.assertIsNotNone(idx, "Query textbox handle not found in a11y tree")
        text = "internal-path"
        from hand.action.cdp_act import cdp_type_do
        r = cdp_type_do(f"[{idx}]|{text}")
        read_back = eval_js("document.querySelector('#q').value")
        J.assert_verdict(self, J.judge_type(r, text, read_back=read_back, task="type(handle)"))

    # ── shot ────────────────────────────────────────────────────────
    def test_shot_returns_real_png(self):
        router.route_open(_FX.url("/basic"))
        r = router.route_screenshot(with_data=True)
        J.assert_verdict(self, J.judge_screenshot(r, task="shot"))
        self.assertTrue(r["data"].startswith("iVBORw0KGgo"),
                        "screenshot data is not a PNG header")

    # ── close ───────────────────────────────────────────────────────
    def test_close_tab_no_residual_processes(self):
        router.route_open(_FX.url("/basic"))   # keep a live session
        base_pages = len(list_pages())
        base_procs = runner.chrome_proc_count()
        for _ in range(2):
            tab = open_new_tab(_FX.url("/basic"))
            time.sleep(0.5)
            req = urllib.request.Request(f"{CDP_HOST}/json/close/{tab['id']}", method="PUT")
            urllib.request.urlopen(req, timeout=5).read()
        time.sleep(1.0)
        pages = list_pages()
        self.assertEqual(len(pages), base_pages, "closed tabs still listed")
        procs = runner.chrome_proc_count()
        # closing tabs must not leak renderer processes (allow +1 slack for the
        # tab we kept open / transient zygote accounting)
        self.assertLessEqual(procs, base_procs + 1,
                             f"process leak: {base_procs} -> {procs}")
        # the browser itself is still alive (endpoint-level close is L6)


if __name__ == "__main__":
    unittest.main()
