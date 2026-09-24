"""
CDP Action — browser click/type via Chrome DevTools Protocol.
4-tier fallback for click preserved from V5.

COORDINATE CONTRACT: all coordinates in this module (see output such as
interactive_map/_element_info, and do input such as "xy:X,Y") are PHYSICAL
pixels = CSS px × devicePixelRatio. CDP Input.dispatchMouseEvent expects
viewport CSS px, so _click_at divides by dpr before dispatching.
"""
import json, time
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call,
    _init_domains, _element_info, _scroll_into_view,
    _get_dpr, _header, _write_last, LOAD_TIMEOUT
)
from hand.perception.ax_tree import looks_like_handle, resolve_handle

# ── Receipt evidence helpers (v6.11.0) ──────────────────────────────
# Contract: every receipt carries {"verified": bool, "evidence": {...}}.
# verified=True  → the claim is backed by an observed fact recorded in evidence.
# verified=False → the receipt MUST carry a reason (no silent ok).

def _element_evidence(info: dict) -> dict:
    """Describe the element a click/type actually landed on."""
    tag = (info.get('tag') or '').upper()
    text = (info.get('text') or '').strip()
    return {
        'element': f'{tag} "{text}"' if text else (tag or 'unknown'),
        'tag': tag,
        'text': text[:80],
    }


def _receipt_fail(method: str, reason: str, **fields) -> dict:
    """Unverified failure receipt — always names why."""
    out = {
        'method': method,
        'error': reason,
        'verified': False,
        'evidence': {'verified': False, 'reason': reason},
    }
    out.update(fields)
    return out


def _selector_hit(ws, selector: str, msg_id: int = 2) -> dict:
    """Does `selector` match an element right now? (document.querySelector)

    Pre-flight check for blind clicks/types: a selector that matches nothing
    must fail *here*, not silently after the fact.
    """
    expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
            'if(!el)return JSON.stringify({found:false});'
            'return JSON.stringify({found:true,tag:el.tagName,'
            'text:(el.innerText||el.value||"").substring(0,80)});'
            '})()')
    raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)
    value = raw.get('result', {}).get('value') or '{}'
    try:
        data = json.loads(value)
    except Exception as e:
        # Cannot read the verification result → treat as unverified, say so.
        return {'found': False, 'parse_error': f'{type(e).__name__}: {e}'}
    return data if isinstance(data, dict) else {'found': False, 'parse_error': 'non-dict verification payload'}


def _active_element(ws, msg_id: int = 2) -> dict:
    """Current focus target (document.activeElement) as {tag,id,type} or {}."""
    expr = ('(function(){var el=document.activeElement;'
            'if(!el)return JSON.stringify({});'
            'return JSON.stringify({tag:el.tagName,id:el.id||"",'
            'type:(el.getAttribute&&el.getAttribute("type"))||""});'
            '})()')
    raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)
    value = raw.get('result', {}).get('value') or '{}'
    try:
        data = json.loads(value)
    except Exception as e:
        return {'parse_error': f'{type(e).__name__}: {e}'}
    return data if isinstance(data, dict) else {}


def _focus_label(focus: dict) -> str:
    tag = (focus.get('tag') or '').upper()
    bits = [tag] if tag else []
    if focus.get('id'):
        bits.append(f"#{focus['id']}")
    if focus.get('type'):
        bits.append(f"[type={focus['type']}]")
    return ''.join(bits) or 'unknown'


def _click_at(ws, x, y, dpr):
    """Dispatch a real mouse click (pressed + released) at viewport (x, y).

    Input is PHYSICAL pixels (CSS px × devicePixelRatio). CDP
    Input.dispatchMouseEvent expects CSS px viewport coordinates, so we
    divide by dpr here. Viewport-relative — no scrollX/scrollY adjustment.
    """
    x_scaled, y_scaled = x / dpr, y / dpr
    cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mousePressed','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=3)
    cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mouseReleased','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=4)

# ── Enter semantics (0.9.4-P3) ───────────────────────────────────────
# `Input.insertText` inserts *text*: it produces no KeyboardEvent. A "\n" in a
# single-line input therefore never becomes keydown(13), and reactive
# search/submit handlers (React onKeyDown) never fire — the typing looks fine
# and nothing submits. `"\n"` thus forks by element type: a real newline in a
# multiline field, a real Enter press everywhere else.
# Spec: docs/spec-0.9.4-p3-enter-submit.md

ENTER_MODE_KEYBOARD = 'keyboard_event'
ENTER_MODE_TEXT = 'text_insert'


def _type_enter_mode(tag, role=None):
    """What "\n" means for this element: submit (keyboard) or newline (text).

    textarea — or any element whose role says multiline — keeps the literal
    newline; everything else (input, contenteditable single-line, …) treats
    "\n" as the submit intent.
    """
    if (tag or '').upper() == 'TEXTAREA':
        return ENTER_MODE_TEXT
    if role and 'multiline' in str(role).lower():
        return ENTER_MODE_TEXT
    return ENTER_MODE_KEYBOARD


def _dispatch_enter(ws, msg_id=36):
    """A real Enter press through the Input domain: keyDown + keyUp.

    windowsVirtualKeyCode/nativeVirtualKeyCode 13 is what makes the browser
    expose keyCode 13 to page handlers — the whole point of not using
    insertText. No keypress event (deprecated; keydown + keyup is enough).
    """
    for kind in ('keyDown', 'keyUp'):
        cdp_call(ws, 'Input.dispatchKeyEvent',
                 {'type': kind, 'key': 'Enter', 'code': 'Enter',
                  'windowsVirtualKeyCode': 13, 'nativeVirtualKeyCode': 13},
                 msg_id=msg_id)


