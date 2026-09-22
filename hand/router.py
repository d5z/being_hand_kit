"""
Router — the internal routing layer.

Being says "open" / "see" / "do". The router selects which backend to use,
based on the current place type. Being does not choose backends.
The framework code chooses.

Priority order matters:
  - Desktop app: AX app layer (0-latency) → AX UI layer → Vision OCR
  - Browser:      CDP DOM (structured) → AX UI → Vision OCR
  - Unknown:      Vision OCR (see first) → AX UI (then touch)
"""

from typing import Optional
from hand.platform import is_macos
from hand.receipt import skipped, merge_hints
from hand.session import get_session, Place, reset_session

# ── Permission of backends per platform ────────────────────────────
# ax_* / vision_ocr / keystroke only exist on macOS (osascript, screencapture).
# On other platforms they are silently dropped from the priority chains —
# no "command not found" noise.

_MAC_ONLY_BACKENDS = {"ax_app", "ax_ui", "ax_click", "vision_ocr", "keystroke"}


def _available(backends: list) -> list:
    if is_macos():
        return backends
    return [b for b in backends if b not in _MAC_ONLY_BACKENDS]


# ── Perception backends ────────────────────────────────────────────

# Browser perception, fastest-and-richest first. Since 0.7.0 the AX tree
# (cdp_a11y) is the DEFAULT browser snapshot — the A/B experiment showed 87% vs
# 58% for GLM-5.3 (experiments/a11y_ab/REPORT_phase2.md). cdp_dom stays in the
# chain as graceful degradation: if the AX tree cannot be pulled, the DOM text
# snapshot still answers, and the receipt says which backend actually spoke.
SEE_PRIORITY = {
    "browser":      _available(["cdp_a11y", "cdp_dom", "cdp_network", "cdp_interactive", "ax_ui", "vision_ocr"]),
    "desktop_app":  _available(["ax_app", "ax_ui", "vision_ocr"]),
    "unknown":      _available(["cdp_a11y", "cdp_dom", "cdp_interactive", "vision_ocr", "ax_ui"]),
}

# ── Action backends ─────────────────────────────────────────────────

DO_PRIORITY = {
    "browser":      _available(["cdp_click", "cdp_type", "cdp_scroll"]),
    "desktop_app":  _available(["keystroke", "ax_click"]),
    "unknown":      _available(["keystroke", "ax_click"]),
}

# ── Pre-actions per app ─────────────────────────────────────────────
# Some apps need context setup before certain actions.
# e.g. Notes can only create a new note (Cmd+N) when in list view.

PRE_ACTIONS = {
    ("Notes", "新建笔记"): ["Cmd+0"],
    ("Notes", "Cmd+N"):    ["Cmd+0"],
    ("Notes", "cmd+n"):    ["Cmd+0"],
}


# ── Open ─────────────────────────────────────────────────────────────

def route_open(target: str) -> dict:
    """
    Set the current place. Creates a new session.

    target: app name ("Notes"), URL ("https://..."), file path, etc.

    Receipt (v6.11.0): the plain `{"open": "ok"}` was indistinguishable between
    "navigation confirmed", "only the CDP endpoint is alive" and "no endpoint".
    The receipt now carries the evidence level reported by `open_place`:
    `evidence.level` = "navigate_confirmed" | "endpoint_alive" | "activate_issued",
    with `verified` true only for a confirmed navigation. Path ③ (no endpoint)
    still raises out of `open_place` — unchanged.
    """
    from hand.place.detect import open_place, get_open_evidence

    # Open/launch the place — returns a Place with type auto-detected
    place = open_place(target)
    reset_session()
    session = get_session()
    session.place = place

    evidence = get_open_evidence(place)
    if not evidence:
        evidence = {
            "level": "unknown",
            "detail": f"open_place 未提供证据（target={target!r}）",
        }
    # F14 unified shape: evidence itself carries the verdict it backs, so a
    # consumer reading only `evidence` still sees verified vs claimed.
    evidence.setdefault("verified", evidence.get("level") == "navigate_confirmed")

    return {
        "open": "ok",
        "place": {
            "type": place.type,
            "identifier": place.identifier,
        },
        "verified": evidence.get("level") == "navigate_confirmed",
        "evidence": evidence,
    }


