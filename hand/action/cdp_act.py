"""
CDP Action — browser click/type via Chrome DevTools Protocol.
4-tier fallback for click preserved from V5.
"""
import json, time
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call,
    _init_domains, _element_info, _scroll_into_view,
    _get_dpr, _header, _write_last, LOAD_TIMEOUT
)

def cdp_click(selector, page_sel=None):
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        info = _element_info(ws, selector)
        if 'error' in info:
            return {'method': 'cdp_click', 'error': info['error'], 'selector': selector}
        if not info.get('visible'):
            _scroll_into_view(ws, selector)
            time.sleep(0.2)
            info = _element_info(ws, selector)
        x, y = info['x'], info['y']
        dpr = _get_dpr(ws)
        x_scaled, y_scaled = x / dpr, y / dpr

        cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mousePressed','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=3)
        cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mouseReleased','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=4)
        _js_click(ws, selector, msg_id=10)
        # 输入元素（input/textarea）只聚焦不提交：_js_focus_enter 触发 Enter 键、
        # _js_submit 触发 form.submit()，对搜索框这类输入框是破坏性的（提交空查询、
        # 清空焦点）。只有动作元素（button/a）才需要这两步真正触发动作。
        tag = (info.get('tag') or '').upper()
        if tag not in ('INPUT', 'TEXTAREA'):
            _js_focus_enter(ws, selector, msg_id=15)
            _js_submit(ws, selector, msg_id=20)

        _write_last(idx)
        return {'method': 'cdp_click', 'selector': selector, 'page_index': idx, 'result': 'ok', 'tiers': '4-tier'}
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
            data = json.loads(value_str)
            _write_last(idx)
            return {'method': 'cdp_type', 'page_index': idx, 'fast': True, 'text': text, **data}
        pass  # Input domain needs no enable
        info = _element_info(ws, selector)
        if 'error' in info:
            return {'method': 'cdp_type', 'error': info['error'], 'selector': selector}
        x, y = info['x'], info['y']
        dpr = _get_dpr(ws)
        x_scaled, y_scaled = x / dpr, y / dpr
        cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mousePressed','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=3)
        cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mouseReleased','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=4)
        for char in text:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=20)
            time.sleep(0.001)
        _write_last(idx)
        return {'method': 'cdp_type', 'page_index': idx, 'selector': selector, 'text': text, 'result': 'ok'}
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
    """
    sel = action
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
                return {'method': 'cdp_click', 'error': info['error'], 'action': action}

            x, y = info['x'], info['y']
            dpr = _get_dpr(ws)
            x_scaled, y_scaled = x / dpr, y / dpr
            cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mousePressed','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=3)
            cdp_call(ws, 'Input.dispatchMouseEvent', {'type':'mouseReleased','x':x_scaled,'y':y_scaled,'button':'left','clickCount':1}, msg_id=4)
            _write_last(idx)
            return {'method': 'cdp_click', 'text_match': text_val, 'tag': info.get('tag'), 'page_index': idx, 'result': 'ok'}
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
        return cdp_type(sel.strip(), text.strip())
    return {'error': 'cdp_type needs selector|text format', 'action': action}


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
        # Input domain needs no enable
        for char in text:
            cdp_call(ws, 'Input.insertText', {'text': char}, msg_id=20)
        _write_last(idx)
        return {'method': 'cdp_type', 'page_index': idx, 'text': text, 'result': 'ok'}
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
        return {'method': 'cdp_scroll', 'direction': d,
                'scrollY_before': before, 'scrollY_after': after,
                'moved': after != before}
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