def _insert_text(ws, text, enter_mode, msg_id=35):
    """Type `text` char by char; every "\n" follows `enter_mode`.

    Returns the mode actually exercised: 'keyboard_event' / 'text_insert', or
    None when the text carries no "\n" at all (nothing was forked).
    """
    used = None
    for char in text:
        if char == '\n':
            used = enter_mode
            if enter_mode == ENTER_MODE_TEXT:
                cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=msg_id)
            else:
                _dispatch_enter(ws, msg_id=msg_id)
        else:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=msg_id)
        time.sleep(0.001)
    return used


# ── [idx] handle path (0.7.0 S2) ─────────────────────────────────────
# cdp_see(kind=a11y) numbers every node `[idx]`. A handle resolves through the
# snapshot's handle map (hand/perception/ax_tree.py) to a backendNodeId, and the
# click re-reads the element's box *now*: the snapshot's own x,y are
# informational, and clicking a stale coordinate would be a blind click. The
# verification is that fresh read (node resolvable + non-zero box), not the map
# entry — the map only says "this handle existed at snapshot time".

def _handle_label(entry):
    """Human-readable target of a handle, in the tree's own grammar."""
    name = (entry.get("name") or "").strip()
    return f'{entry.get("role")} "{name}"' if name else str(entry.get("role") or "?")


def _handle_fail(reason, entry=None, handle=None, method="cdp_click", nav=None, **fields):
    """Unverified handle receipt — same shape as _receipt_fail, plus the target.

    `nav` is the navigation-anchor fragment (0.9.4-P1 M2); it rides in evidence
    so a stale-handle failure still warns, not just a successful click.
    """
    ev = {"verified": False, "reason": reason}
    if entry is not None:
        ev["element"] = _handle_label(entry)
        ev["handle"] = f'[{entry.get("idx")}]'
    if nav:
        ev.update(nav)
    out = _receipt_fail(method, reason, **fields)
    out["evidence"] = ev
    if handle is not None:
        out["handle"] = handle
    return out


# ── Navigation anchor (0.9.4-P1 M2) ─────────────────────────────────
# The handle map records the navigation index at `cdp_see` time (ax_tree
# NAV_ID_KEY). Reading the index again at action time turns "the table may be
# stale" from a gamble into a signal. The element-identity check
# (DOM.resolveNode / fresh box) still decides success or failure; the anchor
# only *warns*, and only when both readings are known and differ.
STALE_WARNING = "navigation occurred since last cdp_see — handle table may be stale"


def _read_nav_id(ws, msg_id=29):
    """Page.getNavigationHistory currentEntry index, or None if unreadable."""
    try:
        r = cdp_call(ws, "Page.getNavigationHistory", {}, msg_id=msg_id, timeout=5)
        v = (r or {}).get("currentIndex")
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    except Exception:
        return None


def _nav_evidence(see_nav_id, nav_id_at_action):
    """Evidence fragment: the action-time anchor (+ stale warning when it moved).

    Only *known* anchors that disagree warn — an unreadable anchor on either
    side must never be turned into a false warning.
    """
    ev = {"nav_id_at_action": nav_id_at_action}
    if (see_nav_id is not None and nav_id_at_action is not None
            and see_nav_id != nav_id_at_action):
        ev["warnings"] = [STALE_WARNING]
    return ev


# ── Interactive-descendant redirect (0.9.4-P4 M2) ────────────────────
# `<h3><a href…>title</a></h3>` exposes two AX nodes: heading (non-interactive)
# and link. Clicking the heading only works because the link happens to fill it —
# a coincidence that breaks as soon as the heading gains another child. When the
# AX map marks a non-interactive node as wrapping interactive descendants, click
# the descendant instead (unique) or refuse and name the candidates (several).
_DESC_SELECTOR = "a,button,input,select,textarea,[role]"
_TAG_ROLE = {"A": "link", "BUTTON": "button", "INPUT": "textbox",
             "SELECT": "combobox", "TEXTAREA": "textbox"}


# ── Clickable point (0.9.4-P5) ───────────────────────────────────────
# getBoundingClientRect returns the *bounding box*. For a multi-line inline
# element (GitHub's issue-title <a>) the box spans the line gaps — points that
# belong to no element. A coordinate click dispatched at the box centre then
# hits an ancestor container: the click's target chain has no <a>, so the
# browser never performs the default navigation (receipt says ok, nothing
# happens). Fix: before dispatching, verify with elementFromPoint that the
# point's hit chain contains the target (the element itself or a descendant);
# when the centre misses, grid-scan the box for a point that does. An ancestor
# hit does NOT count — that is exactly the bug.
_FIND_CLICKABLE_FN = (
    "function(){"
    "var el=this;var r=el.getBoundingClientRect();"
    "if(r.width<=0||r.height<=0)return JSON.stringify({point:null,why:'zero-size box'});"
    "var vw=window.innerWidth,vh=window.innerHeight;"
    "if(r.right<0||r.bottom<0||r.left>vw||r.top>vh)"
    "return JSON.stringify({point:null,why:'outside viewport'});"
    "function hits(x,y){var e=document.elementFromPoint(x,y);"
    "return !!(e&&(e===el||el.contains(e)));}"
    "var cx=r.left+r.width/2,cy=r.top+r.height/2;"
    "if(hits(cx,cy))return JSON.stringify({point:[cx,cy],how:'center'});"
    "for(var yi=1;yi<=15;yi++){for(var xi=1;xi<=5;xi++){"
    "var x=r.left+r.width*xi/6;var y=r.top+r.height*yi/16;"
    "if(hits(x,y))return JSON.stringify({point:[x,y],how:'grid_scan'});}}"
    "return JSON.stringify({point:null,why:'no clickable point (covered)'});"
    "}")


