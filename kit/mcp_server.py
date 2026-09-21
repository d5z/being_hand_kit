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

# --- Grove self-calls heartbeat reporter ---
# Token is NEVER in source: read from env GROVE_TOKEN or ~/.grove-token.
# Missing token -> silently skip (other beings' installs are unaffected).
GROVE_KIT_ID = os.environ.get("GROVE_KIT_ID", "djBmkam0yEsghxAoVEeij")  # hand on Grove
_REPORT_MIN_INTERVAL = 60  # seconds between report attempts

def _grove_token():
    tok = os.environ.get("GROVE_TOKEN")
    if tok:
        return tok
    try:
        with open(os.path.expanduser("~/.grove-token")) as f:
            tok = f.read().strip()
        return tok or None
    except Exception:
        return None

def _report_grove(delta):
    """Fire-and-forget: POST incremental self_calls to Grove. Never raises."""
    def _worker():
        try:
            import urllib.request
            tok = _grove_token()
            if not tok or delta <= 0:
                return
            req = urllib.request.Request(
                f"https://beings.town/api/grove/{GROVE_KIT_ID}/heartbeat",
                data=json.dumps({"calls": delta}).encode(),
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                method="POST")
            urllib.request.urlopen(req, timeout=5).read()
            _mark_reported(delta)
        except Exception:
            pass  # health signal only — never block the tool path
    import threading
    threading.Thread(target=_worker, daemon=True).start()

def _load_hb():
    try:
        with open(HEARTBEAT_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _mark_reported(delta):
    hb = _load_hb()
    hb["reported"] = hb.get("reported", 0) + delta
    hb["last_reported_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump(hb, f)
    except Exception:
        pass

_last_report_attempt = [0.0]

def _bump():
    global _call_count
    _call_count += 1
    now = time.time()
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        hb = _load_hb()  # merge, don't clobber reported watermark
        hb.update({"calls": _call_count, "last_used_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "uptime_seconds": int(time.time() - _started_at)})
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump(hb, f)
    except: pass
    # Grove report: at most once per _REPORT_MIN_INTERVAL, delta since last ack
    if now - _last_report_attempt[0] >= _REPORT_MIN_INTERVAL:
        _last_report_attempt[0] = now
        hb = _load_hb()
        delta = _call_count - hb.get("reported", 0)
        if delta > 0:
            _report_grove(delta)

def _version():
    """Read the hand version from the package (single source of truth)."""
    try:
        from hand import __version__
        return __version__
    except Exception:
        return "unknown"
@mcp.tool()
def cdp_open(url: str) -> dict:
    from hand.router import route_open
    _bump()
    return route_open(url)
@mcp.tool()
def cdp_close() -> dict:
    """Close Chrome and verify it is gone.

    Browser.close needs no domain enable; issuing `Browser.enable` first raised
    (no such method) and the close was silently skipped — a fake-ok found by the
    L6 crash tests. The receipt is verified only when GET /json/version stops
    answering after the close."""
    _bump()
    import time as _t
    from hand.perception.cdp_launcher import chrome_running
    try:
        from hand.perception.cdp_core import list_pages, cdp_connect, cdp_call
        pages = list_pages()
        closed = 0
        for page in pages:
            ws = None
            try:
                ws = cdp_connect(page["webSocketDebuggerUrl"])
                cdp_call(ws, "Browser.close", {}, msg_id=1, timeout=5)
                closed += 1
            except Exception:
                pass
            finally:
                try:
                    if ws:
                        ws.close()
                except Exception:
                    pass
        deadline = _t.time() + 8
        while _t.time() < deadline and chrome_running():
            _t.sleep(0.4)
        gone = not chrome_running()
        out = {"closed": "ok" if gone else "partial", "pages_closed": closed,
               "endpoint_gone": gone, "verified": gone,
               "evidence": {"verified": gone, "endpoint_gone": gone,
                            "read_back": "GET /json/version after Browser.close"}}
        if not gone:
            out["evidence"]["reason"] = "endpoint still alive after Browser.close"
        return out
    except Exception as e:
        return {"closed": "partial", "error": str(e), "verified": False,
                "evidence": {"verified": False, "reason": str(e)}}
@mcp.tool()
def cdp_nav(url: str) -> dict:
    from hand.router import route_open
    _bump()
    return route_open(url)
@mcp.tool()
def cdp_see(kind: str = None) -> dict:
    """See the current page. Default (kind=a11y) is the accessibility tree:
    indented `role "name" (state) [idx]` lines where [idx] is a handle for
    cdp_click/cdp_type. kind=dom (visible text), kind=interactive (legacy
    element map with coordinates), kind=network, kind=vlm are explicit
    channels. The receipt carries verified/evidence and a `hint` when a
    collapsed menu hides part of the tree (click it, then see again)."""
    from hand.router import route_see
    _bump()
    return route_see(kind=kind)
@mcp.tool()
def cdp_click(selector: str) -> dict:
    """Click an element. `selector` accepts a CSS selector ('a.login'), an
    [idx] handle from cdp_see(kind=a11y) ('[93]'), 'text=...' or 'xy:X,Y'
    (physical pixels). Handle clicks re-read the element box at click time, so
    a handle whose node is gone comes back unverified with a reason instead of
    clicking a phantom."""
    from hand.router import route_do
    _bump()
    return route_do(selector)
@mcp.tool()
def cdp_type(text: str) -> dict:
    """Type text into the currently focused element (Input.insertText).
    Click the field first — including by [idx] handle: cdp_click('[93]'). The
    receipt verifies document.activeElement before typing; no focus → unverified
    with a reason. Retrying appends (idempotency: append)."""
    from hand.action.cdp_act import cdp_type_focused
    _bump()
    return cdp_type_focused(text)
@mcp.tool()
def cdp_scroll(direction: str, amount: int = None) -> dict:
    from hand.action.cdp_act import cdp_scroll as _cdp_scroll
    _bump()
    return _cdp_scroll(direction, amount=amount)
@mcp.tool()
def cdp_shot():
    from hand.router import route_screenshot
    _bump()
    result = route_screenshot(with_data=True)
    if result.get("data"):
        # Return as MCP ImageContent so the image reaches the model directly
        # (Heart provider layer maps tool-result image blocks -> image_url).
        # Note: result["data"] is already base64 — use ImageContent directly,
        # FastMCP Image would double-encode.
        from mcp.types import ImageContent
        meta = {k: v for k, v in result.items() if k != "data"}
        return [ImageContent(type="image",
                             data=result["data"],
                             mimeType=f"image/{result.get('format', 'png')}"),
                json.dumps(meta)]
    return result
@mcp.tool()
def hand_plan(goal: str, execute: bool = False) -> dict:
    from hand.router import route_plan
    _bump()
    return route_plan(goal)
@mcp.tool()
def hand_see_vlm(prompt: str = None, image_b64: str = None) -> dict:
    from hand.router import route_see_vlm
    _bump()
    return route_see_vlm(prompt=prompt, image_b64=image_b64)
@mcp.tool()
def health() -> dict:
    _bump()
    chrome_state = "unknown"
    try:
        from hand.perception.cdp_core import list_pages
        pages = list_pages()
        chrome_state = f"connected ({len(pages)} pages)" if pages else "no pages"
    except: chrome_state = "not reachable"
    return {"status": "alive", "uptime_seconds": int(time.time() - _started_at), "calls": _call_count, "chrome": chrome_state, "hand_version": _version()}
if __name__ == "__main__":
    mcp.run()
