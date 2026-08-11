# see(NETWORK) - Browser Network Perception

PRD - 2026-08-12 - Alice - Hand v6.6.0

---

## Motivation

Hand currently perceives browsers in one dimension: DOM.
see() reads page text. see(screenshot) captures visual.
But modern web apps move critical data through XHR/fetch responses.

A page may say Loading while an API already returned 500.
DOM is skin. Network is blood. A being needs to see the data flow.

## Goal

Two granularity levels:

| Level | Call | Returns | Use case |
|---|---|---|---|
| Summary | see(NETWORK) | Request table: method, URL, status, size, content-type | See what data is flowing |
| Detail | see(NETWORK, request_id=3) | Full response body | Dive into a specific request |

## Design Principles

1. Do not return bodies by default. A page has dozens of requests, each potentially MB-sized JS bundles. Surface first, then dive.

2. Auto-include small JSON bodies. When content-type is application/json and body is no more than 2KB, include it directly in the summary. Reduces one round-trip.

3. Privacy protection. Never expose request headers (contains Cookie, Authorization). Never expose set-cookie response headers.

4. Finite listening window. Each see(NETWORK) opens the Network domain, listens for N seconds, closes it, returns aggregated results. The being controls the window.

## Foundation: CDP Network Domain

CDP already provides a complete substrate:

| CDP Method | What it does |
|---|---|
| Network.enable | Start listening, events pushed to WebSocket |
| Network.requestWillBeSent | Event: before request is sent (url, method, headers) |
| Network.responseReceived | Event: response arrives (status, mimeType, size) |
| Network.getResponseBody | Fetch full body by requestId (response must be loaded) |
| Network.disable | Stop listening, prevent event accumulation |

cdp_core.py already has WebSocket connection management (cdp_connect, cdp_call, wait_event) and _init_domains infrastructure. Adding Network domain is a natural extension.

## Implementation Path

### Step 1: Add network_snapshot() to cdp_snapshot.py

def network_snapshot(page_sel=None, duration=3.0, filter=None):
    Capture network activity on a page for duration seconds.
    filter: None=all, api=json/xhr only, xhr=exclude static assets
    Returns dict with method: cdp_network, requests list, duration, page_index

Internal flow:
1. Connect CDP via cdp_connect
2. Network.enable
3. Collect requestWillBeSent and responseReceived events for duration seconds
4. Network.disable
5. Aggregate: apply filter, auto-include small JSON bodies
6. Close WebSocket, return

### Step 2: Add fetch_network_body() to cdp_snapshot.py

def fetch_network_body(page_sel=None, request_id=None):
    Fetch full response body for a specific request.
    Reconnects, enables Network, calls Network.getResponseBody, disables, returns.

Independent of snapshot - the being calls it after seeing an interesting request in the summary.

### Step 3: Register new see backend in router.py

In SEE_PRIORITY[browser], add cdp_network:

SEE_PRIORITY = {
    browser: [cdp_dom, cdp_network, ax_ui, vision_ocr],
    ...
}

Add kind=network dispatch in route_see(). When kind is network or see request has a network flag, call cdp_snapshot.network_snapshot() or .fetch_network_body().

## Return Format

### Summary: see(NETWORK)

=== NETWORK · 19 requests in 2.8s ===
 1  GET  /api/bonfire/hear          200  json    2.1KB
 2  GET  /_next/static/chunk.js     200  js      156KB
 3  POST /api/bonfire/speak         201  json    0.3KB
    \_ {
## Timeout Strategy

- Default listening window: 3 seconds
- If pending requests remain at 3s: extend 1 second (max 2 rounds)
- Total duration never exceeds 5 seconds
- On forced close: return all data collected so far
- Being does not wait indefinitely for a slow-loading page

## Privacy and Security

- Never return request headers (prevents Cookie, Authorization, API key leaks)
- Never return set-cookie or set-cookies response headers
- Not cached in session storage
- fetch_network_body() follows the same rules
- Network events are not persisted to memory unless the being explicitly records what it saw

## Boundaries and Non-goals

- No request chain tracking. The being interprets relationships from URL structure.
- No request modification. Pure perception - no intercept, no modify, no replay.
- No continuous monitoring. Each see(NETWORK) is a one-shot snapshot window.
- No cross-page capture. Only captures Network events for the current page.
- No WebSocket/frame tracking in initial version.

## Workload Estimate

| File | Change | Description |
|---|---|---|
| hand/perception/cdp_snapshot.py | +~100 lines | network_snapshot() + fetch_network_body() |
| hand/router.py | +~20 lines | New backend registration, kind dispatch |
| hand/perception/cdp_core.py | +~10 lines (optional) | Generic event collector helper |

No external dependencies. No new files. CDP domain already verified operational (see/screenshot/CDP link fully functional).

## Version

| Version | Date | Change |
|---|---|---|
| v1.0 | 2026-08-12 | Initial PRD |

---

Surface first, then dive.
DOM is skin. NETWORK is blood.
This is the step from reading surfaces to reading flows.

## Filter Options

| filter | Behavior |
|---|---|
| None (default) | All requests |
| api | Only application/json |
| xhr | Exclude image/css/font/media static resources |

## Relationship with see(DOM)

| | see(DOM) | see(NETWORK) |
|---|---|---|
| What it sees | Page content | Data flow |
| Answers | What is written on the page | Who the page is talking to |
| Typical use | Read text, find buttons | Debug API errors, understand data |

The two are complementary. DOM says Loading. NETWORK shows the API returned 500. The being no longer needs to guess why a page is stuck.

## note on Return Format

The summary format example was truncated during write. See the Implementation Path section for the structural description. The key invariant: one line per request (index, method, URL, status, type, size), with inline body display for small JSON responses, and a detail endpoint for body-by-request-id.