def _clickable_point(ws, object_id, msg_id=36):
    """(point_css_px, how) for a live node, or (None, why) / (None, None).

    The point's elementFromPoint hit chain must contain the node itself (or a
    descendant) — an ancestor hit means the click would land on the wrong
    element (0.9.4-P5). (None, why) is returned only when the JS probe
    *explicitly* reports no clickable point (covered / zero-size). A probe
    that could not run, or whose answer has an unexpected shape, returns
    (None, None) — the caller falls back to the legacy centre instead of
    failing blind on a probe artefact.
    """
    try:
        raw = cdp_call(ws, "Runtime.callFunctionOn",
                       {"objectId": object_id, "functionDeclaration": _FIND_CLICKABLE_FN,
                        "returnByValue": True}, msg_id=msg_id, timeout=10)
    except Exception:
        return None, None
    value = ((raw or {}).get("result") or {}).get("value")
    try:
        data = json.loads(value)
    except Exception:
        return None, None
    if not isinstance(data, dict) or "point" not in data:
        return None, None
    pt = data.get("point")
    if isinstance(pt, list) and len(pt) == 2:
        return [float(pt[0]), float(pt[1])], data.get("how")
    return None, data.get("why") or "no clickable point"


def _desc_role(tag, role_attr):
    if role_attr:
        return role_attr
    return _TAG_ROLE.get((tag or "").upper(), (tag or "").lower() or "?")


def _desc_label(c):
    role = _desc_role(c.get("tag"), c.get("role"))
    text = (c.get("text") or "").strip()
    return f'{role} "{text}"' if text else str(role or "?")


def _desc_brief(c):
    """Compact candidate for a failure receipt (P2 diagnostic style)."""
    brief = {"tag": c.get("tag"), "text": (c.get("text") or "")[:80]}
    if c.get("href") is not None:
        brief["href"] = c.get("href")
    return brief


def _redirect_candidates(ws, object_id, msg_id=34):
    """(the node's rendered interactive descendants, error-or-None).

    A simplified DOM reading of the spec's rule — a/button/input/select/textarea
    plus any element carrying a non-empty `role` — kept to elements that have a
    real box (zero-size candidates are not click targets anywhere in hand). The
    container is scrolled into view first (behavior:'instant'), so the returned
    boxes are viewport CSS px, the space Input.dispatchMouseEvent wants.
    """
    fn = ("function(){"
          "this.scrollIntoView({block:'center',inline:'center',behavior:'instant'});"
          "var sel='" + _DESC_SELECTOR + "';"
          "function findClickablePoint(el){"
          "var r=el.getBoundingClientRect();"
          "if(r.width<=0||r.height<=0)return null;"
          "function hits(x,y){var h=document.elementFromPoint(x,y);"
          "return !!(h&&(h===el||el.contains(h)));}"
          "var cx=r.left+r.width/2,cy=r.top+r.height/2;"
          "if(hits(cx,cy))return [cx,cy];"
          "for(var yi=1;yi<=15;yi++){for(var xi=1;xi<=5;xi++){"
          "var gx=r.left+r.width*xi/6;var gy=r.top+r.height*yi/16;"
          "if(hits(gx,gy))return [gx,gy];}}"
          "return null;}"
          "var all=this.querySelectorAll(sel);var out=[];"
          "for(var i=0;i<all.length;i++){var e=all[i];"
          "var r=e.getBoundingClientRect();"
          "if(!(r.width>0&&r.height>0))continue;"
          "out.push({tag:e.tagName,"
          "text:(e.innerText||e.value||'').trim().substring(0,80),"
          "href:e.getAttribute('href'),role:e.getAttribute('role'),"
          "x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height,"
          "click:findClickablePoint(e)});}"
          "return JSON.stringify(out);}")
    try:
        raw = cdp_call(ws, "Runtime.callFunctionOn",
                       {"objectId": object_id, "functionDeclaration": fn,
                        "returnByValue": True}, msg_id=msg_id, timeout=10)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    value = ((raw or {}).get("result") or {}).get("value")
    try:
        data = json.loads(value)
    except Exception as e:
        return None, f"unreadable redirect probe ({type(e).__name__}: {e})"
    return (data if isinstance(data, list) else []), None


def _dpr_now(ws):
    """devicePixelRatio through this module's call surface (mockable)."""
    try:
        r = cdp_call(ws, "Runtime.evaluate",
                     {"expression": "window.devicePixelRatio", "returnByValue": True},
                     msg_id=28, timeout=5)
        v = r.get("result", {}).get("value")
        return float(v) if v else _get_dpr(ws)
    except Exception:
        return _get_dpr(ws)


def _viewport_size(ws, msg_id=33):
    """Viewport size in CSS px (`window.innerWidth/innerHeight`) → (size, known).

    0.9.3-P0: a rect taken after `scrollIntoView` is only a *landing point* if the
    scroll already happened. Pages with `html {scroll-behavior: smooth}` (GitHub)
    animate it asynchronously, so the sync rect read can still be the
    pre-animation position and the dispatch lands outside the viewport — where
    the mouse event has no target and the click is silently lost.

    `known=False` when the browser cannot answer (no usable w/h): the caller must
    then not claim a geometric check it never made (nothing is fabricated).
    """
    try:
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": "JSON.stringify({w: window.innerWidth, "
                                      "h: window.innerHeight})",
                        "returnByValue": True}, msg_id=msg_id, timeout=5)
    except Exception:
        return {"w": 0, "h": 0}, False
    value = ((raw or {}).get("result") or {}).get("value")
    if not isinstance(value, str):
        return {"w": 0, "h": 0}, False
    try:
        data = json.loads(value)
    except Exception:
        return {"w": 0, "h": 0}, False
    if not isinstance(data, dict):
        return {"w": 0, "h": 0}, False
    w, h = data.get("w"), data.get("h")
    if (isinstance(w, (int, float)) and isinstance(h, (int, float))
            and not isinstance(w, bool) and not isinstance(h, bool)
            and w > 0 and h > 0):
        return {"w": int(w), "h": int(h)}, True
    return {"w": 0, "h": 0}, False


