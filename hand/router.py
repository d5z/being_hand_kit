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

SEE_PRIORITY = {
    "browser":      _available(["cdp_dom", "cdp_network", "cdp_interactive", "ax_ui", "vision_ocr"]),
    "desktop_app":  _available(["ax_app", "ax_ui", "vision_ocr"]),
    "unknown":      _available(["vision_ocr", "ax_ui"]),
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
    """
    from hand.place.detect import open_place

    # Open/launch the place — returns a Place with type auto-detected
    place = open_place(target)
    reset_session()
    session = get_session()
    session.place = place

    return {
        "open": "ok",
        "place": {
            "type": place.type,
            "identifier": place.identifier,
        },
    }


# ── See ──────────────────────────────────────────────────────────────

def route_see(place: Optional[Place] = None, kind: Optional[str] = None) -> dict:
    """
    Look at the screen / current place.

    Routing:
      desktop_app → ax_app (0ms) → ax_ui (tree) → vision_ocr (~500ms)
      browser     → cdp_dom       → ax_ui        → vision_ocr
      unknown     → vision_ocr    → ax_ui

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
                session = get_session()
                session.last_see = result
                return result
        except Exception as e:
            return {"error": "cdp_network failed", "details": str(e)}

    if kind == "interactive":
        # Interactive element map is a place-independent channel too — the
        # CDP browser exposes the interactive nodes regardless of the
        # current Place. Handle it before Place resolution, same as network.
        try:
            from hand.perception.cdp_snapshot import interactive_map
            result = interactive_map()
            if result and result.get("method"):
                session = get_session()
                session.last_see = result
                return result
        except Exception as e:
            return {"error": "cdp_interactive failed", "details": str(e)}

    if place is None:
        session = get_session()
        place = session.place

    if place is None:
        # No place set — try vision OCR as universal fallback
        try:
            from hand.perception.vision_ocr import vision_ocr_see
            result = vision_ocr_see()
            return result
        except Exception as e:
            return {"error": "no place set and vision_ocr failed", "details": str(e)}

    place_type = place.type
    backends = SEE_PRIORITY.get(place_type, SEE_PRIORITY["unknown"])

    errors = []

    if not backends:
        # No backend available for this place on this platform — honest
        # boundary statement, not a fake "everything failed" error.
        return {"error": f"no see backends for '{place_type}' on this platform",
                "details": f"platform has no perception backend for {place_type}"}

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

            if result is not None and result.get("method"):
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

    return {"error": "all see backends failed", "details": errors}


# ── Do ───────────────────────────────────────────────────────────────

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

def route_screenshot(place=None) -> dict:
    """Take a screenshot. Updates session cache.

    Browser -> CDP Page.captureScreenshot
    Other -> vision_ocr (screencapture on macOS)
    """
    if place is None:
        from hand.session import get_session
        session = get_session()
        place = session.place

    if place is not None and place.type == "browser":
        from hand.perception.cdp_core import cdp_screenshot
        result = cdp_screenshot()
        if result.get("data"):
            session = get_session()
            session.screenshot_path = "cdp:" + result["format"]
            return {
                "method": "screenshot",
                "source": "cdp",
                "data_length": len(result["data"]),
                "format": result["format"],
            }

    from hand.perception.vision_ocr import _capture_screenshot
    path = _capture_screenshot()
    session = get_session()
    session.screenshot_path = path
    return {
        "method": "screenshot",
        "source": "vision_ocr",
        "path": path,
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
