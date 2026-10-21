"""
CDP Core - shared CDP connection, helpers, page resolution.
Extracted from Hand V5 browser_cdp.py. Production-tested.
"""
import json, os, time, urllib.request, tempfile, websocket
from typing import Optional

CDP_HOST = f"http://127.0.0.1:{os.environ.get('HAND_CDP_PORT', '9222')}"

# LOCAL PATCH 2026-09-25 (haitian-mac): loopback CDP must bypass proxies
# (macOS system proxy 502s localhost) - see cdp_launcher.py note.
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CONNECT_TIMEOUT = 10
LOAD_TIMEOUT = 30
LAST_STATE_FILE = os.path.join(tempfile.gettempdir(), 'hand_cdp_last_idx')

def _state_file():
    """Session-page record path.

    HAND_CDP_STATE_FILE lets a test run (or a second browser session) keep its
    own record instead of reading whatever the machine's last real interaction
    left behind — a unit test that answers to the dev machine's session state is
    not hermetic, and it fails for reasons that have nothing to do with the code
    under test.
    """
    return os.environ.get('HAND_CDP_STATE_FILE') or LAST_STATE_FILE


def _json_get(path):
    url = f'{CDP_HOST}{path}'
    with _NO_PROXY.open(url, timeout=CONNECT_TIMEOUT) as resp:
        return json.loads(resp.read().decode())
def list_pages():
    return [p for p in _json_get('/json') if p.get('type') == 'page']
def _read_last_state():
    """The recorded session page. Legacy files held a bare index; current ones
    hold {'idx', 'id', 'url'}. A bare index is not an identity — see
    _resolve_session_page."""
    try:
        with open(_state_file(), encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return None
    if not raw: return None
    if raw.isdigit(): return {'idx': int(raw)}
    try:
        st = json.loads(raw)
    except Exception:
        return None
    return st if isinstance(st, dict) else None
def _read_last():
    """Back-compat: the recorded index, or None."""
    st = _read_last_state() or {}
    return st.get('idx')
def _write_last(idx, page=None):
    """Remember the session page by *identity*; the index is only a hint.

    0.13: storing the index alone was the root of a silent class of wrong-page
    bugs. Indices shift whenever any tab closes, so a stale index names a
    different page and every later call without an explicit page_sel works on
    the wrong tab — the reading stays green and the target is wrong. Measured:
    a full-suite run reported "no text field in the handle map" while it was
    actually interrogating an unrelated page left in the session.
    """
    if page is None:
        try:
            pages = list_pages()
            if isinstance(idx, int) and 0 <= idx < len(pages): page = pages[idx]
        except Exception:
            page = None
    st = {'idx': idx}
    if page:
        st['id'] = page.get('id')
        st['url'] = (page.get('url') or '')[:300]
    try:
        os.makedirs(tempfile.gettempdir(), exist_ok=True)
        with open(_state_file(),'w',encoding="utf-8") as f: f.write(json.dumps(st))
    except: pass
def _clear_last():
    """Forget the session page. Called when the browser instance itself is
    replaced: target ids belong to the process that minted them."""
    try:
        os.remove(_state_file())
    except Exception:
        pass
def _resolve_session_page(pages):
    """The recorded session page: identity first.

    An index is only trusted when it is all the record has (a file written by an
    older build). A record that names a page we can no longer find raises
    instead of falling back to pages[0] — falling back is what turns "my tab
    closed" into "I silently read a different page and believed it".
    """
    st = _read_last_state()
    if not st: return 0, pages[0]          # no session page has ever been set
    pid, url, idx = st.get('id'), st.get('url'), st.get('idx')
    if pid:
        for i, p in enumerate(pages):
            if p.get('id') == pid: return i, p
    if url:
        for i, p in enumerate(pages):
            if (p.get('url') or '').startswith(url[:120]): return i, p
    if not pid and not url and isinstance(idx, int) and 0 <= idx < len(pages):
        return idx, pages[idx]             # legacy record: index is all we have
    raise RuntimeError(
        "Session page is gone (recorded id=%s url=%s); %d page(s) open now. "
        "Pass an explicit page_sel, or run one see/click to set a new session page."
        % (pid or '-', (url or '-')[:80], len(pages)))
def resolve_page(selector, pages):
    if not pages: raise RuntimeError('No open pages')
    if selector is None or selector == 'first':
        return _resolve_session_page(pages)
    if selector == 'last':
        if not _read_last_state(): raise RuntimeError('No last page recorded')
        return _resolve_session_page(pages)
    try:
        idx = int(selector)
        if 0 <= idx < len(pages): return idx, pages[idx]
        raise RuntimeError(f'Page index {idx} out of range')
    except ValueError: pass
    for i, p in enumerate(pages):
        haystack = (p.get('url','') + ' ' + p.get('title','')).lower()
        if selector.lower() in haystack: return i, p
    raise RuntimeError(f'No page matching {selector!r}')
def _ref(page):
    return page.get('id','unknown')[:8]
def _header(idx, page):
    title = (page.get('title') or '(no title)')[:60]
    url = (page.get('url') or '')[:60]
    return f'#p{idx} r:{_ref(page)} {title} | {url}'
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
    # 0.9.3-P0: behavior:'instant' — a page with `html{scroll-behavior:smooth}`
    # (GitHub) would animate this scroll asynchronously, so the physical click
    # that follows the (kept) sleep(0.2) could still land outside the viewport.
    import json as jm
    cdp_call(ws,'Runtime.evaluate',{'expression':'document.querySelector('+jm.dumps(selector)+').scrollIntoView({block:"center",behavior:"instant"})'})

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
            # 0.10 D3: hand the frame over so a blank candidate can be voted on
            # without a second capture (pixels.pixel_vote re-shoots only when
            # the frame is too large to decode cheaply).
            visual = visual_probe(ws, call=cdp_call,
                                  png_b64=data if format == 'png' else None)
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
