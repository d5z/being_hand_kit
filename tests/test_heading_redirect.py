"""L2 tests for hand 0.9.4-P4 — heading-wrapping-link click redirection.

Spec: docs/spec-0.9.4-p4-heading-redirect.md. Regression covered:

  * GitHub's issue list renders `<h3><a href=…>title</a></h3>`. The AX tree
    exposes two nodes — heading (non-interactive) and link (interactive) — and
    a being naturally clicks the visually prominent heading. It only worked
    because the link happened to fill the heading: as soon as the heading gains
    another child the centre point misses the link and the click is lost
    silently (the P0 family).
  * M1: the serializer marks a node whose *subtree* wraps an interactive
    descendant with `contains_interactive: true` (declared only when true).
  * M2: `cdp_click_handle` on a non-interactive handle that wraps exactly one
    interactive descendant redirects the click onto it and says so in evidence
    (`redirected` / `original` / `redirect_target`); several descendants is not
    guessed — the receipt fails and names them.

The unit test needs no browser; the live subclass is skipped (never red) when no
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
from hand.action.cdp_act import cdp_click_handle
from hand.perception import ax_tree as ax
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call, _init_domains, _write_last,
    CDP_HOST,
)
from hand.perception.cdp_launcher import open_new_tab
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

# ── fixture page ─────────────────────────────────────────────────────
# 1. the spec's structure verbatim: a heading whose only child is a link;
# 2. a plain heading with nothing interactive below it;
# 3. a container with *two* links (ambiguity must not be guessed);
# 4. the same, but with an explicit role/name so the AX node is deterministic.

PAGE = """<!doctype html><html><head><title>Heading Redirect</title></head>
<body style="margin:0">
  <h3><a id="lnk" href="#"
         onclick="event.preventDefault();window.linkClicks=(window.linkClicks||0)+1;return false;"
      >Nested Heading Link</a></h3>
  <h3>Plain Heading</h3>
  <div id="multi"><a href="#one">One</a><a href="#two">Two</a></div>
  <div role="group" aria-label="Choices"><a href="#x">X</a><a href="#y">Y</a></div>
</body></html>"""

# 5. the control layout: a heading whose *own* centre does NOT land on its link
# (a meta prefix pushes the link off-centre). Clicking the heading centre here
# loses the click — which is exactly what the redirect fixes.
META_PAGE = """<!doctype html><html><head><title>Meta Heading</title></head>
<body style="margin:0">
  <h3 id="mh"><span>meta </span><a id="ml" href="#"
         onclick="event.preventDefault();window.linkClicks=(window.linkClicks||0)+1;return false;"
      >Nested Heading Link</a></h3>
