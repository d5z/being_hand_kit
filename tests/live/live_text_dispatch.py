"""Live acceptance: the text= path can now say how many times the click landed.

The gap this closes: `text=` and `selector=` claim the same action but their
receipts had different vocabularies — no `dispatch{}`, no `dpr{}`, no probe. So
the two were not comparable, and a triple-fire on the text path (the bug fixed
for `selector=` in 8e96817) would have been invisible: a receipt that says
`verified: true` without counting executions cannot contradict one.

What is asserted here, on a real Chrome and a real mouse:
  1. the page's own handler runs exactly once (window.n == 1)
  2. the receipt carries dispatch{trusted_clicks: 1, escalation: 'none'}
  3. the receipt carries dpr/dpr_reads/dispatched, same names as selector=

Run with HAND_CDP_PORT=9444 against an isolated Chrome.
"""
import json
import sys
import time
import urllib.parse

sys.path.insert(0, "/home/alice/Hand")
from hand.action import cdp_act
from hand.perception import cdp_core
from hand.perception import cdp_launcher as L

HTML = """<!doctype html><meta charset=utf-8><style>
body{margin:0}
#t{position:absolute;left:240px;top:160px;width:80px;height:40px}
</style>
<button id=t onclick="window.n=(window.n||0)+1">go</button>
<script>
window.__log = [];
document.addEventListener('click', function (e) {
  window.__log.push({target: e.target.id, trusted: e.isTrusted});
}, true);
</script>
"""


def _eval(ws_expr):
    idx, page = cdp_core.resolve_page(None, cdp_core.list_pages())
    ws = cdp_core.cdp_connect(page["webSocketDebuggerUrl"])
    try:
        r = cdp_core.cdp_call(ws, "Runtime.evaluate",
                              {"expression": ws_expr, "returnByValue": True},
                              timeout=10)
        return r.get("result", {}).get("value")
    finally:
        ws.close()


def main():
    url = "data:text/html;charset=utf-8," + urllib.parse.quote(HTML)
    idx, page = cdp_core.resolve_page(None, cdp_core.list_pages())
    ws = cdp_core.cdp_connect(page["webSocketDebuggerUrl"])
    try:
        cdp_core.cdp_call(ws, "Page.navigate", {"url": url}, timeout=15)
    finally:
        ws.close()
    time.sleep(1.0)

    out = cdp_act.cdp_click_do("text=go")
    ev = out.get("evidence") or {}
    print("receipt: result=%s verified=%s" % (out.get("result"), out.get("verified")))
    print("  dispatch:  ", json.dumps(ev.get("dispatch"), sort_keys=True))
    print("  dpr:       ", ev.get("dpr"), "reads:", ev.get("dpr_reads"))
    print("  dispatched:", json.dumps(ev.get("dispatched"), sort_keys=True))

    seen = json.loads(_eval("JSON.stringify({n:window.n||0, log:window.__log})"))
    print("page says: handler fired %s time(s); listener saw %d click(s)"
          % (seen["n"], len(seen["log"])))

    d = ev.get("dispatch") or {}
    checks = [
        ("handler fired exactly once", seen["n"] == 1),
        ("probe saw exactly one trusted click", d.get("trusted_clicks") == 1),
        ("no untrusted click", (d.get("untrusted_clicks") or 0) == 0),
        ("no escalation was needed", d.get("escalation") == "none"),
        ("dispatches == 1", d.get("dispatches") == 1),
        ("dpr reported once", ev.get("dpr_reads") == 1),
        ("dispatched carries css+physical", bool(ev.get("dispatched"))),
    ]
    for name, ok in checks:
        print("  [%s] %s" % ("ok" if ok else "FAIL", name))
    print("ALL OK" if all(ok for _, ok in checks) else "SOME FAILED")


if __name__ == "__main__":
    L.ensure_chrome()
    main()
