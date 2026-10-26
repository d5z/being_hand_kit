"""
CDP Action — browser click/type via Chrome DevTools Protocol.
4-tier fallback for click preserved from V5.

COORDINATE CONTRACT: all coordinates in this module (see output such as
interactive_map/_element_info, and do input such as "xy:X,Y") are PHYSICAL
pixels = CSS px × devicePixelRatio. CDP Input.dispatchMouseEvent expects
viewport CSS px, so _click_at divides by dpr before dispatching.
"""
import json, re, time
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


# ── Type target editability + read-back (F22) ────────────────────────
# Input.insertText goes to the browser text-input context, not
# document.activeElement. A SELECT or a BODY focus used to produce an
# ok+verified receipt with zero landing. Pre-flight refuses non-editable
# / readonly / disabled targets; post-flight substring-reads the field
# (before keyboard-mode Enter, which may submit-and-clear).

_NON_TEXT_INPUT_TYPES = frozenset({
    'checkbox', 'radio', 'button', 'submit', 'reset',
    'file', 'image', 'color', 'range', 'hidden',
})


def _is_text_editable(tag, input_type=None, is_content_editable=False):
    """Can Input.insertText land in this element?"""
    tag_u = (tag or '').upper()
    if tag_u == 'TEXTAREA':
        return True
    if tag_u == 'INPUT':
        return (input_type or '').lower() not in _NON_TEXT_INPUT_TYPES
    if is_content_editable:
        return True
    return False


def _not_editable_reason(tag):
    tag_u = (tag or '').upper() or '?'
    return (
        f"target is not text-editable (<{tag_u}>) — Input.insertText would go "
        "to the browser text-input context, not this element; use cdp_click "
        "on an option, or a custom dropdown control"
    )


def _land_fail_reason(typed, after):
    return (
        f"text did not land (zero-landing): typed {typed!r}, field now {after!r} "
        "— the browser text-input context dropped or redirected it"
    )


def _preflight_type_block(tag, input_type=None, is_content_editable=False,
                          readonly=False, disabled=False):
    """Pre-flight reason, or None if typing may proceed."""
    if not _is_text_editable(tag, input_type, is_content_editable):
        return _not_editable_reason(tag)
    if (tag or '').upper() in ('INPUT', 'TEXTAREA') and (readonly or disabled):
        return 'field is readonly/disabled'
    return None


def _rb_evidence(rb):
    if not rb:
        return {'before': '', 'after': '', 'landed': False}
    return {
        'before': rb.get('before', ''),
        'after': rb.get('after', ''),
        'landed': bool(rb.get('landed')),
    }


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


def _insert_text(ws, text, enter_mode, msg_id=35, before_enter=None):
    """Type `text` in segments; every "\n" follows `enter_mode`.

    Keyboard-mode "\n" is a submit intent: the text segment is inserted
    first, then `before_enter(segment)` runs (post-flight read-back must
    see the field before a submit handler clears it), then Enter is
    dispatched. If `before_enter` returns a truthy value, insertion stops
    and that value is the second return item.

    ENTER_MODE_TEXT inserts the literal newline and never calls
    `before_enter` — caller does one read-back after everything.

    Returns (used_mode, early_stop). used_mode is 'keyboard_event' /
    'text_insert', or None when the text carries no "\n".
    """
    if enter_mode == ENTER_MODE_TEXT or '\n' not in text:
        for char in text:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=msg_id)
            time.sleep(0.001)
        used = enter_mode if (enter_mode == ENTER_MODE_TEXT and '\n' in text) else None
        return used, None

    parts = text.split('\n')
    used = ENTER_MODE_KEYBOARD
    for i, part in enumerate(parts):
        for char in part:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=msg_id)
            time.sleep(0.001)
        if i < len(parts) - 1:
            if before_enter is not None:
                early = before_enter(part)
                if early:
                    return used, early
            _dispatch_enter(ws, msg_id=msg_id)
            time.sleep(0.001)
    return used, None


def _type_target_attrs(ws, selector=None, msg_id=21):
    """Editability + current value of the type target.

    selector=None → document.activeElement. One Runtime.evaluate returns
    tag/type/name/id/isContentEditable/readonly/disabled/value.
    """
    if selector is not None:
        el_expr = 'document.querySelector(' + json.dumps(selector) + ')'
    else:
        el_expr = 'document.activeElement'
    expr = (
        '(function(){var el=' + el_expr + ';'
        'if(!el)return JSON.stringify({found:false});'
        'var tag=el.tagName||"";'
        'var val=(tag==="INPUT"||tag==="TEXTAREA")?(el.value||""):(el.textContent||"");'
        'return JSON.stringify({found:true,tag:tag,id:el.id||"",'
        'name:(el.getAttribute&&el.getAttribute("name"))||"",'
        'type:(el.getAttribute&&el.getAttribute("type"))||"",'
        'isContentEditable:!!el.isContentEditable,'
        'readonly:!!el.readOnly,disabled:!!el.disabled,value:val});'
        '})()'
    )
    raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True},
                   msg_id=msg_id)
    value = raw.get('result', {}).get('value') or '{}'
    try:
        data = json.loads(value)
    except Exception as e:
        return {'found': False, 'parse_error': f'{type(e).__name__}: {e}'}
    return data if isinstance(data, dict) else {'found': False}


def _read_back_target(ws, typed, before, selector=None, expect_focus=None, msg_id=22):
    """Post-flight: did `typed` appear as a substring of the field value?

    selector path reads the same selector. handle/focused reads
    document.activeElement and, when `expect_focus` is given, reports
    focus_moved if tag/id/name disagree with the pre-flight capture.
    """
    attrs = _type_target_attrs(ws, selector=selector, msg_id=msg_id)
    after = attrs.get('value', '') if attrs.get('found') else ''
    out = {'before': before, 'after': after, 'landed': typed in after}
    if expect_focus is not None:
        same = (
            attrs.get('found')
            and (attrs.get('tag') or '').upper() == (expect_focus.get('tag') or '').upper()
            and (attrs.get('id') or '') == (expect_focus.get('id') or '')
            and (attrs.get('name') or '') == (expect_focus.get('name') or '')
        )
        if not same:
            out['focus_moved'] = True
            out['landed'] = False
    return out


def _type_with_readback(ws, text, enter_mode, *, selector=None,
                        expect_focus=None, msg_id=20):
    """Insert `text` and post-flight read-back.

    Keyboard-mode "\n": read-back runs on each text segment *before* Enter.
    ENTER_MODE_TEXT / no newline: one read-back after everything.

    Returns (used_enter, read_back, fail_reason). fail_reason is None on
    success. read_back is {before, after, landed}.
    """
    before_attrs = _type_target_attrs(ws, selector=selector, msg_id=msg_id + 1)
    before = before_attrs.get('value', '') if before_attrs.get('found') else ''
    last_rb = None

    def before_enter(segment):
        nonlocal last_rb
        last_rb = _read_back_target(
            ws, segment, before, selector=selector,
            expect_focus=expect_focus, msg_id=msg_id + 2)
        if last_rb.get('focus_moved'):
            return 'focus moved during type'
        if not last_rb.get('landed'):
            return _land_fail_reason(segment, last_rb.get('after', ''))
        return None

    used, early = _insert_text(
        ws, text, enter_mode, msg_id=msg_id,
        before_enter=before_enter if enter_mode == ENTER_MODE_KEYBOARD else None)
    if early:
        return used, last_rb, early

    if enter_mode == ENTER_MODE_KEYBOARD and '\n' in text and text.endswith('\n'):
        return used, last_rb, None

    check = text
    if enter_mode == ENTER_MODE_KEYBOARD and '\n' in text:
        check = text.rsplit('\n', 1)[-1]
    last_rb = _read_back_target(
        ws, check, before, selector=selector,
        expect_focus=expect_focus, msg_id=msg_id + 2)
    if last_rb.get('focus_moved'):
        return used, last_rb, 'focus moved during type'
    if not last_rb.get('landed'):
        return used, last_rb, _land_fail_reason(check, last_rb.get('after', ''))
    return used, last_rb, None


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


_DPR_DECL_RE = re.compile(r'@dpr=([0-9]*\.?[0-9]+)(?=@|$)')


def _split_dpr_decl(spec):
    """('412,188@dpr=2') → ('412,188', 2.0). No declaration → (spec, None).

    A physical-pixel coordinate is *computed* under one devicePixelRatio and
    *dispatched* under whatever the page reports at dispatch time. When those
    two differ, the same number points at a different place on screen — and
    nothing in the receipt can say so: `dpr` is printed, but not the dpr the
    caller assumed when it did the multiplication. Declaring it here turns a
    silent miss into a refusal.

    The declaration may sit anywhere after the coordinates (before or after
    `@expect=`): '412,188@dpr=2@expect=#save' and '412,188@expect=#save@dpr=2'
    are the same string to this parser.
    """
    s = str(spec or '')
    m = _DPR_DECL_RE.search(s)
    if not m:
        return s, None
    try:
        declared = float(m.group(1))
    except ValueError:
        return s, None
    if declared <= 0:
        return s, None
    rest = (s[:m.start()] + s[m.end():]).strip().strip('@').strip()
    return rest, declared


