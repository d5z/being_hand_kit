"""System prompt + tool contract handed to the opencode agent."""

HAND_PLANNER_SYSTEM_PROMPT = '''\
You are hand-planner. You ONLY output step plans.
You NEVER execute steps.

Available primitives:
  open <target>   app|URL|file
  see             perceive current place
  do <action>     keyboard shortcut or semantic intent
  done            all steps listed

Rules:
1. Output ALL steps needed, one JSON per line. NO prose.
2. You MUST emit at least one open/see/do before done.
3. Never answer the goal directly - only list steps.

Example (save date to file):
{"step":"open","target":"~/note.txt"}
{"step":"do","action":"type: 2026-08-06"}
{"step":"done","summary":"written"}
'''


def _build_prompt(goal: str, context: dict | None = None, sp: str | None = None) -> str:
    """Build the full prompt sent to opencode for a planning run."""
    sys = sp or HAND_PLANNER_SYSTEM_PROMPT
    ctx = "\n".join(f"  {k}: {v}" for k, v in (context or {}).items())
    ctx_block = f"Context:\n{ctx}\n\n" if context else ""
    return f"{sys}\n\n{ctx_block}Goal: {goal}\n"


def _goal_met(steps) -> bool:
    """Return True if any step is a 'done' step."""
    return any(s.kind == "done" for s in steps)


def _last_summary(steps) -> str:
    """Extract the summary from the last 'done' step."""
    for s in reversed(steps):
        if s.kind == "done":
            return s.raw.get("summary", "") or s.raw.get("action", "") or s.action
    return ""