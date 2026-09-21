# S4 subject-2 — raw evidence appendix

Companion to `S4-subject-2-report.md`. Receipts are verbatim from the `hand` session
(`hand 0.8.0-dev`), reproduced with `json.dumps(..., ensure_ascii=False)`.

## Determinism control test (calls 15-16, no scroll between them)

```
a = hand.see(); b = hand.see()
json.dumps(a) == json.dumps(b)      -> True   (len 57843)
a['evidence']['sha256'] == b[...]   -> True   (47864599fc8406f5...)
```

## Call 17 — `hand.do("scroll top")`

```json
{
 "ok": true,
 "action": "do",
 "kind": null,
 "verb": "scroll",
 "target": "top",
 "method": "cdp_scroll",
 "url": null,
 "title": null,
 "verified": true,
 "error": null,
 "hint": null,
 "expect": null,
 "result": null,
 "evidence": {
  "scrollY_before": 2358,
  "scrollY_after": 0,
  "moved": true,
  "direction": "top",
  "read_back": "window.scrollY",
  "verified": true
 },
 "direction": "top",
 "moved": true,
 "scrollY_after": 0,
 "scrollY_before": 2358
}
```

## Call 18 — `hand.see()` (post scroll-top) vs call 15 `a` (post scroll-bottom), SAME document

```
url/title identical: https://beings.town/ | Beings Town
tree identical : True
evidence.sha256 : 47864599fc8406f5... (identical)
node_count      : 157 == 157
json.dumps equal: False

10 differing leaf fields, all y, all delta = 2358 (= scrollY):
  .handles.68.y: -877 -> 1481
  .handles.80.y: -689 -> 1669
  .handles.88.y: -527 -> 1831
  .handles.96.y: -338 -> 2020
  .handles.152.y: 366 -> 2724
  .coords.68.y: -877 -> 1481
  .coords.80.y: -689 -> 1669
  .coords.88.y: -527 -> 1831
  .coords.96.y: -338 -> 2020
  .coords.152.y: 366 -> 2724
```

## Call 19-20 — off-screen handle click

`hand.do("scroll bottom")` -> {"scrollY_before": 0, "scrollY_after": 2358, "moved": true, "direction": "bottom", "read_back": "window.scrollY", "verified": true}

`hand.do("click [80]", expect="url:/grove", timeout=8)` (stale handle map said y = -689):

```json
{
 "ok": true,
 "action": "do",
 "kind": null,
 "verb": "click",
 "target": "[80]",
 "method": "cdp_click",
 "url": null,
 "title": null,
 "verified": true,
 "error": null,
 "hint": null,
 "expect": {
  "spec": "url:/grove",
  "kind": "url",
  "needle": "/grove",
  "met": true,
  "waited_ms": 181,
  "checks": 1,
  "evidence": {
   "url": "https://beings.town/grove",
   "title": ""
  }
 },
 "page_index": 0,
 "result": "ok",
 "tiers": "handle",
 "evidence": {
  "element": "link \"Browse the Grove →\"",
  "role": "link",
  "name": "Browse the Grove →",
  "handle": "[80]",
  "backend_node_id": 66,
  "box": {
   "x": 137.9,
   "y": 300.0,
   "w": 122.7,
   "h": 16
  },
  "space": "physical",
  "dpr": 1.0,
  "dispatched": [
   138,
   300
  ],
  "read_back": "getBoundingClientRect via DOM.resolveNode",
  "source": "cdp_see(kind=a11y) handle map",
  "verified": true
 },
 "handle": "[80]"
}
```

## Call 21 — `hand.see()` after the off-screen click

```
url   : https://beings.town/grove
title : Kit Grove · Beings Town
h1    : - heading "🌳 Kit Grove" (h1) [3]
```

## Secondary observation — reload changes backend_node_id (calls 2 vs 13)

```
call 2  (beings.town, document A): nodes[1].backend_node_id = 9
call 13 (beings.town, document B, after open() re-navigation): nodes[1].backend_node_id = 12
tree text and evidence.sha256 identical in both; handles[*].y differed by the 2358 scroll offset
(confounded in that pair: reload + scroll happened together — isolated cleanly in call 17/18 above).
```

## Session audit (`hand.history()`, 21 calls)