def _dpr_decl_error(declared, runtime):
    """Reason string when the caller's dpr assumption does not hold, else None.

    `declared is None` means the caller made no claim — nothing to enforce.
    An unreadable runtime dpr is *not* a pass: the declaration exists exactly
    to prevent a silent misplacement, so guessing is the one thing we can't do.
    """
    if declared is None:
        return None
    try:
        rt = float(runtime)
    except (TypeError, ValueError):
        rt = None
    if rt is None or rt <= 0:
        return ('coordinates were declared for dpr=%s but this page would not '
                'report devicePixelRatio — refusing rather than guessing'
                % declared)
    if abs(rt - declared) < 1e-6:
        return None
    return ('dpr mismatch: coordinates were computed for dpr=%s but this page '
            'reports dpr=%s — physical px do not transfer across dpr, so this '
            'number lands on a different element. Refused before dispatch '
            '(recompute under dpr=%s, or drop the @dpr= declaration to accept '
            'the risk)' % (declared, rt, rt))


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


def _main_frame_id(ws, msg_id=44):
    """The page's root frame id (None if the browser will not say)."""
    try:
        raw = cdp_call(ws, "Page.getFrameTree", {}, msg_id=msg_id, timeout=10)
    except Exception:
        return None
    tree = ((raw or {}).get("frameTree") or {})
    return ((tree.get("frame") or {}).get("id")) or None


def _node_frame_id(ws, object_id, msg_id=45):
    """frameId that owns a live node (None unknown).

    0.13.1: a handle from cdp_see can point INTO a merged child frame. Whether it
    does changes the meaning of every number this module reads for it.
    """
    try:
        raw = cdp_call(ws, "DOM.describeNode", {"objectId": object_id},
                       msg_id=msg_id, timeout=10)
    except Exception:
        return None
    return ((raw or {}).get("node") or {}).get("frameId") or None


def _frame_content_origin(ws, frame_id, msg_id=46):
    """(dx, dy) — a child frame's CONTENT box top-left in top-level CSS px.

    Measured 2026-10-22 on a two-level fixture: DOM.getBoxModel on a frame's
    owner returns the box already in TOP-LEVEL viewport coordinates (a frame at
    (100,50) holding a frame at (20,30) reported its inner owner at (120,80),
    not (20,30)). So one lookup is enough at any nesting depth — no summing.

    Contrast with `getBoundingClientRect` via Runtime.callFunctionOn, which is
    FRAME-local for a node inside a frame. That mismatch was the 0.13.0 bug:
    see drew the right pixel (getBoxModel, top-level) and click dispatched a
    frame-local one (the probe and the rect are both frame-local, then used as
    top-level).
    """
    try:
        own = cdp_call(ws, "DOM.getFrameOwner", {"frameId": frame_id},
                       msg_id=msg_id, timeout=10)
        bid = (own or {}).get("backendNodeId")
        if not bid:
            return None
        box = cdp_call(ws, "DOM.getBoxModel", {"backendNodeId": bid},
                       msg_id=msg_id + 1, timeout=10)
    except Exception:
        return None
    model = (box or {}).get("model") or {}
    quad = model.get("content") or model.get("border") or []
    if not isinstance(quad, list) or len(quad) < 8:
        return None
    xs, ys = quad[0::2], quad[1::2]
    return float(min(xs)), float(min(ys))


def _element_border_quad(ws, backend_node_id, msg_id=47):
    """The element's BORDER box corners in top-level viewport px, or None.

    0.13.2: this is the read `cdp_see` draws with — so a click point taken from
    it lives in the space see drew, by construction. It also reflects CSS
    transforms on the element AND on its ancestors, which is exactly what no
    read taken inside a child frame can see: a `transform: scale(0.5)` on the
    <iframe> owner is invisible to `getBoundingClientRect` running in the
    frame's own context (measured 2026-10-22: 0.13.1 translated but did not
    scale — dispatched (123,126) where see drew (112,89)).
    """
    try:
        raw = cdp_call(ws, "DOM.getBoxModel", {"backendNodeId": backend_node_id},
                       msg_id=msg_id, timeout=10)
    except Exception:
        return None
    quad = ((raw or {}).get("model") or {}).get("border") or []
    if not isinstance(quad, list) or len(quad) < 8:
        return None
    return [float(v) for v in quad[:8]]


def _map_local_to_top(quad, local_bounds, pt):
    """frame-local point → top-level px, via the element's own quad (bilinear).

    An affine transform (translate / scale / rotate / skew) preserves bilinear
    interpolation on a quad, so expressing the local point's position inside the
    local rect and reading that position across the quad's corners is exact for
    every affine — not just the pure translation 0.13.1 handled.
    """
    w = local_bounds.get("width") or 1.0
    h = local_bounds.get("height") or 1.0
    u = (pt[0] - local_bounds.get("left", 0.0)) / w
    v = (pt[1] - local_bounds.get("top", 0.0)) / h
    tl = (quad[0], quad[1])
    tr = (quad[2], quad[3])
    br = (quad[4], quad[5])
    bl = (quad[6], quad[7])
    x = ((1 - u) * (1 - v) * tl[0] + u * (1 - v) * tr[0]
         + u * v * br[0] + (1 - u) * v * bl[0])
    y = ((1 - u) * (1 - v) * tl[1] + u * (1 - v) * tr[1]
         + u * v * br[1] + (1 - u) * v * bl[1])
    return x, y


def _quad_center_size(quad):
    """(cx, cy, w, h) of a border quad in top-level px — the same numbers
    cdp_see reports for the node, so receipt and drawing cannot drift apart."""
    tl = (quad[0], quad[1])
    tr = (quad[2], quad[3])
    br = (quad[4], quad[5])
    bl = (quad[6], quad[7])
    cx = (tl[0] + tr[0] + br[0] + bl[0]) / 4.0
    cy = (tl[1] + tr[1] + br[1] + bl[1]) / 4.0
    w = ((tr[0] - tl[0]) ** 2 + (tr[1] - tl[1]) ** 2) ** 0.5
    h = ((bl[0] - tl[0]) ** 2 + (bl[1] - tl[1]) ** 2) ** 0.5
    return cx, cy, w, h


