#!/usr/bin/env python3
import sys, os, json, time
_HERE = os.path.dirname(os.path.abspath(__file__))
# Support two layouts:
#   dev:    <root>/kit/mcp_server.py  -> hand at <root>/hand  (../hand)
#   bundle: <root>/mcp_server.py      -> hand at <root>/hand  (./hand)
_root = None
for _cand in (os.path.dirname(_HERE), _HERE):
    if os.path.isdir(os.path.join(_cand, 'hand')):
        _root = _cand
        break
if _root is None:
    _root = os.path.dirname(_HERE)
if _root not in sys.path:
    sys.path.insert(0, _root)
from mcp.server import FastMCP
mcp = FastMCP("hand")
HEARTBEAT_FILE = os.path.expanduser("~/.heart-portal/kits/hand/.heartbeat.json")
_started_at = time.time()
_call_count = 0
def _bump():
    global _call_count
    _call_count += 1
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump({"calls": _call_count, "last_used_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "uptime_seconds": int(time.time() - _started_at)}, f)
    except: pass
@mcp.tool()
def cdp_open(url: str) -> dict:
    from hand.router import route_open
    _bump()
    return route_open(url)
@mcp.tool()
def cdp_close() -> dict:
    _bump()
    try:
        from hand.perception.cdp_core import list_pages, cdp_connect, cdp_call, _init_domains
        pages = list_pages()
        closed = 0
        for page in pages:
            try:
                ws = cdp_connect(page["webSocketDebuggerUrl"])
                _init_domains(ws, "Browser")
                cdp_call(ws, "Browser.close")
                ws.close()
                closed += 1
            except: pass
        return {"closed": "ok", "pages_closed": closed}
    except Exception as e:
        return {"closed": "partial", "error": str(e)}
@mcp.tool()
def cdp_nav(url: str) -> dict:
    from hand.router import route_open
    _bump()
    return route_open(url)
@mcp.tool()
def cdp_see(kind: str = None) -> dict:
    from hand.router import route_see
    _bump()
    return route_see(kind=kind)
@mcp.tool()
def cdp_click(selector: str) -> dict:
    from hand.router import route_do
    _bump()
    return route_do(selector)
@mcp.tool()
def cdp_type(text: str) -> dict:
    from hand.action.cdp_act import cdp_type_focused
    _bump()
    return cdp_type_focused(text)
@mcp.tool()
def cdp_shot() -> dict:
    from hand.router import route_screenshot
    _bump()
    return route_screenshot()
@mcp.tool()
def hand_plan(goal: str, execute: bool = False) -> dict:
    from hand.router import route_plan
    _bump()
    return route_plan(goal)
@mcp.tool()
def health() -> dict:
    _bump()
    chrome_state = "unknown"
    try:
        from hand.perception.cdp_core import list_pages
        pages = list_pages()
        chrome_state = f"connected ({len(pages)} pages)" if pages else "no pages"
    except: chrome_state = "not reachable"
    return {"status": "alive", "uptime_seconds": int(time.time() - _started_at), "calls": _call_count, "chrome": chrome_state, "hand_version": "6.5.1"}
if __name__ == "__main__":
    mcp.run()
