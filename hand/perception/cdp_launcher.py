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

Spawn strategy (0.7.0 F7): isolated `--user-data-dir` by default (never fights
the human's Chrome for the profile lock); HAND_PROFILE=persistent and
HAND_HEADLESS=0 are explicit opt-ins. See the profile-strategy block below.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import json

CDP_PORT = int(os.environ.get("HAND_CDP_PORT", "9222"))
CDP_HOST = f"http://localhost:{CDP_PORT}"

# LOCAL PATCH 2026-09-25 (haitian-mac, reported to #34): on macOS with a
# system-level proxy (scutil --proxy), urllib's default opener routes loopback
# CDP traffic through the proxy -> HTTP 502, even though the proxy's own
# ExceptionsList covers localhost. CDP_HOST is always loopback: never proxy it.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

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
        with _NO_PROXY_OPENER.open(f"{CDP_HOST}/json/version", timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def chrome_running() -> bool:
    """Is a CDP endpoint already answering on 9222?"""
    return endpoint_info() is not None


# ── Profile / headless strategy (0.7.0 F7) ──────────────────────────
# Default = ISOLATED: the kit spawns with its own user-data-dir under the kit
# home, so it can never collide with the human's running Chrome (profile lock)
# and never touches the human's cookies/sessions. The directory is *kept*
# between runs — isolated from the human, not wiped — so logins survive a kit
# restart (F7 acceptance step 5).
#
# taojun 954 (Windows Feishu) is the opposite need: headless fingerprint
# throttling cleared up with a headed browser + persistent profile. So both
# knobs are explicit opt-ins rather than one hard-coded default:
#   HAND_PROFILE=isolated (default) | persistent
#   HAND_PROFILE_DIR=<path>            explicit dir for either mode
#   HAND_HEADLESS=1 (default) | 0     0 → headed window
HAND_PROFILE_ENV = "HAND_PROFILE"
HAND_PROFILE_DIR_ENV = "HAND_PROFILE_DIR"
HAND_HEADLESS_ENV = "HAND_HEADLESS"
PROFILE_DIR_NAME = ".chrome-profile"

_FALSEY = ("0", "false", "no", "off")

# Repo root / bundle root (the directory holding hand/ — and kit/ in the dev tree).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _kit_dir() -> str:
    """The kit home: <root>/kit in the dev tree, <root> in a Grove bundle."""
    kit = os.path.join(_ROOT, "kit")
    return kit if os.path.isdir(kit) else _ROOT


def _platform_user_data_dir() -> str:
    """The human's real Chrome profile dir (persistent mode)."""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "Google", "Chrome", "User Data")
    return os.path.expanduser("~/.config/google-chrome")


def profile_mode() -> str:
    """'isolated' (default) or 'persistent' (explicit opt-in)."""
    mode = (os.environ.get(HAND_PROFILE_ENV) or "isolated").strip().lower()
    return "persistent" if mode == "persistent" else "isolated"


def profile_dir() -> str:
    """user-data-dir for the next spawn (HAND_PROFILE_DIR wins if set)."""
    explicit = (os.environ.get(HAND_PROFILE_DIR_ENV) or "").strip()
    if explicit:
        return explicit
    if profile_mode() == "persistent":
        return _platform_user_data_dir()
    return os.path.join(_kit_dir(), PROFILE_DIR_NAME)


def headless() -> bool:
    return (os.environ.get(HAND_HEADLESS_ENV) or "").strip().lower() not in _FALSEY


def _chrome_flags() -> list:
    """Flags for the spawn. The profile dir is created here (first run)."""
    profile = profile_dir()
    try:
        os.makedirs(profile, exist_ok=True)
    except OSError:
        pass  # best effort: Chrome creates it too; a failure must not block spawn
    flags = [
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
    ]
    if headless():
        flags.append("--headless")
    flags += [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-software-rasterizer",
        "--disable-extensions",
    ]
    return flags


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

    flags = _chrome_flags()
    proc = subprocess.Popen(
        [chrome] + flags,
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
            # F7 acceptance protocol step 4: the spawn carries its own flags, so
            # `ps` (or the receipt) can prove --user-data-dir was in the argv.
            proc.cdp_flags = flags
            proc.cdp_profile = {"dir": profile_dir(), "mode": profile_mode(),
                                "headless": headless(), "binary": chrome}
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
    with _NO_PROXY_OPENER.open(req, timeout=10) as resp:
        return json.loads(resp.read().decode())
