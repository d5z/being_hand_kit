"""Parse opencode run --format json event stream into ordered Step objects."""

import json
import re
from dataclasses import dataclass, field

STEP_KINDS = {"open", "see", "do", "verify", "done", "error"}


@dataclass
class Step:
    """A single planned Hand primitive."""
    kind: str          # open | see | do | verify | done | error
    action: str = ""
    raw: dict = field(default_factory=dict)


def parse_events(stdout: str, stderr: str = "") -> list[Step]:
    """Parse opencode JSONL event stream into ordered Steps.

    opencode emits one JSON object per line in --format json mode.
    Hand steps appear as {"step": ...} JSON objects, either:
    (a) as top-level lines, or
    (b) embedded in assistant text content (type: "text" events).
    """
    steps: list[Step] = []
    seen_done = False

    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue

        objs: list[dict] = []
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            # not JSON — skip (opencode sometimes emits non-JSON headers)
            continue

        if _is_step(ev):
            # case (a): line is itself a step object
            objs = [ev]
        else:
            # case (b): step embedded in opencode event payload
            text = _extract_text(ev)
            if text:
                objs = _find_step_objects(text)

        for obj in objs:
            if seen_done and obj.get("step") != "done" and obj.get("step") != "error":
                continue  # nothing after done matters
            steps.append(_to_step(obj))
            if obj.get("step") == "done":
                seen_done = True

    return steps


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _is_step(ev) -> bool:
    return isinstance(ev, dict) and ev.get("step") in STEP_KINDS


def _extract_text(ev: dict) -> str:
    """Pull human-readable text from various opencode event shapes."""
    # opencode event types: text, tool_use, step_start, step_finish, etc.
    ev_type = ev.get("type", "")

    if ev_type == "text" or ev_type == "assistant_message" or ev_type == "message":
        # direct text content
        part = ev.get("part", {})
        if isinstance(part, dict):
            text = part.get("text", "")
            if text:
                return text
        text = ev.get("text", "")
        if text:
            return text

    # data.text — common in tool_use responses
    data = ev.get("data")
    if isinstance(data, dict):
        text = data.get("text", "")
        if text:
            return text

    # message.content
    msg = ev.get("message")
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if content:
            return content

    return ""


# Match {"step": "kind", ...} objects
_STEP_RE = re.compile(
    r'\{\s*"step"\s*:\s*"([a-z]+)"\s*,\s*'
    r'"([a-z_]+)"\s*:\s*("[^"]*"|[^,}]+)'
)


def _find_step_objects(text: str) -> list[dict]:
    """Extract {"step": ...} object(s) from assistant text."""
    found: list[dict] = []
    for m in _STEP_RE.finditer(text):
        kind = m.group(1)
        if kind not in STEP_KINDS:
            continue
        obj = {"step": kind}
        start = m.start()
        end = text.find("}", m.end())
        if end != -1:
            try:
                parsed = json.loads(text[start:end + 1])
                obj.update(parsed)
            except json.JSONDecodeError:
                # fallback: use the captured value
                val = m.group(3).strip("'")
                obj[m.group(2)] = val.strip('"')
        found.append(obj)
    return found


def _to_step(obj: dict) -> Step:
    kind = obj.get("step", "error")
    action = obj.get("action", "") or obj.get("summary", "") or obj.get("target", "") or obj.get("path", "") or obj.get("url", "") or ""
    return Step(kind=kind, action=action, raw=obj)
