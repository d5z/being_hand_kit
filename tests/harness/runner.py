"""Unified runner: run a scenario -> collect receipts -> judge -> three-state.

Also the shared environment helpers used by every L2-L6 test module:
  * chrome_available()   — is a CDP endpoint answering?
  * host_reachable(url)  — network gate for real-site journeys (SKIP, not red)
  * chrome_proc_count()  — process-leak accounting for L2/L6
  * close_browser()      — the kit cdp_close path (Browser.close), no mcp import
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, "/home/alice/Hand")

from tests.harness import judge as J


# ── environment ──────────────────────────────────────────────────────

def chrome_available(timeout=2):
    try:
        from hand.perception.cdp_launcher import endpoint_info
        return endpoint_info(timeout=timeout) is not None
    except Exception:
        return False


def host_reachable(url, timeout=8):
    """TCP-connect + HTTP HEAD/GET the host — network gate for L3."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            pass
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "hand-prod-test"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def chrome_proc_count():
    """Count chrome/chromium processes leaking outside the CDP browser.

    Uses /proc-style ps; counts processes whose cmdline mentions a chrome
    binary. Renderer/zygote/gpu children are counted too — the point is a
    before/after delta, not an absolute.
    """
    try:
        out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return -1
    n = 0
    for line in out.splitlines()[1:]:
        low = line.lower()
        if ("chrome-headless-shell" in low or "/chrome " in low
                or "chromium" in low or "google-chrome" in low):
            if "ps -eo" in low or "grep" in low:
                continue
            n += 1
    return n


# ── journeys ─────────────────────────────────────────────────────────

def run_journey(journey, ctx=None, step_timeout=25):
    """Execute a Journey's steps in order; return a trace dict.

    Each step gets a callable(ctx) -> receipt. ctx accumulates the trace so a
    later step can act on an earlier step's result (data-driven journeys).
    """
    ctx = ctx if ctx is not None else {}
    trace = {"journey": journey.name, "layer": journey.layer,
             "start_url": journey.start_url, "steps": [], "error": None}
    ctx["trace"] = trace
    ctx["steps"] = trace["steps"]
    for step_name, fn in journey.steps:
        t0 = time.time()
        try:
            receipt = fn(ctx)
            err = None
        except Exception as e:
            receipt = {"error": f"{type(e).__name__}: {e}", "verified": False,
                       "evidence": {"verified": False, "reason": str(e)}}
            err = receipt["error"]
        rec = {"step": step_name, "receipt": receipt, "error": err,
               "latency_s": round(time.time() - t0, 2)}
        trace["steps"].append(rec)
        ctx.setdefault("receipts", {})[step_name] = receipt
    try:
        verdict = journey.judge(ctx)
    except Exception as e:
        verdict = J.miss(journey.name, f"judge raised {type(e).__name__}: {e}")
    trace["verdict"] = verdict.as_dict()
    return trace


# ── close (kit cdp_close path, no mcp import) ────────────────────────

def close_browser():
    """Mirror kit/mcp_server.py::cdp_close — Browser.close on every page."""
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
            except Exception:
                pass
        return {"closed": "ok", "pages_closed": closed,
                "verified": False, "evidence": {"verified": False,
                "reason": "cdp_close is claimed (Browser.close issued); no post-close browser probe"}}
    except Exception as e:
        return {"closed": "partial", "error": str(e)}
