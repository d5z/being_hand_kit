"""AX tree perception — a11y v2 (hand 0.7.0, PRD docs/prd-ax-perception.md S1).

Productizes experiments/a11y_ab/serialize_ax.py: CDP
`Accessibility.getFullAXTree` → curation → YAML-style indented tree with stable
`[idx]` handles → `backendNodeId → coordinates` map for click/type execution.

FORMAT IS A DATA CONTRACT
-------------------------
The serialized tree may become the representation being LLMs are post-trained
on for computer use (PRD S1). Therefore:

  * Determinism: the same page state serializes to byte-identical output. The
    only inputs are the CDP node payload and the explicit limits below. State
    properties are listed in a declared *order* (`STATE_PROPS` is a tuple, not a
    set: Python's str set iteration order varies with PYTHONHASHSEED and would
    silently make output non-reproducible across processes).
  * Handles: `[idx]` is assigned in curated pre-order traversal. Following the
    experiment's v2 serializer, a node that curates to no line (a StaticText
    duplicating its parent's name) still consumes an index — indices are
    traversal positions, not dense line numbers. Handles are stable for a page
    state and resolvable later by click/type (`resolve_handle`).
  * Truncation is explicit: beyond `max_lines` the tree is cut, `truncated` is
    True and `nodes_omitted` counts the dropped lines; no `[idx]` is emitted
    without a matching handle entry. Per-node accessible names longer than
    `MAX_NAME` are cut mid-name and declared: the receipt carries
    `text_truncated_count` and each affected node's meta has
    `text_truncated: True` (v2.1; in v2 the cut was silent — S4 subject-1
    caught it reading a half Chinese sentence with truncated=False).

COORDINATE CONTRACT
-------------------
`coords` / handle-map `x,y` are PHYSICAL pixels (CSS px × devicePixelRatio),
matching hand's coordinate contract everywhere else (cdp_click_do "xy:X,Y",
_element_info, interactive_map). Deviation note: the experiment prototype
returned raw CSS px from `DOM.getBoxModel` because it was a static measurement
tool; the production layer must agree with the rest of hand, so it multiplies
by dpr once, here. `DOM.getBoxModel` itself is CSS px.

Fidelity notes vs experiments/a11y_ab/serialize_ax.py (deliberate, documented):
  * curation rules, collapse rule, duplicate-StaticText rule and line grammar are
    byte-for-byte the v2 serializer's (validated by the 87%-vs-58% A/B report).
  * state order is now declared (fixes a latent determinism bug).
  * coordinates are physical px (see above), not CSS px.
"""

import hashlib
import json
import os
import sys
import tempfile

from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call,
    _init_domains, _header, _write_last, _get_dpr, _build_coord,
)
from hand.receipt import truncation, skipped, merge_hints
from hand.perception.visual_state import probe as visual_probe

AX_FORMAT_VERSION = "a11y-v2.1"
# 0.13: coordinate budget. Every node carrying a backend id now gets a box
# (interactive ones first when a page is huge), plus one hit test per box —
# a self-hit is the third leg of perception: not only "what" and "where", but
# "would a hand aimed here land on it".
MAX_COORD_NODES = 400

# 0.13: iframe budget. Page.getFrameTree + one getFullAXTree per child frame.
# A page that embeds ads or a video player can nest dozens; past this many we
# stop merging and say so rather than spend the perception in someone's ad net.
MAX_FRAMES = 8

# 0.13: roles whose "centre" is not a click target — a document/root node spans
# the viewport, so a hit test at its centre answers whatever descendant sits
# there and always reads as "covered by its own content". They keep their box,
# they just do not get a verdict.
NON_TARGET_ROLES = frozenset({"RootWebArea", "WebArea", "document", "Document"})

# Roles that can be acted on — these are the nodes that get coordinates.
INTERACTIVE_ROLES = frozenset({
    "link", "button", "textbox", "combobox", "checkbox", "radio",
    "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option",
    "switch", "searchbox", "slider", "spinbutton", "listbox",
})

# Pure-layout / redundant roles dropped by curation.
LAYOUT_ROLES = frozenset({"InlineTextBox", "ListMarker"})

# Semantically useful state properties. ORDER IS PART OF THE FORMAT (see module
# docstring) — append only, never reorder without bumping AX_FORMAT_VERSION.
STATE_PROPS = ("disabled", "checked", "expanded", "selected", "pressed",
               "hasPopup", "required", "invalid", "level", "value")

MAX_NAME = 200         # chars of accessible name kept per line; longer names
# are cut mid-name AND declared (text_truncated_count / per-node
# text_truncated). v2 had 60 + silent cut — S4 subject-1 read half a sentence
# without knowing. 200 covers real paragraph lines while bounding tokens.
# 600 lines keeps the heaviest page of the A/B experiment intact
# (github.com/d5z/being_hand_kit v2 snapshot = 478 lines / 17.7 KB) while still
# bounding pathological SPA trees.
DEFAULT_MAX_LINES = 600

# Where the last snapshot's [idx] → target map lives, so that a *later* process
# (MCP server restarts between tool calls) can still resolve a handle.
HANDLE_MAP_FILE = os.path.join(tempfile.gettempdir(), "hand_ax_handles.json")

