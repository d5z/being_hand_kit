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
        with open(HEARTBEAT_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}

def _mark_reported(delta):
    hb = _load_hb()
    hb["reported"] = hb.get("reported", 0) + delta
    hb["last_reported_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
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
        # calls_total must survive process restarts. The kit is lazily spawned,
        # so the in-process counter resets to 0 while the persisted "reported"
        # watermark keeps growing: delta = 0 - reported goes negative after the
        # first report and the reporter silently stops for good (observed on
        # hand 09-22 and prime 09-01 with the same shape). First run after this
        # fix inherits "reported" so history is never double-counted.
        if "calls_total" not in hb:
            hb["calls_total"] = int(hb.get("reported", 0))
        hb["calls_total"] = int(hb["calls_total"]) + 1
        hb.update({"calls": _call_count, "last_used_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "uptime_seconds": int(time.time() - _started_at)})
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            json.dump(hb, f)
    except: pass
    # Grove report: at most once per _REPORT_MIN_INTERVAL, delta since last ack
    if now - _last_report_attempt[0] >= _REPORT_MIN_INTERVAL:
        _last_report_attempt[0] = now
        hb = _load_hb()
        delta = int(hb.get("calls_total", 0)) - int(hb.get("reported", 0))
        if delta > 0:
            _report_grove(delta)

def _version():
    """Read the hand version from the package (single source of truth)."""
    try:
        from hand import __version__
        return __version__
    except Exception:
        return "unknown"

def _manifest_version(base=None):
    """What the installer / router believes this kit is.

    The package literal answers "what am I now"; the manifest answers
    "what am I taken to be". Nothing keeps the two equal (a bump that
    touches one and not the other still parses, imports, and reports
    green), so health names both and flags the fork instead of picking
    one and staying silent.

    Only a *sibling* manifest counts. Both real layouts put the manifest
    beside the server (deployed kit: ./manifest.json; repo: kit/ beside
    kit/mcp_server.py), so walking up the tree buys nothing and costs
    correctness: 2026-10-26 a stray /tmp/manifest.json ("hand 6.9.0",
    left by a publish fixture) was one directory above a temp probe and
    would have been reported as this kit's installed version.
    """
    import json, pathlib
    here = pathlib.Path(base) if base else pathlib.Path(__file__).resolve().parent
    try:
        return json.loads((here / "manifest.json").read_text()).get("version", "unknown")
    except Exception:
        return "absent"



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
    collapsed menu hides part of the tree (click it, then see again). The
    a11y receipt also carries `nav_id` (navigation anchor) — click/type
    compare it against the page's current anchor and warn `STALE_WARNING`
    in evidence when the page navigated since the snapshot."""
    from hand.router import route_see
    _bump()
    return route_see(kind=kind)
@mcp.tool()
def cdp_click(selector: str, verify: bool = True) -> dict:
    """Click an element. `selector` accepts a CSS selector ('a.login'), an
    [idx] handle from cdp_see(kind=a11y) ('[93]'), 'text=...' or 'xy:X,Y'
    (physical pixels). Handle clicks re-read the element box at click time, so
    a handle whose node is gone comes back unverified with a reason instead of
    clicking a phantom. A non-interactive node that wraps exactly one
    interactive descendant (e.g. a heading around a link) redirects the click
    onto it — the receipt says `redirected: true` with the target. Every
    coordinate dispatch verifies the elementFromPoint hit chain contains the
    target and grid-scans the box when the centre misses (multi-line inline
    elements); a fully covered element fails loudly. `evidence.click_point`
    names how the point was chosen ('center', 'grid_scan',
    'redirect_target_clickable_point').

    0.12 — `effected` is judged, not deferred. With verify=True (default)
    hand reads the world on two channels — `pixel` (a frame before and after,
    diffed in a +/-60px box around the dispatched point) and `document` (the
    a11y tree as text, plus URL and title, which is also the only one of the
    two that reaches inside child frames). `change.channels` carries each
    channel's own verdict and a `blind_to` line saying what that channel
    cannot see; pixel is blind to title/URL/aria state (they never become
    ink), document is blind to colour, position and repaint. `effected` is
    'changed' if either channel saw something, 'no_change' only when both
    looked and saw nothing, and 'unknown' when the silent one could not look
    — a blind channel's silence is never reported as a negative. `change`
    also carries the region, ratio and bbox, plus `whole_frame` and
    `changed_outside_region` when the world moved somewhere other than where
    you clicked. verify=False reproduces the 0.11 receipt exactly, with no
    extra captures."""
    from hand.router import route_do
    from hand.action.effect import probe_action
    _bump()
    return probe_action('click', lambda: route_do(selector), verify=verify)
@mcp.tool()
def cdp_type(text: str) -> dict:
    """Type text into the currently focused element. Click the field first —
    including by [idx] handle: cdp_click('[93]'). The receipt verifies
    document.activeElement before typing; no focus → unverified with a
    reason. Retrying appends (idempotency: append). Text ending in a
    newline submits like a real Enter key (keyboard event), not
    insertText — the receipt's `enter_mode` says which path ran; sites that
    listen for keydown submit only on the keyboard path. This tool types
    its argument literally — to type into an [idx] handle without a
    separate click, pass '[93]|text' to cdp_click (the do router parses
    the pipe form and focuses the handle's element first)."""
    from hand.action.cdp_act import cdp_type_focused
    _bump()
    return cdp_type_focused(text)
@mcp.tool()
def cdp_drag(from_spec: str, to_spec: str, steps: int = 10, interval_ms: int = 16,
             verify: bool = True) -> dict:
    """Drag from one point to another: mousePressed -> N x mouseMoved -> mouseReleased.

    This is what makes canvas surfaces reachable at all — a 3D viewport, a
    whiteboard, a slider. A click cannot create a shape; a drag can.

    `from_spec` / `to_spec` each accept 'xy:X,Y' (physical pixels), an [idx]
    handle from cdp_see(kind=a11y), or a CSS selector. `steps` is how many
    intermediate mouseMoved events the path is cut into (more = smoother for
    apps that sample motion), `interval_ms` the gap between them.

    The receipt carries three separate facts: `resolved` (both endpoints
    found), `landed` (elementFromPoint at the start point is the claimed
    element), and `effected` — which 0.12 judges instead of deferring. With
    verify=True (default) hand reads two channels: `pixel` (a frame before and
    after, diffed over the rectangle spanned by the two endpoints, +24px
    padding) and `document` (a11y tree / URL / title, the only one that sees
    inside child frames). `change.channels` names each channel's verdict and
    what it is blind to; `effected` is 'changed' if either saw something,
    'no_change' only if both looked and saw nothing, 'unknown' when the silent
    one could not look. Both pixel frames are anchored in evidence
    (`frame_before` / `frame_after`: scrollX, scrollY, viewport, dpr) so a
    later reader can tell whether the page moved underneath the coordinates.
    """
    from hand.action.cdp_act import cdp_drag as _cdp_drag
    from hand.action.effect import probe_action
    _bump()
    return probe_action(
        'drag',
        lambda: _cdp_drag(from_spec, to_spec, steps=steps,
                          interval_ms=interval_ms),
        verify=verify)


@mcp.tool()
def cdp_key(keys: str, verify: bool = True) -> dict:
    """Press a key combination: modifiers down, main key down/up, modifiers up.

    'Control+z', 'Meta+Shift+t', 'Enter', 'Escape', 'ArrowLeft', 'Space'.
    Modifier order in the string does not matter — the dispatched modifier
    bitmask (Alt=1 / Ctrl=2 / Meta=4 / Shift=8) is what counts.

    Use this where cdp_type cannot go: undo, save, switch tabs, and the entire
    keyboard vocabulary of application-driven UIs (Blender's G/R/S + X/Y/Z +
    digits). cdp_type inserts text; this dispatches real key events.

    The receipt reports `resolved` (the combo parsed), `landed` (true only
    when document.activeElement changed — otherwise null, meaning "could not
    tell") and `effected`, which 0.12 judges by diffing the whole frame
    around the press (a key has no focus element to scope to by default).
    Undo, delete, tool switching all land somewhere — if the frame did not
    move, the key very likely did not either. `change.region` says whether
    the diff was scoped or whole-frame; verify=False skips the captures.
    """
    from hand.action.cdp_act import cdp_key as _cdp_key
    from hand.action.effect import probe_action
    _bump()
    return probe_action('key', lambda: _cdp_key(keys), verify=verify)


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
def hand_eye_check(op: str = "challenge", challenge_id: str = None,
                   answer: str = None, chars: int = None,
                   font_px: int = None, ttl_s: int = None) -> dict:
    """Self-proof that a rendered frame actually reached you (hand 0.10 D4).

    The other acceptance layers verify whether the *tool* behaved correctly.
    This one verifies whether the *perception* arrived — a question only the
    being whose context the pixels land in can answer.

    op=challenge: draws a random string on a fresh canvas page and returns
    {challenge_id, place, expires_at}. The string is NOT in the receipt, NOT in
    the DOM (no text node), NOT in the page title, and NOT in the HTML source
    (it is injected after load). Read it off the image.
    op=verify: pass answer=<what you read>; single use, destroyed either way.
    op=list: active challenge ids only.

    A pass means the pixels reached you and you read them. A failure is data,
    not a bug report — on a substrate without vision this must fail, otherwise
    the whole exercise is theatre. Ambiguous glyphs (O/0/I/1/L) are excluded
    from the alphabet on purpose: this measures delivery, not legibility.
    """
    from hand.router import route_eye_check
    _bump()
    return route_eye_check(op=op, challenge_id=challenge_id, answer=answer,
                           chars=chars, font_px=font_px, ttl_s=ttl_s)
@mcp.tool()
def hand_see_vlm(prompt: str = None, image_b64: str = None) -> dict:
    from hand.router import route_see_vlm
    _bump()
    return route_see_vlm(prompt=prompt, image_b64=image_b64)
@mcp.tool()
def hand_see_ocr(query: str = None) -> dict:
    """Read exact on-screen text via Apple Vision OCR (zh-Hans/zh-Hant/en/ja).
    Complementary to hand_see_vlm (VLM describes what-is-this) — this reads
    what-does-it-say. Pass query to locate a specific string: returns
    matching lines with pixel coordinates (x/y/w/h/center_x/center_y)
    for subsequent clicking.
    """
    _bump()
    if query is not None:
        from hand.perception.vision_ocr import find_text
        return find_text(query)
    from hand.perception.vision_ocr import vision_ocr_see
    return vision_ocr_see()
@mcp.tool()
def health() -> dict:
    _bump()
    chrome_state = "unknown"
    try:
        from hand.perception.cdp_core import list_pages
        pages = list_pages()
        chrome_state = f"connected ({len(pages)} pages)" if pages else "no pages"
    except: chrome_state = "not reachable"
    pkg_v, man_v = _version(), _manifest_version()
    out = {"status": "alive", "uptime_seconds": int(time.time() - _started_at), "calls": _call_count,
           "chrome": chrome_state, "hand_version": pkg_v, "manifest_version": man_v}
    if man_v not in ("absent", "unknown") and man_v != pkg_v:
        out["version_fork"] = {
            "package": pkg_v, "manifest": man_v,
            "detail": "package literal and manifest disagree: 'what I am now' is not 'what I am taken to be'",
        }
    return out
if __name__ == "__main__":
    mcp.run()
