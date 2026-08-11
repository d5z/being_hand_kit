import json, time, websocket
from hand.perception.cdp_core import list_pages, resolve_page, cdp_connect, _write_last


def network_snapshot(page_sel=None, duration=3.0, kind=None, max_small_body=2048):
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])

    try:
        ws.send(json.dumps({'id': 50001, 'method': 'Network.enable'}))

        requests = {}
        deadline = time.time() + duration
        enable_done = False

        while time.time() < deadline:
            remaining = max(0.05, deadline - time.time())
            ws.settimeout(min(0.5, remaining))
            try:
                raw = ws.recv()
                msg = json.loads(raw)

                if msg.get('id') == 50001 and not enable_done:
                    enable_done = True
                    if 'error' in msg:
                        return {'error': 'Network.enable failed', 'method': 'cdp_network'}
                    continue

                method = msg.get('method', '')

                if method == 'Network.requestWillBeSent':
                    params = msg.get('params', {})
                    req = params.get('request', {})
                    req_id = params.get('requestId', '')
                    if req_id and req_id not in requests:
                        requests[req_id] = {
                            'id': req_id,
                            'method': req.get('method', ''),
                            'url': req.get('url', ''),
                            'type': params.get('type', ''),
                            'status': None,
                            'size': 0,
                            'body': None,
                        }

                elif method == 'Network.responseReceived':
                    params = msg.get('params', {})
                    resp = params.get('response', {})
                    req_id = params.get('requestId', '')
                    if req_id in requests:
                        r = requests[req_id]
                        r['status'] = resp.get('status', 0)
                        mime = resp.get('mimeType', '')
                        if mime:
                            r['type'] = mime
                        r['size'] = resp.get('encodedDataLength', 0)

            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break

        for req_id, req in list(requests.items()):
            mime = req.get('type', '')
            size = req.get('size', 0)
            if (req.get('status') is not None
                    and 'json' in mime
                    and 0 < size <= max_small_body):
                try:
                    body_result = cdp_call_raw(ws, 'Network.getResponseBody',
                                               {'requestId': req_id},
                                               msg_id=60000 + abs(hash(req_id)) % 10000)
                    body_text = body_result.get('body', '')
                    if body_text:
                        try:
                            req['body'] = json.loads(body_text)
                        except (json.JSONDecodeError, ValueError):
                            req['body'] = body_text[:max_small_body]
                except Exception:
                    pass

        try:
            ws.send(json.dumps({'id': 50002, 'method': 'Network.disable'}))
        except Exception:
            pass

    finally:
        ws.close()

    req_list = list(requests.values())

    if kind == 'api':
        req_list = [r for r in req_list
                    if 'json' in r.get('type', '') or 'xml' in r.get('type', '')]
    elif kind == 'xhr':
        skip = ('image/', 'video/', 'font/', 'text/css', 'application/font')
        req_list = [r for r in req_list
                    if not r.get('type', '').startswith(skip)]

    req_list.sort(key=lambda r: r.get('id', ''))

    _write_last(idx)
    return {
        'method': 'cdp_network',
        'page_index': idx,
        'duration': duration,
        'total_requests': len(req_list),
        'requests': req_list,
    }


def cdp_call_raw(ws, method, params=None, msg_id=1, timeout=5):
    ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(max(0.1, deadline - time.time()))
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        msg = json.loads(raw)
        if msg.get('id') == msg_id:
            if 'error' in msg:
                raise RuntimeError(f'CDP error: {msg[chr(34)+chr(101)+chr(114)+chr(114)+chr(111)+chr(114)+chr(34)]}')
            return msg.get('result', {})
    raise TimeoutError(f'CDP call {method} timed out')


def fetch_network_body(page_sel=None, request_id=None):
    if not request_id:
        return {'error': 'request_id required', 'method': 'cdp_network'}

    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])

    try:
        ws.send(json.dumps({'id': 70001, 'method': 'Network.enable'}))
        result = cdp_call_raw(ws, 'Network.getResponseBody',
                              {'requestId': request_id},
                              msg_id=70002, timeout=10)
        body_text = result.get('body', '')
        is_base64 = result.get('base64Encoded', False)
        try:
            ws.send(json.dumps({'id': 70003, 'method': 'Network.disable'}))
        except Exception:
            pass
    finally:
        ws.close()

    return {
        'method': 'cdp_network',
        'page_index': idx,
        'request_id': request_id,
        'body': body_text,
        'base64_encoded': is_base64,
    }
