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


def _handle_fail(reason, entry=None, handle=None, method="cdp_click", **fields):
    """Unverified handle receipt — same shape as _receipt_fail, plus the target."""
    ev = {"verified": False, "reason": reason}
    if entry is not None:
        ev["element"] = _handle_label(entry)
        ev["handle"] = f'[{entry.get("idx")}]'
    out = _receipt_fail(method, reason, **fields)
    out["evidence"] = ev
    if handle is not None:
        out["handle"] = handle
    return out


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
    scroll_js = "this.scrollIntoView({block:'center',inline:'center'});"
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
        oid = _handle_object_id(ws, entry["backend_node_id"])
        if not oid:
            return _handle_fail(
                f'handle [{entry["idx"]}] element is gone (backendNodeId '
                f'{entry["backend_node_id"]} does not resolve) — call cdp_see again',
                entry=entry, handle=str(handle))
        rect = _handle_rect(ws, oid)
        if rect is None:
            return _handle_fail(
                f'handle [{entry["idx"]}] element has no box (display:none, '
                f'zero-size or detached) — call cdp_see again',
                entry=entry, handle=str(handle))
        dpr = _dpr_now(ws)
        dispatched = [round(rect["x"] * dpr), round(rect["y"] * dpr)]
        _click_at(ws, dispatched[0], dispatched[1], dpr)
        _write_last(idx)
        return {"method": "cdp_click", "handle": f'[{entry["idx"]}]',
                "page_index": idx, "result": "ok", "tiers": "handle",
                "verified": True,
                "evidence": {
                    "element": _handle_label(entry),
                    "role": entry.get("role"),
                    "name": entry.get("name"),
                    "handle": f'[{entry["idx"]}]',
                    "backend_node_id": entry["backend_node_id"],
                    "box": {"x": round(rect["x"], 1), "y": round(rect["y"], 1),
                            "w": round(rect["w"], 1), "h": round(rect["h"], 1)},
                    "space": "physical", "dpr": dpr, "dispatched": dispatched,
                    "read_back": "getBoundingClientRect via DOM.resolveNode",
                    "source": "cdp_see(kind=a11y) handle map",
                    "verified": True,
                }}
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
        oid = _handle_object_id(ws, entry["backend_node_id"])
        if not oid:
            out = _handle_fail(
                f'handle [{entry["idx"]}] element is gone (backendNodeId '
                f'{entry["backend_node_id"]} does not resolve) — call cdp_see again',
                entry=entry, handle=str(handle), method="cdp_type")
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
                entry=entry, handle=str(handle), method="cdp_type")
            out["text"] = text
            return out
        for char in text:
            cdp_call(ws, "Input.insertText", {"text": char}, msg_id=35)
            time.sleep(0.001)
        _write_last(idx)
        return {"method": "cdp_type", "handle": f'[{entry["idx"]}]',
                "page_index": idx, "text": text, "result": "ok",
                "verified": True,
                "evidence": {
                    "element": _handle_label(entry),
                    "role": entry.get("role"), "name": entry.get("name"),
                    "handle": f'[{entry["idx"]}]',
                    "backend_node_id": entry["backend_node_id"],
                    "focus": _focus_label(focus),
                    "method_detail": "DOM.resolveNode → focus() → Input.insertText",
                    "verified": True,
                }}
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
        for char in text:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=20)
            time.sleep(0.001)
        _write_last(idx)
        ev = _element_evidence(info)
        ev['verified'] = True
        ev['selector'] = selector
        ev['read_back'] = 'document.querySelector hit + Input.insertText'
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
            expr = (
                "(function(){"
                "var xpath='//a[contains(text(),"+q+")]|"
                "//button[contains(text(),"+q+")]|"
                "//*[text()="+q+"]';"
                "var r=document.evaluate(xpath,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);"
                "var el=r.singleNodeValue;"
                "if(!el)return JSON.stringify({error:'text element not found',search:"+q+"});"
                "var box=el.getBoundingClientRect();var dpr=window.devicePixelRatio||1;"
                "return JSON.stringify({x:(box.left+box.width/2)*dpr,y:(box.top+box.height/2)*dpr,tag:el.tagName,text:(el.innerText||'').substring(0,80)});"
                "})()")
            raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
            value_str = raw.get('result', {}).get('value', '{}')
            info = json.loads(value_str)
            if 'error' in info:
                return _receipt_fail('cdp_click',
                                     f"text element not found: {text_val!r}",
                                     action=action, text_match=text_val)

            x, y = info['x'], info['y']
            dpr = _get_dpr(ws)
            _click_at(ws, x, y, dpr)
            _write_last(idx)
            ev = _element_evidence({'tag': info.get('tag'),
                                    'text': info.get('text')})
            ev['verified'] = True
            ev['text_match'] = text_val
            ev['read_back'] = 'XPath text() hit + getBoundingClientRect'
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
        # Input domain needs no enable
        for char in text:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=20)
        _write_last(idx)
        return {'method': 'cdp_type', 'page_index': idx, 'text': text,
                'result': 'ok', 'verified': True,
                'evidence': {'focus': _focus_label(focus), 'tag': tag,
                             'focus_id': focus.get('id') or '',
                             'focus_type': focus.get('type') or '',
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