# ── Receipt evidence for perception (v6.11.0) ───────────────────────
# Perception receipts already carry natural evidence (title/url, element count,
# request count, screenshot length). This wraps it in the unified shape
# {"verified": bool, "evidence": {...}} — verified=False always names a reason.

def _error_receipt(error: str, **fields) -> dict:
    """Failure receipt in the unified shape — reason always present."""
    out = {"error": error, "verified": False,
           "evidence": {"verified": False, "reason": error}}
    out.update(fields)
    return out


def _with_receipt(result: dict) -> dict:
    """Attach verified/evidence to a perception receipt (additive)."""
    if not isinstance(result, dict) or "method" not in result:
        return result
    if "verified" in result:
        return result
    method = result.get("method")
    ev = {"backend": method}
    verified = True
    reason = None

    if method == "cdp_snapshot":
        ev["url"] = result.get("url")
        ev["page_title"] = result.get("page_title")
        ev["chars"] = result.get("chars")
        if not result.get("url") and not result.get("page_title"):
            verified, reason = False, "cdp_dom returned neither url nor title"
    elif method == "cdp_a11y":
        # S3: a11y v2 snapshot (0.7.0). verified = a tree was really pulled AND
        # curated to a non-empty tree; evidence = node/byte counts, truncation
        # marker and the AX source version. A truncated tree is still verified —
        # truncation is declared, not hidden.
        ev["node_count"] = result.get("node_count")
        ev["raw_node_count"] = result.get("raw_node_count")
        ev["serialized_bytes"] = result.get("serialized_bytes")
        ev["truncated"] = result.get("truncated")
        ev["nodes_omitted"] = result.get("nodes_omitted")
        ev["text_truncated_count"] = result.get("text_truncated_count")
        ev["format"] = result.get("format")
        ev["ax_version"] = result.get("ax_version")
        ev["sha256"] = result.get("sha256")
        ev["root_role"] = result.get("root_role")
        ev["hint"] = result.get("hint")
        if not result.get("node_count") or not result.get("root_role"):
            verified, reason = False, (
                "Accessibility.getFullAXTree produced no curated root "
                f"(root_role={result.get('root_role')!r}, "
                f"nodes={result.get('node_count')!r}) — nothing was perceived")
    elif method == "cdp_interactive":
        ev["count"] = result.get("count")
        ev["total"] = result.get("total")
        if not result.get("count"):
            verified, reason = False, "interactive map matched 0 elements"
    elif method == "cdp_network":
        ev["total_requests"] = result.get("total_requests")
        ev["duration"] = result.get("duration")
        if result.get("total_requests") is None:
            verified, reason = False, "network snapshot carried no request count"
    elif method == "vision_ocr":
        ev["screenshot"] = result.get("screenshot")
        ev["total_lines"] = result.get("total_lines")
        if result.get("error"):
            verified, reason = False, f"vision_ocr error: {result['error']}"
    else:
        ev["detail"] = "backend receipt wrapped without backend-specific checks"

    # S1 (0.9): the unified truncation block (when present) travels into the
    # evidence too, beside the legacy per-backend counts.
    if result.get("truncation"):
        ev["truncation"] = result["truncation"]
    if reason:
        ev["reason"] = reason
    ev["verified"] = verified
    result = dict(result)
    result["verified"] = verified
    result["evidence"] = ev
    return result


# ── See ──────────────────────────────────────────────────────────────

