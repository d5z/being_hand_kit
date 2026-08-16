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


# ── Interactive map ──────────────────────────────────────────────────

def interactive_map(page_sel=None, max_elems=200):
    """Element map of interactive nodes, batch-fetched in one Runtime.evaluate.

    Each entry: {tag, text, selector, x, y, w, h, visible}.
    Coordinates are center-of-element in CSS px scaled by devicePixelRatio
    (same convention as _element_info). Sorted visible-first, text-first,
    then DOM order; truncated to max_elems.
    """
    pages = list_pages()
    idx, page = resolve_page(page_sel, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        expr = (
            '''(function(){
var SEL='a[href], button, input, textarea, select, [role="button"], [role="link"], [role="checkbox"], [role="tab"], [onclick], [tabindex]:not([tabindex="-1"])';
var els=document.querySelectorAll(SEL);
var dpr=window.devicePixelRatio||1;
var out=[];
for(var i=0;i<els.length;i++){
  var el=els[i];
  var r=el.getBoundingClientRect();
  var t=(el.innerText||el.getAttribute("placeholder")||"").replace(/\\s+/g," ").trim();
  out.push({tag:el.tagName,text:t.substring(0,80),selector:mk(el),
    x:(r.left+r.width/2)*dpr,y:(r.top+r.height/2)*dpr,
    w:r.width,h:r.height,visible:r.width>0&&r.height>0});
}
return JSON.stringify(out);
function mk(el){
  if(el.id)return "#"+el.id;
  if(el.name)return el.tagName.toLowerCase()+"[name="+el.name+"]";
  var cls=el.className;
  if(typeof cls==="string"&&cls.trim()){
    return el.tagName.toLowerCase()+"."+cls.trim().split(/\\s+/)[0];
  }
  var p=el.parentNode;
  if(p&&p.children){
    var n=1;
    for(var j=0;j<p.children.length;j++){
      if(p.children[j]===el)return el.tagName.toLowerCase()+":nth-of-type("+n+")";
      if(p.children[j].tagName===el.tagName)n++;
    }
  }
  return el.tagName.toLowerCase();
}
})()'''
        )
        raw = cdp_call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        value_str = raw.get('result', {}).get('value') or '[]'
        elems = json.loads(value_str)
        total = len(elems)
        elems.sort(key=lambda e: (0 if e.get('visible') else 1,
                                  0 if (e.get('text') or '').strip() else 1))
        elems = elems[:max_elems]
        _write_last(idx)
        return {
            'method': 'cdp_interactive',
            'page_index': idx,
            'count': len(elems),
            'total': total,
            'truncated': total > len(elems),
            'elems': elems,
        }
    finally:
        ws.close()


# ── Network ───────────────────────────────────────────────────────────
from hand.perception.cdp_network import network_snapshot, fetch_network_body

cdp_network_see = network_snapshot
