"""MCPEngine - Tier 4: call opencode via MCP kit protocol.

Instead of spawning opencode CLI directly (Tier 1) or managing a server
process (Tier 2), MCPEngine connects to the opencode kit's MCP server
via stdio and uses its async run/poll pattern.

This is the same MCP interface that Portal uses - Hand and Portal share
a single entry point for opencode.
"""

import json
import os
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from .parser import Step, parse_events
from .prompts import HAND_PLANNER_SYSTEM_PROMPT, _build_prompt, _goal_met, _last_summary

# Path to the kit's server.mjs
KIT_SERVER_PATH = os.path.expanduser('~/.heart-portal/kits/opencode/server.mjs')


@dataclass
class MCPPlanningResult:
    """Outcome of an MCP-based planning run."""
    goal: str
    steps: list = field(default_factory=list)
    ok: bool = False
    summary: str = ''
    error: str | None = None
    run_id: str = ''


class MCPEngine:
    """Plan via opencode kit's MCP tools (async run/poll pattern)."""

    def __init__(self, kit_path: str | None = None, model: str | None = None,
                 agent: str = 'build', timeout: int = 180):
        self.kit_path = kit_path or self._find_kit()
        self.model = model
        self.agent = agent
        self.timeout = timeout

    def plan(self, goal: str, context: dict | None = None) -> MCPPlanningResult:
        """Run the planner via MCP."""
        if not self.kit_path:
            return MCPPlanningResult(
                goal=goal, ok=False,
                error='opencode kit not found'
            )

        prompt = _build_prompt(goal, context or {})
        full_prompt = prompt + chr(10)*2 + 'Output your plan as JSON step objects.'

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._mcp_plan(full_prompt))
            loop.close()
            return result
        except Exception as e:
            return MCPPlanningResult(goal=goal, ok=False, error=str(e))

    def _find_kit(self) -> str | None:
        if os.path.isfile(KIT_SERVER_PATH):
            return KIT_SERVER_PATH
        return None

    async def _mcp_plan(self, prompt: str) -> MCPPlanningResult:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession

        params = StdioServerParameters(
            command='node',
            args=[self.kit_path],
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                run_result = await session.call_tool('opencode_run', {
                    'prompt': prompt,
                    'directory': os.getcwd(),
                    'model': self.model or 'opencode/deepseek-v4-flash-free',
                    'timeout': self.timeout,
                })

                run_data = self._parse_tool_result(run_result)
                run_id = run_data.get('run_id', '')
                if not run_id:
                    return MCPPlanningResult(goal=prompt[:100], ok=False,
                        error='no run_id returned from opencode_run')

                import time
                deadline = time.time() + self.timeout
                while time.time() < deadline:
                    await asyncio.sleep(2)
                    poll_result = await session.call_tool('opencode_result', {
                        'run_id': run_id
                    })
                    poll_data = self._parse_tool_result(poll_result)
                    status = poll_data.get('status', 'unknown')

                    if status == 'done':
                        stdout = poll_data.get('stdout', '')
                        stderr = poll_data.get('stderr', '')
                        steps = parse_events(stdout, stderr)
                        ok = _goal_met(steps)
                        return MCPPlanningResult(goal=prompt[:100], steps=steps,
                            ok=ok, summary=_last_summary(steps), run_id=run_id)
                    elif status in ('error', 'timeout'):
                        error_msg = (poll_data.get('error', '') or
                                     poll_data.get('stderr', '') or
                                     'status: ' + status)
                        return MCPPlanningResult(goal=prompt[:100], ok=False,
                            error=error_msg, run_id=run_id)

                return MCPPlanningResult(goal=prompt[:100], ok=False,
                    error='timed out after ' + str(self.timeout) + 's polling', run_id=run_id)

    def _parse_tool_result(self, result) -> dict:
        try:
            if hasattr(result, 'content') and result.content:
                text = result.content[0].text
                if text:
                    return json.loads(text)
            return {}
        except (json.JSONDecodeError, IndexError, AttributeError):
            return {}


# Convenience: default engine instance
mcpplan = MCPEngine()
