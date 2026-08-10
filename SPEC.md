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

### Tier 4 - MCP-native (planned)
- opencode as MCP tool (no subprocess/SSE)
- Full bidirectional control

## Module Topology

```
hand/
  cli.py              -- CLI entry: hand plan <goal>
  router.py           -- route_open/see/do + route_plan (T1+T3) + route_plan_stream (T2)
  session.py          -- cross-turn context cache, plan_trace
  plan/
    __init__.py
    engine.py        -- PlanningEngine (opencode subprocess)
    stream_engine.py  -- StreamingEngine (opencode server + SSE)
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