```
[
 {
  "n": 1,
  "action": "open",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 2,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 3,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 4,
  "action": "do",
  "verb": "click",
  "target": "[80]",
  "ok": true,
  "error": null,
  "met": true
 },
 {
  "n": 5,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 6,
  "action": "open",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 7,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 8,
  "action": "open",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 9,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 10,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 11,
  "action": "open",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 12,
  "action": "do",
  "verb": "scroll",
  "target": "bottom",
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 13,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 14,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 15,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 16,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 17,
  "action": "do",
  "verb": "scroll",
  "target": "top",
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 18,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 19,
  "action": "do",
  "verb": "scroll",
  "target": "bottom",
  "ok": true,
  "error": null,
  "met": null
 },
 {
  "n": 20,
  "action": "do",
  "verb": "click",
  "target": "[80]",
  "ok": true,
  "error": null,
  "met": true
 },
 {
  "n": 21,
  "action": "see",
  "verb": null,
  "target": null,
  "ok": true,
  "error": null,
  "met": null
 }
]
```

---

# Addendum — F13/F14/F15/F16 raw material (second verification pass, calls 22-24)

## Calls 22-24 — three `see(kind=…)` probes returned a page I never opened

My previous call (21) left the session on `https://beings.town/grove`. No navigation happened on my side.

```
call 22 see(kind="screenshot") -> url=http://127.0.0.1:33673/basic  title=Fixture Basic  method=cdp_a11y
call 23 see(kind="vlm")        -> url=None  title=None  method=vision_llm  model=qwen/qwen3-vl-8b-instruct  source=cdp
call 24 see(kind="interactive")-> url=None  title=None  method=cdp_interactive  count=2
hand.handles() (same moment)   -> root name "Fixture Big", backend_node_id 3631...
```

### call 22 receipt (a11y-shaped, `kind` field says `screenshot`, no image anywhere)

```json
{
 "ok": true,
 "action": "see",
 "kind": "screenshot",
 "method": "cdp_a11y",
 "url": "http://127.0.0.1:33673/basic",
 "title": "Fixture Basic",
 "verified": true,
 "error": null,
 "hint": null,
 "expect": null,
 "tree": "- RootWebArea \"Fixture Basic\" (focusable) [1]\n- heading \"Fixture Basic\" (h1) [2]\n- paragraph \"\" [4]\n  - StaticText \"Deterministic page for hand L2 integration.\" [5]\n- link \"Go to form\" [6]\n- button \"Mark\" [8]",
 "handles": {
  "1": {
   "role": "RootWebArea",
   "name": "Fixture Basic",
   "backend_node_id": 15,
   "interactive": false,
   "x": null,
   "y": null
  },
  "2": {
   "role": "heading",
   "name": "Fixture Basic",
   "backend_node_id": 20,
   "interactive": false,
   "x": null,
   "y": null
  },
  "4": {
   "role": "paragraph",
   "name": "",
   "backend_node_id": 21,
   "interactive": false,
   "x": null,
   "y": null
  },
  "5": {
   "role": "StaticText",
   "name": "Deterministic page for hand L2 integration.",
   "backend_node_id": 25,
   "interactive": false,
   "x": null,
   "y": null
  },
  "6": {
   "role": "link",
   "name": "Go to form",
   "backend_node_id": 22,
   "interactive": true,
   "x": 44,
   "y": 123
  },
  "8": {
   "role": "button",
   "name": "Mark",
   "backend_node_id": 23,
   "interactive": true,
   "x": 106,
   "y": 124
  }
 },
 "coords": {
  "6": {
   "x": 44,
   "y": 123
  },
  "8": {
   "x": 106,
   "y": 124
  }
 },
 "truncated": false,
 "nodes_omitted": 0,
 "text_truncated_count": 0,
 "node_count": 6,
 "line_count": 6,
 "serialized_bytes": 208,
 "sha256": "2d42220272c264d1637ab23241fba3783b8df071197328cccb6e941d555c27ea",
 "format": "a11y-v2.1",
 "ax_version": {
  "product": "HeadlessChrome/151.0.7922.34",
  "protocol": "1.3",
  "tree": "Accessibility.getFullAXTree"
 },
 "header": "#p0 r:3E8EA2F4 Fixture Basic | http://127.0.0.1:33673/basic",
 "page_index": 0,
 "coord": {
  "space": "physical",
  "dpr": 1,
  "viewport": {
   "w": 800,
   "h": 600
  },
  "image": {
   "w": 800,
   "h": 600,
   "scale": 1.0
  },
  "coords_space": "physical"
 },
 "evidence": {
  "backend": "cdp_a11y",
  "node_count": 6,
  "raw_node_count": 15,
  "serialized_bytes": 208,
  "truncated": false,
  "nodes_omitted": 0,
  "text_truncated_count": 0,
  "format": "a11y-v2.1",
  "ax_version": {
   "product": "HeadlessChrome/151.0.7922.34",
   "protocol": "1.3",
   "tree": "Accessibility.getFullAXTree"
  },
  "sha256": "2d42220272c264d1637ab23241fba3783b8df071197328cccb6e941d555c27ea",
  "root_role": "RootWebA
... [tree/nodes truncated here] ...
```

