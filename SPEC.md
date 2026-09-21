# Hand V6 - Spec & Architecture
_2026-08-10 15:36 +08:00_ Alice@beings.town
 "One being, one hand."

---

## Overview

Hand is a unified GUI perception and action framework.
Beings use Hand to see screens, understand interfaces, and perform actions.

## Version Status

| Version | Date | Status | Notes |
| V5 | 2026-06 | stable | pure DDP browser control |
| V6-alpha | 2026-07 | stable | unified multi-channel |
| V6.0.0 | 2026-08-04 | released | Grove Kit v1.0.0 |
| V6.1.0 | 2026-08-05 | released | opencode planning engine |
| V6.1.1 | 2026-08-06 | released | cli.py + agent fix |
| V6.1.1b | 2026-08-10 | released | Grove bundle API fix |
| V6.2.0 | 2026-08-10 | released | Tier 2 (streaming) + Tier 3 (recovery) |
| V6.3.0 | 2026-08-10 | released | Tier 4 (MCP-native) |
| V6.4.0 | 2026-08-10 | released | Tier 5 (Proactive Self-Healing) |
| V6.5.0 | 2026-08-11 | released | Tier 4 MCP integrated into router (route_plan_mcp) |
| V6.5.1 | 2026-08-12 | released | see(NETWORK) browser network layer perception, CDP event ingestion fix |
| V6.5.2 | 2026-08-16 | released | cdp_type input chain fix, route_see kind=network place-independent, kit/sync.sh |
| V6.6.0 | 2026-08-16 | released | see(INTERACTIVE) element map, do(scroll), grounding + wheel scroll |
| V6.7.0 | 2026-08-16 | released | do(xy) 坐标桥 — 眼(元素地图坐标)→手(按坐标点击)通路，坐标契约统一物理像素 |
| V6.8.0 | 2026-08-18 | released | hand_see_vlm 视觉 LLM 模式（route_see_vlm，网络级 VLM 通道） |
| V6.8.2 | 2026-09-01 | released | cdp_shot 图片直达 being（MCP ImageContent）；route_screenshot place=None 陷阱修复 |
| V6.9.0 | 2026-09-06 | released | 感知契约 v1：see→do(xy) 坐标闭环三步验收（69 tests），acceptance-contract-v1-cdp.md |
| V6.10.0 | 2026-09-19 | released | Windows 支持（感知三角修复：cdp_shot/hand_see_vlm/cdp_see 三件套），taojun 反馈驱动 |

## Architecture Tiers

### Tier 1 - Base (stable)
```
Being goal -> cli.py -> PlanningEngine -> opencode subprocess -> steps -> router -> done
```
- Planning and execution SEPARATED
- One-shot subprocess call per goal
- No screen access during planning

### Tier 2 - Streaming (stable)
```
opencode server (persistent) -> SSE event stream -> StreamingEngine -> real-time steps
```
- Persistent opencode server (no per-goal spawn)
- SSE event stream parsed in real-time
- StreamingEngine yields steps as they arrive
- route_plan_stream() for streaming execution

### Tier 3 - Recovery (stable)
```
step fails -> build_recovery_prompt(failure context) -> PlanningEngine -> recovery steps -> retry
```
- Closed-loop feedback on step failure
- build_recovery_prompt() includes goal, failed step, recent trace
- Recovery agent knows it is mid-plan (does NOT restart from scratch)
- At most max_recoveries=3 rounds per goal
- Recovery steps inserted inline into execution sequence

### Tier 4 - MCP-native (stable)
```
Hand -> MCP stdio client -> opencode kit server.mjs -> opencode_run (async) -> poll opencode_result -> steps
```
- opencode called via MCP kit protocol - no subprocess/SSE in Hand
- Reuses kit async run/poll pattern (no 30s timeout blocking)
- Same MCP interface Portal uses - Hand and Portal share one entry point
- MCPEngine in hand/plan/mcp_engine.py
- route_plan_mcp() in hand/router_mcp.py: integrated into router, auto-fallback to Tier 1 CLI
- Dogfood-tested: engine=mcp, 4-step trace OK

### Tier 5 - Proactive Self-Healing (stable)
```
FailurePredictor
  predict(kind, action, place_set, trace) -> StepPrediction(risk, signal, healing)

HealingEngine
  heal(goal, steps, execute_fn, max_recoveries) -> result with heal_count + predictions
```
- Predicts step failure BEFORE execution, not after
- no_place -> insert_open (re-open the target if available)
- repeated_failure -> skip the duplicate action
- unknown_kind -> skip before dispatch crash
- records near-misses (predicted low but actually failed) for future learning
- Falls back to Tier 3 reactive recovery when prediction misses


## Module Topology

```
hand/
  cli.py              -- CLI entry: hand plan <goal>
  router.py           -- route_open/see/do + route_plan (T1+T3) + route_plan_stream (T2)
  router_mcp.py       -- route_plan_mcp (Tier 4, MCP-native router integration)
  session.py          -- cross-turn context cache, plan_trace
  plan/
    __init__.py
    engine.py        -- PlanningEngine (opencode subprocess)
    stream_engine.py  -- StreamingEngine (opencode server + SSE)
    mcp_engine.py     -- MCPEngine (opencode via MCP kit) [T4]
    healing.py        -- FailurePredictor + HealingEngine [T5]
    parser.py         -- parse opencode JSON event stream
    prompts.py        -- system prompt + tool contract
    tier2_prompts.py  -- streaming-optimized prompt
    recovery.py      -- RECOVERY_SYSTEM_PROMPT + build_recovery_prompt()
  backends/
    ...
  docs/
    grove_publish_sop.md
    opencode_kit_friction.md
  tests/
    test_plan.py
```

## Grove Publish Status

- Bundle uploaded (v6.1.1, hash: 4f143a)
- Method: Judy bundle API (bundle embeds manifest.json)
- SOP: docs/grove_publish_sop.md
- Grove listing: alice has 2 kits (hand + hand-v6)
