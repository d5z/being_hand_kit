"""Live acceptance for 0.13.8: dpr read once, carried.

Page lies the way Neuromancer's fixture did: `window.devicePixelRatio` is a
getter that answers 2 on the FIRST read and 1 on every read after. The button is
centred at CSS(280,180). Old shape (page multiplies under its own read, driver
re-reads to divide) → dispatched at CSS 560,180: double, on nothing. New shape
(one read, carried) → 280,180 and the page's own log says x=280.

Run with HAND_CDP_PORT=9444 against an isolated Chrome.
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, "/home/alice/Hand")
from hand.action import cdp_act
from hand.perception import cdp_core

HTML = """<!doctype html><meta charset=utf-8><style>
body{margin:0}
#t{position:absolute;left:240px;top:160px;width:80px;height:40px}
</style>
<button id=t>go</button>
<script>
var n = 0;
Object.defineProperty(window, 'devicePixelRatio', {
  get: function () { n += 1; window.__reads = n; return n === 1 ? 2 : 1; }
});
window.__log = [];
document.addEventListener('click', function (e) {
  window.__log.push({x: e.clientX, y: e.clientY, target: e.target.id,
                     trusted: e.isTrusted, dpr_now: window.devicePixelRatio,
                     reads_at_click: window.__reads});
}, true);
</script>
"""


def main():
    url = "data:text/html;charset=utf-8," + urllib.parse.quote(HTML)
    pages = cdp_core.list_pages()
    idx, page = cdp_core.resolve_page(None, pages)
    ws = cdp_core.cdp_connect(page["webSocketDebuggerUrl"])
    try:
        cdp_core.cdp_call(ws, "Page.navigate", {"url": url}, timeout=15)
    finally:
        ws.close()
    import time
    time.sleep(1.0)

    out = cdp_act.cdp_click("#t")
    print("receipt:")
    print("  result:", out.get("result"), "verified:", out.get("verified"))
    ev = out.get("evidence") or {}
    print("  dpr:", ev.get("dpr"), "dpr_reads:", ev.get("dpr_reads"))
    print("  dispatched:", json.dumps(ev.get("dispatched"), sort_keys=True))
    print("  dispatch:", json.dumps(ev.get("dispatch"), sort_keys=True))

    idx, page = cdp_core.resolve_page(None, cdp_core.list_pages())
    ws = cdp_core.cdp_connect(page["webSocketDebuggerUrl"])
    try:
        r = cdp_core.cdp_call(ws, "Runtime.evaluate",
                              {"expression": "JSON.stringify({log:window.__log, reads:window.__reads})",
                               "returnByValue": True}, timeout=10)
        data = json.loads(r["result"]["value"])
    finally:
        ws.close()
    print("page says:", json.dumps(data, sort_keys=True))


main()