# Reserved (non-digit) key inside the handle map file carrying the *see-time*
# navigation anchor. It is browser-side state (`Page.getNavigationHistory`
# currentEntry index), stable across MCP process restarts, so a later
# click/type can tell whether the page navigated since the snapshot was taken
# (0.9.4-P1). A digit-only key namespace can never collide with it.
NAV_ID_KEY = "nav_id"


# ── Curation ─────────────────────────────────────────────────────────

def _role(node) -> str:
    return (node.get("role") or {}).get("value", "?") or "?"


def _name(node) -> str:
    return (node.get("name") or {}).get("value") or ""


def prop_value(node, name):
    for p in node.get("properties") or []:
        if p.get("name") == name:
            return (p.get("value") or {}).get("value")
    return None


def filter_nodes(nodes):
    """Drop ignored nodes and pure-layout roles (PRD S1 curation rules)."""
    kept = []
    for n in nodes or []:
        if n.get("ignored"):
            continue
        if _role(n) in LAYOUT_ROLES:
            continue
        kept.append(n)
    return kept


def index_tree(kept):
    """{parentId: [children in payload order]} + roots (parent missing/dropped)."""
    by_id = {n["nodeId"]: n for n in kept}
    children = {}
    roots = []
    for n in kept:
        pid = n.get("parentId")
        if pid and pid in by_id:
            children.setdefault(pid, []).append(n)
        else:
            roots.append(n)
    return children, roots


# ── Label grammar: `role "name" (state, ...) [idx]` ──────────────────

def node_states(node, role=None):
    role = role or _role(node)
    states = []
    for p in STATE_PROPS:
        v = prop_value(node, p)
        if v in (None, False, "false", ""):
            continue
        if p == "level":
            # AX attaches level to list/listitem too; it is only meaningful for
            # headings (experiment curation rule).
            if role != "heading":
                continue
            states.append(f"h{v}")
            continue
        states.append(f"{p}={v}")
    if prop_value(node, "focusable") and role not in INTERACTIVE_ROLES:
        states.append("focusable")
    return states


def sanitize_name(name, limit=MAX_NAME):
    """AX name → (single line, was_truncated). Surrounding whitespace is
    PRESERVED (the A/B experiment's snapshots kept it: `StaticText " Star "`)
    because the serialization is a data contract and the tested format is the
    reference. A mid-name cut is returned as a flag so the receipt can declare
    it (v2.1: never silent)."""
    line = (name or "").replace("\n", " ")
    return line[:limit], len(line) > limit


def node_label(node):
    """(role, sanitized name, state suffix, name was truncated) — the line's
    semantic content plus its truncation verdict."""
    role = _role(node)
    states = node_states(node, role)
    state_s = f" ({', '.join(states)})" if states else ""
    name, name_cut = sanitize_name(_name(node))
    return role, name, state_s, name_cut


# ── Serialization ────────────────────────────────────────────────────

def _subtree_interactive(children, roots):
    """{nodeId: bool} — does this node's subtree contain an interactive *descendant*?

    Iterative post-order (same no-recursion-limit discipline as _traverse): a
    node counts as containing interactive when any child is interactive or any
    child itself contains interactive. The node's *own* role is not consulted —
    "contains_interactive" describes the subtree below it (0.9.4-P4 M1), which
    is what lets a click on a non-interactive heading be redirected to the link
    it wraps.
    """
    res = {}
    stack = [(r["nodeId"], False) for r in reversed(roots)]
    while stack:
        nid, expanded = stack.pop()
        if expanded:
            res[nid] = any(_role(c) in INTERACTIVE_ROLES or res.get(c["nodeId"], False)
                           for c in children.get(nid, []))
        else:
            stack.append((nid, True))
            for c in reversed(children.get(nid, [])):
                stack.append((c["nodeId"], False))
    return res


