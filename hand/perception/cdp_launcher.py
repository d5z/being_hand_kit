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
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import json

CDP_PORT = int(os.environ.get("HAND_CDP_PORT", "9222"))
CDP_HOST = f"http://127.0.0.1:{CDP_PORT}"

# 2026-10-20 (root cause from Judy's Windows 实测, D5-NJ-DT-0067): 必须是
# 127.0.0.1 字面量, 不能写 localhost。Windows 上 localhost 的 getaddrinfo
# 同时返回 AF_INET/AF_INET6, TCP 栈先试 ::1; Chrome 调试端口只监听
# 127.0.0.1, ::1 的拒绝要约 2s 才返回再回退 IPv4。单次截图付两遍这笔
# (list_pages + ws 握手) => 4.2s/帧, 真正抓帧只有 30ms。改为字面量后
# 4203ms -> 123ms。Linux 上 localhost 只回 127.0.0.1, 所以此病在 Linux
# 完全隐形, 别把它"优化"回去。

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


# ── Ownership of the browser on the debug port ──────────────────────────────
# 2026-10-26: "I am connected to it" is not "I started it". A close that only
# talks to whatever answers on :9222 will happily take down a browser somebody
# else started (a 166-day orphan on this machine, killed by a teardown that
# believed it was closing its own). The property "whose is this" cannot be read
# back off the process table afterwards — ppid is 1 for everything that outlived
# its parent — so it has to be written down at the moment of the spawn.
#
# The record is written by ensure_chrome() when *we* launch, and read by close
# before it dispatches Browser.close. A close with no record, or with a record
# whose pid/start-time no longer describes a live process, refuses to kill and
# says so in the receipt instead of guessing.

OWNER_FILE = os.path.join(os.path.expanduser("~"), ".hand-cdp-owner.json")


def _owner_file():
    """HAND_CDP_OWNER_FILE lets a test keep its own record (same reason
    HAND_CDP_STATE_FILE exists: a hermetic test must not answer to the dev
    machine's real spawn history)."""
    return os.environ.get("HAND_CDP_OWNER_FILE") or OWNER_FILE


def _proc_start_ticks(pid):
    """Process start time in clock ticks since boot (Linux), else None.

    pid alone is recyclable; pid + start time is not. macOS has no /proc, so
    there the identity degrades to pid-only and the record says so."""
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as f:
            raw = f.read()
        # comm may contain spaces/parens: split after the last ')'
        return int(raw.rsplit(")", 1)[1].split()[19])
    except Exception:
        return None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _proc_cmdline(pid):
    """argv of a live process, or None when it cannot be read.

    Linux: /proc/<pid>/cmdline. Elsewhere: ps. None means "no evidence either
    way" — never "it isn't ours"."""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            raw = f.read()
        parts = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
        if parts:
            return parts
    except Exception:
        pass
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))],
                             capture_output=True, text=True, timeout=5)
        line = (out.stdout or "").strip()
        return line.split() if line else None
    except Exception:
        return None


def _listener_pid(port=None, timeout=5.0):
    """The pid actually LISTENING on `port` — the process that owns the endpoint.

    Why the Popen pid is not good enough: Chrome re-execs. Measured 2026-10-27 by
    Neuromancer (macOS, hand 0.13.5): the pid `Popen` returned was alive when the
    record was written and gone seconds later — the port was held by a different
    pid, and the launcher had exited and been reparented. A record built on that
    pid describes a process that no longer exists, so every later check answers
    "not mine" about our own browser and close refuses, leaving a browser nobody
    can close.

    Returns `(pid, how)` with `how` in {'ss', 'lsof', None}. `(None, None)` means
    "could not find out" — never "nobody is listening".
    """
    port = CDP_PORT if port is None else port
    deadline = time.time() + max(0.0, timeout)
    while True:
        # Linux: iproute2's ss. macOS has no ss but ships lsof. Both are asked
        # rather than dispatching on sys.platform: a Linux box with lsof and no
        # iproute2 is real, and so is the reverse in a container.
        for cmd, how, pat in (
            (["ss", "-lptnH", f"sport = :{port}"], "ss", r"pid=(\d+)"),
            (["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], "lsof",
             r"^(\d+)$"),
        ):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=5)
            except Exception:
                # A probe that cannot run is "could not find out", never a
                # reason to fail the spawn that just succeeded.
                continue
            for line in (out.stdout or "").splitlines():
                m = re.search(pat, line.strip())
                if m:
                    return int(m.group(1)), how
        if time.time() >= deadline:
            return None, None
        time.sleep(0.2)


