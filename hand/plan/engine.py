"""PlanningEngine — spawns opencode CLI, feeds goals, collects steps.

Tier 1 (V6.1): one-shot subprocess. Blocking, stateless-per-call but
resumable via OPENCODE_PLAN_SESSION env var / -s flag.
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from .parser import Step, parse_events


# Known locations to search for opencode binary
_OPENCODE_CANDIDATES = [
    "/home/alice/.local/bin/opencode",
    "/usr/local/bin/opencode",
    "/usr/bin/opencode",
]


def _find_opencode() -> str | None:
    """Find opencode binary, checking PATH first, then known locations."""
    found = shutil.which("opencode")
    if found:
        return found
    for p in _OPENCODE_CANDIDATES:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


@dataclass
class PlanningResult:
    """Outcome of a planning run."""
    goal: str
    steps: list = field(default_factory=list)
    ok: bool = False
    summary: str = ""
    error: str | None = None


class PlanningEngine:
    """Convert a natural-language goal into ordered Hand steps via opencode."""

    def __init__(self, cwd=".", model=None, agent="hand-planner", system_prompt=None,
                 timeout=300, opencode_bin=None):
        self.cwd = cwd
        self.model = model
        self.agent = agent
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.opencode_bin = opencode_bin or _find_opencode()

    # -- public API -----------------------------------------------------

    def plan(self, goal: str, context: dict | None = None) -> PlanningResult:
        """Run the planner on a goal. Returns a PlanningResult."""
        if not self.opencode_bin:
            return PlanningResult(goal=goal, ok=False,
                                  error="opencode binary not found on PATH")

        prompt = _build_prompt(goal, context or {}, self.system_prompt)
        cmd = self._build_cmd(prompt)

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout, cwd=self.cwd,
            )
        except subprocess.TimeoutExpired:
            return PlanningResult(goal=goal, ok=False,
                                  error=f"opencode timed out after {self.timeout}s")

        if proc.returncode != 0:
            return PlanningResult(goal=goal, ok=False,
                                  error=proc.stderr.strip() or "opencode exited non-zero")

        steps = parse_events(proc.stdout, proc.stderr)
        ok = _goal_met(steps)
        return PlanningResult(
            goal=goal, steps=steps, ok=ok,
            summary=_last_summary(steps),
        )

    # -- internals ------------------------------------------------------

    def _build_cmd(self, prompt: str) -> list[str]:
        cmd = [self.opencode_bin, "run", prompt,
               "--format", "json"]
        if self.agent:
            cmd += ["--agent", self.agent]
        if self.model:
            cmd += ["-m", self.model]
        # auto-approve read-only permissions to avoid interactive prompts
        cmd += ["--auto"]
        session = os.environ.get("OPENCODE_PLAN_SESSION")
        if session:
            cmd += ["-s", session]
        return cmd


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

HAND_PLANNER_SYSTEM_PROMPT = """\
You are hand-planner, the planning brain of Hand (a GUI perception/action framework).
You DO NOT touch the screen. You plan steps and Hand executes them.

Available Hand primitives:
  open <target>   app name | https://URL | file path
  see             perceive current place
  do <action>     semantic intent ("\u65b0\u5efa\u7b14\u8bb0") or shortcut ("Cmd+N")

Rules:
1. Emit exactly one JSON object per message, no prose.
2. Prefer keystrokes over clicks for desktop apps.
3. If a see shows failure, retry or replan.
4. When the goal is met, emit {"step": "done", "summary": "your summary"}.
5. Never invent UI elements.
"""


def _build_prompt(goal: str, context: dict, sp: str | None = None) -> str:
    sys = sp or HAND_PLANNER_SYSTEM_PROMPT
    ctx = "\n".join(f"  {k}: {v}" for k, v in (context or {}).items())
    ctx_block = f"Context:\n{ctx}\n\n" if context else ""
    return f"{sys}\n\n{ctx_block}Goal: {goal}\n"


def _goal_met(steps) -> bool:
    return any(s.kind == "done" for s in steps)


def _last_summary(steps) -> str:
    for s in reversed(steps):
        if s.kind == "done":
            # model may use action or summary field
            return s.raw.get("summary", "") or s.raw.get("action", "") or s.action
    return ""
