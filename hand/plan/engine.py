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
from .prompts import HAND_PLANNER_SYSTEM_PROMPT, _build_prompt, _goal_met, _last_summary

# Sentinel to distinguish "not provided" from explicit None
_UNSET = object()


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

    def __init__(self, cwd=".", model=None, agent="build", system_prompt=None,
                 timeout=300, opencode_bin=_UNSET):
        self.cwd = cwd
        self.model = model
        self.agent = agent
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.opencode_bin = _find_opencode() if opencode_bin is _UNSET else opencode_bin

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
