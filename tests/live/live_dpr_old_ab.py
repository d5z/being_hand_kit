"""A/B: the same lying fixture, driven through the OLD composition.

Old shape = `_element_info` (page multiplies under its own dpr read) followed by
`_get_dpr` (a second read) used to divide. Same page, same getter (2 then 1),
same button centred at CSS(280,180). Expected: the page logs a click at 560,180
— 280px to the right of the target — while the receipt is still ok/verified.
"""
import json
import sys
import time
import urllib.parse

sys.path.insert(0, "/home/alice/Hand")
from hand.action import cdp_act
from hand.perception import cdp_core
from live_dpr_once import HTML


def fresh_page():
    url = "data:text/html;charset=utf-8," + urllib.parse.quote(HTML)
    idx, page = cdp_core.resolve_page(None, cdp_core.list_pages())
    ws = cdp_core.cdp_connect(page["webSocketDebuggerUrl"])
    cdp_core.cdp_call(ws, "Page.navigate", {"url": url}, timeout=15)
    time.sleep(1.0)
    return ws


def main():
    ws = fresh_page()
    try:
        info = cdp_act._element_info(ws, "#t")          # page's own dpr read
        dpr2 = cdp_act._get_dpr(ws)                     # second, independent read
        cdp_act._click_at(ws, info["x"], info["y"], dpr2)
        time.sleep(0.3)
        r = cdp_core.cdp_call(ws, "Runtime.evaluate",
                              {"expression": "JSON.stringify({log:window.__log, reads:window.__reads})",
                               "returnByValue": True}, timeout=10)
        data = json.loads(r["result"]["value"])
    finally:
        ws.close()
    print("old path: info =", {k: info.get(k) for k in ("x", "y")},
          " second dpr read =", dpr2,
          " dispatched css =", (info["x"] / dpr2, info["y"] / dpr2))
    print("page says:", json.dumps(data, sort_keys=True))


main()
