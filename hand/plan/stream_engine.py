"""StreamingEngine - Tier 2: persistent opencode server + multi-turn planning."""

import json, os, re, shutil, subprocess, time
from dataclasses import dataclass, field
from typing import Optional
from .parser import Step, STEP_KINDS
from .tier2_prompts import HAND_PLANNER_STREAM_PROMPT

_UNSET = object()

_OPENCODE_CANDIDATES = [
    "/home/alice/.local/bin/opencode",
    "/usr/local/bin/opencode",
    "/usr/bin/opencode",
]

def _find_opencode():
    found = shutil.which("opencode")
    if found: return found
    for p in _OPENCODE_CANDIDATES:
        if os.path.isfile(p) and os.access(p, os.X_OK): return p
    return None

_STEP_JSON_RE = re.compile(r'\{\s*"step"\s*:\s*"([a-z]+)"')

@dataclass
class StreamStep:
    step: Step
    result: dict = field(default_factory=dict)
    error: Optional[str] = None

class StreamingEngine:
    def __init__(self, port=14096, host="127.0.0.1", model=None, agent="build", opencode_bin=_UNSET, timeout=120):
        self.port = port
        self.host = host
        self.model = model
        self.agent = agent
        self.timeout = timeout
        self.opencode_bin = _find_opencode() if opencode_bin is _UNSET else opencode_bin
        self._server_proc = None
        self._session_id = None
        self._base_url = None

    def start_server(self):
        if not self.opencode_bin: return False
        if self._server_proc and self._server_proc.poll() is None: return True
        self._server_proc = subprocess.Popen(
            [self.opencode_bin, "serve", "--port", str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(30):
            if self._server_proc.poll() is not None: return False
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                r = s.connect_ex((self.host, self.port))
                s.close()
                if r == 0:
                    self._base_url = f"http://{self.host}:{self.port}"
                    return True
            except: pass
            time.sleep(0.2)
        return False

    def stop_server(self):
        if self._server_proc and self._server_proc.poll() is None:
            self._server_proc.terminate()
            try: self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired: self._server_proc.kill()
        self._server_proc = None
        self._session_id = None
        self._base_url = None

    def plan_stream(self, goal, context=None, max_steps=20):
        if not self.opencode_bin:
            return [StreamStep(Step(kind="error",action="opencode not found"),error="binary not found")]
        if not self._base_url:
            if not self.start_server():
                return [StreamStep(Step(kind="error",action="server failed"),error="could not start server")]

        ctx_parts = []
        if context:
            for k,v in context.items(): ctx_parts.append(f"  {k}: {v}")
        ctx_block = f"Context:\n{chr(10).join(ctx_parts)}\n\n" if ctx_parts else ""
        initial = f"{HAND_PLANNER_STREAM_PROMPT}\n\n{ctx_block}Goal: {goal}\n\nOutput your first step:"
        trace = []

        for turn in range(max_steps):
            r = self._send_message(initial if turn == 0 else None)
            if r is None:
                trace.append(StreamStep(Step(kind="error",action="no response"),error=f"no response turn {turn}"))
                break
            step_obj, sid = r
            self._session_id = sid
            if step_obj.kind == "done":
                trace.append(StreamStep(step_obj,result={"ok":True,"summary":step_obj.action}))
                break
            if step_obj.kind == "error":
                trace.append(StreamStep(step_obj,error=step_obj.action))
                break
            exec_result = self._execute_step(step_obj)
            trace.append(StreamStep(step_obj,result=exec_result))
            initial = f"Step {turn+1} result: {json.dumps(exec_result)}\n\nOutput your next step:"
        return trace

    def _send_message(self, message=None):
        cmd = [self.opencode_bin, "run", "--attach", self._base_url, "--format", "json"]
        if self._session_id: cmd += ["-s", self._session_id]
        if self.model: cmd += ["-m", self.model]
        if self.agent: cmd += ["--agent", self.agent]
        cmd += ["--auto"]
        if message: cmd.append(message)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired: return None
        if proc.returncode != 0: return None
        return self._parse_response(proc.stdout)

    def _parse_response(self, stdout):
        session_id = None
        full_text = ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line: continue
            try: ev = json.loads(line)
            except: continue
            sid = ev.get("sessionID") or ev.get("part",{}).get("sessionID")
            if sid: session_id = sid
            if ev.get("type") == "text":
                text = ev.get("part",{}).get("text","")
                if text: full_text += text + "\n"
        if not full_text.strip(): return None
        step = self._extract_step(full_text)
        if step is None: return None
        return step, session_id

    def _extract_step(self, text):
        for m in _STEP_JSON_RE.finditer(text):
            kind = m.group(1)
            if kind not in STEP_KINDS: continue
            start = m.start()
            end = text.find("}", m.end())
            if end == -1: continue
            try: obj = json.loads(text[start:end+1])
            except: continue
            action = obj.get("action") or obj.get("target") or obj.get("summary") or obj.get("url") or ""
            return Step(kind=kind, action=action, raw=obj)
        return None

    def _execute_step(self, step):
        try:
            from hand.router import route_open, route_see, route_do
            if step.kind == "open": return route_open(step.action)
            elif step.kind == "see": return route_see()
            elif step.kind == "do":
                result = route_do(step.action)
                try:
                    after = route_see()
                    result["after_see"] = after
                except: pass
                return result
            else: return {"error": f"unknown step kind: {step.kind}"}
        except Exception as e: return {"error": str(e)}
