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
    without a matching handle entry.

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

from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call,
    _init_domains, _header, _write_last, _get_dpr, _build_coord,
)

AX_FORMAT_VERSION = "a11y-v2"

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

MAX_NAME = 60          # chars of accessible name kept per line
# 600 lines keeps the heaviest page of the A/B experiment intact
# (github.com/d5z/being_hand_kit v2 snapshot = 478 lines / 17.7 KB) while still
# bounding pathological SPA trees.
DEFAULT_MAX_LINES = 600

# Where the last snapshot's [idx] → target map lives, so that a *later* process
# (MCP server restarts between tool calls) can still resolve a handle.
HANDLE_MAP_FILE = "/tmp/hand_ax_handles.json"


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
    """AX name → single line, truncated. Surrounding whitespace is PRESERVED
    (the A/B experiment's snapshots kept it: `StaticText " Star "`), because the
    serialization is a data contract and the tested format is the reference."""
    return (name or "").replace("\n", " ")[:limit]


def node_label(node):
    """(role, sanitized name, state suffix) — the line's semantic content."""
    role = _role(node)
    states = node_states(node, role)
    state_s = f" ({', '.join(states)})" if states else ""
    return role, sanitize_name(_name(node)), state_s


# ── Serialization ────────────────────────────────────────────────────

def _traverse(kept):
    """Curated pre-order (iterative: no recursion limit on deep trees).

    Yields (line, meta) for every node that gets a line; silent nodes (collapsed
    structural chains, duplicate StaticText) consume an index but emit nothing.
    """
    children, roots = index_tree(kept)
    counter = 0
    lines = []
    meta = []
    # (node, depth, name of the nearest emitted ancestor line)
    stack = [(r, 0, "") for r in reversed(roots)]
    while stack:
        node, depth, parent_name = stack.pop()
        role, name, state_s = node_label(node)
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
        meta.append({
            "idx": idx,
            "role": role,
            "name": name,
            "states": states,
            "backend_node_id": bid,
            "interactive": role in INTERACTIVE_ROLES,
            "has_popup": bool(prop_value(node, "hasPopup")),
        })
        for c in reversed(kids):
            stack.append((c, depth + 1, name))
    return lines, meta


def serialize(nodes, max_lines=DEFAULT_MAX_LINES):
    """AX nodes → {"lines", "nodes", "truncated", "nodes_omitted", ...}.

    Deterministic: same nodes + same max_lines → identical bytes.
    """
    raw = list(nodes or [])
    kept = filter_nodes(raw)
    lines, meta = _traverse(kept)
    truncated = max_lines is not None and len(lines) > max_lines
    if truncated:
        omitted = len(lines) - max_lines
        lines = lines[:max_lines]
        meta = meta[:max_lines]
    else:
        omitted = 0
    ser = {
        "lines": lines,
        "nodes": meta,
        "truncated": truncated,
        "nodes_omitted": omitted,
        "raw_node_count": len(raw),
        "kept_count": len(kept),
        "max_lines": max_lines,
        "format": AX_FORMAT_VERSION,
    }
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
            quad = ((box or {}).get("model") or {}).get("content") or []
        except Exception:
            out[bid] = None   # not in the render tree (display:none, detached…)
            continue
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
        }
    return out


# ── [idx] handle map ─────────────────────────────────────────────────

def save_handle_map(handles, path=None):
    path = path or HANDLE_MAP_FILE
    try:
        with open(path, "w") as f:
            json.dump(handles, f, ensure_ascii=False, sort_keys=True)
        return path
    except Exception:
        return None


def load_handle_map(path=None):
    path = path or HANDLE_MAP_FILE
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
        return {"error": f"handle [{idx}] not in the last AX snapshot "
                         f"({len(handles)} handles) — call cdp_see again"}
    out = dict(entry)
    out["idx"] = idx
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
        ser = serialize(nodes, max_lines=max_lines)

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
        if resolve_coords:
            wanted = [n for n in ser["nodes"] if n["interactive"] and n["backend_node_id"]]
            if wanted:
                by_bid = backend_ids_to_coords(cdp_call, ws,
                                               [n["backend_node_id"] for n in wanted],
                                               dpr=dpr)
                for n in wanted:
                    coords[str(n["idx"])] = by_bid.get(n["backend_node_id"])

        handles = {}
        for n in ser["nodes"]:
            if not n["backend_node_id"]:
                continue
            c = coords.get(str(n["idx"]))
            handles[str(n["idx"])] = {
                "role": n["role"],
                "name": n["name"],
                "backend_node_id": n["backend_node_id"],
                "interactive": n["interactive"],
                "x": (c or {}).get("x"),
                "y": (c or {}).get("y"),
            }
        handle_map_path = save_handle_map(handles, path=handle_map_path)

        tree = snapshot_text(ser)
        text_bytes = len(tree.encode("utf-8"))
        # NOTE: this function reports natural evidence only. The
        # {"verified": bool, "evidence": {...}} wrapper is applied by
        # hand.router._with_receipt — one ruler for every perception backend
        # (PRD S3: "新眼睛过同一把尺").
        try:
            metrics = cdp_call(ws, "Page.getLayoutMetrics", {}, msg_id=62, timeout=5)
            vp = metrics.get("cssLayoutViewport") or {}
            coord = _build_coord(vp.get("clientWidth", 0), vp.get("clientHeight", 0), dpr)
        except Exception:
            coord = _build_coord(0, 0, dpr)
        coord["coords_space"] = "physical"

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
            "hint": overflow_hint(ser["nodes"]),
            "node_count": len(ser["lines"]),
            "raw_node_count": ser["raw_node_count"],
            "curated_node_count": ser["kept_count"],
            "line_count": len(ser["lines"]),
            "serialized_bytes": text_bytes,
            "truncated": ser["truncated"],
            "nodes_omitted": ser["nodes_omitted"],
            "max_lines": ser["max_lines"],
            "sha256": ser["sha256"],
            "ax_version": ax_version,
            "handle_map": handle_map_path,
            "coords_resolved": sum(1 for v in coords.values() if v),
        }
        _write_last(idx)
        return out
    finally:
        close = getattr(ws, "close", None)
        if close:
            try:
                close()
            except Exception:
                pass