### call 23 receipt (VLM works on this Linux box)

```json
{
 "ok": true,
 "action": "see",
 "kind": "vlm",
 "method": "vision_llm",
 "url": null,
 "title": null,
 "verified": null,
 "error": null,
 "hint": null,
 "expect": null,
 "evidence": null,
 "model": "qwen/qwen3-vl-8b-instruct",
 "source": "cdp",
 "text": "截图显示一个极简网页，标题为“Fixture Basic”，副标题说明是“用于手L2集成的确定性页面”。页面左上角有蓝色“Go to form”链接和灰色“Mark”按钮。整体为纯白背景，黑色文字，无图片或复杂图标。布局简洁，仅包含标题、说明文字和两个交互元素，用于技术或测试场景。"
}
```

### call 24 receipt (`interactive`)

```json
{
 "ok": true,
 "action": "see",
 "kind": "interactive",
 "method": "cdp_interactive",
 "url": null,
 "title": null,
 "verified": true,
 "error": null,
 "hint": null,
 "expect": null,
 "truncated": false,
 "page_index": 0,
 "coord": {
  "space": "physical",
  "dpr": 1,
  "viewport": {
   "w": 800,
   "h": 600
  },
  "image": {
   "w": 800,
   "h": 600,
   "scale": 1.0
  }
 },
 "evidence": {
  "backend": "cdp_interactive",
  "count": 2,
  "total": 2,
  "verified": true
 },
 "count": 2,
 "elems": [
  {
   "tag": "A",
   "text": "Go to form",
   "selector": "#to-form",
   "x": 43.5546875,
   "y": 123.375,
   "w": 71.109375,
   "h": 17,
   "in_viewport": true,
   "occluded": false,
   "visible": true
  },
  {
   "tag": "BUTTON",
   "text": "Mark",
   "selector": "#mark",
   "x": 105.921875,
   "y": 124.375,
   "w": 45.625,
   "h": 21,
   "in_viewport": true,
   "occluded": false,
   "visible": true
  }
 ],
 "total": 2
}
```

## Source evidence that the browser endpoint and the handle map are machine-global

```
hand/perception/cdp_core.py:8    CDP_HOST = 'http://localhost:9222'
hand/perception/cdp_core.py:11   LAST_STATE_FILE = '/tmp/hand_cdp_last_idx'
hand/perception/cdp_launcher.py:34  CDP_PORT = 9222
hand/perception/cdp_launcher.py:144 """Is a CDP endpoint already answering on 9222?"""
hand/perception/cdp_launcher.py:164 PROFILE_DIR_NAME = ".chrome-profile"
hand/perception/cdp_launcher.py:216 f"--remote-debugging-port={CDP_PORT}"
hand/perception/ax_tree.py:83    HANDLE_MAP_FILE = "/tmp/hand_ax_handles.json"
hand/perception/ax_tree.py:363-379  resolve_handle(): handles = load_handle_map(path)  <-- reads the FILE
                                    at action time, not per-session memory
```

## Live process evidence (read-only)

```
ps: exactly one CDP endpoint
  chrome-headless-shell --remote-debugging-port=9222 --user-data-dir=/home/alice/Hand/kit/.chrome-profile ...
  PID turnover: 1016206 @23:04 -> 1016935 @23:05 -> 1017834 @23:07:27
  defunct chrome-headless-shell processes from 22:15 and 22:43
ss: LISTEN 127.0.0.1:9222 users:("chrome-headless",pid=1016206)
ls /tmp/hand_*:  hand_ax_handles.json (Sep 21 23:04...)   hand_cdp_last_idx (Sep 21 23:04)
```

## Passive proof of a concurrent writer (no hand calls from me during the window)

```
before : 2026-09-21 23:06:35.193882128 +0800  723 bytes  root name: Fixture Basic  handles: 6
sleep 25   (I made zero hand calls)
after  : 2026-09-21 23:06:54.757918479 +0800  706 bytes  root name: Fixture Basic  handles: 6
=> another process rewrote /tmp/hand_ax_handles.json while my session was idle
```

## Timeline

```
22:41-22:43  another agent's fixture work in /tmp/hand_doc_check (page1.html, run*.py, out.json)
23:02:07/23:02:40  this report + evidence appendix written (my task answers were all collected before this)
23:04-23:07  my calls 22-24 hit that other session's fixture; Chrome restarted 3x in ~3 minutes
```