def _dispatch_offset(ws, object_id, frame_id=None):
    """(dx, dy, frame_id, error) → top-level offset for a node's own frame.

    `frame_id` is the handle's own record (cdp_see writes it for merged child
    frames); DOM.describeNode is the fallback, and it does NOT report frameId for
    element nodes (measured 2026-10-22) — which is why the handle map carries it.

    Main-frame node: (0, 0, None, None) — unchanged behaviour. Child frame whose
    box cannot be located: error set, because dispatching a frame-local number at
    top level is a silent miss (that was 0.13.0).

    0.13.2 keeps this as the *diagnostic* origin (it names where the frame sits),
    not as the dispatch translation — that now comes from the element's own quad,
    because a translation cannot express a scale.
    """
    fid = frame_id or _node_frame_id(ws, object_id)
    main = _main_frame_id(ws)
    if not fid or not main or fid == main:
        return 0.0, 0.0, fid, None
    origin = _frame_content_origin(ws, fid)
    if origin is None:
        return 0.0, 0.0, fid, ('element lives in child frame '
                               f'{fid[:8]} but its position could not be read — '
                               'refusing to dispatch a frame-local point')
    return origin[0], origin[1], fid, None


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
        # 0.13.1/0.13.2: inside a merged child frame every number read above is
        # FRAME-local (getBoundingClientRect and the elementFromPoint probe both
        # run in the frame's own context), while Input.dispatchMouseEvent wants
        # top-level viewport px. 0.13.0 skipped the translation (dispatched the
        # frame-local number, receipt still said landed=true); 0.13.1 translated
        # by the frame origin, which is right only for an untransformed owner.
        # 0.13.2 takes the dispatch point from the element's own border quad —
        # the same read cdp_see draws with — so translation, scale and rotation
        # all come from one source and receipt/drawing cannot drift apart.
        dx, dy, frame_id, frame_err = _dispatch_offset(ws, oid,
                                                       entry.get("frame_id"))
        main_id = _main_frame_id(ws)
        is_child = bool(frame_id) and bool(main_id) and frame_id != main_id
        if is_child and frame_err:
            return _handle_fail(
                f'handle [{entry["idx"]}] {frame_err}',
                entry=entry, handle=str(handle), nav=nav_ev,
                frame_id=frame_id)
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
        # 0.13.1/0.13.2: click_pt is frame-local here (probe or centre, both in
        # the node's own frame). Keep it — it is the auditable local answer — and
        # dispatch its top-level image. For a main-frame node the two spaces are
        # the same (an element's own transform is already inside
        # getBoundingClientRect); for a frame node the mapping comes from the
        # element's border quad, not from adding the frame origin.
        click_local = [float(click_pt[0]), float(click_pt[1])]
        rect_local = {"x": rect["x"], "y": rect["y"],
                      "w": rect["w"], "h": rect["h"]}
        local_bounds = {"left": round(rect_local["x"] - rect_local["w"] / 2.0, 3),
                        "top": round(rect_local["y"] - rect_local["h"] / 2.0, 3),
                        "width": rect_local["w"], "height": rect_local["h"]}
        mapping = "same space (main frame)"
        if is_child:
            quad = _element_border_quad(ws, entry["backend_node_id"])
            if quad is None:
                return _handle_fail(
                    f'handle [{entry["idx"]}] element lives in child frame '
                    f'{frame_id[:8]} but its border box could not be read — '
                    f'refusing to dispatch a frame-local point',
                    entry=entry, handle=str(handle), nav=nav_ev,
                    frame_id=frame_id)
            click_pt = list(_map_local_to_top(quad, local_bounds, click_local))
            qcx, qcy, qw, qh = _quad_center_size(quad)
            rect = {"x": qcx, "y": qcy, "w": qw, "h": qh}
            mapping = "element border quad (bilinear, top-level)"
        else:
            click_pt = [click_local[0], click_local[1]]
            rect = dict(rect_local)
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
        # 0.11.0: a probe that landed on the element is `landed=True`; the
        # legacy centre fallback is `landed=None` — "could not tell", never
        # claimed as true.
        landed_probe = True if click_how in ('center', 'grid_scan',
                                             'redirect_target_clickable_point') else None
        # 0.13.6: the probe above is a *pre-dispatch promise* ("this point
        # belongs to the target"). It never said who received the event. Read
        # the receiver back and judge `landed` on that, so "clicked the wrong
        # element" and "clicked right, nothing happened" stop sharing a receipt.
        # The point is frame-local — the same space the caller dispatched from
        # and the space `objectId` lives in — so no re-mapping here.
        hit = _hit_relation(ws, oid, click_local[0], click_local[1], msg_id=78)
        if hit is not None:
            landed = hit.get('relation') in ('self', 'descendant')
            landed_source = 'post-dispatch elementFromPoint vs target node'
        else:
            # Node detached (navigation) or context gone: the read cannot
            # answer, but the probe's promise is still real knowledge. Keep it
            # and name where it came from rather than degrading to None.
            landed = landed_probe
            landed_source = 'pre-dispatch probe only (post-dispatch read failed)'
        evidence = {
            "element": _handle_label(entry),
            "role": entry.get("role"),
            "name": entry.get("name"),
            "handle": f'[{entry["idx"]}]',
            "backend_node_id": entry["backend_node_id"],
            # 0.11.0 (PRD F3): `box.x/y` are the CENTRE, not the top-left —
            # the field name lied through 0.10.x. `bounds` carries the real
            # rect and `center` the point; `box` stays for one more version.
            "box": {"x": round(rect["x"], 1), "y": round(rect["y"], 1),
                    "w": round(rect["w"], 1), "h": round(rect["h"], 1)},
            "box_deprecated": "x/y are the centre; use bounds or center",
            "center": {"x": round(rect["x"], 1), "y": round(rect["y"], 1)},
            "bounds": {"left": round(rect["x"] - rect["w"] / 2.0, 1),
                       "top": round(rect["y"] - rect["h"] / 2.0, 1),
                       "right": round(rect["x"] + rect["w"] / 2.0, 1),
                       "bottom": round(rect["y"] + rect["h"] / 2.0, 1),
                       "width": round(rect["w"], 1),
                       "height": round(rect["h"], 1)},
            "space": "physical", "dpr": dpr, "dispatched": dispatched,
            "viewport": {"w": vw, "h": vh},
            "in_viewport": in_viewport,
            "click_point": {"how": click_how,
                            "x": round(click_pt[0], 1), "y": round(click_pt[1], 1)},
            "read_back": "getBoundingClientRect via DOM.resolveNode",
            "source": "cdp_see(kind=a11y) handle map",
            "element_at_point": hit,
            "hit_relation": (hit or {}).get("relation"),
            "landed_source": landed_source,
            "verified": True,
        }
        if is_child:
            # 0.13.1/0.13.2: which space each number lives in, stated rather than
            # implied — and how the local point became a dispatch point.
            evidence["frame"] = {
                "frame_id": frame_id,
                "origin": None if frame_err else {"x": round(dx, 2), "y": round(dy, 2)},
                "local_space": "frame viewport (getBoundingClientRect / probe)",
                "dispatch_space": "top-level viewport",
                "mapping": mapping,
                "local": {"center": {"x": round(click_local[0], 1),
                                     "y": round(click_local[1], 1)},
                          "bounds": {"left": round(local_bounds["left"], 1),
                                     "top": round(local_bounds["top"], 1),
                                     "width": round(local_bounds["width"], 1),
                                     "height": round(local_bounds["height"], 1)}},
            }
        evidence['three_state'] = _three_state(True, landed, 'no_readback')
        if redirect_ev:
            evidence.update(redirect_ev)
        evidence.update(nav_ev)
        return {"method": "cdp_click", "handle": f'[{entry["idx"]}]',
                "page_index": idx, "result": "ok", "tiers": "handle",
                "verified": True,
                "resolved": True, "landed": landed, "effected": "unknown",
                "evidence": evidence}
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
        focus = _type_target_attrs(ws, selector=None, msg_id=34)
        tag = (focus.get("tag") or "").upper()
        if tag in ("", "BODY", "HTML"):
            out = _handle_fail(
                f'focus did not land on handle [{entry["idx"]}] '
                f'(activeElement is {tag or "missing"}) — call cdp_see again',
                entry=entry, handle=str(handle), method="cdp_type", nav=nav_ev)
            out["text"] = text
            return out
        block = _preflight_type_block(
            tag,
            input_type=focus.get("type"),
            is_content_editable=bool(focus.get("isContentEditable")),
            readonly=bool(focus.get("readonly")),
            disabled=bool(focus.get("disabled")),
        )
        if block:
            out = _handle_fail(
                block, entry=entry, handle=str(handle),
                method="cdp_type", nav=nav_ev)
            out["text"] = text
            out["evidence"]["tag"] = tag
            if entry.get("role"):
                out["evidence"]["role"] = entry.get("role")
            if entry.get("name"):
                out["evidence"]["name"] = entry.get("name")
            return out
        # 0.9.4-P3: the focused element's own tag decides what "\n" means.
        enter_mode = _type_enter_mode(tag, entry.get("role"))
        used_enter, rb, fail = _type_with_readback(
            ws, text, enter_mode, expect_focus=focus, msg_id=35)
        _write_last(idx)
        if fail:
            out = _handle_fail(
                fail, entry=entry, handle=str(handle),
                method="cdp_type", nav=nav_ev)
            out["text"] = text
            out["evidence"]["read_back"] = _rb_evidence(rb)
            return out
        evidence = {
            "element": _handle_label(entry),
            "role": entry.get("role"), "name": entry.get("name"),
            "handle": f'[{entry["idx"]}]',
            "backend_node_id": entry["backend_node_id"],
            "focus": _focus_label(focus),
            "method_detail": "DOM.resolveNode → focus() → Input.insertText",
            "enter_mode": used_enter,
            "read_back": _rb_evidence(rb),
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
        # 0.13.7 — a click must reach the page's handler exactly once.
        #
        # Before this, the selector branch fired the handler up to THREE times:
        # real mouse (trusted), `el.click()` (untrusted), then `el.onclick()`
        # from _js_submit — a direct handler call that dispatches **no click
        # event at all**. Measured on a page with an inline onclick:
        #   window.n = 3   but   document-level click listeners saw 2
        # So a page's own analytics/listeners cannot even see the third one;
        # an "add to cart" ran three times while reporting one verified click.
        #
        # The escalations were meant as fallbacks for a click that lands but is
        # ignored. They ran unconditionally after a click that had already
        # succeeded — pre-emptive redundancy, not fallback. Now: dispatch the
        # real click, *ask the page* whether it landed, and escalate at most
        # once, only on evidence of nothing landing.
        probe = _install_click_probe(ws, selector, msg_id=5)
        _click_at(ws, x, y, dpr)
        seen = _read_click_probe(ws, msg_id=6)
        escalation = _click_escalation(seen['trusted'], seen['untrusted'])
        if escalation == 'js_click':
            _js_click(ws, selector, msg_id=10)
            seen = _read_click_probe(ws, msg_id=11)
            if seen['trusted'] == 0 and seen['untrusted'] == 0 and seen['has_form']:
                escalation = 'request_submit'
                _js_request_submit(ws, selector, msg_id=12)
        _clear_click_probe(ws, msg_id=13)
        tag = (info.get('tag') or '').upper()
        if tag not in ('INPUT', 'TEXTAREA'):
            # Kept for pages that submit on Enter, but never as a click
            # substitute: it dispatches keydown/keyup, not a click.
            _js_focus_enter(ws, selector, msg_id=15)

        _write_last(idx)
        ev = _element_evidence(info)
        ev['verified'] = True
        ev['selector'] = selector
        ev['read_back'] = 'document.querySelector hit + getBoundingClientRect'
        ev['dispatch'] = {
            'trusted_clicks': seen['trusted'],
            'untrusted_clicks': seen['untrusted'],
            'probe': 'capture-phase listener installed before dispatch, removed after',
            'escalation': escalation,
            'dispatches': 1 + (1 if escalation != 'none' else 0),
        }
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
        attrs = _type_target_attrs(ws, selector, msg_id=18)
        tag = (attrs.get('tag') or info.get('tag') or '').upper()
        block = _preflight_type_block(
            tag,
            input_type=attrs.get('type'),
            is_content_editable=bool(attrs.get('isContentEditable')),
            readonly=bool(attrs.get('readonly')),
            disabled=bool(attrs.get('disabled')),
        )
        if block:
            out = _receipt_fail('cdp_type', block, selector=selector, text=text)
            out['evidence']['tag'] = tag
            if attrs.get('name'):
                out['evidence']['name'] = attrs['name']
            return out
        x, y = info['x'], info['y']
        _click_at(ws, x, y, _get_dpr(ws))
        # 0.9.4-P3: the target's tag decides what "\n" means.
        enter_mode = _type_enter_mode(tag)
        used_enter, rb, fail = _type_with_readback(
            ws, text, enter_mode, selector=selector, msg_id=20)
        _write_last(idx)
        if fail:
            out = _receipt_fail('cdp_type', fail, selector=selector, text=text)
            out['evidence']['read_back'] = _rb_evidence(rb)
            return out
        ev = _element_evidence(info)
        ev['verified'] = True
        ev['selector'] = selector
        ev['read_back'] = _rb_evidence(rb)
        ev['enter_mode'] = used_enter
        return {'method': 'cdp_type', 'page_index': idx, 'selector': selector,
                'text': text, 'result': 'ok',
                'verified': True, 'evidence': ev}
    finally:
        ws.close()

def _js_request_submit(ws, selector, msg_id):
    """Submit the owning form the way the browser does it (fires `submit`)."""
    expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
            'if(!el||!el.form)return JSON.stringify({error:"no form"});'
            'if(el.form.requestSubmit)el.form.requestSubmit();else el.form.submit();'
            'return JSON.stringify({result:"request_submit ok"});'
            '})()')
    cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)


