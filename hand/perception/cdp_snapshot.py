"""
CDP Snapshot - browser perception via CDP.

COORDINATE CONTRACT: all coordinates returned here (e.g. interactive_map's
{x, y, w, h}) are PHYSICAL pixels = CSS px × devicePixelRatio. Feed them directly
to cdp_click_do("xy:x,y") — do accepts the same physical-pixel convention.
"""
import json
from hand.perception.cdp_core import (
    list_pages, resolve_page, cdp_connect, cdp_call,
    _init_domains, _header, _write_last, LOAD_TIMEOUT,
    _get_dpr, _build_coord
)
from hand.receipt import truncation
from hand.perception.visual_state import probe as visual_probe


def cdp_snapshot(max_chars=8000, page_sel=None):
    """Return page text snapshot.

    COORDINATE CONTRACT: all coordinates are physical pixels (CSS px × DPR)."""
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
        # S1 (0.9): the 8000-char cap was only declared as a bool + total_chars;
        # the unified block says which field, why, and how many chars were cut.
        if data.get('truncated'):
            data['truncation'] = truncation(
                'text', 'max_chars',
                int(data.get('total_chars', 0)) - int(data.get('chars', 0)),
                int(data.get('total_chars', 0)))
        _write_last(idx)
        data['page_index'] = idx
        data['method'] = 'cdp_snapshot'
        # Coordinate contract metadata
        dpr = _get_dpr(ws)
        metrics = cdp_call(ws, 'Page.getLayoutMetrics', msg_id=96, timeout=5)
        css_viewport = metrics.get('cssLayoutViewport', {})
        css_w = css_viewport.get('clientWidth', 0)
        css_h = css_viewport.get('clientHeight', 0)
        data['coord'] = _build_coord(css_w, css_h, dpr)
        # S2 (0.9): the visual state marker (DOM heuristic, no screenshot).
        visual = visual_probe(ws, call=cdp_call)
        data['visual_state'] = visual['visual_state']
        data['visual_signals'] = visual['visual_signals']
        return data
    finally:
        ws.close()


cdp_snapshot_see = cdp_snapshot


# ── Interactive map ──────────────────────────────────────────────────

def _element_sort_key(elem):
    """Sort key for interactive_map: occluded sinks to bottom,
    then visible-first, text-first, preserving DOM order via stable sort."""
    return (
        0 if not elem.get('occluded') else 1,
        0 if elem.get('visible') else 1,
        0 if (elem.get('text') or '').strip() else 1,
    )


def interactive_map(page_sel=None, max_elems=200):
    """Element map of interactive nodes, batch-fetched in one Runtime.evaluate.

    COORDINATE CONTRACT: all xy coordinates are physical pixels (CSS px × DPR).
    Feed them straight to cdp_click_do("xy:x,y").

    Each entry: {tag, text, selector, x, y, w, h, in_viewport, occluded, visible}.
    Coordinates are center-of-element in CSS px scaled by devicePixelRatio
    (same convention as _element_info). x/y are PHYSICAL pixels — feed them
    straight to cdp_click_do("xy:x,y"). Sorted occluded-last, visible-first,
    text-first, then DOM order; truncated to max_elems.
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
var vw=window.innerWidth||0;
var vh=window.innerHeight||0;
var out=[];
var candidates=[];
for(var i=0;i<els.length;i++){
  var el=els[i];
  var r=el.getBoundingClientRect();
  var t=(el.innerText||el.getAttribute("placeholder")||"").replace(/\\s+/g," ").trim();
  var in_vp=r.width > 0 && r.height > 0 && !(r.right < 0 || r.bottom < 0 || r.left > vw || r.top > vh);
  var cx=r.left+r.width/2;
  var cy=r.top+r.height/2;
  out.push({tag:el.tagName,text:t.substring(0,80),selector:mk(el),
    x:cx*dpr,y:cy*dpr,w:r.width*dpr,h:r.height*dpr,
    in_viewport:in_vp,occluded:false});
  if(in_vp && candidates.length < 50){
    candidates.push({idx:i,el:el,cx:cx,cy:cy});
  }
}
for(var j=0;j<candidates.length;j++){
  var c=candidates[j];
  if(c.cx >= 0 && c.cx < vw && c.cy >= 0 && c.cy < vh){
    var hit=document.elementFromPoint(c.cx,c.cy);
    var found=false;
    while(hit){
      if(hit===c.el){found=true;break;}
      hit=hit.parentElement;
    }
    out[c.idx].occluded=!found;
  }
}
for(var k=0;k<out.length;k++){
  var e=out[k];
  e.visible=e.in_viewport && !e.occluded && e.w > 0 && e.h > 0;
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
        elems.sort(key=_element_sort_key)
        elems = elems[:max_elems]
        _write_last(idx)
        # Coordinate contract metadata
        dpr = _get_dpr(ws)
        metrics = cdp_call(ws, 'Page.getLayoutMetrics', msg_id=95, timeout=5)
        css_viewport = metrics.get('cssLayoutViewport', {})
        css_w = css_viewport.get('clientWidth', 0)
        css_h = css_viewport.get('clientHeight', 0)
        out = {
            'method': 'cdp_interactive',
            'page_index': idx,
            'count': len(elems),
            'total': total,
            'truncated': total > len(elems),
            'elems': elems,
            'coord': _build_coord(css_w, css_h, dpr),
        }
        # S1 (0.9): declare the max_elems cut in the unified shape.
        if total > len(elems):
            out['truncation'] = truncation('elems', 'max_elems',
                                           total - len(elems), total)
        return out
    finally:
        ws.close()


# ── Network ───────────────────────────────────────────────────────────
from hand.perception.cdp_network import network_snapshot, fetch_network_body

cdp_network_see = network_snapshot
