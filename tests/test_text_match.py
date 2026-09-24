"""L2 tests for hand 0.9.4-P2 — `text=` matches nested text.

Spec: docs/spec-0.9.4-p2-textmatch.md. Regression covered:

  * the `text=` XPath used `text()`, which matches only *direct* text children.
    A link whose label lives in a nested element (`<a><span>Title</span></a>` —
    GitHub issues and most modern sites) therefore never matched: measured on
    2026-09-24, `//a[contains(text(),"…")]` was false while `//a[contains(.,"…")]`
    was true with an *empty* direct-text child set.
  * the third branch (`//*[text()="q"]`) was an exact match, so a prefix query
    could not fall through to it.

The fix uses `normalize-space(.)` on all three branches (full string value,
whitespace folded) and, when nothing is found, runs one loose a/button scan so
the failure receipt carries `candidates` instead of a bare "not found".

Real headless Chrome against fixture pages served by the repo's own fixture
server (tests/harness/scenarios.FixtureServer), on the shared localhost:9222
CDP endpoint the other real-browser suites use. Skipped (never red) when no
browser can be brought up.
"""

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action.cdp_act import cdp_click_do
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixture page ─────────────────────────────────────────────────────
# Exactly the spec's structure: a nested-text link, a nested-text button, a
# plain link — plus an element whose text matches *only* the third (exact)
# branch, so that branch is exercised too. Every clickable records the click,
# so a receipt claiming a hit can be checked against the page itself.

FIXTURE_HTML = """<!doctype html><html><head><title>Text Match</title></head>
<body style="margin:0">
  <a id="nested" href="#" onclick="window.clicked=(window.clicked||0)+1;return false"><span>Nested Target</span></a>
  <button id="deep" onclick="window.clicked=(window.clicked||0)+1"><em>Deep Button</em></button>
  <a id="plain" href="#" onclick="window.clicked=(window.clicked||0)+1;return false">Plain Link</a>
  <div id="exact">Exact Only</div>
</body></html>"""

PATHS = {"/text-match": FIXTURE_HTML}

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
    """Fresh measurement conditions: no recorded clicks."""
    return _js("(function(){window.clicked=0;return window.clicked;})()")


def _clicked():
    return _js("window.clicked||0")


def _xpath_hits(xpath):
    """Does `xpath` match anything? Used to prove the old branch missed."""
    expr = ("(function(){var r=document.evaluate(" + json.dumps(xpath)
            + ",document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);"
            + "return r.singleNodeValue!==null;})()")
    return _js(expr)