def _install_click_probe(ws, selector, msg_id):
    """Install a capture-phase click listener *before* dispatching the mouse.

    The instrument has to be in place before the event, or it records the
    absence of something that already happened (the same mistake as listening
    for a keydown after the key was pressed — `[]` is then the only possible
    output and means nothing).
    """
    expr = ('(function(){var el=document.querySelector(' + json.dumps(selector) + ');'
            'if(!el)return JSON.stringify({error:"element not found"});'
            'window.__handProbe={el:el,trusted:0,untrusted:0,has_form:!!el.form};'
            'window.__handProbeH=function(e){var p=window.__handProbe;'
            'if(!p||!p.el)return;'
            'if(e.target===p.el||(p.el.contains&&p.el.contains(e.target))){'
            'if(e.isTrusted)p.trusted++;else p.untrusted++;}};'
            'document.addEventListener("click",window.__handProbeH,true);'
            'return JSON.stringify({result:"probe installed"});'
            '})()')
    cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)


def _read_click_probe(ws, msg_id):
    """Count what actually reached the element (trusted real-mouse vs JS click)."""
    expr = ('(function(){var p=window.__handProbe||{};'
            'return JSON.stringify({trusted:p.trusted||0,untrusted:p.untrusted||0,'
            'has_form:!!p.has_form});})()')
    raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)
    try:
        val = raw['result'].get('value') or '{}'
        data = json.loads(val)
    except Exception:
        data = {}
    return {'trusted': int(data.get('trusted') or 0),
            'untrusted': int(data.get('untrusted') or 0),
            'has_form': bool(data.get('has_form'))}


def _clear_click_probe(ws, msg_id):
    expr = ('(function(){try{document.removeEventListener("click",window.__handProbeH,true);}'
            'catch(e){}delete window.__handProbeH;delete window.__handProbe;'
            'return JSON.stringify({result:"probe removed"});})()')
    cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, msg_id=msg_id)


