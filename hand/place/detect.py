"""Place detection — figure out where I am and how to get somewhere.

Receipt contract (v6.11.0): `open_place` attaches an `evidence` dict to the
returned Place's `session_cache["open_evidence"]`, so `route_open` can say
*how* the open was verified instead of a bare `{"open": "ok"}`.
"""
import subprocess, sys, time
from urllib.parse import urlsplit
from hand.session import Place, get_session


_EVIDENCE_KEY = "open_evidence"


def _url_host(url: str) -> str:
    """Host of a URL, lowercased, or "" when unparseable."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _navigate_confirmed(target: str, ws=None, nav_error=None):
    """(confirmed, reason) — did the navigation actually land on `target`?

    Two independent facts are required:
      1. Page.navigate reported no errorText (net::ERR_NAME_NOT_RESOLVED, ...)
      2. the *live document* (Runtime.evaluate `location.href`) sits on the
         target host.

    Checking the /json page list alone is a false positive: Chrome keeps the
    requested URL (and the host as the title) in /json while the document is
    actually a `chrome-error://chromewebdata/` page. Found by dogfood on
    2026-09-21 — see tests/test_receipt_contract.py::
    test_error_page_is_not_confirmed_even_if_json_lists_target.
    """
    if nav_error:
        return False, f"Page.navigate errorText: {nav_error}"
    host = _url_host(target)
    if not host:
        return False, f"目标 URL 无法解析出 host: {target!r}"
    href = None
    if ws is not None:
        try:
            from hand.perception.cdp_core import cdp_call
            raw = cdp_call(ws, 'Runtime.evaluate',
                           {'expression': 'location.href', 'returnByValue': True},
                           msg_id=1)
            href = raw.get('result', {}).get('value')
        except Exception as e:
            href = None
            read_error = f"{type(e).__name__}: {e}"
        else:
            read_error = None
    else:
        read_error = "no CDP session to read the live document"
    if not href:
        if not read_error:
            read_error = "Runtime.evaluate 未返回 location.href"
        return False, (f"无法读取活文档 location.href（导航未证实）: {read_error}")
    if host in href.lower():
        return True, f"活文档 href={href} 命中目标 host {host}"
    return False, f"活文档 href={href} 未命中目标 host {host}（可能是错误页/重定向到别处）"


def _with_evidence(place: Place, evidence: dict) -> Place:
    place.session_cache[_EVIDENCE_KEY] = evidence
    return place


def get_open_evidence(place) -> dict:
    """Evidence attached by open_place (empty dict when absent)."""
    cache = getattr(place, "session_cache", None) or {}
    ev = cache.get(_EVIDENCE_KEY)
    return dict(ev) if isinstance(ev, dict) else {}


def _activate_evidence(target: str, error=None) -> dict:
    """Evidence for non-URL targets (app activation).

    The PRD's enum covers the browser path; non-URL opens get the same receipt
    shape with an explicit level so callers never read an unlabelled "ok".
    Activation is *issued* (osascript / `start`), not verified — there is no
    AX check in v6.11.0, so verified is always False on this path.
    """
    detail = ("已发出激活请求（未做 AX 复核，需要 cdp_see/see 才能确认前台）")
    if error:
        detail += f"；{error}"
    return {"level": "activate_issued", "detail": detail}


def _browser_place(target: str, navigate_confirmed: bool, reason=None) -> Place:
    """Browser Place + honest evidence level.

    navigate_confirmed=True  → level "navigate_confirmed" (path ①)
    otherwise                → level "endpoint_alive"     (path ② downgrade)
    `reason` says exactly which fact failed — the downgrade is never silent.
    """
    if navigate_confirmed:
        evidence = {
            "level": "navigate_confirmed",
            "detail": f"Page.navigate 无 errorText 且活文档命中目标 host: {reason}",
        }
    else:
        detail = "导航未证实，仅 CDP endpoint 存活"
        if reason:
            detail += f"；{reason}"
        evidence = {"level": "endpoint_alive", "detail": detail}
    try:
        from hand.perception.cdp_launcher import endpoint_info
        info = endpoint_info()
        version = (info or {}).get("Browser") or (info or {}).get("browser")
        if version:
            evidence["browser"] = version
    except Exception as e:
        # Optional enrichment only — record why it is missing, never swallow silently.
        evidence["browser_probe_error"] = f"{type(e).__name__}: {e}"
    return _with_evidence(Place(type="browser", identifier=target), evidence)


def detect_place() -> Place:
    """Detect the current foreground application."""
    if sys.platform == "win32":
        try:
            ps = (
                "powershell", "-NoProfile", "-Command",
                "Get-Process | Where-Object {$_.MainWindowTitle} | "
                "Select-Object -First 1 -ExpandProperty ProcessName",
            )
            result = subprocess.run(
                ps, capture_output=True, text=True, timeout=5
            )
            proc = result.stdout.strip().lower()
            if proc in ("chrome", "msedge", "firefox"):
                place_type = "browser"
            elif proc:
                place_type = "desktop_app"
            else:
                place_type = "unknown"
            return Place(type=place_type, identifier=proc or None)
        except Exception:
            return Place(type="unknown", identifier=None)

    try:
        script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        app_name = result.stdout.strip()
        if app_name in ("Google Chrome", "Safari", "Firefox", "Chromium"):
            place_type = "browser"
        elif app_name:
            place_type = "desktop_app"
        else:
            place_type = "unknown"
        return Place(type=place_type, identifier=app_name)
    except Exception:
        return Place(type="unknown", identifier=None)


def open_place(target: str) -> Place:
    """
    Open/activate a place.
    - URL: navigate via CDP (if Chrome debug port open), else fallback to 'open'
    - app name: AppleScript activate

    The returned Place carries `evidence` in `session_cache` ("navigate_confirmed"
    / "endpoint_alive" / "activate_issued"); `route_open` surfaces it in the receipt.
    """
    # ── URL → browser ───────────────────────────────────────────────
    if target.startswith("http://") or target.startswith("https://"):
        # Guarantee a CDP endpoint. On headless Linux this spawns Chrome.
        from hand.perception.cdp_launcher import ensure_chrome, chrome_running
        if not chrome_running():
            ensure_chrome()

        # Path ①: CDP navigate (reuse or create a tab), then *verify* it.
        nav_error = None
        try:
            from hand.perception.cdp_core import list_pages, resolve_page, cdp_connect, cdp_call, _init_domains
            pages = list_pages()
            if not pages:
                from hand.perception.cdp_launcher import open_new_tab
                open_new_tab(target)
                time.sleep(2)
                pages = list_pages()
            if pages:
                idx, page = resolve_page(None, pages)
                ws = cdp_connect(page['webSocketDebuggerUrl'])
                try:
                    _init_domains(ws, 'Page')
                    nav = cdp_call(ws, 'Page.navigate', {'url': target})
                    if isinstance(nav, dict) and nav.get('errorText'):
                        nav_error = nav['errorText']
                    time.sleep(1)
                    # Read the live document *before* dropping the session —
                    # /json alone cannot tell a landed page from an error page.
                    confirmed, reason = _navigate_confirmed(target, ws, nav_error)
                finally:
                    ws.close()
                return _browser_place(target, confirmed, reason)
        except Exception as e:
            # Path ② downgrade — never silent: the receipt must be able to say
            # "endpoint alive, navigation unproven" and name the exception.
            nav_error = f"{type(e).__name__}: {e}"

        # Only claim success when a CDP endpoint is actually alive.
        # Otherwise this was a previous fake success that corrupted downstream
        # routing state (every later cdp_* call would fail confusingly).
        if chrome_running():
            return _browser_place(target, False, nav_error)
        raise RuntimeError(
            f"cannot open {target}: no CDP endpoint and no browser binary — "
            "set $CHROME or install Chrome/Edge"
        )

    # ── App name ────────────────────────────────────────────────────
    if sys.platform == "win32":
        # Best-effort Windows activation via cmd `start` (AppleScript does not
        # exist here). Limited by design: detect_place then reports whichever
        # foreground app PowerShell can see.
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", target],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            pass
        time.sleep(0.5)
        place = detect_place()
        if place.type == "unknown":
            place = Place(type="desktop_app", identifier=target)
        return _with_evidence(place, _activate_evidence(target))

    try:
        script = f'tell application "{target}" to activate'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        time.sleep(0.5)
        place = detect_place()
        if place.type == "unknown":
            place = Place(type="desktop_app", identifier=target)
        return _with_evidence(place, _activate_evidence(target))
    except Exception:
        return _with_evidence(Place(type="unknown", identifier=target),
                              _activate_evidence(target, error="osascript failed"))