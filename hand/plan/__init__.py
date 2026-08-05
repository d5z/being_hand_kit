"""hand/plan — opencode planning engine for Hand V6.1.

PlanningEngine spawns opencode CLI to convert natural-language goals
into structured sequences of Hand primitives (open / see / do / verify).

Usage:
    from hand.plan import PlanningEngine, plan

    engine = PlanningEngine()
    steps = engine.plan("新建一个笔记并写入今天的日期")
    for step in steps:
        print(f"[{step.kind}] {step.action}")
"""

from .engine import PlanningEngine
from .parser import Step, parse_events

__all__ = ["PlanningEngine", "Step", "parse_events", "plan"]

# Convenience: default engine instance
plan = PlanningEngine()