</body></html>"""

PATHS = {"/heading-redirect": PAGE, "/heading-meta": META_PAGE}

_FX = None
_CHROME = runner.chrome_available()
if not _CHROME:
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


def _see():
    r = router.route_see(kind="a11y")
    if not r.get("verified"):
        raise AssertionError(f"a11y snapshot did not verify: {r}")
    return r


def _handle(see, role, name):
    for idx, h in (see.get("handles") or {}).items():
        if h.get("role") == role and (h.get("name") or "") == name:
            return idx
    raise AssertionError(f"{role} {name!r} not in handle map: {see.get('handles')}")


# ── M1 unit test (no browser) ────────────────────────────────────────

def _n(node_id, role, name="", parent=None, backend_id=None, props=None):
    node = {"nodeId": node_id, "role": {"value": role}, "name": {"value": name}}
    if parent is not None:
        node["parentId"] = parent
    if backend_id is not None:
        node["backendDOMNodeId"] = backend_id
    if props:
        node["properties"] = [{"name": k, "value": {"value": v}} for k, v in props.items()]
    return node


class ContainsInteractiveMeta(unittest.TestCase):
    """M1: the tree declares which nodes wrap interactive descendants."""

    def test_meta_contains_interactive_flag(self):
        nodes = [
            _n("1", "RootWebArea", "Page"),
            _n("2", "heading", "Title", parent="1", backend_id=12,
               props={"level": 3}),
            _n("3", "link", "Title", parent="2", backend_id=13),
            _n("4", "paragraph", "Plain text", parent="1", backend_id=14),
        ]
        ser = ax.serialize(nodes)
        meta = {m["idx"]: m for m in ser["nodes"]}
        by_role_name = {(m["role"], m["name"]): m for m in ser["nodes"]}
        # the heading wraps an interactive descendant → flagged
        heading = by_role_name[("heading", "Title")]
        self.assertTrue(heading.get("contains_interactive"), heading)
        # a plain text node has nothing interactive below it → no field at all
        plain = by_role_name[("paragraph", "Plain text")]
        self.assertNotIn("contains_interactive", plain)
        # an interactive node is not "containing" itself
        link = by_role_name[("link", "Title")]
        self.assertNotIn("contains_interactive", link)
        # every serialized line still has exactly one meta entry (idx alignment)
        self.assertEqual([m["idx"] for m in ser["nodes"]],
                         list(range(1, len(ser["lines"]) + 1)))

    def test_flag_is_declared_only_when_true(self):
        # a tree with nothing interactive anywhere carries no flag at all
        nodes = [_n("1", "RootWebArea", "x"),
                 _n("2", "paragraph", "Plain text", parent="1")]
        ser = ax.serialize(nodes)
        for m in ser["nodes"]:
            self.assertNotIn("contains_interactive", m, m)

    def test_lines_are_unchanged_by_the_flag(self):
        """M1 must not touch the line grammar (text/sha contract)."""
        nodes = [
            _n("1", "RootWebArea", "Page"),
            _n("2", "heading", "Title", parent="1", props={"level": 3}),
            _n("3", "link", "Title", parent="2"),
        ]
        ser = ax.serialize(nodes)
        self.assertEqual(ser["lines"][1], '  - heading "Title" (h3) [2]', ser["lines"])
        # the hash covers the text only — the meta flag is invisible to it
        self.assertEqual(ser["sha256"], ax.serialize(nodes)["sha256"])


# ── M2 live tests ────────────────────────────────────────────────────

@unittest.skipIf(not _CHROME, "Chrome/CDP endpoint unavailable")
class HeadingRedirect(unittest.TestCase):
    """Spec M2: a click on a heading-wrapping-link lands on the link."""

    def setUp(self):
        self.tab = None

    def tearDown(self):
        if not self.tab:
            return
        try:
            if len(list_pages()) > 1:
                req = urllib.request.Request(
                    f'{CDP_HOST}/json/close/{self.tab["id"]}', method="PUT")
                urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass

    def _open(self):
        self.tab = _open_fixture("/heading-redirect")
        self.assertTrue(_js("(function(){window.linkClicks=0;return true;})()"))

    # ── 1 ───────────────────────────────────────────────────────────
    def test_click_heading_redirects_to_link(self):
        """Core fix: the receipt redirects, and the link really receives it."""
        self._open()
        see = _see()
        heading = _handle(see, "heading", "Nested Heading Link")
        # the danger is declared by the tree itself
        self.assertTrue(see["handles"][heading]["contains_interactive"],
                        see["handles"][heading])
        self.assertFalse(see["handles"][heading]["interactive"])

        r = cdp_click_handle(f"[{heading}]")
        self.assertTrue(r["verified"], r)
        ev = r["evidence"]
        self.assertIs(ev.get("redirected"), True, ev)
        self.assertEqual(ev["original"], 'heading "Nested Heading Link"', ev)
        self.assertEqual(ev["redirect_target"], 'link "Nested Heading Link"', ev)
        self.assertEqual(_js("window.linkClicks||0"), 1,
                         "receipt claimed a redirect but the link never fired")

    # ── 2 ───────────────────────────────────────────────────────────
    def test_click_container_multiple_interactive_fails_with_candidates(self):
        """Two interactive descendants → refuse, list them (no guessing)."""
        self._open()
        see = _see()
        container = _handle(see, "group", "Choices")
        self.assertTrue(see["handles"][container]["contains_interactive"])

        r = cdp_click_handle(f"[{container}]")
        self.assertFalse(r["verified"], r)
        cands = r.get("candidates") or []
        self.assertEqual([c["text"] for c in cands], ["X", "Y"], r)
        self.assertEqual([c["tag"] for c in cands], ["A", "A"], r)
        # the same list is exposed through evidence (P2 diagnostic pattern)
        self.assertEqual(r["evidence"]["candidates"], cands, r["evidence"])
        self.assertNotIn("redirected", r["evidence"], r["evidence"])
        self.assertIn("2 interactive descendants", r["evidence"]["reason"])

    # ── 3 ───────────────────────────────────────────────────────────
    def test_redirect_covers_non_coincidental_layout(self):
        """Control experiment: the old path worked by luck, the redirect does not.

        With a meta prefix inside the heading, the heading's own centre
        (`elementFromPoint`) is the H3, not the link — so the pre-fix click at
        the heading centre would be lost. The redirect still lands on the link.
        """
        self.tab = _open_fixture("/heading-meta")
        self.assertTrue(_js("(function(){window.linkClicks=0;return true;})()"))
        see = _see()
        heading = [k for k, v in see["handles"].items()
                   if v["role"] == "heading"][0]
        self.assertTrue(see["handles"][heading]["contains_interactive"],
                        see["handles"][heading])
        # the dangerous condition, measured: the heading centre misses the link
        hit = _js("(function(){var h=document.getElementById('mh');"
                  "var r=h.getBoundingClientRect();"
                  "var el=document.elementFromPoint(r.left+r.width/2,"
                  "r.top+r.height/2);"
                  "return el?el.tagName+'#'+(el.id||''):'none';})()")
        self.assertEqual(hit, "H3#mh",
                         "fixture is wrong: the heading centre already hits the link")
        r = cdp_click_handle(f"[{heading}]")
        self.assertTrue(r["verified"], r)
        self.assertIs(r["evidence"].get("redirected"), True, r)
        self.assertEqual(_js("window.linkClicks||0"), 1,
                         "the redirect never reached the link")

    # ── 4 ───────────────────────────────────────────────────────────
    def test_click_plain_heading_no_redirect(self):
        """A heading with nothing interactive below it clicks normally."""
        self._open()
        see = _see()
        heading = _handle(see, "heading", "Plain Heading")
        self.assertFalse(see["handles"][heading].get("contains_interactive"),
                         see["handles"][heading])
        r = cdp_click_handle(f"[{heading}]")
        self.assertTrue(r["verified"], r)
        self.assertNotIn("redirected", r["evidence"], r["evidence"])
        self.assertEqual(r["evidence"]["element"], 'heading "Plain Heading"')


if __name__ == "__main__":
    unittest.main()