def _cmdline_has(pid, needle):
    """True/False when the argv was readable, None when it was not.

    None is "no evidence either way" (macOS: another user's process), and the
    callers must not turn it into a yes or a no."""
    if not needle:
        return None
    cmd = _proc_cmdline(pid)
    if cmd is None:
        return None
    return any(str(needle) in a for a in cmd)


CLAIM_TIMEOUT = 2.0     # seconds to find the listener of a port we just heard


def _claim_listener(profile, timeout=None):
    """(pid, how, profile_match) for the process serving our port, or None.

    The listener is accepted only when its argv names *this install's* profile
    directory: the port is shared by every hand install on the machine, so the
    profile — not the port, and not the pid we spawned — is what says "ours".

    `profile_match is None` means the argv could not be read (unreadable
    process); the caller decides whether that is enough, and the record says so.
    """
    pid, how = _listener_pid(timeout=CLAIM_TIMEOUT if timeout is None else timeout)
    if not pid:
        return None
    return pid, how, _cmdline_has(pid, profile)


def record_owner(proc, binary=None, claim_listener=True):
    """Write the spawn record: who started the browser on this port, and when.

    Deliberately a separate file from the session-page state: losing the page
    record must not lose the ownership fact.

    The pid recorded is the *listener's* (0.13.8), not `Popen`'s. When the
    listener cannot be found or its argv does not name our profile, the spawn
    pid is kept and `pid_source` says which one it is — a record that says
    "spawn pid, unverified listener" is honest; one that silently claims the
    spawn pid is the browser is the lie this field exists to prevent.
    """
    try:
        prof = profile_dir()
    except Exception:
        prof = None
    spawn_pid = getattr(proc, "pid", None)
    pid, pid_source, listener_via, match = spawn_pid, "spawn", None, None
    if claim_listener:
        claim = _claim_listener(prof)
        if claim:
            lid, listener_via, match = claim
            if match is not False:      # True, or unreadable
                pid, pid_source = lid, "listener"
    rec = {
        "pid": pid,
        "start_ticks": _proc_start_ticks(pid),
        "spawn_pid": spawn_pid,
        "pid_source": pid_source,
        "listener_via": listener_via,
        "listener_profile_match": match,
        "cwd": os.getcwd(),
        "binary": binary,
        "profile": prof,
        "port": CDP_PORT,
        "spawned_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        with open(_owner_file(), "w", encoding="utf-8") as f:
            json.dump(rec, f)
    except Exception:
        pass
    return rec


def read_owner():
    try:
        with open(_owner_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_owner():
    try:
        os.unlink(_owner_file())
    except Exception:
        pass


def _reclaim_by_profile(rec):
    """(pid, how, why) — why says what happened when nothing could be claimed.

    This is the Chrome re-exec case: the browser we started is still serving the
    port, under a pid different from the one we recorded. Identity here is
    (port + profile directory), which survives the re-exec; the recorded pid is
    a clue about the birth, not the identity. A listener whose argv names a
    *different* profile is not accepted — that is another install's browser and
    calling it "mine" is the wrongful kill this whole module exists to prevent.

    The three ways of *not* claiming are deliberately not one answer (2026-10-27,
    after Neuromancer's pid-1 sample: `proc_pidinfo(1)` is EPERM while `ps` sees
    it, so "in/out" alone would read a live process as gone):
      'no-profile'        the record does not even name a profile
      'no-listener'       nothing answers the port — positive evidence of absence
      'unreadable'        someone listens, but the argv could not be read — no
                          evidence either way; must not be reported as a stranger
      'other-profile'     someone listens and is demonstrably not ours
    """
    prof = (rec or {}).get("profile")
    if not prof:
        return None, None, "no-profile"
    pid, how = _listener_pid(timeout=1.0)
    if not pid:
        return None, None, "no-listener"
    match = _cmdline_has(pid, prof)
    if match is None:
        return None, how, "unreadable"
    if match is False:
        return None, how, "other-profile"
    return pid, how, None


def owner_status():
    """Who owns the browser the endpoint is answering for?

    'mine'      this install spawned it and the process still matches
    'stranger'  a record exists but its process is gone or is a different one
                (pid recycled, or the browser we started has died)
    'unknown'   no record at all — we never recorded a spawn here

    0.13.8: "the recorded pid is gone" is no longer the end of the question.
    Chrome re-execs on macOS (Neuromancer, 2026-10-27), so the pid we recorded
    at birth routinely dies while the same browser keeps serving the port. The
    browser's identity is the port + its profile directory; when the listener
    carries our recorded profile, the answer is still 'mine' and the receipt
    says the pid came from the listener rather than the record.
    """
    rec = read_owner()
    if not rec:
        return {"owner": "unknown", "record": None,
                "reason": "no spawn record"}
    pid = rec.get("pid")
    alive = _pid_alive(pid) if pid else False
    if not alive:
        claim_pid, claim_how, why = _reclaim_by_profile(rec)
        if claim_pid:
            return {"owner": "mine", "record": rec, "pid_alive": True,
                    "pid_source": "listener", "listener_via": claim_how,
                    "listener_pid": claim_pid,
                    "reason": ("recorded pid is gone; the listener on this "
                               "port carries this record's profile (browser "
                               "re-exec, not a stranger)")}
        if why == "unreadable":
            # 0.13.8: "could not find out" is not "it is someone else's".
            # Reporting a stranger here would be evidence we do not have; the
            # close path refuses either way, but the receipt must not claim
            # knowledge it lacks.
            return {"owner": "unknown", "record": rec, "pid_alive": False,
                    "pid_source": "listener", "listener_via": claim_how,
                    "reason": ("recorded pid is gone and the listener's argv "
                               "could not be read — no evidence either way")}
        return {"owner": "stranger", "record": rec, "pid_alive": False,
                "reason": ("recorded process is not alive and no listener on "
                           "this port carries this record's profile"
                           if why != "no-listener" else
                           "recorded process is not alive; nothing is "
                           "listening on this port")}
    now_ticks = _proc_start_ticks(pid)
    recorded = rec.get("start_ticks")
    if recorded is not None and now_ticks is not None and now_ticks != recorded:
        claim_pid, claim_how, _why = _reclaim_by_profile(rec)
        if claim_pid:
            return {"owner": "mine", "record": rec, "pid_alive": True,
                    "pid_source": "listener", "listener_via": claim_how,
                    "listener_pid": claim_pid, "start_ticks_now": now_ticks,
                    "reason": ("recorded pid was recycled; the listener on this "
                               "port carries this record's profile")}
        return {"owner": "stranger", "record": rec, "pid_alive": True,
                "start_ticks_now": now_ticks,
                "reason": "pid was recycled (start time differs)"}
    # A live pid with matching start time still has to be a browser *serving
    # this port* — otherwise "a process we started" would be enough to justify
    # killing whatever answers on :9222, which is the mistake this module exists
    # to prevent. Unreadable argv is no evidence either way (macOS other-user
    # processes): say so instead of pretending it was checked.
    cmd = _proc_cmdline(pid)
    flag = f"--remote-debugging-port={CDP_PORT}"
    if cmd is not None and not any(flag in a for a in cmd):
        return {"owner": "stranger", "record": rec, "pid_alive": True,
                "cmdline_checked": True,
                "reason": f"pid {pid} is alive but is not serving {flag}"}
    return {"owner": "mine", "record": rec, "pid_alive": True,
            "start_ticks_now": now_ticks,
            "cmdline_checked": cmd is not None}


def close_refusal(status):
    """The receipt a close returns when it declines to kill someone else's browser."""
    return {
        "closed": "refused",
        "endpoint_gone": False,
        "verified": False,
        "owner": status.get("owner"),
        "evidence": {
            "verified": False,
            "refused": True,
            "owner": status,
            "reason": ("the endpoint on this port is not a browser this install "
                       "spawned; refusing to close it. Pass force=true only if "
                       "you know whose it is."),
        },
    }


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
        if sys.platform == "win32":
            # The Windows chain (install paths + PATH) never reads the Playwright
            # cache: headless-shell on Windows is the old-headless pipeline behind
            # the cdp_shot timeout family (bonfire #2299 five-cell matrix).
            # "install playwright chromium" would point Windows users straight at
            # that dead end — the honest direction on Windows is Chrome/Edge.
            raise RuntimeError(
                "no chrome binary found on Windows — set $CHROME to chrome.exe / "
                "msedge.exe, or install Chrome/Edge (the Windows chain checks "
                "install paths and PATH only; it deliberately skips the "
                "Playwright cache)"
            )
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
            # Ownership is written at birth, not inferred later (0.13.7): the
            # receipt for a later close can only say "mine" if something said
            # so at the moment of the spawn.
            proc.cdp_owner = record_owner(proc, chrome)
            # 0.13: a fresh browser instance invalidates the recorded session
            # page — target ids belong to the old process. Clearing the record
            # is what keeps the next resolve on the "no session page yet" path
            # instead of raising "the page you were on is gone", which would be
            # true but useless right after we ourselves restarted the browser.
            try:
                from hand.perception.cdp_core import _clear_last
                _clear_last()
            except Exception:
                pass
            return proc
        time.sleep(CDP_PROBE_INTERVAL)

    # It didn't come up — don't leave a zombie behind.
    kill_error = None
    try:
        proc.kill()
    except Exception as e:
        kill_error = f"{type(e).__name__}: {e}"
    # A record pointing at a process that never answered would make the next
    # close report "stranger" for our own failure; drop it here.
    clear_owner()

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
