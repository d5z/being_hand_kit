"""
CDP Launcher — spawn headless Chrome/Chromium for CDP.

The rest of the perception stack (cdp_core, cdp_snapshot, cdp_act) only
*connects* to localhost:9222. This module owns the other half of the
contract: making sure a browser is actually there to connect to.

Why this exists as a separate module:
  - macOS: a human normally has Chrome/Safari open; CDP is optional.
  - Linux (headless server): nothing is there until *we* launch it.
  - The old deployed kit hid this in an async server.py that never made
    it into git. This is the honest, router-accessible version.

Resolution order for the browser binary:
  1. $CHROME env var (explicit override, e.g. from kit/start.sh)
  2. Windows (<win32 only>): Chrome install paths → PATH chrome.exe/msedge.exe → Edge install paths
  2b. macOS (<darwin only>): /Applications Chrome → Chromium → Canary → Edge → ~/Applications
  3. Playwright cache (~/.cache/ms-playwright/...), headless-shell first
  4. System chrome/chromium on PATH
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import json

CDP_PORT = 9222
CDP_HOST = f"http://localhost:{CDP_PORT}"

# Library dir for bundled Linux .so deps (libasound, libatk, ...).
# Playwright's headless shell links against these but doesn't ship them.
# The kit bundles them under lib/; start.sh sets LD_LIBRARY_PATH.
_LIB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "lib",
)


def _find_chrome() -> str | None:
    """Locate a runnable chrome/chromium/headless-shell binary."""
    # 1. Explicit env override
    env = os.environ.get("CHROME", "").strip()
    if env and os.path.exists(env):
        return env

    # 1b. Windows: standard install paths → PATH chrome.exe/msedge.exe → Edge install paths.
    # Edge is a stock-Chromium fallback present on every Windows box.
    if sys.platform == "win32":
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in chrome_paths:
            if os.path.isfile(p):
                return p

        for name in ("chrome.exe", "msedge.exe"):
            p = shutil.which(name)
            if p:
                return p

        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for p in edge_paths:
            if os.path.isfile(p):
                return p
        return None

    # 1c. macOS: standard install locations (F8). Checked *before* the Playwright
    # cache so a human-installed Chrome wins on a Mac — the same reasoning as the
    # Windows chain above. The path Cotton's wrapper hard-coded (935) is now part
    # of the regular discovery chain instead of a separate script.
    if sys.platform == "darwin":
        mac_candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        for p in mac_candidates:
            if os.path.isfile(p):
                return p

    # 2. Playwright cache (headless-shell preferred: lighter, no X deps)
    cache = os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")
    if os.path.isdir(cache):
        entries = sorted(os.listdir(cache), reverse=True)
        for d in entries:
            if "headless_shell" in d:
                p = os.path.join(
                    cache, d, "chrome-headless-shell-linux64",
                    "chrome-headless-shell",
                )
                if os.path.exists(p):
                    return p
        for d in entries:
            if d.startswith("chromium"):
                p = os.path.join(cache, d, "chrome-linux64", "chrome")
                if os.path.exists(p):
                    return p

    # 3. System chrome/chromium
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


# ── Endpoint probe (v6.11.0 receipt contract) ───────────────────────
# Spawn success ≠ endpoint alive: a chrome that dies on a missing .so leaves
# Popen() returning happily. Every "is it up?" question goes through
# endpoint_info() and is answered by /json/version, never by Popen's exit code.
CDP_PROBE_INTERVAL = 0.5   # seconds between /json/version probes
CDP_PROBE_TIMEOUT = 6.0    # seconds of patience after spawn


def endpoint_info(timeout: float = 2):
    """GET /json/version → dict (browser version, protocol) or None.

    Contract: never raises. None means "endpoint not answering" — callers must
    treat that as evidence level "endpoint_alive"-or-worse, not as success.
    """
    try:
        with urllib.request.urlopen(f"{CDP_HOST}/json/version", timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def chrome_running() -> bool:
    """Is a CDP endpoint already answering on 9222?"""
    return endpoint_info() is not None


def _chrome_flags() -> list:
    return [
        f"--remote-debugging-port={CDP_PORT}",
        "--headless",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-software-rasterizer",
        "--disable-extensions",
    ]


def ensure_chrome(url: str = "about:blank") -> subprocess.Popen | None:
    """
    Guarantee a CDP endpoint on localhost:9222.

    Returns the Popen handle if we launched it (with `.cdp_endpoint` holding the
    probed /json/version payload), None if it was already running. Raises
    RuntimeError if no browser binary can be found, or if the spawned browser
    never became reachable — a spawned-but-dead Chrome is *not* silently
    reported as a live endpoint (PRD F-2 / S2).
    """
    if chrome_running():
        return None

    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError(
            "no chrome binary found — set $CHROME or install playwright chromium"
        )

    env = dict(os.environ)
    # Bundle bundled .so deps first if they exist (Linux headless).
    if os.path.isdir(_LIB_DIR):
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{_LIB_DIR}:{existing}" if existing else _LIB_DIR
        )

    proc = subprocess.Popen(
        [chrome] + _chrome_flags(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    # Probe /json/version until it answers (bounded) — the spawn itself proves
    # nothing, so we only return once the endpoint has actually spoken.
    deadline = time.time() + CDP_PROBE_TIMEOUT
    while time.time() < deadline:
        info = endpoint_info()
        if info:
            proc.cdp_endpoint = {
                "url": CDP_HOST,
                "browser": info.get("Browser") or info.get("browser"),
                "protocol": info.get("Protocol-Version"),
            }
            return proc
        time.sleep(CDP_PROBE_INTERVAL)

    # It didn't come up — don't leave a zombie behind.
    kill_error = None
    try:
        proc.kill()
    except Exception as e:
        kill_error = f"{type(e).__name__}: {e}"

    msg = (
        f"Chrome spawned but CDP endpoint never became reachable at {CDP_HOST} "
        f"within {CDP_PROBE_TIMEOUT}s (probe interval {CDP_PROBE_INTERVAL}s)"
    )
    if kill_error:
        msg += f"; additionally kill() failed: {kill_error}"
    raise RuntimeError(msg)


def open_new_tab(url: str) -> dict:
    """Open a new tab via the CDP /json/new endpoint. Returns page dict."""
    req = urllib.request.Request(
        f"{CDP_HOST}/json/new?{urllib.request.quote(url)}",
        method="PUT",
        data=b"",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())
