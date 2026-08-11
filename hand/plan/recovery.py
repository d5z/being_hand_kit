# -*- coding: utf-8 -*-
"""Recovery prompt for Tier 3: closed-loop replanning."""

RECOVERY_SYSTEM_PROMPT = """\
You are hand-planner (recovery mode). A previous step FAILED.
Your job: output ONLY the steps needed to RECOVER and CONTINUE toward the goal.

Available primitives:
  open <target>   app|URL|file
  see             perceive current place
  do <action>     keyboard shortcut or semantic intent
  done            all steps listed

Rules:
1. You are mid-plan. Do NOT restart from scratch.
2. Output ONLY the steps needed to fix the failure and continue.
3. One JSON per line. NO prose.
4. If the failure is unfixable, emit a single:
   {"step":"error","action":"<why it cannot be recovered>"}
5. You MUST emit at least one see before any do, to verify current state.

Example (file-open failed because path wrong):
{"step":"see"}
{"step":"open","target":"~/note.txt"}
{"step":"do","action":"type: 2026-08-06"}
{"step":"done","summary":"recovered"}
"""


def build_recovery_prompt(goal, failed_step, trace):
    """Build a recovery prompt from the failed step and current trace."""
    fail = failed_step.get("raw", "") or failed_step.get("action", "")
    fail_kind = failed_step.get("kind", "?")
    fail_result = failed_step.get("result", {})

    recent = trace[-6:] if trace else []
    summary_lines = []
    for e in recent:
        r = e.get("result", {})
        err = r.get("error") if isinstance(r, dict) else None
        ok = "OK" if not err else "FAIL: " + str(err)
        kind = e.get("kind", "")
        action = e.get("action", "")
        summary_lines.append("  [" + kind + "] " + action + " -> " + ok)
    trace_block = "\n".join(summary_lines) if summary_lines else "  (empty)"

    return (
        RECOVERY_SYSTEM_PROMPT
        + "\n\nContext:\n"
        + "  Goal: " + str(goal) + "\n"
        + "  Failed step: " + fail_kind + " " + str(fail) + "\n"
        + "  Failure detail: " + str(fail_result) + "\n"
        + "  Recent trace:\n"
        + trace_block
        + "\n\nOutput recovery steps:\n"
    )