def _click_escalation(trusted, untrusted):
    """Escalate only on evidence that the real mouse click did not land.

    A trusted click landing on the element means the page's own handler ran —
    doing anything else on top of it is a second execution of the same user
    intent, which is exactly the bug this replaces.
    """
    if trusted > 0:
        return 'none'
    if untrusted > 0:
        return 'none'          # a JS click already landed; don't stack another
    return 'js_click'


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
      Optional `@dpr=<n>` declares the ratio the numbers were computed under:
      if the page reports a different one at dispatch time, the click is
      refused instead of silently landing somewhere else.
      'xy:412,188@dpr=2@expect=#save' accepts both suffixes.
    """
    sel = action
    if looks_like_handle(action):
        # cdp_see(kind=a11y) handle: '[93]' / 'idx:93'
        return cdp_click_handle(action)
    if action.startswith('text='):
        text_val = action[5:]
        if not text_val.strip():
            # 0.13.7: an empty query contains every label, so the first match is
            # whatever sits first in the document. Real page found this the day
            # it was first used (a variable that resolved to an empty string).
            return _receipt_fail('cdp_click',
                                 'empty text= query — refusing to match the whole page',
                                 action=action)
        pages = list_pages()
        idx, page = resolve_page(None, pages)
        ws = cdp_connect(page['webSocketDebuggerUrl'])
        try:
            _init_domains(ws, 'Runtime')
            q = json.dumps(text_val)  # produces "Learn more" — double-quoted
            # 0.9.4-P2 (spec docs/spec-0.9.4-p2-textmatch.md): `text()` matches
            # only *direct* text children, so an `<a><span>Title</span></a>` —
            # GitHub issues, most modern sites — never matched, while `.` is the
            # node's full string value (all descendant text). The third branch
            # keeps the exact ("whole text") semantic as a fallback. Matching
            # stays case-sensitive.
            #
            # 0.13.7: normalize-space() folds only ASCII whitespace. A label
            # whose text carries U+00A0 ("52\u00a0comments") therefore never
            # matched the query "52 comments", and the receipt said
            # "text element not found" — which reads as "no such label" while
            # the truth was a byte difference inside one word. The scan now
            # folds Unicode spaces on both sides and reports, per candidate,
            # whether it matched raw bytes or only after folding, so a byte
            # mismatch is named as a byte mismatch.
            expr = (
                "(function(){"
                "var qRaw=" + q + ";"
                "function fold(s){return (''+(s==null?'':s))"
                ".replace(/[\\u00a0\\u1680\\u2000-\\u200a\\u202f\\u205f\\u3000\\ufeff]/g,' ')"
                ".replace(/\\s+/g,' ').trim();}"
                "var q=fold(qRaw);var qLower=q.toLowerCase();"
                "var hit=null,exact=false;"
                "var prim=document.querySelectorAll('a,button,[role=\"button\"],"
                "[role=\"link\"],input[type=\"submit\"],input[type=\"button\"]');"
                "for(var i=0;i<prim.length;i++){var n=prim[i];"
                "var t=(n.innerText!==undefined&&n.innerText!==null)?n.innerText:(n.value||'');"
                "if(fold(t).indexOf(q)>=0){hit={el:n,raw:t};break;}}"
                "if(!hit){var all=document.querySelectorAll('body *');"
                "for(var i=0;i<all.length;i++){var n=all[i];var t=n.innerText||'';"
                "if(fold(t)!==q)continue;var kids=n.children,same=false;"
                "for(var j=0;j<kids.length;j++){if(fold(kids[j].innerText||'')===q){same=true;break;}}"
                "if(!same){hit={el:n,raw:t};exact=true;break;}}}"
                "if(!hit){var out=[];"
                "var scan=document.querySelectorAll('a,button,[role=\"button\"],"
                "[role=\"link\"],label,summary');"
                "for(var i=0;i<scan.length&&out.length<5;i++){var n=scan[i];var t=n.innerText||'';"
                "if(!t)continue;var ft=fold(t);"
                "if(ft.toLowerCase().indexOf(qLower)>=0){"
                "out.push({tag:n.tagName,text:t.substring(0,80),"
                "raw_contains:(t.indexOf(qRaw)>=0),"
                "casefold_contains:(t.toLowerCase().indexOf((''+qRaw).toLowerCase())>=0),"
                "folded_contains:true,"
                "href:(n.getAttribute?n.getAttribute('href'):null)});}}"
                "var wsOnly=false,caseOnly=false;"
                "for(var i=0;i<out.length;i++){var c=out[i];"
                "if(!c.folded_contains||c.raw_contains)continue;"
                "if(c.casefold_contains)wsOnly=true;else caseOnly=true;}"
                "return JSON.stringify({error:'text element not found',search:qRaw,"
                "folded_search:q,search_folding_changed:(q!==(''+qRaw).trim()),"
                "whitespace_mismatch_only:wsOnly,case_mismatch_only:caseOnly,"
                "candidates:out});}"
                "var el=hit.el;"
                # 0.13.7: a label below the fold used to be reported as
                # "no clickable point (covered)" — elementFromPoint answers
                # null outside the viewport, which is not the same fact as
                # "something covers it". Bring the node into view first, the
                # way the handle path already does, then measure.
                "el.scrollIntoView({block:'center',inline:'center',behavior:'instant'});"
                "function hits(x,y){var e=document.elementFromPoint(x,y);"
                "return !!(e&&(e===el||el.contains(e)));}"
                "var r=el.getBoundingClientRect();var dpr=window.devicePixelRatio||1;"
                "if(r.width<=0||r.height<=0)"
                "return JSON.stringify({error:'no clickable point (zero-size)',search:qRaw});"
                "var rawText=''+hit.raw;"
                "var info={tag:el.tagName,text:rawText.substring(0,80),match:{"
                "mode:'unicode-space-folded contains',exact_branch:exact,"
                "folded_query:q,raw_query:qRaw,matched_raw_bytes:(rawText.indexOf(qRaw)>=0),"
                "folding_changed_query:(q!==(''+qRaw).trim())}};"
                "var cx=r.left+r.width/2,cy=r.top+r.height/2;"
                "if(hits(cx,cy)){info.x=cx*dpr;info.y=cy*dpr;info.how='center';"
                "return JSON.stringify(info);}"
                "for(var yi=1;yi<=15;yi++){for(var xi=1;xi<=5;xi++){"
                "var gx=r.left+r.width*xi/6;var gy=r.top+r.height*yi/16;"
                "if(hits(gx,gy)){info.x=gx*dpr;info.y=gy*dpr;info.how='grid_scan';"
                "return JSON.stringify(info);}}}"
                "return JSON.stringify({error:'no clickable point (covered)',search:qRaw,"
                "tag:el.tagName,text:rawText.substring(0,80)});"
                "})()")
            raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
            value_str = raw.get('result', {}).get('value', '{}')
            info = json.loads(value_str)
            if 'error' in info:
                # Failure receipt + one loose scan: the labels that came
                # closest, so "not found" is diagnosable instead of a guess.
                # The scan ignores case on purpose (a case miss is the most
                # common reason a label exists but the match did not hit).
                # 0.13.7: each candidate now says whether it matched raw bytes
                # or only after Unicode-space folding, and the receipt carries
                # `byte_mismatch_only` — the label existed; the bytes differed.
                cands = info.get('candidates') or []
                out = _receipt_fail('cdp_click',
                                    f"{info['error']}: {text_val!r}",
                                    action=action, text_match=text_val,
                                    candidates=cands)
                out['evidence']['candidates'] = cands
                out['evidence']['whitespace_mismatch_only'] = bool(
                    info.get('whitespace_mismatch_only'))
                out['evidence']['case_mismatch_only'] = bool(
                    info.get('case_mismatch_only'))
                out['evidence']['folded_search'] = info.get('folded_search')
                out['evidence']['match_mode'] = 'unicode-space-folded contains'
                return out

            x, y = info['x'], info['y']
            dpr = _get_dpr(ws)
            _click_at(ws, x, y, dpr)
            _write_last(idx)
            ev = _element_evidence({'tag': info.get('tag'),
                                    'text': info.get('text')})
            ev['verified'] = True
            ev['text_match'] = text_val
            ev['match'] = info.get('match')
            ev['click_point'] = {'how': info.get('how'),
                                 'x': round(x / dpr, 1), 'y': round(y / dpr, 1)}
            ev['read_back'] = ('Unicode-space-folded text hit + '
                               'elementFromPoint hit-chain verified')
            return {'method': 'cdp_click', 'text_match': text_val,
                    'tag': info.get('tag'), 'match': info.get('match'),
                    'page_index': idx, 'result': 'ok',
                    'verified': True, 'evidence': ev}
        finally:
            ws.close()
    if action.startswith('xy:') or action.startswith('xy@'):
        spec = action[3:].strip()
        spec, declared_dpr = _split_dpr_decl(spec)
        frame_ref = None
        expect_spec = None
        # 0.11.0 (S4) documented 'xy@img:<sha8>:X,Y' but only 'xy:' was ever
        # accepted: a string starting 'xy@' fell through to CSS-selector
        # handling and failed as "element not found". 0.13.7 accepts it.
        if action.startswith('xy@'):
            lead, _, coords = spec.rpartition(':')
            if coords and ',' in coords:
                frame_ref = lead.strip() or None
                spec = coords
        # 0.13.7: the caller may declare what it expects under the point.
        # Without a declared target a bare coordinate has nothing to compare
        # against — which is why 0.13.6 could only report who sits there.
        # `@expect` takes the rest of the string: a CSS selector may contain
        # spaces (descendant combinators), and a real page found that hole the
        # first time it was used.
        m = re.search(r'@expect=(.+)$', spec)
        if m:
            expect_spec = m.group(1).strip()
            spec = spec[:m.start()].strip()
        if '@' in spec:                        # legacy in-spec frame naming
            frame_ref, spec = spec.split('@', 1)
            frame_ref = frame_ref.strip() or None
        try:
            parts = spec.strip().split(',')
            x, y = int(round(float(parts[0].strip()))), int(round(float(parts[1].strip())))
        except (ValueError, IndexError):
            return _receipt_fail('cdp_click',
                                 'invalid xy format, expected "xy:X,Y" '
                                 '[@expect=<handle|selector>] [@dpr=<n>]', action=action)
        pages = list_pages()
        idx, page = resolve_page(None, pages)
        ws = cdp_connect(page['webSocketDebuggerUrl'])
        try:
            _init_domains(ws, 'Runtime')
            dpr = _get_dpr(ws)
            decl_err = _dpr_decl_error(declared_dpr, dpr)
            if decl_err:
                return _receipt_fail('cdp_click', decl_err, action=action,
                                     xy=[x, y], dpr_declared=declared_dpr,
                                     dpr_runtime=dpr)
            frame = _frame_at(ws, msg_id=41)
            vp, vp_known = _viewport_size(ws, msg_id=42)
            in_viewport = None
            if vp_known:
                in_viewport = (0 <= x / dpr < vp['w']) and (0 <= y / dpr < vp['h'])
                if not in_viewport:
                    # 0.13.7 pre-check: outside the viewport a mouse event has
                    # no target and is dropped without a trace. Refuse, and
                    # name the viewport that made it impossible.
                    return _receipt_fail(
                        'cdp_click',
                        'point (%d,%d) is outside viewport (%dx%d) — refused '
                        'before dispatch' % (x, y, vp['w'], vp['h']),
                        action=action, xy=[x, y])
            # Resolve the declared target BEFORE dispatching: a stale handle is
            # its own fault, not a miss to be discovered after the fact.
            expect_oid = None
            expect_selector = None
            expect_label = None
            if expect_spec:
                if looks_like_handle(expect_spec):
                    entry = resolve_handle(expect_spec)
                    if 'error' in entry:
                        return _receipt_fail('cdp_click',
                                             'xy @expect target: %s' % entry['error'],
                                             action=action, expect=expect_spec)
                    expect_oid = _handle_object_id(ws, entry.get('backend_node_id'))
                    if not expect_oid:
                        return _receipt_fail(
                            'cdp_click',
                            'xy @expect handle %s element is gone — call cdp_see again'
                            % expect_spec, action=action, expect=expect_spec)
                    expect_label = _handle_label(entry)
                else:
                    prox = _element_info(ws, expect_spec)
                    if not prox or prox.get('error'):
                        return _receipt_fail(
                            'cdp_click',
                            'xy @expect selector %r not found: %s'
                            % (expect_spec, (prox or {}).get('error', 'no element')),
                            action=action, expect=expect_spec)
                    expect_selector = expect_spec
                    expect_label = '%s %r' % (prox.get('tag'),
                                              (prox.get('text') or '')[:40])
            before_doc = _doc_identity(ws, msg_id=44)
            at_point_before = _element_at(ws, x / dpr, y / dpr, msg_id=43)
            _click_at(ws, x, y, dpr)
            _write_last(idx)
            # 0.13.7: judge after the fact, in this order.
            #   1) did the document change? Then no hit/miss is readable — the
            #      same coordinate now means something else. (0.11.0 learned
            #      this about the *dispatch*; this is that lesson applied to
            #      the verdict.)
            #   2) declared target? landed = did the event reach it.
            #   3) no target declared? report who sits there now; invent nothing.
            after_doc = _doc_identity(ws, msg_id=45)
            navigated = None
            if before_doc.get('ok') and after_doc.get('ok'):
                navigated = (before_doc.get('href') != after_doc.get('href')
                             or before_doc.get('timeOrigin') != after_doc.get('timeOrigin'))
            hit = None
            at_point_after = None
            if navigated:
                landed = None
                landed_source = ('page navigated during dispatch (different '
                                 'document) — no hit/miss verdict')
            elif expect_spec:
                if expect_oid:
                    hit = _hit_relation(ws, expect_oid, x / dpr, y / dpr, msg_id=46)
                else:
                    hit = _hit_relation_selector(ws, expect_selector,
                                                 x / dpr, y / dpr, msg_id=46)
                relation = (hit or {}).get('relation')
                if relation in ('self', 'descendant'):
                    landed = True
                elif relation in ('ancestor', 'other', 'none'):
                    landed = False
                else:
                    landed = None
                landed_source = ('post-dispatch elementFromPoint vs declared '
                                 'target (@expect)')
            else:
                at_state, at_point_after = _element_at_checked(
                    ws, x / dpr, y / dpr, msg_id=46)
                if at_state == 'hit':
                    landed = True
                    landed_source = 'post-dispatch elementFromPoint at the point'
                elif at_state == 'none':
                    landed = None
                    landed_source = ('post-dispatch elementFromPoint returned no '
                                     'element — nothing there to judge')
                else:
                    landed = None
                    landed_source = ('post-dispatch read failed — no verdict '
                                     '(a bare coordinate declares no target)')
            state = _three_state(in_viewport is not False, landed, 'no_readback')
            ev = {'verified': False, 'space': 'physical',
                  'dispatched': [x, y], 'dpr': dpr,
                  'dpr_declared': declared_dpr,
                  'frame': frame, 'in_viewport': in_viewport,
                  'frame_ref': frame_ref,
                  'element_at_point': at_point_before,
                  'element_at_point_before': at_point_before,
                  'element_at_point_after': at_point_after,
                  'hit_relation': (hit or {}).get('relation'),
                  'expect': ({'spec': expect_spec, 'element': expect_label}
                             if expect_spec else None),
                  'navigated': navigated,
                  'document_before': before_doc if before_doc.get('ok') else None,
                  'document_after': after_doc if after_doc.get('ok') else None,
                  'landed_source': landed_source,
                  'read_back': 'document.elementFromPoint before and after dispatch',
                  'three_state': state,
                  'reason': 'coordinate click: dispatch-only unless @expect names '
                            'a target; no claim that the world changed'}
            if frame_ref:
                # Honest limit: this build records the frame on the receipt but
                # keeps no ledger of past frames, so it cannot re-check one.
                ev['frame_verified'] = False
                ev['frame_reason'] = ('no_frame_ledger: past frames are not '
                                      're-checkable in this build')
            return {'method': 'cdp_click', 'xy': [x, y], 'page_index': idx,
                    'result': 'ok', 'verified': False,
                    'element_at_point': at_point_before,
                    'element_at_point_after': at_point_after,
                    'hit_relation': (hit or {}).get('relation'),
                    'landed_source': landed_source,
                    'navigated': navigated,
                    'resolved': state['resolved'], 'landed': state['landed'],
                    'effected': state['effected'], 'evidence': ev}
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
        # does, the text vanishes. Verify the focus target first (PRD S3 / F22).
        focus = _type_target_attrs(ws)
        if focus.get('parse_error'):
            return _receipt_fail('cdp_type',
                                 f"focus verification failed: {focus['parse_error']}",
                                 text=text)
        tag = (focus.get('tag') or '').upper()
        if tag in ('', 'BODY', 'HTML'):
            return _receipt_fail(
                'cdp_type',
                f"no focused element (activeElement is {tag or 'missing'}) — "
                "click the field first (cdp_click '[idx]'), then cdp_type(text); "
                "or pass '[idx]|text' to cdp_click, which routes it to the type path",
                text=text)
        block = _preflight_type_block(
            tag,
            input_type=focus.get('type'),
            is_content_editable=bool(focus.get('isContentEditable')),
            readonly=bool(focus.get('readonly')),
            disabled=bool(focus.get('disabled')),
        )
        if block:
            out = _receipt_fail('cdp_type', block, text=text)
            out['evidence']['tag'] = tag
            if focus.get('name'):
                out['evidence']['name'] = focus['name']
            return out
        # Input domain needs no enable. 0.9.4-P3: the pre-flight already read
        # activeElement, so its tagName (already in `focus`) decides the "\n"
        # fork without a second round trip.
        enter_mode = _type_enter_mode(tag)
        used_enter, rb, fail = _type_with_readback(
            ws, text, enter_mode, expect_focus=focus, msg_id=20)
        _write_last(idx)
        if fail:
            out = _receipt_fail('cdp_type', fail, text=text)
            out['evidence']['read_back'] = _rb_evidence(rb)
            return out
        return {'method': 'cdp_type', 'page_index': idx, 'text': text,
                'result': 'ok', 'verified': True,
                'evidence': {'focus': _focus_label(focus), 'tag': tag,
                             'focus_id': focus.get('id') or '',
                             'focus_type': focus.get('type') or '',
                             'enter_mode': used_enter,
                             'read_back': _rb_evidence(rb),
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


# ── 0.11.0 action primitives: drag / key / three-state receipt ───────
# Spec: docs/prd-0.11-action-primitives.md
#
# Why these exist: in a pure-visual surface (Blender, Excalidraw, any canvas
# app) there is no a11y metadata to lean on — only pixels and coordinates.
# 0.10 could point; it could not drag or press a modifier. Two primitives are
# missing before "computer use" means anything outside a DOM.
#
# Every receipt here carries three CO-LATERAL facts instead of one `verified`:
#   resolved — we found a target (selector hit / handle live / coord in viewport)
#   landed   — the event reached that target (elementFromPoint at the point)
#   effected — the world changed; 0.11 always reports `unknown` + a reason,
#              because no read-back exists for it yet. Never faked.

_ELEMENT_AT_FN = (
    "(function(x,y){var e=document.elementFromPoint(x,y);"
    "if(!e)return 'null';"
    "return JSON.stringify({tag:e.tagName,id:e.id||'',"
    "name:(e.getAttribute&&(e.getAttribute('aria-label')||e.getAttribute('name')))||'',"
    "text:(e.innerText||e.value||'').slice(0,40)});})"
)

_FRAME_FN = (
    "(function(){return JSON.stringify({"
    "scrollX:Math.round(window.scrollX||0),"
    "scrollY:Math.round(window.scrollY||0),"
    "innerW:window.innerWidth,innerH:window.innerHeight,"
    "dpr:window.devicePixelRatio||1});})()"
)

_MODIFIER_BITS = {'alt': 1, 'ctrl': 2, 'control': 2, 'meta': 4, 'cmd': 4,
                  'command': 4, 'shift': 8}
_MODIFIER_KEYS = {
    1: ('Alt', 'AltLeft', 18),
    2: ('Control', 'ControlLeft', 17),
    4: ('Meta', 'MetaLeft', 91),
    8: ('Shift', 'ShiftLeft', 16),
}
_NAMED_KEYS = {
    'enter': ('Enter', 'Enter', 13),
    'tab': ('Tab', 'Tab', 9),
    'escape': ('Escape', 'Escape', 27),
    'esc': ('Escape', 'Escape', 27),
    'backspace': ('Backspace', 'Backspace', 8),
    'delete': ('Delete', 'Delete', 46),
    'space': (' ', 'Space', 32),
    'arrowleft': ('ArrowLeft', 'ArrowLeft', 37),
    'arrowup': ('ArrowUp', 'ArrowUp', 38),
    'arrowright': ('ArrowRight', 'ArrowRight', 39),
    'arrowdown': ('ArrowDown', 'ArrowDown', 40),
    'home': ('Home', 'Home', 36),
    'end': ('End', 'End', 35),
    'pageup': ('PageUp', 'PageUp', 33),
    'pagedown': ('PageDown', 'PageDown', 34),
}


def _three_state(resolved, landed, effected_reason='no_readback'):
    """The receipt's three faces. `landed=None` means "could not tell"."""
    state = {'resolved': bool(resolved),
             'landed': landed,
             'effected': 'unknown'}
    if effected_reason:
        state['effected_reason'] = effected_reason
    return state