def _handle_object_id(ws, backend_node_id):
    """backendNodeId → live objectId (None if the node is gone / unresolvable).

    Contract: never raises. A handle whose node vanished (page navigated, list
    re-rendered) must produce an unverified receipt naming that, never a crash.
    """
    try:
        cdp_call(ws, "DOM.getDocument", {"depth": 0}, msg_id=30, timeout=10)
        res = cdp_call(ws, "DOM.resolveNode", {"backendNodeId": backend_node_id},
                       msg_id=31, timeout=10)
        return ((res or {}).get("object") or {}).get("objectId")
    except Exception:
        return None


def _handle_rect(ws, object_id, scroll=True):
    """Viewport CSS-px center + size of a live node, or None if it has no box.

    getBoundingClientRect is viewport-relative by definition — exactly the space
    Input.dispatchMouseEvent wants (hand's physical px = CSS × dpr).
    """
    scroll_js = "this.scrollIntoView({block:'center',inline:'center',behavior:'instant'});"
    fn = ("function(){" + (scroll_js if scroll else "") +
          "var r=this.getBoundingClientRect();"
          "return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,"
          "w:r.width,h:r.height});}")
    raw = cdp_call(ws, "Runtime.callFunctionOn",
                   {"objectId": object_id, "functionDeclaration": fn,
                    "returnByValue": True}, msg_id=32, timeout=10)
    value = ((raw or {}).get("result") or {}).get("value")
    try:
        data = json.loads(value)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("w") or not data.get("h"):
        return None      # zero-size: not clickable, say so instead of clicking
    return data


def cdp_click_handle(handle, page_sel=None):
    """Click the element behind a cdp_see(kind=a11y) `[idx]` handle."""
    entry = resolve_handle(handle)
    if "error" in entry:
        return _handle_fail(entry["error"], handle=str(handle))
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        # 0.9.4-P1 M2: the action-time navigation anchor. The stale warning rides
        # in evidence (design decision #1) and appears on failure receipts too.
        nav_ev = _nav_evidence(entry.get("_see_nav_id"), _read_nav_id(ws))
        oid = _handle_object_id(ws, entry["backend_node_id"])
        if not oid:
            return _handle_fail(
                f'handle [{entry["idx"]}] element is gone (backendNodeId '
                f'{entry["backend_node_id"]} does not resolve) — call cdp_see again',
                entry=entry, handle=str(handle), nav=nav_ev)
        rect = None
        redirect_ev = None
        # 0.9.4-P4 M2: a non-interactive node that wraps interactive descendants
        # (heading → link) is clicked at the descendant, not at the coincidental
        # overlap. Several descendants → refuse and name them; zero (a stale
        # contains_interactive flag) or an unreadable probe → normal path below.
        if not entry.get("interactive") and entry.get("contains_interactive"):
            cands, derr = _redirect_candidates(ws, oid)
            if derr is None and cands is not None:
                if len(cands) > 1:
                    briefs = [_desc_brief(c) for c in cands[:3]]
                    out = _handle_fail(
                        f'handle [{entry["idx"]}] {_handle_label(entry)} is not '
                        f'interactive and contains {len(cands)} interactive '
                        f'descendants — ambiguous target, not redirecting; click '
                        f'one of the candidates explicitly',
                        entry=entry, handle=str(handle), nav=nav_ev,
                        candidates=briefs)
                    # same double exposure as the P2 text-match failure: the
                    # candidates are diagnosable from the top level and from the
                    # evidence block alike.
                    out["evidence"]["candidates"] = briefs
                    return out
                if len(cands) == 1:
                    c = cands[0]
                    # 0.9.4-P5: the unique candidate's dispatch point is its
                    # verified clickable point (elementFromPoint hit chain), not
                    # the bounding-box centre — an inline multi-line link's
                    # centre can sit in a line gap that belongs to no element.
                    if not c.get("click"):
                        return _handle_fail(
                            f'handle [{entry["idx"]}] {_handle_label(entry)} '
                            f'redirect target has no clickable point (covered) '
                            f'— not dispatching',
                            entry=entry, handle=str(handle), nav=nav_ev)
                    rect = {"x": c["click"][0], "y": c["click"][1],
                            "w": c["w"], "h": c["h"]}
                    redirect_ev = {
                        "redirected": True,
                        "original": _handle_label(entry),
                        "redirect_target": _desc_label(c),
                        "redirect_target_href": c.get("href"),
                    }
        if rect is None:
            rect = _handle_rect(ws, oid)
        if rect is None:
            return _handle_fail(
                f'handle [{entry["idx"]}] element has no box (display:none, '
                f'zero-size or detached) — call cdp_see again',
                entry=entry, handle=str(handle), nav=nav_ev)
        # 0.9.4-P5: the box centre may sit in an inline line gap — a point that
        # belongs to no element, where the click would land on an ancestor
        # (receipt ok, nothing happens). Verify the hit chain; grid-scan when
        # the centre misses. A probe *transport* failure falls back to the
        # centre (legacy behaviour) rather than failing blind. A P4 redirect
        # already carries its own verified clickable point — do not overwrite
        # it with a probe of the (non-interactive) original node.
        if redirect_ev:
            click_pt = [rect["x"], rect["y"]]
            click_how = "redirect_target_clickable_point"
        else:
            click_pt, click_how = _clickable_point(ws, oid)
            # 'outside viewport' defers to the 0.9.3-P0 viewport check below —
            # its failure names the real viewport size; a JS-side size would be
            # a second, weaker source of the same fact.
            if (click_pt is None and click_how is not None
                    and click_how != "outside viewport"):
                return _handle_fail(
                    f'handle [{entry["idx"]}] element has no clickable point '
                    f'({click_how}) — covered by another element',
                    entry=entry, handle=str(handle), nav=nav_ev)
            if click_pt is None:
                click_pt = [rect["x"], rect["y"]]
                click_how = "center (probe unavailable)"
        viewport, vp_known = _viewport_size(ws)
        vw, vh = viewport["w"], viewport["h"]
        in_viewport = None
        if vp_known:
            # the dispatch point (click_pt, viewport CSS px) is compared against
            # the real viewport before dispatching. A point outside has no target
            # element, so the mouse event would be dropped without a trace.
            in_viewport = (0 <= click_pt[0] < vw) and (0 <= click_pt[1] < vh)
            if not in_viewport:
                return _handle_fail(
                    f'handle [{entry["idx"]}] click point '
                    f'({click_pt[0]:.0f},{click_pt[1]:.0f}) is outside viewport '
                    f'({vw}x{vh}) — scroll did not take effect',
                    entry=entry, handle=str(handle), nav=nav_ev)
        dpr = _dpr_now(ws)
        dispatched = [round(click_pt[0] * dpr), round(click_pt[1] * dpr)]
        _click_at(ws, dispatched[0], dispatched[1], dpr)
        _write_last(idx)
        evidence = {
            "element": _handle_label(entry),
            "role": entry.get("role"),
            "name": entry.get("name"),
            "handle": f'[{entry["idx"]}]',
            "backend_node_id": entry["backend_node_id"],
            "box": {"x": round(rect["x"], 1), "y": round(rect["y"], 1),
                    "w": round(rect["w"], 1), "h": round(rect["h"], 1)},
            "space": "physical", "dpr": dpr, "dispatched": dispatched,
            "viewport": {"w": vw, "h": vh},
            "in_viewport": in_viewport,
            "click_point": {"how": click_how,
                            "x": round(click_pt[0], 1), "y": round(click_pt[1], 1)},
            "read_back": "getBoundingClientRect via DOM.resolveNode",
            "source": "cdp_see(kind=a11y) handle map",
            "verified": True,
        }
        if redirect_ev:
            evidence.update(redirect_ev)
        evidence.update(nav_ev)
        return {"method": "cdp_click", "handle": f'[{entry["idx"]}]',
                "page_index": idx, "result": "ok", "tiers": "handle",
                "verified": True, "evidence": evidence}
    finally:
        ws.close()