def _traverse(kept):
    """Curated pre-order (iterative: no recursion limit on deep trees).

    Yields (line, meta) for every node that gets a line; silent nodes (collapsed
    structural chains, duplicate StaticText) consume an index but emit nothing.
    """
    children, roots = index_tree(kept)
    subtree_int = _subtree_interactive(children, roots)
    counter = 0
    lines = []
    meta = []
    # (node, depth, name of the nearest emitted ancestor line)
    stack = [(r, 0, "") for r in reversed(roots)]
    while stack:
        node, depth, parent_name = stack.pop()
        role, name, state_s, name_cut = node_label(node)
        kids = children.get(node["nodeId"], [])
        # Collapse: nameless, stateless, non-interactive single-child chains do
        # not occupy a line — their child is lifted into this depth.
        if role in ("generic", "none", "") and not name and not state_s and len(kids) == 1:
            stack.append((kids[0], depth, parent_name))
            continue
        # StaticText curation (noise + redundancy):
        #   * an empty accessible name carries no information — the line would
        #     read `- StaticText "" [n]`, pure noise;
        #   * a name already on the nearest emitted ancestor line is a duplicate.
        # Both consume an index (traversal positions stay stable) but emit nothing.
        if role == "StaticText":
            stripped = name.strip()
            if not stripped or stripped == parent_name.strip():
                counter += 1
                continue
        counter += 1
        idx = counter
        lines.append(f"{'  ' * depth}- {role} \"{name}\"{state_s} [{idx}]")
        bid = node.get("backendDOMNodeId")
        states = node_states(node, role)
        entry = {
            "idx": idx,
            "role": role,
            "name": name,
            # internal (0.13.4): lets serialize() tell whether this line came
            # from a merged child frame. Stripped before the map is returned.
            "_node_id": node["nodeId"],
            "states": states,
            "backend_node_id": bid,
            "interactive": role in INTERACTIVE_ROLES,
            "has_popup": bool(prop_value(node, "hasPopup")),
            "text_truncated": name_cut,
        }
        # 0.9.4-P4 M1: does this node's subtree wrap an interactive descendant
        # (GitHub's `<h3><a>…</a></h3>`)? Declared only when true — every line
        # carrying a flag would be noise; false is the silent default. The line
        # grammar is untouched, so the text/sha256 contract is unchanged.
        if subtree_int.get(node["nodeId"]):
            entry["contains_interactive"] = True
        meta.append(entry)
        for c in reversed(kids):
            stack.append((c, depth + 1, name))
    return lines, meta


def serialize(nodes, max_lines=DEFAULT_MAX_LINES, frame_nodeids=None):
    """AX nodes → {"lines", "nodes", "truncated", "nodes_omitted", ...}.

    Deterministic: same nodes + same max_lines → identical bytes.

    `frame_nodeids` (0.13.4) is the set of AX nodeIds that came from merged
    child frames. It only feeds one counter — how many *printed lines* from
    those frames have no backend id, i.e. are readable but cannot be aimed at.
    Before 0.13.4 the count was taken over raw AX nodes instead, which counted
    structural nodes that never become a line at all: a cross-origin fixture
    with every visible node addressable still reported "3 node(s) … have no
    [idx] handle", and a nested fixture reported "1". Both were arithmetic
    facts about the payload and lies about the tree.
    """
    raw = list(nodes or [])
    kept = filter_nodes(raw)
    lines, meta = _traverse(kept)
    frame_lines_without_handle = 0
    if frame_nodeids:
        frame_lines_without_handle = sum(
            1 for m in meta
            if m.get("backend_node_id") is None and m.get("_node_id") in frame_nodeids)
    for m in meta:
        m.pop("_node_id", None)
    full_line_count = len(lines)
    truncated = max_lines is not None and full_line_count > max_lines
    if truncated:
        omitted = full_line_count - max_lines
        lines = lines[:max_lines]
        meta = meta[:max_lines]
    else:
        omitted = 0
    text_truncated_count = sum(1 for m in meta if m.get("text_truncated"))
    # S1 (0.9): the unified declaration block. The tree cut takes precedence;
    # when the tree is complete but node names were cut (v2.1 MAX_NAME), that
    # cut is declared in the same shape. Absent when nothing was dropped.
    block = truncation("tree", "max_lines", omitted, full_line_count)
    if block is None and text_truncated_count:
        block = truncation("names", "max_name", text_truncated_count, len(meta))
    ser = {
        "lines": lines,
        "nodes": meta,
        "truncated": truncated,
        "nodes_omitted": omitted,
        "text_truncated_count": text_truncated_count,
        "raw_node_count": len(raw),
        "kept_count": len(kept),
        "max_lines": max_lines,
        "format": AX_FORMAT_VERSION,
        "frame_lines_without_handle": frame_lines_without_handle,
    }
    if block:
        ser["truncation"] = block
    ser["sha256"] = hashlib.sha256(snapshot_text(ser).encode("utf-8")).hexdigest()
    return ser


def snapshot_text(ser) -> str:
    return "\n".join(ser["lines"])


def overflow_hint(nodes_meta):
    """Two-step strategy hint when the AX tree hides a collapsed menu.

    Known blind spot (PRD / REPORT_phase2): content behind an overflow/⋯ control
    is not in the AX tree. If the snapshot has a popup-opening control, say so.
    """
    for n in nodes_meta or []:
        if n.get("has_popup") and n.get("name"):
            return (f'hint: {n["role"]} "{n["name"]}" [{n["idx"]}] opens a collapsed menu '
                    f'(hasPopup) — its contents are not in the AX tree; '
                    f'click [{n["idx"]}] then see again')
    return None


# ── backendNodeId → coordinates ──────────────────────────────────────