def _frame_at(ws, msg_id=70):
    """The frame anchor: what the page looked like when we acted.

    0.10 receipts carried `img:<sha8>` but not the scroll position, so a
    coordinate measured on one frame could be dispatched onto another with no
    trace (observed: 2026-10-20, Excalidraw — scrollIntoView moved the page
    between shot and click; the click reported ok and hit nothing).
    """
    try:
        raw = cdp_call(ws, 'Runtime.evaluate',
                       {'expression': _FRAME_FN, 'returnByValue': True},
                       msg_id=msg_id, timeout=5)
        value = ((raw or {}).get('result') or {}).get('value')
        data = json.loads(value) if isinstance(value, str) else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {'known': False}
    return {'known': True,
            'scrollX': data.get('scrollX'), 'scrollY': data.get('scrollY'),
            'viewport': {'w': data.get('innerW'), 'h': data.get('innerH')},
            'dpr': data.get('dpr')}


def frame_anchor(page_sel=None):
    """Public frame anchor for the current page (screenshot receipts use it)."""
    try:
        pages = list_pages()
        idx, page = resolve_page(page_sel, pages)
        ws = cdp_connect(page["webSocketDebuggerUrl"])
    except Exception:
        return {'known': False}
    try:
        _init_domains(ws, "Runtime")
        return _frame_at(ws, msg_id=45)
    except Exception:
        return {'known': False}
    finally:
        ws.close()


