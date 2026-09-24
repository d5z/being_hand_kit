"""L2 tests for hand 0.9.4-P1 — handle-table staleness signal (nav anchor).

Spec: docs/spec-0.9.4-p1-handle-staleness.md. Regression covered:

  * the `[idx]` handle map is a snapshot taken at `cdp_see` time. After a page
    navigation the old table is dead, but a being reusing a handle had no way
    to know: the stale signal only appeared as a failure *after* a wasted
    round-trip (or worse, a lucky click on a coincidentally-matching point).
  * the fix adds one browser-side anchor — `Page.getNavigationHistory`'s
    currentEntry index — to the see receipt (`nav_id`, top level) and to the
    handle map file. `cdp_click_handle` / `cdp_type_handle` read the index again
    at action time and, when it moved, put a warning in **evidence**
    (design decision #1: warnings belong to the receipt's check-declaration
    area, not its top level).

The fixtures navigate for real, in new tabs on the shared localhost:9222 CDP
endpoint. Skipped (never red) when no browser can be brought up.
"""

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router
from hand.action import cdp_act
from hand.action.cdp_act import cdp_click_handle, cdp_type_handle, STALE_WARNING
from hand.perception import ax_tree as ax
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixture pages ────────────────────────────────────────────────────
# A and B are two ordinary documents. `see` snapshots A; the link navigates to
# B; the handles taken from A are then dead (their backendNodeIds belong to A's
# DOM) and the navigation anchor proves *why*.

PAGE_A = """<!doctype html><html><head><title>Stale A</title></head>
<body style="margin:0">
  <h1>Stale A</h1>
  <h2 id="ah">Alpha Heading</h2>
  <input id="q" type="text" aria-label="Alpha Field">
  <a id="tob" href="/stale-b">Go B</a>
</body></html>"""

PAGE_B = """<!doctype html><html><head><title>Stale B</title></head>
<body style="margin:0">
  <h1>Stale B</h1>
  <h2 id="bh">Beta Heading</h2>
</body></html>"""

PATHS = {"/stale-a": PAGE_A, "/stale-b": PAGE_B}

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
    """Open `path` in its own tab and make it the session page."""
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