def cdp_type_handle(handle, text, page_sel=None):
    """Focus the element behind an `[idx]` handle, then type into it."""
    entry = resolve_handle(handle)
    if "error" in entry:
        out = _handle_fail(entry["error"], handle=str(handle), method="cdp_type")
        out["text"] = text
        return out
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        # 0.9.4-P1 M2: same navigation anchor as the click path. Type is *not*
        # redirected onto descendants (P4 explicitly excludes it — an ambiguous
        # focus target is worse than an explicit staleness signal).
        nav_ev = _nav_evidence(entry.get("_see_nav_id"), _read_nav_id(ws))
        oid = _handle_object_id(ws, entry["backend_node_id"])
        if not oid:
            out = _handle_fail(
                f'handle [{entry["idx"]}] element is gone (backendNodeId '
                f'{entry["backend_node_id"]} does not resolve) — call cdp_see again',
                entry=entry, handle=str(handle), method="cdp_type", nav=nav_ev)
            out["text"] = text
            return out
        cdp_call(ws, "Runtime.callFunctionOn",
                 {"objectId": oid,
                  "functionDeclaration": "function(){this.focus();"
                                         "return JSON.stringify({focused:true});}",
                  "returnByValue": True}, msg_id=33, timeout=10)
        focus = _active_element(ws, msg_id=34)
        tag = (focus.get("tag") or "").upper()
        if tag in ("", "BODY", "HTML"):
            out = _handle_fail(
                f'focus did not land on handle [{entry["idx"]}] '
                f'(activeElement is {tag or "missing"}) — call cdp_see again',
                entry=entry, handle=str(handle), method="cdp_type", nav=nav_ev)
            out["text"] = text
            return out
        # 0.9.4-P3: the focused element's own tag decides what "\n" means.
        enter_mode = _type_enter_mode(tag, entry.get("role"))
        used_enter = _insert_text(ws, text, enter_mode, msg_id=35)
        _write_last(idx)
        evidence = {
            "element": _handle_label(entry),
            "role": entry.get("role"), "name": entry.get("name"),
            "handle": f'[{entry["idx"]}]',
            "backend_node_id": entry["backend_node_id"],
            "focus": _focus_label(focus),
            "method_detail": "DOM.resolveNode → focus() → Input.insertText",
            "enter_mode": used_enter,
            "verified": True,
        }
        evidence.update(nav_ev)
        return {"method": "cdp_type", "handle": f'[{entry["idx"]}]',
                "page_index": idx, "text": text, "result": "ok",
                "verified": True, "evidence": evidence}
    finally:
        ws.close()