def backend_ids_to_coords(call, ws, backend_ids, dpr=1.0):
    """{backendNodeId: {"x","y"} in PHYSICAL px | None if not rendered}.

    `call(ws, method, params, msg_id, timeout)` is injected so this is testable
    without a browser; production passes cdp_core.cdp_call.
    """
    ids = [b for b in backend_ids if b]
    if not ids:
        return {}
    call(ws, "DOM.getDocument", {"depth": 0}, msg_id=71, timeout=10)
    res = call(ws, "DOM.pushNodesByBackendIdsToFrontend",
               {"backendNodeIds": ids}, msg_id=72, timeout=10)
    node_ids = res.get("nodeIds") or []
    out = {}
    for bid, nid in zip(ids, node_ids):
        if not nid:
            out[bid] = None
            continue
        try:
            box = call(ws, "DOM.getBoxModel", {"nodeId": nid}, msg_id=73, timeout=10)
            model = (box or {}).get("model") or {}
        except Exception:
            out[bid] = None   # not in the render tree (display:none, detached…)
            continue
        # 0.13: the box a reader needs is the CLICKABLE one — border box,
        # which is what getBoundingClientRect reports and where a control's
        # padding lives. The content box under-reported every padded control
        # (a 44px button with a 24px icon read as 24px), so w/h answered
        # "how much room is there" with the wrong number — measured on
        # github.com 2026-10-21, 71/233 nodes off by >2px, worst cases 2x.
        quad = model.get("border") or model.get("padding") or model.get("content") or []
        if len(quad) < 8:
            out[bid] = None
            continue
        xs = quad[0::2]
        ys = quad[1::2]
        if max(xs) - min(xs) <= 0 or max(ys) - min(ys) <= 0:
            # Degenerate box (zero-area node, e.g. a visually hidden skip link):
            # not a clickable target — None, so nobody clicks a phantom.
            out[bid] = None
            continue
        out[bid] = {
            "x": round((min(xs) + max(xs)) / 2 * dpr),
            "y": round((min(ys) + max(ys)) / 2 * dpr),
            # 0.13: the box, not just its centre. A centre alone answers "where
            # to aim"; w/h answers "how much room is there" — which is what
            # tells a reader whether a few px of error still lands (a 150px
            # block forgives 40px, a 20px icon does not).
            "w": round((max(xs) - min(xs)) * dpr),
            "h": round((max(ys) - min(ys)) * dpr),
        }
    return out


def dom_parents(call, ws):
    """{backendNodeId: parent_backendNodeId} for the whole document.

    0.13: needed to read a hit test honestly. `elementFromPoint` returns the
    DEEPEST element under a point, so a node whose centre reports its own
    child, or its own container, was never "covered" — the click lands inside
    it and the event bubbles. Only a node from an unrelated branch is actually
    blocked. This map is what makes that distinction computable.
    """
    doc = call(ws, "DOM.getDocument", {"depth": -1, "pierce": True},
               msg_id=75, timeout=20)
    out = {}
    stack = [(doc or {}).get("root")]
    while stack:
        n = stack.pop()
        if not n:
            continue
        bid = n.get("backendNodeId")
        # 0.13: shadow roots hang off their host, not off `children`. Their
        # direct children are placed on the host's chain — that is the chain a
        # click would bubble along. Without this branch, every node inside a
        # web component (github.com uses several) was "cross-branch" by
        # construction: no parent, no chain, no verdict but "covered".
        for sr in (n.get("shadowRoots") or []):
            for c in (sr.get("children") or []):
                cb = c.get("backendNodeId")
                if cb and bid:
                    out[cb] = bid
                stack.append(c)
        for c in (n.get("children") or []):
            cb = c.get("backendNodeId")
            if cb and bid:
                out[cb] = bid
            stack.append(c)
        # 0.13: pseudo-elements (::before / ::after) are not children — they
        # hang off `pseudoElements`. A hit test over a button's icon often lands
        # on its ::before, which is part of the button, not a stranger on top.
        # Measured on developer.mozilla.org 2026-10-21: "Toggle navigation"
        # read as covered by a 24x24 ::before while a real click hit the button.
        for p in (n.get("pseudoElements") or []):
            pb = p.get("backendNodeId")
            if pb and bid:
                out[pb] = bid
            stack.append(p)
        # 0.13: frame content hangs off `contentDocument`, not off `children`.
        # Without this branch every iframe-internal node has no chain at all,
        # so the first honest hit test would call all of them covered by
        # strangers. Measured on the one-iframe fixture: the frame's own button
        # reported "covered" until its document was walked. The document node
        # itself usually carries no backend id, so its children are attached to
        # the <iframe> element instead — that is the chain a click bubbles along.
        cd = n.get("contentDocument")
        if cd:
            for c in (cd.get("children") or []):
                cb = c.get("backendNodeId")
                if cb and bid:
                    out[cb] = bid
                stack.append(c)
            for sr in (cd.get("shadowRoots") or []):
                stack.append(sr)
    return out


def on_same_chain(a, b, parents):
    """True when a and b are equal, or one is an ancestor of the other.

    Same-chain means a click at b's centre still belongs to a: it lands on a
    descendant and bubbles up, or on a container and stays inside it. Anything
    off the chain is a different branch painted on top — a real block.
    """
    if a == b:
        return True
    seen = set()
    cur = a
    while cur is not None and cur not in seen:
        seen.add(cur)
        cur = parents.get(cur)
        if cur == b:
            return True
    cur = b
    while cur is not None and cur not in seen:
        seen.add(cur)
        cur = parents.get(cur)
        if cur == a:
            return True
    return False


