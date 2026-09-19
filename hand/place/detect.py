"""
Place detection — figure out where I am and how to get somewhere.
"""
import subprocess, time
from hand.session import Place, get_session


def detect_place() -> Place:
    """Detect the current foreground application."""
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
    """
    # ── URL → browser ───────────────────────────────────────────────
    if target.startswith("http://") or target.startswith("https://"):
        # Guarantee a CDP endpoint. On headless Linux this spawns Chrome.
        from hand.perception.cdp_launcher import ensure_chrome, chrome_running
        if not chrome_running():
            ensure_chrome()

        # Try CDP navigate (reuse or create a tab)
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
                _init_domains(ws, 'Page')
                cdp_call(ws, 'Page.navigate', {'url': target})
                ws.close()
                time.sleep(1)
                return Place(type="browser", identifier=target)
        except Exception:
            pass
        # Last resort: only claim success when a CDP endpoint is actually alive.
        # Otherwise this was a previous fake success that corrupted downstream
        # routing state (every later cdp_* call would fail confusingly).
        if chrome_running():
            return Place(type="browser", identifier=target)
        raise RuntimeError(
            f"cannot open {target}: no CDP endpoint and no browser binary — "
            "set $CHROME or install Chrome/Edge"
        )

    # ── App name ────────────────────────────────────────────────────
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
        return place
    except Exception:
        return Place(type="unknown", identifier=target)