def cdp_click(selector, page_sel=None):
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        # Pre-flight: never click blind. A selector that matches nothing fails here.
        hit = _selector_hit(ws, selector)
        if not hit.get('found'):
            reason = f'selector did not match any element: {selector!r}'
            if hit.get('parse_error'):
                reason += f" (verification failed: {hit['parse_error']})"
            return _receipt_fail('cdp_click', reason, selector=selector)
        info = _element_info(ws, selector)
        if 'error' in info:
            return _receipt_fail('cdp_click',
                                 f"element info failed: {info['error']}", selector=selector)
        if not info.get('visible'):
            _scroll_into_view(ws, selector)
            time.sleep(0.2)
            info = _element_info(ws, selector)
        x, y = info['x'], info['y']
        dpr = _get_dpr(ws)
        _click_at(ws, x, y, dpr)
        _js_click(ws, selector, msg_id=10)
        # 输入元素（input/textarea）只聚焦不提交：_js_focus_enter 触发 Enter 键、
        # _js_submit 触发 form.submit()，对搜索框这类输入框是破坏性的（提交空查询、
        # 清空焦点）。只有动作元素（button/a）才需要这两步真正触发动作。
        tag = (info.get('tag') or '').upper()
        if tag not in ('INPUT', 'TEXTAREA'):
            _js_focus_enter(ws, selector, msg_id=15)
            _js_submit(ws, selector, msg_id=20)

        _write_last(idx)
        ev = _element_evidence(info)
        ev['verified'] = True
        ev['selector'] = selector
        ev['read_back'] = 'document.querySelector hit + getBoundingClientRect'
        return {'method': 'cdp_click', 'selector': selector, 'page_index': idx,
                'result': 'ok', 'tiers': '4-tier',
                'verified': True, 'evidence': ev}
    finally:
        ws.close()

def cdp_type(selector, text, page_sel=None, fast=False):
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        if fast:
            expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
                    'if(!el)return JSON.stringify({error:"element not found"});'
                    'el.value=' + json.dumps(text) + ';'
                    'el.dispatchEvent(new Event("input",{bubbles:true}));'
                    'el.dispatchEvent(new Event("change",{bubbles:true}));'
                    'return JSON.stringify({result:"ok",fast:true});'
                    '})()')
            result = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
            value_str = result.get('result', {}).get('value', '{}')
            try:
                data = json.loads(value_str)
            except Exception as e:
                return _receipt_fail('cdp_type',
                                     f"fast-path result unreadable: {type(e).__name__}: {e}",
                                     selector=selector, text=text)
            _write_last(idx)
            out = {'method': 'cdp_type', 'page_index': idx, 'fast': True,
                   'text': text, **data}
            if data.get('error'):
                out.update(_receipt_fail('cdp_type',
                                         f"fast path failed: {data['error']}",
                                         selector=selector, text=text))
                out['page_index'] = idx
                out['fast'] = True
            else:
                # JS path writes the value and dispatches input/change — it does
                # not go through focus/keyboard, so the evidence says exactly that.
                out['verified'] = True
                out['evidence'] = {'element': selector, 'value_length': len(text),
                                   'method_detail': 'el.value set + input/change events dispatched',
                                   'keyboard_events': False, 'verified': True}
            return out
        pass  # Input domain needs no enable
        hit = _selector_hit(ws, selector)
        if not hit.get('found'):
            reason = f'selector did not match any element: {selector!r}'
            if hit.get('parse_error'):
                reason += f" (verification failed: {hit['parse_error']})"
            return _receipt_fail('cdp_type', reason, selector=selector, text=text)
        info = _element_info(ws, selector)
        if 'error' in info:
            return _receipt_fail('cdp_type',
                                 f"element info failed: {info['error']}",
                                 selector=selector, text=text)
        x, y = info['x'], info['y']
        _click_at(ws, x, y, _get_dpr(ws))
        # 0.9.4-P3: _element_info already reports the tag, so "\n" forks here.
        enter_mode = _type_enter_mode(info.get('tag'))
        used_enter = _insert_text(ws, text, enter_mode, msg_id=20)
        _write_last(idx)
        ev = _element_evidence(info)
        ev['verified'] = True
        ev['selector'] = selector
        ev['read_back'] = 'document.querySelector hit + Input.insertText'
        ev['enter_mode'] = used_enter
        return {'method': 'cdp_type', 'page_index': idx, 'selector': selector,
                'text': text, 'result': 'ok',
                'verified': True, 'evidence': ev}
    finally:
        ws.close()

def _js_click(ws, selector, msg_id):
    expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
            'if(!el)return JSON.stringify({error:"element not found"});'
            'el.click();return JSON.stringify({result:"js_click ok"});'
            '})()')
    cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)

def _js_focus_enter(ws, selector, msg_id):
    expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
            'if(!el)return JSON.stringify({error:"element not found"});'
            'el.focus();el.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",keyCode:13,bubbles:true}));'
            'el.dispatchEvent(new KeyboardEvent("keyup",{key:"Enter",keyCode:13,bubbles:true}));'
            'return JSON.stringify({result:"focus_enter ok"});'
            '})()')
    cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)

def _js_submit(ws, selector, msg_id):
    expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
            'if(!el)return JSON.stringify({error:"element not found"});'
            'if(el.form)el.form.submit();else if(el.onclick)el.onclick();'
            'else el.dispatchEvent(new MouseEvent("click",{bubbles:true}));'
            'return JSON.stringify({result:"submit ok"});'
            '})()')
    cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)

# ── Router-compatible wrappers ──────────────────────────────────────

