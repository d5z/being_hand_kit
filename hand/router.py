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
from hand.session import get_session, Place, reset_session

# ── Perception backends ────────────────────────────────────────────

SEE_PRIORITY = {
    "browser":      ["cdp_dom", "ax_ui", "vision_ocr"],
    "desktop_app":  ["ax_app", "ax_ui", "vision_ocr"],
    "unknown":      ["vision_ocr", "ax_ui"],
}

# ── Action backends ─────────────────────────────────────────────────

DO_PRIORITY = {
    "browser":      ["cdp_click", "cdp_type"],
    "desktop_app":  ["keystroke", "ax_click"],
    "unknown":      ["keystroke", "ax_click"],
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

def route_see(place: Optional[Place] = None) -> dict:
    """
    Look at the screen / current place.

    Routing:
      desktop_app → ax_app (0ms) → ax_ui (tree) → vision_ocr (~500ms)
      browser     → cdp_dom       → ax_ui        → vision_ocr
      unknown     → vision_ocr    → ax_ui

    On success, updates session cache.
    """
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

    place_type = place.type
    backends = DO_PRIORITY.get(place_type, DO_PRIORITY["unknown"])

    # Run pre-actions (context setup) for certain app+action combos
    try:
        _run_pre_actions(place.identifier, action, place.identifier)
    except Exception:
        pass  # pre-actions are best-effort

    errors = []

    for backend in backends:
        try:
            if backend == "cdp_click":
                from hand.action.cdp_act import cdp_click_do
                result = cdp_click_do(action, app_name=place.identifier)
            elif backend == "cdp_type":
                from hand.action.cdp_act import cdp_type_do
                result = cdp_type_do(action, app_name=place.identifier)
            elif backend == "keystroke":
                from hand.action.keystroke import keystroke_do
                result = keystroke_do(action, app_name=place.identifier)
            elif backend == "ax_click":
                from hand.action.ax_click import ax_click_do
                result = ax_click_do(action, app_name=place.identifier)

            if result is not None and result.get("success", True):
                # Invalidate perception cache after action
                session = get_session()
                session.clear()
                return result
        except Exception as e:
            errors.append(f"{backend}: {e}")
            continue

    return {"error": "all action backends failed", "details": errors}


# ── Screenshot ───────────────────────────────────────────────────────

def route_screenshot(place: Optional[Place] = None) -> dict:
    """Take a screenshot. Updates session cache."""
    from hand.perception.vision_ocr import _capture_screenshot

    path = _capture_screenshot()
    session = get_session()
    session.screenshot_path = path

    return {
        "method": "screenshot",
        "path": path,
    }


# ── Plan ─────────────────────────────────────────────────────────────

def route_plan(goal: str, steps: Optional[list] = None) -> dict:
    """
    Plan and execute a natural-language goal.

    When steps is None, uses PlanningEngine to decompose the goal into
    ordered Hand primitives.  Iterates steps, dispatching each to
    route_open / route_see / route_do, and collects a trace on the
    session.  After every 'do' a 'see' is automatically inserted for
    closed-loop verification.

    Returns a summary dict with the full trace.
    """
    from hand.plan.engine import PlanningEngine

    session = get_session()
    session.clear_plan_trace()
    trace: list[dict] = session.plan_trace

    if steps is None:
        engine = PlanningEngine()
        result = engine.plan(goal)
        if not result.ok and not result.steps:
            return {"error": "planning failed", "details": result.error}
        steps = [(s.kind, s.action, s.raw) for s in result.steps]

    for kind, action, raw in steps:
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
                # auto-insert see after every do
                see_res = route_see()
                trace.append({"kind": "see", "action": "", "result": see_res})
            elif kind == "done":
                entry["summary"] = raw.get("summary", "")
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

    return {
        "plan": "ok",
        "goal": goal,
        "trace": trace,
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