def route_see_vlm(prompt: Optional[str] = None, image_b64: Optional[str] = None) -> dict:
    """
    Use a vision LLM to describe the current screen.

    Screenshot source: CDP browser (if alive) → screencapture (macOS).
    Returns {"method": "vision_llm", "text": ..., "model": ..., "source": ...}.
    """
    source = None
    if not image_b64:
        # 1) try CDP browser
        try:
            from hand.perception.cdp_core import list_pages, cdp_screenshot
            pages = list_pages()
            if pages:
                shot = cdp_screenshot()
                image_b64 = shot.get("data", "")
                source = "cdp"
        except Exception:
            image_b64 = ""
        # 2) fallback screencapture (macOS)
        if not image_b64:
            import base64, tempfile, os
            from hand.perception.vision_ocr import _capture_screenshot
            path = _capture_screenshot()
            with open(path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
            source = "screencapture"

    from hand.perception.vision_llm import describe_screenshot
    result = describe_screenshot(image_b64, prompt=prompt)
    if result.get("ok"):
        out = {
            "method": "vision_llm",
            "text": result.get("text"),
            "model": result.get("model"),
            "source": source,
        }
        if result.get("finish_reason") is not None:
            out["finish_reason"] = result["finish_reason"]
        if result.get("finish_reason") == "length":
            # S1 (0.9): the description was cut at max_tokens. Declared via the
            # provider verdict; a numeric {dropped,total} would be a guess.
            out["hint"] = skipped("vision description tail",
                                  "the model hit max_tokens (finish_reason=length)")
        return out
    return {
        "method": "vision_llm",
        "text": None,
        "model": result.get("model"),
        "source": source,
        "error": result.get("error"),
        "detail": result.get("detail"),
    }


def route_see(place: Optional[Place] = None, kind: Optional[str] = None) -> dict:
    """
    Look at the screen / current place.

    Routing:
      desktop_app → ax_app (0ms) → ax_ui (tree) → vision_ocr (~500ms)
      browser     → cdp_a11y (AX tree, 0.7.0 default) → cdp_dom → cdp_network
                    → cdp_interactive → ax_ui → vision_ocr
      unknown     → cdp_a11y → cdp_dom → cdp_interactive → vision_ocr → ax_ui

    Explicit `kind` channels (place-independent, checked before Place
    resolution): "a11y" (AX tree, the default), "dom" (text snapshot),
    "interactive" (legacy element map — kept as the coordinate escape hatch),
    "network", "vlm".

    On success, updates session cache.
    """
    if kind == "network":
        # Network is a place-independent channel — the CDP browser exposes
        # request/response flow regardless of the current Place. Handle it
        # before Place resolution so it's never shadowed by the vision
        # fallback when no Place is set.
        try:
            from hand.perception.cdp_network import network_snapshot
            result = network_snapshot()
            if result and result.get("method"):
                result = _with_receipt(result)
                session = get_session()
                session.last_see = result
                return result
        except Exception as e:
            return _error_receipt("cdp_network failed", details=str(e))

    if kind == "a11y":
        # a11y v2 tree is the DEFAULT browser snapshot since 0.7.0 and is a
        # place-independent channel, like network/interactive: it talks to
        # whatever CDP page is live. Handled before Place resolution so it can
        # never be shadowed by the desktop/vision fallback.
        try:
            from hand.perception.ax_tree import ax_snapshot
            result = ax_snapshot()
            if result and result.get("method"):
                result = _with_receipt(result)
                session = get_session()
                session.last_see = result
                if session.place is None:
                    # Perception implies a place: keeps a following do([idx])
                    # routable without an explicit open.
                    session.place = Place(type="browser", identifier="cdp-detected")
                return result
            return _error_receipt("cdp_a11y returned no snapshot",
                                  details="ax_snapshot produced no receipt")
        except Exception as e:
            return _error_receipt(f"cdp_a11y failed: {type(e).__name__}: {e}",
                                  details=str(e))

    if kind == "dom":
        # Explicit legacy channel (0.7.0): the DOM text snapshot, without the
        # a11y default getting in the way.
        try:
            from hand.perception.cdp_snapshot import cdp_snapshot_see
            result = cdp_snapshot_see()
            if result and result.get("method"):
                result = _with_receipt(result)
                session = get_session()
                session.last_see = result
                return result
            return _error_receipt("cdp_dom returned no snapshot",
                                  details="cdp_snapshot_see produced no receipt")
        except Exception as e:
            return _error_receipt(f"cdp_dom failed: {type(e).__name__}: {e}",
                                  details=str(e))

    if kind == "interactive":
        # Interactive element map is a place-independent channel too — the
        # CDP browser exposes the interactive nodes regardless of the
        # current Place. Handle it before Place resolution, same as network.
        try:
            from hand.perception.cdp_snapshot import interactive_map
            result = interactive_map()
            if result and result.get("method"):
                result = _with_receipt(result)
                session = get_session()
                session.last_see = result
                return result
        except Exception as e:
            return _error_receipt("cdp_interactive failed", details=str(e))

    if kind == "vlm":
        return route_see_vlm()

    if place is None:
        session = get_session()
        place = session.place

    if place is None or getattr(place, "type", None) == "unknown":
        # No place set (or a stale "unknown"). Try the live CDP browser first —
        # Chrome may be alive even without an explicit open (the MCP server is
        # lazy-spawned, so a fresh process loses session.place but the browser
        # itself persists). One HTTP GET to /json; cheap and idempotent.
        try:
            from hand.perception.cdp_core import list_pages
            pages = list_pages()
            if pages:
                session = get_session()
                session.place = Place(type="browser", identifier="cdp-detected")
                place = session.place
        except Exception:
            pass
        if place is None:
            # No place at all and no live browser — vision OCR as universal fallback
            try:
                from hand.perception.vision_ocr import vision_ocr_see
                return _with_receipt(vision_ocr_see())
            except Exception as e:
                return _error_receipt("no place set and vision_ocr failed", details=str(e))

    place_type = place.type
    backends = SEE_PRIORITY.get(place_type, SEE_PRIORITY["unknown"])

    errors = []

    if not backends:
        # No backend available for this place on this platform — honest
        # boundary statement, not a fake "everything failed" error.
        return _error_receipt(
            f"no see backends for '{place_type}' on this platform",
            details=f"platform has no perception backend for {place_type}")

    for backend in backends:
        try:
            result = None
            if backend == "ax_app":
                from hand.perception.ax_app import ax_app_see
                result = ax_app_see(place.identifier)
            elif backend == "ax_ui":
                from hand.perception.ax_ui import ax_ui_see
                result = ax_ui_see(place.identifier)
            elif backend == "vision_ocr":
                from hand.perception.vision_ocr import vision_ocr_see
                result = vision_ocr_see()
            elif backend == "cdp_dom":
                from hand.perception.cdp_snapshot import cdp_snapshot_see
                result = cdp_snapshot_see()
            elif backend == "cdp_network":
                from hand.perception.cdp_network import network_snapshot
                result = network_snapshot()
            elif backend == "cdp_interactive":
                from hand.perception.cdp_snapshot import interactive_map
                result = interactive_map()
            elif backend == "cdp_a11y":
                from hand.perception.ax_tree import ax_snapshot
                result = ax_snapshot()

            if result is not None and result.get("method"):
                result = _with_receipt(result)
                # S1 (0.9): a backend that failed on the way here was *skipped*,
                # not silently ignored — declare it in the hint channel.
                if errors:
                    result["hint"] = merge_hints(result.get("hint"), [
                        skipped(e.split(":", 1)[0].strip(),
                                "backend failed: " + e.split(":", 1)[1].strip()[:120])
                        for e in errors])
                # Cache in session: full result for ax_app/ax_ui, screenshot for vision
                session = get_session()
                if backend == "vision_ocr":
                    session.screenshot_path = result.get("screenshot")
                    session.ocr_result = result
                else:
                    session.last_see = result
                return result
        except Exception as e:
            errors.append(f"{backend}: {e}")
            continue

    return _error_receipt("all see backends failed", details=errors)


# ── Do ───────────────────────────────────────────────────────────────

def _handle_action(action) -> bool:
    """Is this action an [idx] handle (optionally `[idx]|text`)? See S2."""
    if not isinstance(action, str):
        return False
    from hand.perception.ax_tree import looks_like_handle
    return looks_like_handle(action.split("|", 1)[0])


def _run_pre_actions(app_name: str, action: str, app_name_param: str):
    """Run any needed pre-actions for this app+action combo."""
    from hand.action.keystroke import keystroke_do
    import time
    key = (app_name, action)
    if key in PRE_ACTIONS:
        for pre in PRE_ACTIONS[key]:
            keystroke_do(pre, app_name=app_name_param)
            time.sleep(0.15)


def route_do(action: str, place: Optional[Place] = None) -> dict:
    """
    Execute an action at the current place.
    action: semantic intent ("新建笔记") or shortcut ("Cmd+N").
    """
    if place is None:
        session = get_session()
        place = session.place

    if place is None and _handle_action(action):
        # A [idx] handle is a coordinate/handle action, not a semantic app
        # intent: it names a node of the last a11y snapshot. If a CDP browser is
        # live, that is enough context (the MCP server is lazily spawned, so a
        # fresh process may have lost session.place but not the browser).
        try:
            from hand.perception.cdp_core import list_pages
            if list_pages():
                session = get_session()
                session.place = Place(type="browser", identifier="cdp-detected")
                place = session.place
        except Exception:
            pass

    if place is None:
        return {"error": "no place — call route_open first"}

    # Normalize: place can be dict or object
    if isinstance(place, dict):
        place_type = place.get("type", "unknown")
        place_id = place.get("identifier", "")
    else:
        place_type = place.type
        place_id = place.identifier

    backends = DO_PRIORITY.get(place_type, DO_PRIORITY["unknown"])

    if not backends:
        return {"error": f"no action backends for '{place_type}' on this platform",
                "details": f"platform has no action backend for {place_type}"}

    # Run pre-actions (context setup) for certain app+action combos
    try:
        _run_pre_actions(place_id, action, place_id)
    except Exception:
        pass  # pre-actions are best-effort

    errors = []

    # Scroll intent — "scroll down/up/top/bottom" routes straight to the CDP
    # scroll backend. Must be intercepted before the backend loop: cdp_click
    # would treat the action as a CSS selector and "fail" (silently returning
    # its error dict, which reads as success), never reaching the scroller.
    if 'cdp_scroll' in backends and action.strip().lower().startswith('scroll'):
        try:
            from hand.action.cdp_act import cdp_scroll_do
            result = cdp_scroll_do(action, app_name=place_id)
            if result is not None:
                session = get_session()
                session.clear()
                return result
        except Exception as e:
            errors.append(f"cdp_scroll: {e}")

    for backend in backends:
        try:
            if backend == "cdp_click":
                from hand.action.cdp_act import cdp_click_do
                result = cdp_click_do(action, app_name=place_id)
            elif backend == "cdp_type":
                from hand.action.cdp_act import cdp_type_do
                result = cdp_type_do(action, app_name=place_id)
            elif backend == "cdp_scroll":
                from hand.action.cdp_act import cdp_scroll_do
                result = cdp_scroll_do(action, app_name=place_id)
            elif backend == "keystroke":
                from hand.action.keystroke import keystroke_do
                result = keystroke_do(action, app_name=place_id)
            elif backend == "ax_click":
                from hand.action.ax_click import ax_click_do
                result = ax_click_do(action, app_name=place_id)

            if result is not None and result.get("success", True):
                # Invalidate perception cache after action
                session = get_session()
                session.clear()
                return result
        except Exception as e:
            errors.append(f"{backend}: {e}")
            continue

    return {"error": "all action backends failed", "details": errors}

def route_screenshot(place=None, with_data: bool = False) -> dict:
    """Take a screenshot. Updates session cache.

    Browser -> CDP Page.captureScreenshot
    Other -> vision_ocr (screencapture on macOS)
    with_data: include raw base64 in return dict (for MCP image content).
    """
    if place is None:
        # NB: get_session is module-level imported; a local re-import here would
        # shadow it for the whole function and break the place=... path
        # (UnboundLocalError) — see tests/test_visual_state.py.
        session = get_session()
        place = session.place

    if place is None:
        # No session place yet: probe for a live CDP browser first
        # (same pattern as route_see), only then fall back to screencapture.
        try:
            from hand.perception.cdp_core import list_pages
            if list_pages():
                from hand.session import Place
                session = get_session()
                if session.place is None:
                    session.place = Place(type="browser", identifier="cdp-detected")
                place = session.place
        except Exception:
            pass
    if place is not None and place.type == "browser":
        from hand.perception.cdp_core import cdp_screenshot
        result = cdp_screenshot()
        if result.get("data"):
            session = get_session()
            session.screenshot_path = "cdp:" + result["format"]
            out = {
                "method": "screenshot",
                "source": "cdp",
                "data_length": len(result["data"]),
                "format": result["format"],
                "verified": True,
                "evidence": {"source": "cdp",
                             "data_length": len(result["data"]),
                             "format": result["format"],
                             "verified": True},
            }
            # S2 (0.9): the visual state marker rides along with the shot.
            if result.get("visual_state") is not None:
                out["visual_state"] = result["visual_state"]
                out["visual_signals"] = result.get("visual_signals")
                out["evidence"]["visual_state"] = result["visual_state"]
            if with_data:
                out["data"] = result["data"]
            return out

    from hand.perception.vision_ocr import _capture_screenshot
    path = _capture_screenshot()
    session = get_session()
    session.screenshot_path = path
    return {
        "method": "screenshot",
        "source": "vision_ocr",
        "path": path,
        "verified": True,
        "evidence": {"source": "vision_ocr", "path": path,
                     "read_back": "screencapture wrote a file",
                     "verified": True},
    }

# ── Plan ─────────────────────────────────────────────────────────────

def route_plan(goal: str, steps: Optional[list] = None,
                 max_recoveries: int = 3) -> dict:
    """
    Plan and execute a natural-language goal (Tier 1 + Tier 3 recovery).

    When steps is None, uses PlanningEngine to decompose the goal into
    ordered Hand primitives.  Iterates steps, dispatching each to
    route_open / route_see / route_do, and collects a trace on the
    session.  After every 'do' a 'see' is automatically inserted for
    closed-loop verification.

    Tier 3: when a step fails, builds a recovery prompt from the failure
    context and calls PlanningEngine again to generate recovery steps.
    At most max_recoveries rounds of recovery are attempted.

    Returns a summary dict with the full trace, including recovery info.
    """
    from hand.plan.engine import PlanningEngine
    from hand.plan.recovery import build_recovery_prompt

    session = get_session()
    session.clear_plan_trace()
    trace: list[dict] = session.plan_trace
    recovery_count = 0

    if steps is None:
        engine = PlanningEngine()
        result = engine.plan(goal)
        if not result.ok and not result.steps:
            return {"error": "planning failed", "details": result.error}
        steps = [(s.kind, s.action, s.raw) for s in result.steps]

    i = 0
    while i < len(steps):
        kind, action, raw = steps[i]
        entry = {"kind": kind, "action": action, "raw": raw}
        try:
            if kind == "open":
                res = route_open(action)
                entry["result"] = res
                trace.append(entry)
            elif kind == "see":
                res = route_see()
                entry["result"] = res
                trace.append(entry)
            elif kind == "do":
                res = route_do(action)
                entry["result"] = res
                trace.append(entry)
                see_res = route_see()
                trace.append({"kind": "see", "action": "", "result": see_res})
            elif kind == "done":
                entry["summary"] = raw.get("summary", "") if raw else ""
                entry["result"] = {"ok": True}
                trace.append(entry)
                break
            elif kind == "error":
                entry["result"] = {"error": action}
                trace.append(entry)
                break
            else:
                entry["result"] = {"error": f"unknown step kind: {kind}"}
                trace.append(entry)
        except Exception as e:
            entry["result"] = {"error": str(e)}
            trace.append(entry)

        result = entry.get("result", {})
        is_failure = (
            isinstance(result, dict) and result.get("error") is not None
        ) or (
            isinstance(result, dict) and result.get("ok") is False
        )

        if is_failure and recovery_count < max_recoveries:
            recovery_count += 1
            recovery_prompt = build_recovery_prompt(goal, entry, trace)
            recovery_engine = PlanningEngine()
            recovery_result = recovery_engine.plan(recovery_prompt)
            if recovery_result.ok and recovery_result.steps:
                recovery_steps = [(s.kind, s.action, s.raw) for s in recovery_result.steps]
                steps = steps[:i+1] + recovery_steps + steps[i+1:]
                trace.append({"kind": "recovery",
                              "action": f"attempt #{recovery_count}",
                              "result": {"ok": True, "recovery_steps": len(recovery_steps)}})
            else:
                trace.append({"kind": "recovery",
                              "action": f"attempt #{recovery_count}",
                              "result": {"error": "recovery planning failed",
                                         "details": recovery_result.error}})
                break

        i += 1

    return {
        "plan": "ok",
        "goal": goal,
        "trace": trace,
        "recoveries": recovery_count,
    }


# ── Utility: see + do combined ──────────────────────────────────────

def see_and_do(action: str, place: Optional[Place] = None) -> dict:
    """
    See before and after an action — full closed-loop verification.

    1. route_see → baseline
    2. route_do → action
    3. route_see → after image
    """
    before = route_see(place)
    do_result = route_do(action, place)
    after = route_see(place)

    return {
        "before": before,
        "action": do_result,
        "after": after,
    }






# ── Plan with healing (Tier 5) ─────────────────────────────────────

def route_plan_healing(goal: str, steps=None, max_recoveries: int = 3) -> dict:
    """Plan and execute a goal with PROACTIVE self-healing (Tier 5)."""
    from hand.plan.engine import PlanningEngine
    from hand.plan.healing import HealingEngine
    from hand.session import get_session

    session = get_session()
    session.clear_plan_trace()

    if steps is None:
        engine = PlanningEngine()
        result = engine.plan(goal)
        if not result.ok and not result.steps:
            return {"error": "planning failed", "details": result.error}
        steps = [(s.kind, s.action, s.raw) for s in result.steps]

    def execute_fn(kind, action):
        from hand.router import route_open, route_see, route_do
        if kind == "open": return route_open(action)
        if kind == "see": return route_see()
        if kind == "do": return route_do(action)
        return {"ok": True}

    heal_engine = HealingEngine()
    return heal_engine.heal(goal, steps, execute_fn, max_recoveries=max_recoveries)

def route_plan_stream(goal, context=None, max_steps=20):
    from hand.plan.stream_engine import StreamingEngine
    session = get_session()
    session.clear_plan_trace()
    trace = session.plan_trace
    engine = StreamingEngine()
    stream_trace = engine.plan_stream(goal, context, max_steps)
    for st in stream_trace:
        entry = dict(kind=st.step.kind, action=st.step.action, raw=st.step.raw, result=st.result)
        if st.error:
            entry[chr(34)+chr(101)+chr(114)+chr(114)+chr(111)+chr(114)+chr(34)] = st.error
        trace.append(entry)
    engine.stop_server()
    return dict(plan=chr(115)+chr(116)+chr(114)+chr(101)+chr(97)+chr(109)+chr(95)+chr(111)+chr(107), goal=goal, trace=trace)
from hand.router_mcp import route_plan_mcp  # Tier 4 (MCP protocol)
