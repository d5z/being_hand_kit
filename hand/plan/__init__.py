"""hand/plan - opencode planning engine for Hand V6.

PlanningEngine spawns opencode CLI to convert natural-language goals
into structured sequences of Hand primitives (open / see / do / verify).
MCPEngine (Tier 4) calls opencode via the MCP kit protocol instead.

Usage:
    from hand.plan import PlanningEngine, plan
    from hand.plan import MCPEngine, mcpplan
"""

from .engine import PlanningEngine
from .parser import Step, parse_events
from .mcp_engine import MCPEngine, MCPPlanningResult

__all__ = ["PlanningEngine", "Step", "parse_events", "plan",
           "MCPEngine", "MCPPlanningResult", "mcpplan"]

plan = PlanningEngine()
mcpplan = MCPEngine()
