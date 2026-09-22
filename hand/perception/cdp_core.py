"""
CDP Core - shared CDP connection, helpers, page resolution.
Extracted from Hand V5 browser_cdp.py. Production-tested.
"""
import json, os, time, urllib.request, websocket
from typing import Optional

CDP_HOST = f"http://localhost:{os.environ.get('HAND_CDP_PORT', '9222')}"
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
    expr = '(function(){var el=document.querySelector('+jm.dumps(selector)+');if(!el)return JSON.stringify({error:"element not found"});var r=el.getBoundingClientRect();var dpr=window.devicePixelRatio||1;return JSON.stringify({x:(r.left+r.width/2)*dpr,y:(r.top+r.height/2)*dpr,w:r.width*dpr,h:r.height*dpr,visible:r.width>0&&r.height>0,tag:el.tagName,text:(el.innerText||"").substring(0,80)});})()'
    result = cdp_call(ws,'Runtime.evaluate',{'expression':expr,'returnByValue':True})
    value = result.get('result',{}).get('value','{}')
    return jm.loads(value)
def _scroll_into_view(ws, selector):
    import json as jm
    cdp_call(ws,'Runtime.evaluate',{'expression':'document.querySelector('+jm.dumps(selector)+').scrollIntoView({block:"center"})'})

def _decode_image_size(data_b64, fmt):
    """Decode PNG/JPEG base64 head to extract width and height."""
    import base64, struct
    try:
        if fmt == 'png':
            head = base64.b64decode(data_b64[:512])
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                w = struct.unpack('!I', head[16:20])[0]
                h = struct.unpack('!I', head[20:24])[0]
                return w, h
        elif fmt == 'jpeg':
            raw = base64.b64decode(data_b64)
            i = 0
            while i < len(raw) - 1:
                if raw[i] == 0xFF:
                    marker = raw[i+1]
                    if marker == 0xD8:
                        i += 2
                        continue
                    elif marker == 0xD9:
                        break
                    elif marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        if i + 9 < len(raw):
                            h = struct.unpack('!H', raw[i+5:i+7])[0]
                            w = struct.unpack('!H', raw[i+7:i+9])[0]
                            return w, h
                        break
                    else:
                        if i + 3 < len(raw):
                            seg_len = struct.unpack('!H', raw[i+2:i+4])[0]
                            i += 2 + seg_len
                            continue
                i += 1
    except Exception:
        pass
    return None, None

def _build_coord(css_w, css_h, dpr, img_w=None, img_h=None):
    """Build perception-contract coordinate metadata.

    COORDINATE CONTRACT: space='physical', dpr from browser,
    viewport in CSS px, image in physical px with scale=image/physical.
    """
    physical_w = css_w * dpr if css_w else 0
    physical_h = css_h * dpr if css_h else 0
    if img_w is None or img_h is None:
        img_w = physical_w
        img_h = physical_h
    scale = round(img_w / physical_w, 3) if physical_w else 1.0
    return {
        'space': 'physical',
        'dpr': dpr,
        'viewport': {'w': css_w, 'h': css_h},
        'image': {'w': img_w, 'h': img_h, 'scale': scale},
    }

def cdp_screenshot(page_sel=None, format='png', quality=None) -> dict:
    """Take a screenshot via CDP Page.captureScreenshot.

    COORDINATE CONTRACT: space='physical', dpr from browser,
    viewport in CSS px, image in physical px with scale=image/physical.
    Returns {'data': base64, 'format': 'png', 'page_index': idx, 'coord': {...}}."""
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Page')
        params = {'format': format}
        if quality is not None and format == 'jpeg':
            params['quality'] = quality
        result = cdp_call(ws, 'Page.captureScreenshot', params, msg_id=42)
        data = result.get('data', '')
        # Layout metrics & DPR for coordinate contract
        dpr = _get_dpr(ws)
        metrics = cdp_call(ws, 'Page.getLayoutMetrics', msg_id=97, timeout=5)
        css_viewport = metrics.get('cssLayoutViewport', {})
        css_w = css_viewport.get('clientWidth', 0)
        css_h = css_viewport.get('clientHeight', 0)
        img_w, img_h = _decode_image_size(data, format)
        if img_w is None:
            img_w, img_h = 0, 0
        coord = _build_coord(css_w, css_h, dpr, img_w, img_h)
        # S2 (0.9): carry the visual state marker on the shot too. Local import
        # keeps the module graph acyclic (visual_state lazily imports cdp_call).
        try:
            from hand.perception.visual_state import probe as visual_probe
            visual = visual_probe(ws, call=cdp_call)
        except Exception:
            visual = {'visual_state': 'unknown', 'visual_signals': ['probe-failed']}
        return {
            'data': data,
            'format': format,
            'page_index': idx,
            'coord': coord,
            'visual_state': visual['visual_state'],
            'visual_signals': visual['visual_signals'],
        }
    finally:
        ws.close()
