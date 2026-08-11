# Changelog

## [1.6.0] - 2026-08-12

#### Added
- **see(NETWORK)**: hand/perception/cdp_network.py
- network_snapshot() captures HTTP request/response via CDP
- bypasses cdp_call() event ingestion bug
- router.py: SEE_PRIORITY updated, kind=network dispatch

## [1.5.0] - 2026-08-11

#### Added
- **Tier 4 MCP router integration**: hand/router_mcp.py with route_plan_mcp()
- Uses MCPEngine when kit available, auto-fallback to Tier 1 CLI
- Tier 3 recovery built-in on both MCP and CLI paths
- Dogfood test: engine=mcp confirmed, 4-step trace with mock routing OK

## [1.4.0] - 2026-08-10

#### Added
- **Tier 5 - Proactive Self-Healing**: hand/plan/healing.py (FailurePredictor + HealingEngine), route_plan_healing() in router
- FailurePredictor: predicts step risk BEFORE execution (no_place, repeated_failure, unknown_kind)
- HealingEngine: wraps execution loop with preventive healing (re-open, skip, replan)
- SPEC.md: Tier 5 marked stable, module topology updated

# Changelog

## [1.3.0] - 2026-08-10

#### Added
- **Tier 4 - MCP-native**: MCPEngine (hand/plan/mcp_engine.py), calls opencode via MCP kit protocol (no subprocess/SSE)
- plan/__init__.py exports MCPEngine + mcpplan default instance
- SPEC.md: Tier 4 marked stable, module topology updated

# Changelog

## [1.2.0] - 2026-08-10

#### Added
- **Tier 2 - Streaming**: StreamingEngine (opencode server + SSE), tier2_prompts.py, route_plan_stream()
- **Tier 3 - Recovery**: recovery.py (RECOVERY_SYSTEM_PROMPT + build_recovery_prompt()), route_plan() now supports max_recoveries=3 param
- SPEC.md: Architecture Tiers section documenting Tier 1-4 architecture

#### Fixed
- Recovery prompt encoding issues (first attempts failed due to shell escaping)

## [1.1.1b] - 2026-08-10

#### Fixed
- Grove publish: use Judy bundle API (bundle embeds manifest.json)
- SPEC.md restored from git (was truncated on disk)
- Docs topology aligned to actual code (cli.py, docs/, tests/)

## [1.1.1] - 2026-08-06

#### Added
- cli.py - hand plan <goal> CLI entry (--json/--model/--session)

#### Fixed
- engine.py: agent name plan -> build (opencode has no plan agent)
- agent.md: marked NOT auto-loaded by opencode
- PLAN-opencode.md: rewritten agent strategy

## [1.1.0] - 2026-08-05

#### Added - V6.1 planning layer
- hand/plan/ module - planning engine
- route_plan() - router planning route
- plan_trace - session planning trace
- hand_plan MCP tool
- tests/test_plan.py (15 cases)

#### Changed
- Version 1.0.0 -> 1.1.0 (V6.1.0)
- SPEC.md planning layer architecture

## [1.0.0] - 2026-08-04

#### Added
- Hand Kit v1.0.0 Grove release
- SPEC.md full module topology
- Docs system (SPEC/CHANGELOG/ROADMAP)

## [0.1.0] - 2026-07

#### Added
- Hand V6 unified framework prototype
- CDP, AX, OCR modules
- Session, Router