def _element_at_checked(ws, x_css, y_css, msg_id=71):
    """Three answers instead of one: ('hit', info) / ('none', None) / ('unknown', None).

    `_element_at` collapses "nothing is there" and "could not read" into None.
    After a dispatch those are different facts: no element at an in-viewport
    point is a reading; a JS error or a dead context is not.
    """
    expr = '%s(%r,%r)' % (_ELEMENT_AT_FN, float(x_css), float(y_css))
    try:
        raw = cdp_call(ws, 'Runtime.evaluate',
                       {'expression': expr, 'returnByValue': True},
                       msg_id=msg_id, timeout=5)
        value = ((raw or {}).get('result') or {}).get('value')
    except Exception:
        return 'unknown', None
    if not isinstance(value, str):
        return 'unknown', None
    if value == 'null':
        return 'none', None
    try:
        data = json.loads(value)
    except Exception:
        return 'unknown', None
    return ('hit', data) if isinstance(data, dict) else ('unknown', None)


def _element_at(ws, x_css, y_css, msg_id=71):
    """Who is under this CSS point right now, or None when unanswerable."""
    state, data = _element_at_checked(ws, x_css, y_css, msg_id=msg_id)
    return data if state == 'hit' else None


def _doc_identity(ws, msg_id=44):
    """Which document are we in? href + timeOrigin, or {'ok': False}.

    A verdict read after a navigation is read in a *different* document, where
    the same coordinate means something else. Unreadable is `ok: False` —
    never silently "the same document".
    """
    expr = ("(function(){var l=location||{};return JSON.stringify({"
            "href:''+(l.href||''),"
            "timeOrigin:(performance&&performance.timeOrigin)||null});})()")
    try:
        raw = cdp_call(ws, 'Runtime.evaluate',
                       {'expression': expr, 'returnByValue': True},
                       msg_id=msg_id, timeout=5)
        value = ((raw or {}).get('result') or {}).get('value')
        data = json.loads(value) if isinstance(value, str) else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {'ok': False}
    data['ok'] = True
    return data


def _element_matches(claim, at):
    """Does `claim` (e.g. 'button "TARGET"') describe the element `at`?

    None when one side is missing — "could not tell", never "matched".
    """
    if not claim or not isinstance(at, dict):
        return None
    text_claim = str(claim).lower()
    tag = str(at.get('tag') or '').lower()
    if tag and tag not in text_claim:
        return False
    for field in ('text', 'name'):
        val = str(at.get(field) or '').strip().lower()
        if val and val in text_claim:
            return True
    return None if not (at.get('text') or at.get('name')) else False


_HIT_REL_FN = (
    "function(x,y){var e=document.elementFromPoint(x,y);"
    "if(!e)return JSON.stringify({relation:'none'});"
    "var r=(e===this)?'self':(this.contains(e)?'descendant':"
    "(e.contains(this)?'ancestor':'other'));"
    "return JSON.stringify({relation:r,tag:e.tagName,id:e.id||'',"
    "text:((e.innerText||e.value||'')+'').slice(0,60)});}"
)


def _hit_relation(ws, object_id, x_css, y_css, msg_id=78):
    """Who actually received the event at this point, relative to `object_id`.

    Runs in the *node's own* execution context, so a frame-local point is the
    right input for a frame node (the caller passes the frame-local point it
    dispatched from). `relation` is one of:
      self / descendant  — the event reached the claimed element (or inside it)
      ancestor           — it landed on a container: the control was missed
      other              — it landed on an unrelated element
      none               — no element at that point
    None means "could not tell" (context died, node detached after a
    navigation, CDP error) — never a silent `other`.
    """
    try:
        raw = cdp_call(ws, "Runtime.callFunctionOn",
                       {"objectId": object_id,
                        "functionDeclaration": _HIT_REL_FN,
                        "arguments": [{"value": float(x_css)},
                                      {"value": float(y_css)}],
                        "returnByValue": True}, msg_id=msg_id, timeout=5)
        value = ((raw or {}).get("result") or {}).get("value")
    except Exception:
        return None
    try:
        data = json.loads(value) if isinstance(value, str) else None
    except Exception:
        return None
    return data if isinstance(data, dict) else None


_HIT_REL_SEL_FN = (
    "function(x,y,sel){var t=document.querySelector(sel);"
    "if(!t)return JSON.stringify({relation:'missing'});"
    "var e=document.elementFromPoint(x,y);"
    "if(!e)return JSON.stringify({relation:'none'});"
    "var r=(e===t)?'self':(t.contains(e)?'descendant':"
    "(e.contains(t)?'ancestor':'other'));"
    "return JSON.stringify({relation:r,tag:e.tagName,id:e.id||'',"
    "text:((e.innerText||e.value||'')+'').slice(0,60)});}"
)


def _hit_relation_selector(ws, selector, x_css, y_css, msg_id=79):
    """`_hit_relation` for a declared CSS selector instead of a live objectId.

    Same relation vocabulary. `missing` means the declared target no longer
    exists (re-render) — the caller decides what that is worth; it is never
    silently folded into `other`. Main document only: a selector has no frame
    identity here, so a target inside a child frame will read `missing`.
    """
    try:
        raw = cdp_call(ws, "Runtime.evaluate",
                       {"expression": "(%s)(%r,%r,%r)"
                        % (_HIT_REL_SEL_FN, float(x_css), float(y_css), selector),
                        "returnByValue": True}, msg_id=msg_id, timeout=5)
        value = ((raw or {}).get("result") or {}).get("value")
    except Exception:
        return None
    try:
        data = json.loads(value) if isinstance(value, str) else None
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _point_from_spec(ws, spec, msg_id=72):
    """(point, error). point = {x, y (CSS px), how, input, dpr[, element]}.

    `spec` accepts 'xy:X,Y' (PHYSICAL px — the module's coordinate contract),
    an `[idx]` handle from cdp_see(kind=a11y), or a CSS selector.
    """
    s = str(spec or '').strip()
    if not s:
        return None, 'empty spec'
    dpr = _dpr_now(ws)
    if s.lower().startswith('xy:'):
        # the declaration only exists for coordinates; a CSS selector that
        # happens to end in '@dpr=2' is left untouched
        s, declared_dpr = _split_dpr_decl(s)
        decl_err = _dpr_decl_error(declared_dpr, dpr)
        if decl_err:
            return None, decl_err
        try:
            parts = s[3:].split(',')
            px, py = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            return None, 'invalid xy spec %r, expected "xy:X,Y"' % s
        return {'x': px / dpr, 'y': py / dpr, 'how': 'xy',
                'input': s, 'dpr': dpr, 'dpr_declared': declared_dpr}, None
    if looks_like_handle(s):
        entry = resolve_handle(s)
        if 'error' in entry:
            return None, entry['error']
        oid = _handle_object_id(ws, entry.get('backend_node_id'))
        if not oid:
            return None, 'handle %s element is gone — call cdp_see again' % s
        pt, how = _clickable_point(ws, oid, msg_id=msg_id)
        if pt is None:
            return None, 'handle %s has no clickable point (%s)' % (s, how)
        return {'x': pt[0], 'y': pt[1], 'how': how, 'input': s, 'dpr': dpr,
                'element': _handle_label(entry)}, None
    info = _element_info(ws, s)
    if not info or info.get('error'):
        return None, 'selector %r not found: %s' % (
            s, (info or {}).get('error', 'no element'))
    try:
        return {'x': float(info['x']) / dpr, 'y': float(info['y']) / dpr,
                'how': info.get('how') or 'selector', 'input': s,
                'dpr': dpr}, None
    except (KeyError, TypeError, ValueError):
        return None, 'selector %r returned no usable point' % s


