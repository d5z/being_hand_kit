# Plan — Integrate opencode as Hand's Planning Engine

_Proposal · 2026-08-05 · Hand V6.1_

> **Goal:** Turn Hand from a *single primitive at a time* (`open` / `see` / `do`)
> into a *goal-driven* framework. The Being states a goal in natural language;
> opencode plans the sequence of Hand primitives and drives them to completion.

---

## 1. Concept & Architecture

Hand keeps its 4-layer topology (`router` / `session` / `perception` / `action`).
opencode is added as a **planning engine** — a fifth layer that sits above the
router and emits decisions, never sensing or touching the screen itself.

```
Being (goal, natural language)
        │
        ▼
┌─────────────────────────┐
│  hand/plan/engine.py    │  ← NEW: PlanningEngine (calls opencode CLI)
│  "what should I do"     │
└─────────────────────────┘
        │  opencode agent returns structured steps
        ▼
┌─────────────────────────┐
│  hand/router.py         │  ← route_plan() → route_see() / route_do()
│  "how do I do it"       │     dispatches each step to the right backend
└─────────────────────────┘
        │
        ▼
┌───────────────┐  ┌───────────────┐
│  perception/  │  │  action/      │
│  (read-only)  │  │  (write-only) │
└───────────────┘  └───────────────┘
```

**Division of responsibility**

| Concern | Owner |
|---|---|
| Sensing screen / DOM / AX tree | `hand/perception/*` |
| Executing clicks / keys / types | `hand/action/*` |
| Backend selection & fallback | `hand/router.py` |
| Cross-turn place context | `hand/session.py` |
| **Goal interpretation, planning, retry, verification** | **opencode agent** |
| Speaking to opencode from Python | `hand/plan/engine.py` (new) |

This preserves all four core design principles in SPEC.md: perception/action
stay separated, routing stays decoupled, session stays transparent, and the
whole thing still ships as a Grove Kit.

---

## 2. Files to Create / Modify

### New files

| File | Purpose |
|---|---|
| `hand/plan/__init__.py` | Package marker, exports `PlanningEngine`, `plan` |
| `hand/plan/engine.py` | `PlanningEngine` class — spawns/attaches opencode, feeds goals, collects steps |
| `hand/plan/prompts.py` | System prompt + tool contract handed to the opencode agent (Hand primitives, place types, output schema) |
| `hand/plan/parser.py` | Parses `opencode run --format json` event stream into ordered `Step` objects |
| `hand/plan/agent.md` | Custom opencode agent definition `hand-planner` (see §5) |
| `tests/test_plan.py` | Unit tests for parser + a dry-run engine test (no screen needed) |
| `hand/kit/hand-plan-manifest.json` | Companion Grove manifest for the planning tool (v1.1.0) |

### Modified files

| File | Change |
|---|---|
| `hand/router.py` | Add `route_plan(goal, steps=None)` — turns a goal or explicit step list into `see`/`do` dispatches; loops with verify; collects a trace |
| `hand/session.py` | Add `plan_trace: list` field to `Session` (audit trail of steps + results); reuse `clear()` to reset it |
| `hand/cli.py` | Add `hand plan <goal>` command; stream step progress to terminal |
| `hand/__init__.py` | Bump `__version__` to `6.1.0`; document `plan` primitive in docstring |
| `SPEC.md` | Add `plan/` to module topology + dependency matrix; add `plan` to MCP tool list |
| `ROADMAP.md` | Promote "planning engine" into V6.1 next-step milestone |
| `.gitignore` | Add `.opencode/`, `*.opencode-session.json` (local session artifacts) |

### Module topology after change (for SPEC.md update)

```
hand/
├── router.py            # open / see / do / plan
├── session.py           # + plan_trace
├── plan/                # NEW — opencode planning engine
│   ├── __init__.py
│   ├── engine.py
│   ├── prompts.py
│   └── parser.py
├── perception/          # unchanged
├── action/              # unchanged
└── kit/                 # + hand-plan manifest
```

---

## 3. How opencode CLI Is Called from Python

Three escalation tiers. V6.1 ships **Tier 1**; Tier 2 and 3 are staged.

### Tier 1 — one-shot subprocess (default, v1)

Blocking, stateless-per-call but resumable via `-s <session>`. No daemon needed.

```python
# hand/plan/engine.py
import json, subprocess, os

class Step:
    kind: str          # "see" | "do" | "verify" | "done" | "error"
    action: str
    raw: dict

class PlanningEngine:
    def __init__(self, cwd=".", model=None, agent="hand-planner", timeout=300):
        self.cwd, self.model, self.agent, self.timeout = cwd, model, agent, timeout
        self.session_id = os.environ.get("OPENCODE_PLAN_SESSION")

    def plan(self, goal: str, context: dict | None = None) -> list[Step]:
        prompt = build_prompt(goal, context)          # prompts.py
        cmd = ["opencode", "run", prompt, "--format", "json",
               "--agent", self.agent, "--dir", self.cwd]
        if self.model:     cmd += ["-m", self.model]
        if self.session_id: cmd += ["-s", self.session_id]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        return parse_events(proc.stdout)              # parser.py → ordered Steps
```

* `--format json` emits one JSON event per line → trivially streamable/parseable.
* `-s` (session id) continues the same model conversation across `hand plan` calls,
  so the agent remembers what it already `see`-ed.
* The agent is sandboxed: it can **only** emit structured Hand steps (see §4),
  it never gets shell/browser tools.

### Tier 2 — persistent server + attach (streaming, v6.2)

Keeps a warm model and live SSE stream; Hand updates the terminal per-step.

