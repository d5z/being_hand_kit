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