def hit_test(call, ws, points, offset=(0.0, 0.0)):
    """{(backendNodeId, css_x, css_y)} → {backendNodeId: hit_backendNodeId|None}.

    0.13: the third leg of a perception. A tree says *what exists*, a box says
    *where*, and this says *whether a hand aimed there would land on it*.
    DOM.getNodeForLocation is the CDP form of document.elementFromPoint: it
    answers with the topmost node at that point, so a node whose centre reports
    someone else's id is covered by it — visible in the DOM, unreachable by a
    click. Points are CSS px (CDP's input space), not the physical px the
    handle map stores.

    None = the browser refused to answer (detached / crashed); "error" strings
    are never written — an unknown hit is unknown, not a mismatch.

    `offset` is the page scroll (scrollX, scrollY) in CSS px. Boxes are viewport
    coordinates, but DOM.getNodeForLocation speaks document coordinates; passing
    the offset here keeps the conversion in the one place that knows both.
    """
    out = {}
    ox, oy = offset
    for bid, x, y in points:
        try:
            # 0.13: NO includeUserAgentShadowDOM. With it, a point over an
            # <input> answers with the input's internal UA-shadow editor div —
            # a node that dom_parents (pierce=False) cannot place on any chain,
            # so every text field read as "covered by a stranger". Measured on
            # github.com 2026-10-21: textbox "Enter your email" reported covered
            # while a real click focused it and document.elementFromPoint
            # answered the input itself. This returns what a click lands on,
            # which is the question the verdict is supposed to answer.
            res = call(ws, "DOM.getNodeForLocation",
                       {"x": int(x + ox), "y": int(y + oy)},
                       msg_id=74, timeout=5)
            out[bid] = (res or {}).get("backendNodeId")
        except Exception:
            out[bid] = None
    return out


# ── [idx] handle map ─────────────────────────────────────────────────

def save_handle_map(handles, path=None, nav_id=None):
    """Persist {idx: entry} (+ optional see-time navigation anchor) atomically.

    `nav_id` is written under the reserved NAV_ID_KEY so the handle entries keep
    their digit-only namespace and a later click/type can compare it against the
    page's current navigation index (0.9.4-P1 M1). Absent when the browser could
    not answer — an unknown anchor must never be mistaken for a matching one.
    """
    path = path or HANDLE_MAP_FILE
    payload = dict(handles)
    if isinstance(nav_id, int) and not isinstance(nav_id, bool):
        payload[NAV_ID_KEY] = nav_id
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        return path
    except Exception as e:
        sys.stderr.write(f"hand: save_handle_map failed ({path}): {e}\n")
        return None


def load_handle_map(path=None):
    path = path or HANDLE_MAP_FILE
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        sys.stderr.write(f"hand: load_handle_map failed ({path}): {e}\n")
        return {}


def handle_map_nav_id(path=None):
    """See-time navigation anchor stored in the handle map, or None.

    A *number* is the only valid anchor (Page.getNavigationHistory currentEntry
    index); anything else is treated as unknown so it can never produce a false
    "matches" verdict.
    """
    v = load_handle_map(path).get(NAV_ID_KEY)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def handle_index(handle):
    """'[93]' / 'idx:93' / '93' → 93; anything else → None."""
    if isinstance(handle, int):
        return handle
    if not isinstance(handle, str):
        return None
    s = handle.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    if s.lower().startswith("idx:"):
        s = s[4:].strip()
    try:
        return int(s)
    except ValueError:
        return None


def looks_like_handle(token) -> bool:
    """True for '[93]' / 'idx:93' (explicit forms only, never a bare number —
    a bare number may be a selector fragment or a coordinate)."""
    if not isinstance(token, str):
        return False
    s = token.strip()
    return (s.startswith("[") and s.endswith("]")) or s.lower().startswith("idx:")


def resolve_handle(handle, path=None):
    """[idx] → handle-map entry (role/name/backend_node_id/x/y) or {'error': ...}."""
    idx = handle_index(handle)
    if idx is None:
        return {"error": f"not an [idx] handle: {handle!r} "
                         "(expected '[93]' or 'idx:93' — see cdp_see)"}
    handles = load_handle_map(path)
    if not handles:
        return {"error": "no AX snapshot handle map yet — call cdp_see first "
                         f"(expected at {path or HANDLE_MAP_FILE})"}
    entry = handles.get(str(idx))
    if not entry:
        n = sum(1 for k in handles if str(k).isdigit())
        return {"error": f"handle [{idx}] not in the last AX snapshot "
                         f"({n} handles) — call cdp_see again"}
    out = dict(entry)
    out["idx"] = idx
    # 0.9.4-P1 M2: carry the snapshot's navigation anchor alongside the entry so
    # click/type can detect a navigation that happened since the `see`. Private
    # (`_see_nav_id`) — it is map-level state, not part of the handle's identity.
    v = handles.get(NAV_ID_KEY)
    out["_see_nav_id"] = v if isinstance(v, int) and not isinstance(v, bool) else None
    return out


# ── Snapshot ─────────────────────────────────────────────────────────

