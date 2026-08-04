"""
CDP Snapshot - browser perception via CDP.
"""
import json
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call,
    _init_domains, _header, _write_last, LOAD_TIMEOUT
)


def cdp_snapshot(max_chars=8000, page_sel=None):
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        m = str(max_chars)
        expr = (
            '(function(){'
            'var b=document.body;'
            'if(!b)return JSON.stringify({error:"no body"});'
            'var t=b.innerText||b.textContent||"";'
            'if(!t.trim())return JSON.stringify({error:"empty page (CSR?)",hint:"try render-wait"});'
            'var r=t.length>' + m + '?t.substring(0,' + m + '):t;'
            'var lines=r.split("\\n").filter(function(l){return l.trim()});'
            'return JSON.stringify({page_title:document.title||"(no title)",url:window.location.href,line_count:lines.length,chars:r.length,total_chars:t.length,truncated:t.length>' + m + ',text:r});'
            '})()')
        raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        value_str = raw.get('result', {}).get('value') or '{}'
        data = json.loads(value_str)
        _write_last(idx)
        data['page_index'] = idx
        data['method'] = 'cdp_snapshot'
        return data
    finally:
        ws.close()


cdp_snapshot_see = cdp_snapshot