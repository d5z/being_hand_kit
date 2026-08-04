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