def _direct_text_of_nested_link():
    """The nested link's direct text children, concatenated (spec: empty)."""
    return _js("(function(){var a=document.getElementById('nested');"
               "var out='';for(var i=0;i<a.childNodes.length;i++){"
               "if(a.childNodes[i].nodeType===3)out+=a.childNodes[i].nodeValue;}"
               "return out;})()")


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class TextMatch(unittest.TestCase):
    """Spec 0.9.4-P2: `text=` must see nested text, and misses must be diagnosable."""

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
    def test_text_match_nested_span(self):
        """The core regression: the label lives in a nested <span>.

        The fixture must be genuinely dangerous — the pre-fix XPath
        (`contains(text(),…)`) must miss on it *because* the link's direct text
        children are empty, while `contains(.,…)` hits.
        """
        self.tab = _open_fixture("/text-match")
        self.assertEqual(_reset(), 0)
        # root cause, measured (the dogfooding probe from the spec)
        self.assertEqual(_direct_text_of_nested_link(), "",
                         "fixture is not dangerous: the link has direct text")
        self.assertFalse(_xpath_hits('//a[contains(text(), "Nested Target")]'),
                         "the pre-fix text() XPath already matched — fixture not dangerous")
        self.assertTrue(_xpath_hits('//a[contains(., "Nested Target")]'),
                        "contains(.) must hit the nested label")
        # the fix
        r = cdp_click_do("text=Nested Target")
        self.assertTrue(r["verified"], r)
        self.assertEqual(r["tag"], "A", r)
        self.assertIn("Nested Target", r["evidence"]["element"], r["evidence"])
        self.assertEqual(_clicked(), 1,
                         "receipt claimed a hit but the page never saw the click")

    # ── 2 ───────────────────────────────────────────────────────────
    def test_text_match_prefix(self):
        """`contains` semantics survive the switch to `.` (prefix query hits)."""
        self.tab = _open_fixture("/text-match")
        self.assertEqual(_reset(), 0)
        # dangerously nested, but queried by prefix: the pre-fix XPath misses it
        # (the button's direct text children are empty) while contains(.) hits.
        self.assertFalse(_xpath_hits('//button[contains(text(), "Deep")]'),
                         "fixture is not dangerous: the pre-fix XPath matched")
        self.assertTrue(_xpath_hits('//button[contains(., "Deep")]'))
        r = cdp_click_do("text=Deep")
        self.assertTrue(r["verified"], r)
        self.assertEqual(r["tag"], "BUTTON", r)
        self.assertIn("Deep Button", r["evidence"]["element"], r["evidence"])
        self.assertEqual(_clicked(), 1)

        # a plain link keeps working as a prefix query too (contains semantics)
        self.assertEqual(_reset(), 0)
        r2 = cdp_click_do("text=Plain")
        self.assertTrue(r2["verified"], r2)
        self.assertEqual(r2["tag"], "A", r2)
        self.assertEqual(_clicked(), 1)

    # ── 3 ───────────────────────────────────────────────────────────
    def test_text_match_exact_branch(self):
        """Third branch: full-string exact match, and it stays *exact*."""
        self.tab = _open_fixture("/text-match")
        self.assertEqual(_reset(), 0)
        r = cdp_click_do("text=Plain Link")
        self.assertTrue(r["verified"], r)
        self.assertEqual(r["tag"], "A", r)

        # a non-a/button element is only reachable through the exact branch
        r2 = cdp_click_do("text=Exact Only")
        self.assertTrue(r2["verified"], r2)
        self.assertEqual(r2["tag"], "DIV", r2)

        # …and that branch is `=`, not `contains`: a prefix of it must not hit
        r3 = cdp_click_do("text=Exact Onl")
        self.assertFalse(r3["verified"], r3)
        self.assertIn("text element not found", r3["error"])

    # ── 4 ───────────────────────────────────────────────────────────
    def test_text_match_not_found_returns_candidates(self):
        """A miss names the closest a/button labels instead of guessing."""
        self.tab = _open_fixture("/text-match")
        self.assertEqual(_reset(), 0)
        # a case miss: the label exists, the (case-sensitive) XPath does not hit
        self.assertTrue(_xpath_hits('//a[contains(normalize-space(.), "Nested Target")]'))
        r = cdp_click_do("text=nested target")
        self.assertFalse(r["verified"], r)
        self.assertIn("text element not found", r["error"])
        cands = r["candidates"]
        self.assertEqual(len(cands), 1, cands)
        self.assertEqual(cands[0]["tag"], "A", cands)
        self.assertEqual(cands[0]["text"], "Nested Target", cands)
        self.assertEqual(cands[0]["href"], "#", cands)
        # both places a diagnosing caller may look carry the same list
        self.assertEqual(r["evidence"]["candidates"], cands)
        self.assertEqual(_clicked(), 0, "a failed match clicked something")

        # nothing similar on the page → an honest empty list, not a guess
        r2 = cdp_click_do("text=nothing-like-this-exists")
        self.assertFalse(r2["verified"], r2)
        self.assertEqual(r2["candidates"], [], r2)
        self.assertEqual(_clicked(), 0)

    # ── 5 ───────────────────────────────────────────────────────────
    def test_text_match_case_sensitive(self):
        """Match semantics stay case-sensitive (spec 边界) — unchanged by P2."""
        self.tab = _open_fixture("/text-match")
        self.assertEqual(_reset(), 0)
        for query in ("plain link", "deep button", "nested target"):
            r = cdp_click_do(f"text={query}")
            self.assertFalse(r["verified"], f"{query!r} must not hit: {r}")
            self.assertIn("text element not found", r["error"])
        self.assertEqual(_clicked(), 0)


if __name__ == "__main__":
    unittest.main()