def cdp_click_do(action, app_name=None):
    """
    Router-compatible wrapper. Accepts:
    - CSS selector: '#submit', 'a.login', 'button'
    - text= prefix: 'text=Learn more'
    - xy: prefix: 'xy:412,188' — physical pixels (CSS px × devicePixelRatio),
      same convention as interactive_map's {x, y}; feed those values straight in.
    """
    sel = action
    if looks_like_handle(action):
        # cdp_see(kind=a11y) handle: '[93]' / 'idx:93'
        return cdp_click_handle(action)
    if action.startswith('text='):
        text_val = action[5:]
        pages = list_pages()
        idx, page = resolve_page(None, pages)
        ws = cdp_connect(page['webSocketDebuggerUrl'])
        try:
            _init_domains(ws, 'Runtime')
            # Use single-quote JS strings for XPath to avoid nesting conflicts with json.dumps double-quotes
            q = json.dumps(text_val)  # produces "Learn more" — double-quoted
            # 0.9.4-P2 (spec docs/spec-0.9.4-p2-textmatch.md): `text()` matches
            # only *direct* text children, so an `<a><span>Title</span></a>` —
            # GitHub issues, most modern sites — never matched, while `.` is the
            # node's full string value (all descendant text). normalize-space()
            # folds whitespace differences; the third branch keeps the exact
            # (`=`) semantic as the "whole text" fallback. Matching stays
            # case-sensitive (XPath contains) — unchanged by this fix.
            expr = (
                "(function(){"
                "var xpath='//a[contains(normalize-space(.),"+q+")]|"
                "//button[contains(normalize-space(.),"+q+")]|"
                "//*[normalize-space(.)="+q+" and not(*[normalize-space(.)="+q+"])]';"
                "var r=document.evaluate(xpath,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);"
                "var el=r.singleNodeValue;"
                "if(!el)return JSON.stringify({error:'text element not found',search:"+q+",candidates:"
                "(function(){var qt="+q+";var out=[];"
                "var all=document.evaluate('//a|//button',document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);"
                "for(var i=0;i<all.snapshotLength&&out.length<3;i++){var n=all.snapshotItem(i);"
                "var t=(n.innerText||'').trim();"
                "if(t&&t.toLowerCase().indexOf(qt.toLowerCase())>=0){"
                "out.push({tag:n.tagName,text:t.substring(0,80),href:n.getAttribute('href')||null});}}"
                "return out;})()});"
                "var box=null;"
                "function hits(x,y){var e=document.elementFromPoint(x,y);"
                "return !!(e&&(e===el||el.contains(e)));}"
                "var r=el.getBoundingClientRect();var dpr=window.devicePixelRatio||1;"
                "if(r.width<=0||r.height<=0)"
                "return JSON.stringify({error:'no clickable point (zero-size)',search:"+q+"});"
                "var cx=r.left+r.width/2,cy=r.top+r.height/2;"
                "if(hits(cx,cy))return JSON.stringify({x:cx*dpr,y:cy*dpr,how:'center',"
                "tag:el.tagName,text:(el.innerText||'').substring(0,80)});"
                "for(var yi=1;yi<=15;yi++){for(var xi=1;xi<=5;xi++){"
                "var gx=r.left+r.width*xi/6;var gy=r.top+r.height*yi/16;"
                "if(hits(gx,gy))return JSON.stringify({x:gx*dpr,y:gy*dpr,how:'grid_scan',"
                "tag:el.tagName,text:(el.innerText||'').substring(0,80)});}}"
                "return JSON.stringify({error:'no clickable point (covered)',search:"+q+","
                "tag:el.tagName,text:(el.innerText||'').substring(0,80)});"
                "})()")
            raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
            value_str = raw.get('result', {}).get('value', '{}')
            info = json.loads(value_str)
            if 'error' in info:
                # Failure receipt + one loose scan: the a/button labels that came
                # closest, so "not found" is diagnosable instead of a guess.
                # The scan ignores case on purpose (a case miss is the most
                # common reason a label exists but the XPath did not hit).
                cands = info.get('candidates') or []
                out = _receipt_fail('cdp_click',
                                    f"{info['error']}: {text_val!r}",
                                    action=action, text_match=text_val,
                                    candidates=cands)
                out['evidence']['candidates'] = cands
                return out

            x, y = info['x'], info['y']
            dpr = _get_dpr(ws)
            _click_at(ws, x, y, dpr)
            _write_last(idx)
            ev = _element_evidence({'tag': info.get('tag'),
                                    'text': info.get('text')})
            ev['verified'] = True
            ev['text_match'] = text_val
            ev['click_point'] = {'how': info.get('how'),
                                 'x': round(x / dpr, 1), 'y': round(y / dpr, 1)}
            ev['read_back'] = ('XPath normalize-space(.) hit + '
                              'elementFromPoint hit-chain verified')
            return {'method': 'cdp_click', 'text_match': text_val,
                    'tag': info.get('tag'), 'page_index': idx, 'result': 'ok',
                    'verified': True, 'evidence': ev}
        finally:
            ws.close()
    if action.startswith('xy:'):
        try:
            parts = action[3:].strip().split(',')
            x, y = int(round(float(parts[0].strip()))), int(round(float(parts[1].strip())))
        except (ValueError, IndexError):
            return _receipt_fail('cdp_click',
                                 'invalid xy format, expected "xy:X,Y"', action=action)
        pages = list_pages()
        idx, page = resolve_page(None, pages)
        ws = cdp_connect(page['webSocketDebuggerUrl'])
        try:
            _init_domains(ws, 'Runtime')
            dpr = _get_dpr(ws)
            _click_at(ws, x, y, dpr)
            _write_last(idx)
            # Dispatch-only: a coordinate click cannot be verified against an
            # element, so it never claims verified=True.
            return {'method': 'cdp_click', 'xy': [x, y], 'page_index': idx,
                    'result': 'ok', 'verified': False,
                    'evidence': {'verified': False, 'space': 'physical',
                                 'dispatched': [x, y], 'dpr': dpr,
                                 'reason': 'coordinate click: dispatch-only, no element to verify '
                                           '(use a selector for a verified receipt)'}}
        finally:
            ws.close()
    return cdp_click(sel)

