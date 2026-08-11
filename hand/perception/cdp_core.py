"""
CDP Core - shared CDP connection, helpers, page resolution.
Extracted from Hand V5 browser_cdp.py. Production-tested.
"""
import json, time, urllib.request, websocket
from typing import Optional

CDP_HOST = 'http://localhost:9222'
CONNECT_TIMEOUT = 10
LOAD_TIMEOUT = 30
LAST_STATE_FILE = '/tmp/hand_cdp_last_idx'

def _json_get(path):
    url = f'{CDP_HOST}{path}'
    with urllib.request.urlopen(url, timeout=CONNECT_TIMEOUT) as resp:
        return json.loads(resp.read().decode())
def list_pages():
    return [p for p in _json_get('/json') if p.get('type') == 'page']
def _read_last():
    try:
        with open(LAST_STATE_FILE) as f: return int(f.read().strip())
    except: return None
def _write_last(idx):
    try:
        with open(LAST_STATE_FILE,'w') as f: f.write(str(idx))
    except: pass
def _ref(page):
    return page.get('id','unknown')[:8]
def _header(idx, page):
    title = (page.get('title') or '(no title)')[:60]
    url = (page.get('url') or '')[:60]
    return f'#p{idx} r:{_ref(page)} {title} | {url}'
def resolve_page(selector, pages):
    if not pages: raise RuntimeError('No open pages')
    if selector is None or selector == 'first':
        idx = _read_last()
        if idx is not None and 0 <= idx < len(pages): return idx, pages[idx]
        return 0, pages[0]
    if selector == 'last':
        idx = _read_last()
        if idx is not None and 0 <= idx < len(pages): return idx, pages[idx]
        raise RuntimeError('No last page recorded')
    try:
        idx = int(selector)
        if 0 <= idx < len(pages): return idx, pages[idx]
        raise RuntimeError(f'Page index {idx} out of range')
    except ValueError: pass
    for i, p in enumerate(pages):
        haystack = (p.get('url','') + ' ' + p.get('title','')).lower()
        if selector.lower() in haystack: return i, p
    raise RuntimeError(f'No page matching {selector!r}')
def cdp_connect(ws_url):
    return websocket.create_connection(ws_url, timeout=CONNECT_TIMEOUT, suppress_origin=True)
def cdp_call(ws, method, params=None, msg_id=1, timeout=LOAD_TIMEOUT):
    payload = {'id':msg_id,'method':method}
    if params is not None: payload['params'] = params
    ws.send(json.dumps(payload))
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(max(0.1, deadline - time.time()))
        try: raw = ws.recv()
        except websocket.WebSocketTimeoutException: continue
        msg = json.loads(raw)
        if msg.get('id') == msg_id:
            if 'error' in msg: raise RuntimeError(f'CDP error: {msg["error"]}')
            return msg.get('result',{})
    raise TimeoutError(f'CDP call {method} timed out')
def wait_event(ws, event_method, timeout=LOAD_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(max(0.1, deadline - time.time()))
        try: raw = ws.recv()
        except websocket.WebSocketTimeoutException: continue
        msg = json.loads(raw)
        if msg.get('method') == event_method: return msg.get('params',{})
    raise TimeoutError(f'Event {event_method} not received')
def _init_domains(ws, *domains):
    for domain in domains:
        cdp_call(ws, f'{domain}.enable', msg_id=abs(hash(domain)) % 10000, timeout=5)
def _get_dpr(ws):
    try:
        result = cdp_call(ws,'Runtime.evaluate',{'expression':'window.devicePixelRatio'},msg_id=99,timeout=5)
        return result.get('result',{}).get('value',1.0)
    except: return 1.0
def _element_info(ws, selector):
    import json as jm
    expr = '(function(){var el=document.querySelector('+jm.dumps(selector)+');if(!el)return JSON.stringify({error:"element not found"});var r=el.getBoundingClientRect();var dpr=window.devicePixelRatio||1;return JSON.stringify({x:(r.left+r.width/2)*dpr,y:(r.top+r.height/2)*dpr,w:r.width,h:r.height,visible:r.width>0&&r.height>0,tag:el.tagName,text:(el.innerText||"").substring(0,80)});})()'
    result = cdp_call(ws,'Runtime.evaluate',{'expression':expr,'returnByValue':True})
    value = result.get('result',{}).get('value','{}')
    return jm.loads(value)
def _scroll_into_view(ws, selector):
    import json as jm
    cdp_call(ws,'Runtime.evaluate',{'expression':'document.querySelector('+jm.dumps(selector)+').scrollIntoView({block:"center"})'})

def cdp_screenshot(page_sel=None, format='png', quality=None) -> dict:
    """Take a screenshot via CDP Page.captureScreenshot. Returns {'data': base64, 'format': 'png'}."""
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        params = {'format': format}
        if quality is not None and format == 'jpeg':
            params['quality'] = quality
        result = cdp_call(ws, 'Page.captureScreenshot', params, msg_id=42)
        return {'data': result.get('data', ''), 'format': format, 'page_index': idx}
    finally:
        ws.close()
