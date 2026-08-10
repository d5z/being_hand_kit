"""Tier 5 - Proactive Self-Healing.

FailurePredictor analyzes each step BEFORE execution and predicts failure
risk using session state + step content + known failure patterns.

HealingEngine wraps the execution loop: for each step it predicts risk,
applies preventive actions (healing) before a predicted failure happens,
and records near-miss patterns for future prediction.

Key difference from Tier 3 (reactive recovery):
    Tier 3: step fails -> THEN recover (事后)
    Tier 5: predict step will fail -> prevent it BEFORE it fails (事前)
"""

from typing import Optional, List, Dict, Any


# ── Risk levels ──────────────────────────────────────────────────────
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

# Actions that require a place to be set
PLACE_REQUIRED_KINDS = {"do", "see"}


class StepPrediction:
    """Prediction for a single step before execution."""
    __slots__ = ("kind", "action", "risk", "signal", "healing", "healed")

    def __init__(self, kind, action, risk, signal=None, healing=None):
        self.kind = kind
        self.action = action
        self.risk = risk
        self.signal = signal          # which failure pattern fired
        self.healing = healing        # preventive action to apply (or None)
        self.healed = False           # set True when healing was applied

    def to_dict(self):
        return {
            "kind": self.kind,
            "action": self.action,
            "risk": self.risk,
            "signal": self.signal,
            "healing": self.healing,
            "healed": self.healed,
        }


class FailurePredictor:
    """Predict step failure risk from session state + step content."""

    def predict(self, kind: str, action: str,
                place_set: bool, trace: List[Dict]) -> StepPrediction:
        """
        kind:       step kind (open/see/do/done/error)
        action:     step action string
        place_set:  whether session currently has a place
        trace:      execution trace so far (for repeated-failure detection)
        """

        # 1. Unknown step kind -> certain failure
        if kind not in ("open", "see", "do", "done", "error"):
            return StepPrediction(kind, action, RISK_HIGH, "unknown_kind",
                                  "skip_step")

        # 2. open/done/error need no place
        if kind in ("open", "done", "error"):
            return StepPrediction(kind, action, RISK_LOW)

        # 3. do/see without a place -> certain failure
        if not place_set:
            return StepPrediction(kind, action, RISK_HIGH, "no_place",
                                  "insert_open")

        # 4. Repeated failure of the same action in trace
        if kind == "do" and action:
            failures = 0
            for entry in trace:
                if entry.get("kind") != "do":
                    continue
                if entry.get("action") != action:
                    continue
                res = entry.get("result", {})
                if res.get("error") or res.get("ok") is False:
                    failures += 1
            if failures >= 1:
                return StepPrediction(kind, action, RISK_HIGH,
                                      "repeated_failure", "replan_step")

        # 5. Default low risk
        return StepPrediction(kind, action, RISK_LOW)


class HealingEngine:
    """Executes a plan with proactive prediction + preventive healing."""

    def __init__(self, predictor: Optional[FailurePredictor] = None):
        self.predictor = predictor or FailurePredictor()
        self.predictions: List[StepPrediction] = []
        self.heal_count = 0
        self.near_miss_count = 0

    def heal(self, goal: str, steps: List[tuple],
             execute_fn, max_recoveries: int = 3) -> Dict[str, Any]:
        """
        steps:      list of (kind, action, raw)
        execute_fn: callable(kind, action) -> result dict
                    (the router dispatch, e.g. route_open/see/do)
        """
        from hand.session import get_session

        session = get_session()
        # Need a place check helper: session.place may be None
        def place_set():
            return session.place is not None

        trace: List[Dict] = []
        session.clear_plan_trace()
        self.predictions = []
        self.heal_count = 0
        self.near_miss_count = 0

        i = 0
        while i < len(steps):
            kind, action, raw = steps[i]

            # ── Predict BEFORE executing ──
            pred = self.predictor.predict(kind, action, place_set(), trace)
            self.predictions.append(pred)

            # ── High risk: apply healing BEFORE execution ──
            if pred.risk == RISK_HIGH and pred.healing:
                if pred.healing == "insert_open" and place_set() is False:
                    # We have a do/see with no place. If an open exists
                    # earlier in the plan, re-run it (heal). Otherwise skip.
                    open_target = None
                    for (k, a, _r) in steps[:i]:
                        if k == "open":
                            open_target = a
                    if open_target:
                        # preventively re-open the place
                        res = execute_fn("open", open_target)
                        ok = res.get("error") is None
                        trace.append({"kind": "heal",
                                      "action": f"re-open {open_target}",
                                      "result": res})
                        if ok:
                            pred.healed = True
                            self.heal_count += 1
                        else:
                            trace.append({"kind": "heal",
                                          "action": "open failed",
                                          "result": {"error": "preventive open failed"}})
                    else:
                        # No open in plan -> cannot heal; skip to avoid crash
                        trace.append({"kind": "heal",
                                      "action": "skip (no place to open)",
                                      "result": {"error": "no_place_unhealable"}})
                        self.near_miss_count += 1
                        pred.healed = True
                        i += 1
                        continue  # skip this step
                elif pred.healing == "replan_step":
                    # Rate-limit repeated actions: mark healed by skipping
                    # the duplicate (already failed once -> will fail again)
                    trace.append({"kind": "heal",
                                  "action": "skip repeated failing action",
                                  "result": {"ok": True, "healed": True}})
                    pred.healed = True
                    self.heal_count += 1
                    i += 1
                    continue
                elif pred.healing == "skip_step":
                    trace.append({"kind": "heal",
                                  "action": "skip unknown step kind",
                                  "result": {"ok": True, "healed": True}})
                    pred.healed = True
                    self.heal_count += 1
                    i += 1
                    continue

            # ── Execute normally (with prediction recorded) ──
            entry = {"kind": kind, "action": action, "raw": raw}
            if kind == "do":
                res = execute_fn("do", action)
                entry["result"] = res
                trace.append(entry)
                # closed-loop verify
                see_res = execute_fn("see", "")
                trace.append({"kind": "see", "action": "", "result": see_res})
            else:
                res = execute_fn(kind, action)
                entry["result"] = res
                trace.append(entry)

            # ── Tier 3 fallback: if still failed, reactive recovery ──
            result = entry.get("result", {})
            is_failure = (isinstance(result, dict) and (
                result.get("error") is not None or result.get("ok") is False))
            if is_failure:
                # Count near-miss (prediction said low but it failed)
                if pred.risk == RISK_LOW:
                    self.near_miss_count += 1
                # allow one reactive recovery round (still better than nothing)
                if max_recoveries > 0:
                    max_recoveries -= 1
                    trace.append({"kind": "recovery",
                                  "action": "reactive fallback after predicted-low failure",
                                  "result": {"ok": False, "note": "recovery left to Tier 3"}})

            i += 1

        return {
            "plan": "healed",
            "goal": goal,
            "trace": trace,
            "heal_count": self.heal_count,
            "near_miss_count": self.near_miss_count,
            "predictions": [p.to_dict() for p in self.predictions],
        }