def _wait_path(path, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _js("location.pathname") == path:
            return True
        time.sleep(0.2)
    return False


def _handle_named(see, role, name):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and name in (h.get("name") or ""):
            return idx
    raise AssertionError(f"{role} {name!r} not in the a11y handle map: "
                         f"{see.get('handles')}")


def _see():
    r = router.route_see(kind="a11y")
    if not r.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {r}")
    return r


@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class HandleStalenessLive(unittest.TestCase):
    """Spec M1/M2 against a real browser: the anchor is real, the warning fires."""

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
    def test_see_receipt_has_nav_anchor(self):
        """a11y see carries `nav_id` (top level) and persists it in the map."""
        self.tabs.append(_open_fixture("/stale-a"))
        see = _see()
        self.assertIn("nav_id", see, see.keys())
        self.assertIsInstance(see["nav_id"], int, see["nav_id"])
        # evidence mirrors it (same check-declaration area the warning uses)
        self.assertEqual(see["evidence"]["nav_id"], see["nav_id"])
        # the anchor is browser-side state, so the cross-process handle map file
        # must carry it too — that file is what a later click reads.
        with open(ax.HANDLE_MAP_FILE) as f:
            saved = json.load(f)
        self.assertEqual(saved.get(ax.NAV_ID_KEY), see["nav_id"])
        # the anchor survives through the map-loading accessor
        self.assertEqual(ax.handle_map_nav_id(), see["nav_id"])

    # ── 2 ───────────────────────────────────────────────────────────
    def test_click_after_navigation_warns(self):
        """see → navigate → click an old handle → stale warning, and it fails."""
        self.tabs.append(_open_fixture("/stale-a"))
        see = _see()
        heading = _handle_named(see, "heading", "Alpha Heading")
        link = _handle_named(see, "link", "Go B")
        see_nav = see["nav_id"]

        # navigate for real, by clicking the fixture's link handle
        nav = cdp_click_handle(f"[{link}]")
        self.assertTrue(nav["verified"], nav)
        self.assertTrue(_wait_path("/stale-b"),
                        "fixture link did not navigate")

        # the old heading handle is reused: gone, and now *declared* stale
        r = cdp_click_handle(f"[{heading}]")
        self.assertFalse(r["verified"], r)
        self.assertNotEqual(r["evidence"]["nav_id_at_action"], see_nav,
                            "the fixture navigation did not move the anchor")
        self.assertIn(STALE_WARNING, r["evidence"].get("warnings") or [],
                      r["evidence"])
        # design decision #1: the warning is a check product → evidence, never
        # a new top-level receipt field
        self.assertNotIn("warnings", r)
        self.assertIn("cdp_see", r["evidence"]["reason"])

    # ── 3 ───────────────────────────────────────────────────────────
    def test_click_same_page_no_warning(self):
        """see → click (no navigation) → anchor unchanged, no warning."""
        self.tabs.append(_open_fixture("/stale-a"))
        see = _see()
        heading = _handle_named(see, "heading", "Alpha Heading")
        r = cdp_click_handle(f"[{heading}]")
        self.assertTrue(r["verified"], r)
        self.assertEqual(r["evidence"]["nav_id_at_action"], see["nav_id"])
        self.assertNotIn("warnings", r["evidence"], r["evidence"])

    # ── 4 ───────────────────────────────────────────────────────────
    def test_type_after_navigation_warns(self):
        """The same anchor guards `cdp_type_handle` (spec M2 names both)."""
        self.tabs.append(_open_fixture("/stale-a"))
        see = _see()
        field = _handle_named(see, "textbox", "Alpha Field")
        link = _handle_named(see, "link", "Go B")
        link_nav = cdp_click_handle(f"[{link}]")
        self.assertTrue(link_nav["verified"], link_nav)
        self.assertTrue(_wait_path("/stale-b"))

        r = cdp_type_handle(f"[{field}]", "hello")
        self.assertFalse(r["verified"], r)
        self.assertEqual(r["text"], "hello")
        self.assertIn(STALE_WARNING, r["evidence"].get("warnings") or [],
                      r["evidence"])
        self.assertNotIn("warnings", r)


# ── no-browser units: the anchor plumbing and warning rule ───────────

class NavAnchorUnits(unittest.TestCase):
    def test_handle_map_round_trips_nav_anchor(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.json")
            ax.save_handle_map({"2": {"role": "link", "name": "a"}}, path=p,
                               nav_id=7)
            self.assertEqual(ax.handle_map_nav_id(p), 7)
            self.assertEqual(ax.resolve_handle("[2]", path=p)["_see_nav_id"], 7)
            # a rejected (non-int) anchor is not written at all
            ax.save_handle_map({"2": {"role": "link", "name": "a"}}, path=p,
                               nav_id="7")
            self.assertIsNone(ax.handle_map_nav_id(p))

    def test_resolve_handle_without_anchor_is_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.json")
            ax.save_handle_map({"2": {"role": "link", "name": "a"}}, path=p)
            self.assertIsNone(ax.resolve_handle("[2]", path=p)["_see_nav_id"])

    def test_unknown_anchor_never_warns(self):
        # a moved anchor warns …
        self.assertIn(STALE_WARNING,
                      cdp_act._nav_evidence(0, 1)["warnings"])
        # … an unknown anchor on either side is silent (no fabricated match)
        self.assertNotIn("warnings", cdp_act._nav_evidence(None, 1))
        self.assertNotIn("warnings", cdp_act._nav_evidence(0, None))
        self.assertNotIn("warnings", cdp_act._nav_evidence(3, 3))
        self.assertEqual(cdp_act._nav_evidence(3, 3)["nav_id_at_action"], 3)

    def test_unreadable_navigation_history_is_none(self):
        from unittest import mock
        with mock.patch.object(cdp_act, "cdp_call",
                               side_effect=RuntimeError("no Page domain")):
            self.assertIsNone(cdp_act._read_nav_id(mock.Mock()))
        with mock.patch.object(cdp_act, "cdp_call", return_value={}):
            self.assertIsNone(cdp_act._read_nav_id(mock.Mock()))


if __name__ == "__main__":
    unittest.main()