def ax_snapshot(page_sel=None, max_lines=DEFAULT_MAX_LINES,
                resolve_coords=True, handle_map_path=None):
    """Perceive the page as an a11y v2 tree. Returns a receipt dict.

    Natural evidence only: node/byte counts, the truncation marker, the AX source
    version, sha256 and the handle map. The verified/evidence wrapper is applied
    by hand.router._with_receipt (S3) so every perception backend is judged by
    the same ruler.
    """
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        raw = cdp_call(ws, "Accessibility.getFullAXTree", {}, msg_id=60)
        nodes = (raw or {}).get("nodes") or []
        # 0.13: iframe content. Accessibility.getFullAXTree without a frameId
        # answers for the root document only — everything a page embeds (video,
        # payment, OAuth, comments, docs widgets) was a black hole: measured on
        # a one-iframe fixture, 0 of the frame's 11 named nodes appeared in the
        # handle map. A frameId gives that frame's own tree, and its
        # backendNodeIds resolve in the top-level DOM agent **already in
        # top-level coordinates** (verified 2026-10-21: an iframe at x=102.7
        # reported its inner button at x=120.7 — border offset included, no
        # hand math). Frames are merged breadth-first, depth-capped so a page
        # that nests ads cannot spend the whole budget here.
        frames_merged = 0
        frame_of_bid = {}
        frame_nodeids = set()
        try:
            ft = cdp_call(ws, "Page.getFrameTree", {}, msg_id=64, timeout=5)
            queue = list(((ft or {}).get("frameTree") or {}).get("childFrames") or [])
            while queue and frames_merged < MAX_FRAMES:
                cf = queue.pop(0)
                queue.extend(cf.get("childFrames") or [])
                fid = (cf.get("frame") or {}).get("id")
                if not fid:
                    continue
                try:
                    sub = cdp_call(ws, "Accessibility.getFullAXTree",
                                   {"frameId": fid}, msg_id=65, timeout=5)
                    sub_nodes = (sub or {}).get("nodes") or []
                    if sub_nodes:
                        # 0.13.1: remember which frame each merged node came
                        # from. A handle that does not say this cannot be
                        # clicked correctly — its rect is frame-local while the
                        # dispatch is top-level (0.13.0 missed by the frame's
                        # own origin and still reported landed=true).
                        for sn in sub_nodes:
                            bnid = sn.get("backendDOMNodeId")
                            if bnid:
                                frame_of_bid[bnid] = fid
                            if sn.get("nodeId"):
                                frame_nodeids.add(sn["nodeId"])
                        nodes.extend(sub_nodes)
                        frames_merged += 1
                except Exception:
                    pass
        except Exception:
            pass
        ser = serialize(nodes, max_lines=max_lines, frame_nodeids=frame_nodeids)

        dpr = _get_dpr(ws)
        ax_version = {}
        try:
            ver = cdp_call(ws, "Browser.getVersion", {}, msg_id=61, timeout=5)
            ax_version = {"product": ver.get("product"),
                          "protocol": ver.get("protocolVersion"),
                          "tree": "Accessibility.getFullAXTree"}
        except Exception as e:
            ax_version = {"tree": "Accessibility.getFullAXTree",
                          "version_error": f"{type(e).__name__}: {e}"}

        coords = {}
        hits = {}
        parents = {}
        coords_skipped = 0
        offscreen = 0
        wanted = []
        vw = vh = 0
        scroll_x = scroll_y = 0.0
        if resolve_coords:
            # Viewport first: a hit test can only answer for points that are
            # actually on screen. Nodes below the fold get a box and no verdict.
            try:
                metrics = cdp_call(ws, "Page.getLayoutMetrics", {}, msg_id=62, timeout=5)
                vp = metrics.get("cssLayoutViewport") or {}
                vw = int(vp.get("clientWidth") or 0)
                vh = int(vp.get("clientHeight") or 0)
                # 0.13: scroll offset. getBoxModel reports VIEWPORT coordinates
                # (same frame as getBoundingClientRect), but DOM.getNodeForLocation
                # wants DOCUMENT coordinates. At scrollY=0 the two coincide, which
                # is why every earlier check passed; on a scrolled page every probe
                # came back "No node found at given location" and the whole verdict
                # layer silently emptied (MDN, scrollY=900: judged 63 → 0).
                vv = metrics.get("cssVisualViewport") or {}
                scroll_x = float(vv.get("pageX") or 0)
                scroll_y = float(vv.get("pageY") or 0)
            except Exception:
                vw = vh = 0
                scroll_x = scroll_y = 0.0
            # 0.13: every node with a backend id, not only the interactive ones.
            # The excluded band was the interesting one: a StaticText or a plain
            # visual container is visible but not clickable, and without a box
            # nothing could be said about where it sits or what covers it.
            # Interactive nodes go first so a budget cut costs the least.
            backed = [n for n in ser["nodes"] if n["backend_node_id"]]
            backed.sort(key=lambda n: (not n["interactive"], n["idx"]))
            wanted = backed[:MAX_COORD_NODES]
            coords_skipped = len(backed) - len(wanted)
            if wanted:
                by_bid = backend_ids_to_coords(cdp_call, ws,
                                               [n["backend_node_id"] for n in wanted],
                                               dpr=dpr)
                for n in wanted:
                    coords[str(n["idx"])] = by_bid.get(n["backend_node_id"])
                pts = []
                offscreen = 0
                for n in wanted:
                    c = by_bid.get(n["backend_node_id"])
                    if not c:
                        continue
                    # 0.13: document-level nodes are not click targets. A
                    # RootWebArea's "centre" is the middle of the page, where a
                    # click lands on whatever descendant happens to sit there —
                    # it always read as covered by its own content (fixture:
                    # RootWebArea ← HTML, a pure artefact). They keep their box
                    # and lose only the verdict, which never meant anything.
                    if (n.get("role") or "") in NON_TARGET_ROLES:
                        continue
                    cx, cy = c["x"] / dpr, c["y"] / dpr
                    # CSS px for the hit test: DOM.getNodeForLocation is CDP
                    # input space, not the physical space in the map. Points
                    # outside the viewport cannot be answered — counted, not
                    # silently skipped.
                    if vw and vh and not (0 <= cx < vw and 0 <= cy < vh):
                        offscreen += 1
                        continue
                    pts.append((n["backend_node_id"], cx, cy))
                if pts:
                    hits = hit_test(cdp_call, ws, pts, offset=(scroll_x, scroll_y))
                    parents = dom_parents(cdp_call, ws)

        # 0.9.4-P1 M1: the see-time navigation anchor. Page.getNavigationHistory
        # is browser-side state (currentEntry index) — it survives MCP process
        # restarts, unlike any in-process counter, so it is the one reliable
        # anchor a later click/type can compare against.
        nav_id = None
        try:
            hist = cdp_call(ws, "Page.getNavigationHistory", {}, msg_id=63, timeout=5)
            v = (hist or {}).get("currentIndex")
            if isinstance(v, int) and not isinstance(v, bool):
                nav_id = v
        except Exception:
            nav_id = None   # unknown anchor: never fabricate a match

        handles = {}
        for n in ser["nodes"]:
            if not n["backend_node_id"]:
                continue
            c = coords.get(str(n["idx"]))
            bid = n["backend_node_id"]
            hit = hits.get(bid)
            entry = {
                "role": n["role"],
                "name": n["name"],
                "backend_node_id": bid,
                "interactive": n["interactive"],
                # 0.9.4-P4: does this node's subtree wrap an interactive node?
                # Read at click time to redirect a heading click onto its link.
                "contains_interactive": bool(n.get("contains_interactive")),
                "x": (c or {}).get("x"),
                "y": (c or {}).get("y"),
                # 0.13: the box. A centre says where to aim; w/h says how much
                # error the target forgives before the click lands elsewhere.
                "w": (c or {}).get("w"),
                "h": (c or {}).get("h"),
            }
            if bid in frame_of_bid:
                # 0.13.1: which child frame this node lives in. cdp_click_handle
                # needs it to translate the frame-local rect into dispatch space;
                # a reader needs it to know the box is drawn inside a frame.
                entry["frame_id"] = frame_of_bid[bid]
            # 0.13: reachability verdict — would a click at this node's centre
            # end up on this node? True when the point lands on the node itself
            # or anywhere on its own ancestor chain (a child of it, or a
            # container wrapping it) — the click still belongs to it. False
            # means another branch is painted on top; `covered_by` carries that
            # node's backendNodeId, resolvable against this same map. The keys
            # are absent when the browser could not answer: unknown is never
            # written as "covered".
            if bid in hits and hits[bid] is not None:
                ok = on_same_chain(hits[bid], bid, parents)
                entry["reachable"] = ok
                if not ok:
                    entry["covered_by"] = hits[bid]
            handles[str(n["idx"])] = entry

        # 0.13: `covered_by` alone is a backendNodeId — readable only when the
        # coverer happened to earn a handle of its own. Measured on github.com
        # 2026-10-21: 5 of 10 coverers printed as "?" , which turns "you cannot
        # click this" into "something, somewhere, is on top" — half a verdict.
        # Resolve every coverer at see time and carry a label next to the id.
        bid_index = {v.get("backend_node_id"): v for v in handles.values()}
        strangers = sorted({e.get("covered_by") for e in handles.values()
                            if e.get("covered_by") is not None})
        stranger_labels = {}
        for sbid in strangers[:64]:
            try:
                d = cdp_call(ws, "DOM.describeNode", {"backendNodeId": sbid},
                             msg_id=76, timeout=5)
                node = (d or {}).get("node") or {}
                attrs = node.get("attributes") or []
                amap = dict(zip(attrs[0::2], attrs[1::2]))
                cls = (amap.get("class") or "").strip()
                stranger_labels[sbid] = "%s%s" % (node.get("nodeName") or "?",
                                                  ("." + cls[:48]) if cls else "")
            except Exception:
                pass
        for e in handles.values():
            cb = e.get("covered_by")
            if cb is None:
                continue
            known = bid_index.get(cb)
            named = (known.get("name") or "").strip() if known else ""
            if known and named:
                e["covered_by_label"] = "%s %s" % (known.get("role"), named)
            elif cb in stranger_labels:
                e["covered_by_label"] = stranger_labels[cb]
            elif known:
                # a handle without a name still gets a face: role alone reads
                # like "generic", which is not a thing a reader can act on.
                e["covered_by_label"] = "%s (%s)" % (stranger_labels.get(cb, known.get("role")),
                                                     known.get("role"))
        handle_map_path = save_handle_map(handles, path=handle_map_path,
                                          nav_id=nav_id)

        tree = snapshot_text(ser)
        text_bytes = len(tree.encode("utf-8"))
        # NOTE: this function reports natural evidence only. The
        # {"verified": bool, "evidence": {...}} wrapper is applied by
        # hand.router._with_receipt — one ruler for every perception backend
        # (PRD S3: "新眼睛过同一把尺").
        if vw and vh:
            coord = _build_coord(vw, vh, dpr)
        else:
            try:
                metrics = cdp_call(ws, "Page.getLayoutMetrics", {}, msg_id=62, timeout=5)
                vp = metrics.get("cssLayoutViewport") or {}
                coord = _build_coord(vp.get("clientWidth", 0), vp.get("clientHeight", 0), dpr)
            except Exception:
                coord = _build_coord(0, 0, dpr)
        coord["coords_space"] = "physical"

        # S1 skipped-step channel: coordinates are resolved for every node in
        # the render tree (0.13), not just the interactive ones; the ones
        # dropped are declared, not silently missing.
        notes = []
        if frames_merged:
            notes.append(f"{frames_merged} child frame(s) merged into this tree "
                         "(iframe content is otherwise invisible)")
            # 0.13.1: merged is not the same as addressable. 0.13.4: say it over
            # *printed lines*, not raw AX nodes — the old counter included
            # structural nodes that never reach the tree, so a page whose every
            # visible frame node was clickable still reported three unclickable
            # nodes. A reader acts on lines, so lines are what the count is about.
            if ser.get("frame_lines_without_handle"):
                notes.append(
                    f"{ser['frame_lines_without_handle']} line(s) from child frames "
                    "have no backend id — readable here, but not aimable: no box, "
                    "no click (nested / cross-origin frames, measured 2026-10-22)")
        if resolve_coords:
            unresolved = sum(1 for n in wanted if not coords.get(str(n["idx"])))
            if unresolved:
                notes.append(skipped(
                    f"coordinates for {unresolved} node(s)",
                    "not in the render tree (display:none / detached)"))
            if coords_skipped:
                notes.append(skipped(
                    f"coordinates for {coords_skipped} node(s)",
                    f"over the {MAX_COORD_NODES}-node budget "
                    "(interactive nodes kept first)"))
            if offscreen:
                notes.append(skipped(
                    f"reachability for {offscreen} node(s)",
                    "centre outside the viewport — placed but not hit-tested; "
                    "scroll to them and see again"))
            # 0.13: the band this release exists for — nodes that are in the
            # tree, have a box, and still cannot be reached, because another
            # branch is painted over their centre. Declared, not silently
            # clickable.
            covered = sum(1 for n in wanted
                          if hits.get(n["backend_node_id"]) is not None
                          and not on_same_chain(hits[n["backend_node_id"]],
                                                n["backend_node_id"], parents))
            if covered:
                notes.append(skipped(
                    f"{covered} node(s) covered at their centre",
                    "hit test reports another branch on top — present and placed, "
                    "but a click aimed there lands on the other one"))
        hint = merge_hints(overflow_hint(ser["nodes"]), notes)

        # S2 (0.9): what the page *looks* like right now (DOM heuristic).
        visual = visual_probe(ws, call=cdp_call)

        out = {
            "method": "cdp_a11y",
            "format": AX_FORMAT_VERSION,
            "page_index": idx,
            "header": _header(idx, page),
            "url": page.get("url"),
            "page_title": page.get("title"),
            "tree": tree,
            "nodes": ser["nodes"],
            "handles": handles,
            "coords": coords,
            "coord": coord,
            "hint": hint,
            "root_role": ser["nodes"][0]["role"] if ser["nodes"] else None,
            "node_count": len(ser["lines"]),
            "raw_node_count": ser["raw_node_count"],
            "curated_node_count": ser["kept_count"],
            "line_count": len(ser["lines"]),
            "serialized_bytes": text_bytes,
            "truncated": ser["truncated"],
            "nodes_omitted": ser["nodes_omitted"],
            "text_truncated_count": ser["text_truncated_count"],
            "max_lines": ser["max_lines"],
            "sha256": ser["sha256"],
            "ax_version": ax_version,
            # 0.9.4-P1 M1: top-level navigation anchor (see-time). None when the
            # browser could not answer — an absent/failed anchor is not a value.
            "nav_id": nav_id,
            "handle_map": handle_map_path,
            "coords_resolved": sum(1 for v in coords.values() if v),
            "visual_state": visual["visual_state"],
            "visual_signals": visual["visual_signals"],
        }
        if ser.get("truncation"):
            out["truncation"] = ser["truncation"]
        _write_last(idx)
        return out
    finally:
        close = getattr(ws, "close", None)
        if close:
            try:
                close()
            except Exception:
                pass