def cdp_drag(from_spec, to_spec, steps=10, interval_ms=16, page_sel=None):
    """Drag from one point to another: mousePressed → N×mouseMoved → released.

    This is the primitive that makes canvas apps reachable at all. Excalidraw
    (2026-10-20): selecting the rectangle tool then clicking the canvas
    creates nothing — a drag creates the shape. Same for Blender's orbit /
    vertex pulls / slider drags.

    from_spec/to_spec take 'xy:X,Y' (physical px), an `[idx]` handle, or a CSS
    selector. The receipt reports resolved/landed/effected separately;
    `effected` is always 'unknown' because a drag has no read-back — verify
    the outcome by comparing two frames, not by trusting this receipt.
    """
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        src, err = _point_from_spec(ws, from_spec, msg_id=60)
        if err:
            out = _receipt_fail('cdp_drag', 'drag source: ' + err,
                                from_spec=from_spec, to_spec=to_spec)
            out['evidence'].update(_three_state(False, None, 'source_unresolved'))
            out['resolved'], out['landed'] = False, None
            out['effected'] = 'unknown'
            return out
        dst, err = _point_from_spec(ws, to_spec, msg_id=62)
        if err:
            out = _receipt_fail('cdp_drag', 'drag target: ' + err,
                                from_spec=from_spec, to_spec=to_spec)
            out['evidence'].update(_three_state(False, None, 'target_unresolved'))
            out['resolved'], out['landed'] = False, None
            out['effected'] = 'unknown'
            return out

        frame_before = _frame_at(ws)
        at_start = _element_at(ws, src['x'], src['y'], msg_id=64)
        # `landed` answers "did the press reach the element I claimed?" — a
        # bare `xy:` source claims no element, so the honest answer is None.
        # What IS known (who sits under the point) rides in element_at_start.
        landed = _element_matches(src.get('element'), at_start)

        n_steps = max(1, int(steps))
        try:
            gap = max(0.0, float(interval_ms)) / 1000.0
        except (TypeError, ValueError):
            gap = 0.0
        t0 = time.time()
        cdp_call(ws, 'Input.dispatchMouseEvent',
                 {'type': 'mousePressed', 'x': src['x'], 'y': src['y'],
                  'button': 'left', 'clickCount': 1}, msg_id=66)
        dispatched = 1
        for i in range(1, n_steps + 1):
            x = src['x'] + (dst['x'] - src['x']) * i / n_steps
            y = src['y'] + (dst['y'] - src['y']) * i / n_steps
            cdp_call(ws, 'Input.dispatchMouseEvent',
                     {'type': 'mouseMoved', 'x': x, 'y': y,
                      'button': 'left', 'buttons': 1}, msg_id=67)
            dispatched += 1
            if gap:
                time.sleep(gap)
        cdp_call(ws, 'Input.dispatchMouseEvent',
                 {'type': 'mouseReleased', 'x': dst['x'], 'y': dst['y'],
                  'button': 'left', 'clickCount': 1}, msg_id=68)
        dispatched += 1
        elapsed_ms = round((time.time() - t0) * 1000, 1)

        _write_last(idx)
        at_end = _element_at(ws, dst['x'], dst['y'], msg_id=69)
        frame_after = _frame_at(ws)
        state = _three_state(True, landed, 'no_readback')
        verified = bool(state['resolved'] and state['landed'] is True)
        return {
            'method': 'cdp_drag',
            'from': {'x': round(src['x'], 1), 'y': round(src['y'], 1),
                     'how': src['how'], 'input': src['input'],
                     'element': src.get('element')},
            'to': {'x': round(dst['x'], 1), 'y': round(dst['y'], 1),
                   'how': dst['how'], 'input': dst['input'],
                   'element': dst.get('element')},
            'steps': n_steps, 'page_index': idx, 'result': 'ok',
            'verified': verified,
            'resolved': state['resolved'], 'landed': state['landed'],
            'effected': state['effected'],
            'evidence': {
                'space': 'css_px', 'dpr': src['dpr'],
                'dispatched_events': dispatched,
                'elapsed_ms': elapsed_ms,
                'step_interval_ms': interval_ms,
                'element_at_start': at_start,
                'element_at_end': at_end,
                'frame_before': frame_before,
                'frame_after': frame_after,
                'read_back': 'document.elementFromPoint at start/end',
                'verified': verified,
                'three_state': state,
                'reason': ('drag has no readback — verify the effect by '
                           'comparing two frames, not by this receipt'),
            },
        }
    finally:
        ws.close()


def _parse_key_combo(spec):
    """'Control+z' → ({modifiers, key, code, vk, ...}, None) | (None, why)."""
    parts = [p.strip() for p in str(spec or '').split('+')]
    if not parts or not parts[-1]:
        return None, 'empty key spec'
    *mods, main = parts
    bits = 0
    names = []
    for m in mods:
        if not m:
            return None, 'empty modifier in %r' % str(spec)
        bit = _MODIFIER_BITS.get(m.lower())
        if bit is None:
            return None, 'unknown modifier %r in %r' % (m, spec)
        bits |= bit
        names.append(m.lower())
    mk = main.lower()
    if mk in _NAMED_KEYS:
        key, code, vk = _NAMED_KEYS[mk]
    elif len(main) == 1:
        key = main
        if main.isalpha():
            code = 'Key' + main.upper()
            vk = ord(main.upper())
        elif main.isdigit():
            code = 'Digit' + main
            vk = ord(main)
        else:
            code = ''
            vk = ord(main)
    else:
        return None, ('unknown key %r — named keys: %s'
                      % (main, ', '.join(sorted(_NAMED_KEYS))))
    return {'modifiers': bits, 'modifier_names': names,
            'key': key, 'code': code, 'vk': vk}, None


def cdp_key(keys, page_sel=None):
    """Press a key combination: modifiers down → main down → main up → mods up.

    'Control+z', 'Meta+Shift+t', 'Enter', 'Escape', 'ArrowLeft'. modifier
    order in the spec does not matter; the bitmask is what gets dispatched.

    Blender's whole vocabulary is this — G/R/S plus X/Y/Z plus digits. Without
    it hand can only type text, which in a 3D viewport is nothing.
    """
    info, err = _parse_key_combo(keys)
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page["webSocketDebuggerUrl"])
    try:
        _init_domains(ws, "Runtime")
        if err:
            out = _receipt_fail('cdp_key', err, keys=str(keys))
            out['evidence'].update(_three_state(False, None, 'key_unparsed'))
            out['resolved'], out['landed'] = False, None
            out['effected'] = 'unknown'
            return out

        focus_before = _focus_label(_active_element(ws, msg_id=50))
        events = []
        for bit in (1, 2, 4, 8):
            if info['modifiers'] & bit:
                k, code, vk = _MODIFIER_KEYS[bit]
                cdp_call(ws, 'Input.dispatchKeyEvent',
                         {'type': 'rawKeyDown',
                          'modifiers': info['modifiers'],
                          'key': k, 'code': code,
                          'windowsVirtualKeyCode': vk,
                          'nativeVirtualKeyCode': vk}, msg_id=51)
                events.append('rawKeyDown:' + k)
        cdp_call(ws, 'Input.dispatchKeyEvent',
                 {'type': 'rawKeyDown', 'modifiers': info['modifiers'],
                  'key': info['key'], 'code': info['code'],
                  'windowsVirtualKeyCode': info['vk'],
                  'nativeVirtualKeyCode': info['vk']}, msg_id=52)
        events.append('rawKeyDown:' + info['key'])
        cdp_call(ws, 'Input.dispatchKeyEvent',
                 {'type': 'keyUp', 'modifiers': info['modifiers'],
                  'key': info['key'], 'code': info['code'],
                  'windowsVirtualKeyCode': info['vk'],
                  'nativeVirtualKeyCode': info['vk']}, msg_id=53)
        events.append('keyUp:' + info['key'])
        for bit in (8, 4, 2, 1):
            if info['modifiers'] & bit:
                k, code, vk = _MODIFIER_KEYS[bit]
                cdp_call(ws, 'Input.dispatchKeyEvent',
                         {'type': 'keyUp', 'modifiers': 0,
                          'key': k, 'code': code,
                          'windowsVirtualKeyCode': vk,
                          'nativeVirtualKeyCode': vk}, msg_id=54)
                events.append('keyUp:' + k)

        focus_after = _focus_label(_active_element(ws, msg_id=55))
        _write_last(idx)
        landed = True if focus_after != focus_before else None
        state = _three_state(True, landed, 'no_readback')
        return {
            'method': 'cdp_key', 'keys': str(keys), 'page_index': idx,
            'result': 'ok', 'verified': False,
            'resolved': state['resolved'], 'landed': state['landed'],
            'effected': state['effected'],
            'parsed': {'modifiers': info['modifiers'],
                       'modifier_names': info['modifier_names'],
                       'key': info['key'], 'code': info['code'],
                       'vk': info['vk']},
            'evidence': {
                'dispatched_events': len(events), 'events': events,
                'focus_before': focus_before, 'focus_after': focus_after,
                'read_back': 'document.activeElement before/after',
                'verified': False,
                'three_state': state,
                'reason': ('a key press has no read-back beyond focus change — '
                           'verify the effect by observing the page'),
            },
        }
    finally:
        ws.close()