def cdp_type_do(action, app_name=None):
    """
    Router-compatible wrapper. 'action' is 'selector|text' format.
    Example: 'input#search|Hello World'
    """
    if '|' in action:
        sel, text = action.split('|', 1)
        if looks_like_handle(sel.strip()):
            # cdp_see(kind=a11y) handle: '[93]|hello'
            return cdp_type_handle(sel.strip(), text.strip())
        return cdp_type(sel.strip(), text.strip())
    return _receipt_fail('cdp_type', 'cdp_type needs selector|text format', action=action)


def cdp_type_focused(text, page_sel=None):
    """Type into the currently focused element via Input.insertText.

    Contract: types into whatever element already has focus (set by a prior
    cdp_click). Distinct from cdp_type(selector, text) which clicks first.
    The MCP tool 'cdp_type' is documented as 'type into focused element', so
    it must use this — NOT route_do, which routes to cdp_click first and
    misinterprets the text as a CSS selector.
    """
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        # Pre-flight: Input.insertText goes to whatever has focus — if nothing
        # does, the text vanishes. Verify the focus target first (PRD S3).
        focus = _active_element(ws)
        if focus.get('parse_error'):
            return _receipt_fail('cdp_type',
                                 f"focus verification failed: {focus['parse_error']}",
                                 text=text)
        tag = (focus.get('tag') or '').upper()
        if tag in ('', 'BODY', 'HTML'):
            return _receipt_fail(
                'cdp_type',
                f"no focused element (activeElement is {tag or 'missing'}) — "
                "click the field first, or use cdp_type(selector, text)",
                text=text)
        # Input domain needs no enable. 0.9.4-P3: the pre-flight already read
        # activeElement, so its tagName (already in `focus`) decides the "\n"
        # fork without a second round trip.
        enter_mode = _type_enter_mode(tag)
        used_enter = _insert_text(ws, text, enter_mode, msg_id=20)
        _write_last(idx)
        return {'method': 'cdp_type', 'page_index': idx, 'text': text,
                'result': 'ok', 'verified': True,
                'evidence': {'focus': _focus_label(focus), 'tag': tag,
                             'focus_id': focus.get('id') or '',
                             'focus_type': focus.get('type') or '',
                             'enter_mode': used_enter,
                             'verified': True}}
    finally:
        ws.close()


# ── Scroll ────────────────────────────────────────────────────────────

def _scroll_y(ws):
    """Current window.scrollY in CSS px."""
    result = cdp_call(ws, 'Runtime.evaluate', {'expression': 'window.scrollY || 0'}, msg_id=30)
    return result.get('result', {}).get('value', 0)


def _viewport_height(ws):
    """One screen height in CSS px — the default scroll amount."""
    result = cdp_call(ws, 'Runtime.evaluate', {'expression': 'window.innerHeight || 800'}, msg_id=31)
    return result.get('result', {}).get('value', 800)


def cdp_scroll(direction='down', amount=None, page_sel=None):
    """Scroll the page. Real wheel events for down/up, scrollTo for top/bottom.

    direction: down / up / top / bottom. down/up default to one screen height
    and use CDP Input.dispatchMouseEvent (mouseWheel) — equivalent to a user
    wheel, triggers lazy loading / infinite scroll; window.scrollBy is the
    fallback. top/bottom use window.scrollTo.
    Returns scrollY before/after; moved=False means already at the end/edge —
    a signal, not an error.
    """
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        d = str(direction).lower()
        before = _scroll_y(ws)

        if d == 'top':
            cdp_call(ws, 'Runtime.evaluate', {'expression': 'window.scrollTo(0,0)'}, msg_id=5)
        elif d == 'bottom':
            cdp_call(ws, 'Runtime.evaluate', {'expression': 'window.scrollTo(0, document.body.scrollHeight)'}, msg_id=6)
        else:
            delta = amount if amount is not None else _viewport_height(ws)
            delta = abs(int(delta))
            deltaY = -delta if d == 'up' else delta
            try:
                cdp_call(ws, 'Input.dispatchMouseEvent',
                         {'type': 'mouseWheel', 'x': 0, 'y': 0,
                          'deltaX': 0, 'deltaY': deltaY,
                          'deltaX_single': 0, 'deltaY_single': deltaY,
                          'modifiers': 0}, msg_id=7)
            except Exception:
                # Fallback: wheel event may fail on some pages — direct scroll.
                cdp_call(ws, 'Runtime.evaluate',
                         {'expression': 'window.scrollBy(0, %d)' % deltaY}, msg_id=8)
        # Scroll (wheel dispatch AND scrollTo) is processed asynchronously —
        # settle before reading scrollY, or the before/after diff reads a stale
        # value. Applies to all directions, not just wheel.
        time.sleep(0.3)

        after = _scroll_y(ws)
        _write_last(idx)
        # Natural evidence: the read-back scrollY diff. moved=False means the
        # page did not move (already at the edge) — a signal, not an error.
        return {'method': 'cdp_scroll', 'direction': d,
                'scrollY_before': before, 'scrollY_after': after,
                'moved': after != before,
                'verified': True,
                'evidence': {'scrollY_before': before, 'scrollY_after': after,
                             'moved': after != before, 'direction': d,
                             'read_back': 'window.scrollY', 'verified': True}}
    finally:
        ws.close()


def cdp_scroll_do(action, app_name=None):
    """Router-compatible wrapper. 'action' is 'scroll down/up/top/bottom'
    (also accepts 'scroll to <direction>'). Direction defaults to down.
    """
    d = 'down'
    toks = action.strip().lower().split()
    if len(toks) >= 2 and toks[1] in ('down', 'up', 'top', 'bottom'):
        d = toks[1]
    elif len(toks) >= 3 and toks[1] == 'to' and toks[2] in ('down', 'up', 'top', 'bottom'):
        d = toks[2]
    return cdp_scroll(d)