```python
server = subprocess.Popen(["opencode", "serve", "--port", "4096"])
proc   = subprocess.Popen(
    ["opencode", "run", goal, "--format", "json",
     "--attach", "http://127.0.0.1:4096",
     "-s", self.session_id, "--agent", self.agent],
    stdout=subprocess.PIPE, text=True,
)
for line in proc.stdout:
    event = json.loads(line)          # incrementally build Step list
    self._emit(event)                 # notify CLI UI
```

### Tier 3 — MCP-native (the endgame, aligns with Grove Kit)

Hand already ships an MCP Kit. Register it with opencode:

```
opencode mcp add hand -- <path>/hand-kit-mcp  # serves the 7+ hand tools
```

The planner becomes a real opencode agent whose tool list **is** Hand's MCP
tools. `route_plan` degrades to a thin proxy: forward the goal, relay the
agent's tool-call events. This is the "one being, one hand" long-term vision
in ROADMAP.md — the Being drives the Hand directly through opencode, with Hand
providing only perception + actuation.

**Recommended path:** Tier 1 for V6.1 (zero infra, testable headlessly),
Tier 2 as soon as streaming UI is wanted, Tier 3 when Grove endpoints are
confirmed (blocks V6.1 per ROADMAP anyway).

---

## 4. The Hand ⇄ opencode Contract

The agent is constrained to emit one JSON step per tool-call. `hand/plan/prompts.py`
renders this system prompt:

```text
You are hand-planner, the planning brain of Hand (a GUI perception/action
framework). You DO NOT touch the screen. You plan steps and Hand executes them.

Available Hand primitives:
  open <target>      app name | https://URL | file path
  see                perceive current place (ax_app / ax_ui / vision_ocr / cdp_dom)
  do <action>        semantic intent ("新建笔记") or shortcut ("Cmd+N")

Rules:
1. Emit exactly one JSON object per message, no prose:
   {"step": "do", "action": "Cmd+N"}
   {"step": "see"}            // always verify after a "do"
2. Prefer keystrokes over clicks for desktop apps (more reliable).
3. If a "see" shows failure or an unexpected state, emit a retry or replan.
4. When the goal is met, emit {"step": "done", "summary": "..."}.
5. Never invent UI elements — only act on what a "see" result showed.
```

`hand/plan/parser.py` maps each JSON event line to a `Step`:

```python
STEP_KINDS = {"open", "see", "do", "verify", "done", "error"}

def parse_events(stdout: str) -> list[Step]:
    steps = []
    for line in stdout.splitlines():
        try:                    ev = json.loads(line)
        except json.JSONDecodeError: continue
        text = ev.get("data", {}).get("text") or ev.get("message", "")
        # extract the {"step": ...} object from assistant tool-call content
        ...
    return steps
```

---

## 5. Custom opencode Agent (`hand/plan/agent.md`)

Registered so `--agent hand-planner` resolves. Kept tiny and hand-only.

```markdown
# hand-planner

Hand's planning brain. Plans sequences of GUI operations; never executes them.
- Tools: none beyond message output (steps are parsed from JSON text).
- Model: default or `-m provider/model` (e.g. high-reasoning variant).
- Session: resume with `-s` so cross-call context persists in `hand/session`.
- System prompt injected from `hand/plan/prompts.py`.
```

(If Tier 3 ships, replace "none" with the Hand MCP tool set.)

---

## 6. User Experience

### Happy path

```bash
$ hand plan "把这段话复制到新笔记"
→ [plan] open Notes … ok (desktop_app)
→ [plan] see → ax_app: 3 notes ["Reading", "Grocery", "Sketch"]
→ [plan] do Cmd+N → new note created
→ [plan] type "Read SPEC.md + ROADMAP.md, then propose…" → ok
→ [plan] verify see → 1 note titled "Untitled" ✓
→ [plan] done — summary: "Created a new note and typed the text."
→ [trace] saved to session.plan_trace (5 steps, 2.1s, backend=keystroke+ax_ui)
```

### Being (API) view

```python
from hand.plan import plan
result = plan("把这段话复制到新笔记", context={"text": "...", "from": session})
# result = {
#   "method": "plan",
#   "goal": "...",
#   "steps": [ {kind, action, result}, ... ],
#   "ok": True,
#   "summary": "Created a new note and typed the text.",
# }
```

### Failure / retry path

```bash
$ hand plan "在 Chrome 里搜索 opencode"
→ [plan] open https://google.com … ok
→ [plan] see → vision_ocr (cdp_dom failed: no debug port) — using OCR fallback ✓
→ [plan] do type "opencode" → error: type box not found
→ [plan] see → OCR shows search box at (x, y)
→ [plan] do click search box → ok
→ [plan] do type "opencode" → ok
→ [plan] done — summary: "Searched for 'opencode' in Chrome."
```

### Observable behaviors

- **Transparency:** every step is printed as it happens; no hidden actions.
- **Verification:** `do` is always followed by `see` unless the agent says otherwise.
- **Resumability:** Ctrl-C then `hand plan "继续"` resumes via `-s` session id.
- **Audit:** full step trace lands in `session.plan_trace` and JSON on disk.

---

## 7. Acceptance Criteria (V6.1)

1. `hand plan "新建一个笔记并写入今天的日期"` completes on Notes end-to-end.
2. Parser unit tests pass: `pytest tests/test_plan.py` (event-stream fixtures, no screen).
3. `hand plan` degrades gracefully when opencode binary is missing
   → clear error, no hang.
4. SPEC.md / ROADMAP.md updated to document the `plan/` layer.
5. `--format json` events fully parsed into ordered `Step`s; `plan_trace` populated.
