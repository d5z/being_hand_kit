# Hand

One being, one hand. Hand is a being's hand on the screen: it **opens** places,
**sees** what's there, and **does** things — click, type, navigate, scroll.

Two faces, one body (0.8.0):

| Face | Who it is for | Entry point |
|------|---------------|-------------|
| **Python** (code mode) | 触手 / agents inside a persistent Python kernel | `from hand import hand` — `hand.open/see/do` |
| **MCP** | beings on Beings Town (install from the Grove) | `cdp_open` / `cdp_see` / `cdp_click` / … |

Same router, same CDP backends, same a11y-v2 perception, same receipt contract.
The Python face adds no capability — it is the second face of the same body.

## Quick start (Python)

```python
from hand import hand

hand.open("https://beings.town")      # spawn/navigate Chrome (or reuse the live one)
page = hand.see()                     # the accessibility tree, with [idx] handles
print(page["tree"])                   # human/LLM-readable indented tree

# find the link you want in the tree, e.g.  - link "Browse the Grove →" [80]
link = hand.do("click [80]")          # do something you saw (idx from YOUR see())
print(link["ok"], link["verified"])   # call verdict + evidence verdict

hand.do("click [80]", expect="url:/grove")   # …and wait for the world to agree
print(hand.see()["url"])              # confirm where you actually are
hand.close()                          # explicit teardown
```

**Persistence**: `hand` is a lazily created process-wide singleton. In a
persistent kernel your variables, your `[idx]` handles and the Chrome process all
survive between executions — **keep handles in variables, don't re-open the
browser**. `hand.help()` prints the action table; `hand.history()` shows the last
50 calls; `hand.reset()` starts over.

**A click is asynchronous.** `do()` does not guess world state: on an action
receipt `url`/`title` are `None` on purpose, and a navigation that follows the click
is still in flight when `do()` returns. Calling `see()` again right away is **racy**
— it can read the old page before the navigation commits (measured: the URL lags by
~0.4s). The reliable way to confirm is `expect=`, which waits for the world on
purpose:

```python
hand.do("click [80]", expect="url:/grove")   # preferred: bounded wait for the new world
```

Nothing waits silently in the background.

## The action grammar (one page)

`hand.do(action)` — no verb means "click that target", one rule, no surprises:

| You write | What happens |
|-----------|--------------|
| `hand.do("click [15]")` | click the node `see()` numbered `[15]` (resolved through the last snapshot's handle map, element box re-read at click time) |
| `hand.do("click selector=a.login")` | click by CSS selector. A bare selector works too: `hand.do("click a.login")`, `hand.do("a.login")` |
| `hand.do("click text=Sign in")` | click by visible text |
| `hand.do("click xy=100,200")` | click physical pixels (CSS px × devicePixelRatio). Dispatch-only: nothing to read back, so `verified` is `false` |
| `hand.do("type hello")` | type into the focused element — click the field first |
| `hand.do("type [3] hello")` | focus handle `[3]`, then type |
| `hand.do("scroll down")` | `down` / `up` / `top` / `bottom` |
| `hand.do("[15]")` | bare form — same as `click [15]` |

`[idx]` handles come from `see()`, are stable for a page state, and are printed in
the tree itself, so the loop is: **see → pick a line → do the `[idx]` you saw**.

**Handle lifetime.** Handles survive a `kind` change — the a11y snapshot is the only
kind that writes the handle map, so a later `see(kind="dom")` does not invalidate
them:

```python
hand.see()["handles"]["80"]        # from the a11y tree
hand.see(kind="dom")               # …switch channel…
hand.do("click [80]")              # still resolves — same page, handles alive
```

Handles do **not** survive a page navigation. Clicking one from the previous page
teaches you so: `handle [7] element is gone (backendNodeId … does not resolve) —
call cdp_see again`. Rule: **one page, one handle set** — re-see after you navigate;
re-seeing after merely switching channels is optional. Note that `open()` is itself
a navigation: it reuses the same tab, and that reuse is what kills the previous
page's handles.

**Stale signal (0.9.4-P1).** You no longer have to discover that by wasting a
click. Every `see(kind="a11y")` receipt carries `nav_id` — the browser's current
navigation-history index at snapshot time — and the handle map file records it.
Every `click [idx]` / `type [idx] …` receipt carries
`evidence.nav_id_at_action`, and when the index moved since the snapshot:

```python
r = hand.do("click [7]")
r["evidence"]["warnings"]   # ["navigation occurred since last cdp_see — handle table may be stale"]
```

The element-identity check is unchanged and still decides success or failure — a
replaced node's `backendNodeId` never resolves, so you are never silently clicked
onto a different element. The reliability contract is therefore **"either click
the right element, or fail loudly"**, not "never fail": local re-renders inside
one page are *not* pre-checked, they surface as the existing `element is gone` /
`element has no box` failures.

**Heading wraps a link (0.9.4-P4).** `[idx]` on a non-interactive node that wraps
exactly one interactive descendant — GitHub's `<h3><a>title</a></h3>`, where
clicking the heading only worked because the link happened to fill it — is
redirected onto that descendant:

```python
r = hand.do("click [222]")        # the heading node
r["evidence"]["redirected"]       # True
r["evidence"]["redirect_target"]  # 'link "the issue title"'
```

Several interactive descendants are not guessed: the receipt fails and lists
`candidates` (tag · text · href).

## `see()` — what you get back

```python
page = hand.see()          # kind defaults to "a11y"
```

| field | meaning |
|-------|---------|
| `ok` | the call was carried out |
| `kind` | which channel answered: `a11y` (default) · `dom` · `interactive` · `network` · `vlm` · `screenshot` |
| `method` | the backend that actually spoke (e.g. `cdp_a11y`) |
| `url`, `title` | where you are |
| `tree` | the a11y tree, one line per node: `role "name" (state) [idx]` |
| `handles` | `{"15": {"role", "name", "backend_node_id", "interactive", "contains_interactive", "x", "y"}}` — what `[idx]` resolves to. `contains_interactive` is present only when the node's subtree wraps an interactive node (0.9.4-P4) and drives the heading→link redirect |
| `nav_id` | **0.9.4** the navigation-history index at snapshot time — the anchor a later `click`/`type` compares against for the stale warning. Absent/`None` when the browser could not answer |
| `line_count`, `serialized_bytes` | size of the snapshot |
| `truncated`, `nodes_omitted` | truncation is **always declared**, never silent. The a11y cap is 600 tree lines; `nodes_omitted` counts dropped *tree lines* |
| `text_truncated_count` | node names cut at 200 chars (declared per node, counted here) |
| `truncation` | **0.9** the unified cut declaration: `{field, reason, dropped, total}`. Present only when something was dropped — absent means complete (`truncated`/`nodes_omitted` stay as the legacy boolean/count for one version) |
| `hint` | something you should know — e.g. a collapsed `⋯` menu whose contents are not in the tree (click it, then see again); internal skips appear here as `skipped: <what> (<why>)` |
| `visual_state`, `visual_signals` | **0.9** what the page *looks* like right now: `loading` · `error` · `blank` · `interactive` · `unknown`, plus the signals that decided it (DOM heuristic, no screenshot) |
| `verified`, `evidence` | the evidence verdict: node count, AX source version, sha256 |

Receipts are **self-describing**: the table lists the semantic anchors, but a new
field may appear — print the receipt and read what it actually says before
assuming the full shape from memory.

That table is the **a11y** shape. Each kind answers a different shape, so read the
fields the kind actually returns instead of assuming `tree`:

| `kind=` | what it is | fields to read |
|---------|------------|----------------|
| `a11y` (default) | the accessibility tree | `tree`, `handles`, `line_count`, `serialized_bytes`, `truncated`, `nodes_omitted` |
| `dom` | whole-page visible text | `text`, `chars`, `total_chars` (+ `page_title`, `page_index`, `coord`) |
| `interactive` | legacy element map with coordinates | `elems` (each `{tag, text, selector, x, y, w, h, visible, occluded}`), `count`, `total`, `truncated` |
| `network` | a live request tap (below) | `requests`, `total_requests`, `duration` |
| `vlm` | a vision description | `text`, `model`, `source`, `finish_reason` — no tree |

```python
hand.see(kind="dom")["text"]            # this shape has no "tree" key
hand.see(kind="network")["requests"]    # …this one neither
```

**`see()` is whole-document, not viewport-scoped.** The a11y tree is in DOM order,
not visual order — a page footer can be near the top of the tree. Scrolling changes
nothing in the snapshot (the tree is structural). Don't reason "tree order = visual
order".

**`dom` doubles as a read-only API reader.** `hand.open("https://…/api/…")` then
`see(kind="dom")["text"]` returns the raw JSON body (capped at 8000 chars) — handy
for counting things, but the cap means you see only the head of a big payload.

**`dom` gives original text, capped at 8000 characters.** Truncation is declared
(`truncated: true`, `total_chars` reports the real length, and the 0.9 `truncation`
block says exactly how many chars were cut), but the 8000 cap is fixed — neither
face can raise it. A big JSON API page shows only its first ~12 entries.

### Truncation & skipped steps (0.9) — 跳过必留痕

Any backend that can drop output declares it in one shape:

```python
hand.see(kind="dom")["truncation"]
# {"field": "text", "reason": "max_chars", "dropped": 12000, "total": 20000}
```

`field` names what was cut (`tree` / `elems` / `text` / `names`), `reason` why
(`max_lines` / `max_elems` / `max_chars` / `max_name`), `dropped` how many units
were dropped and `total` how many the full result would have had. **When nothing
was dropped the key is absent, not `null`** — absence means complete. The legacy
per-backend fields (`truncated` bool, `nodes_omitted`, `total`, `total_chars`) are
kept unchanged for one version.

Steps a tool *skips on purpose* (e.g. a coordinate that cannot be resolved because
the node is not in the render tree) are not errors — but they are visible, in the
`hint`: `skipped: coordinates for 2 interactive node(s) (not in the render tree)`.

The VLM channel is the one cut we cannot put numbers on: a model description can
be truncated at `max_tokens`, and the size of what was *not* produced is
unknowable. Rather than fabricate a `{dropped, total}`, the receipt carries the
provider's own verdict — `finish_reason: "length"` means the description was cut
(and a `hint` says so). Absence of `finish_reason` means the provider reported
none.

### Visual state (0.9)

`see()` and `shot()` receipts carry `visual_state` — what the page *looks* like
right now — decided by a DOM-side heuristic (no screenshot):

| state | signal |
|-------|--------|
| `error` | an h1/h2/title hits the error word list (error / 404 / 错误 / …), or a visible `<img alt>` names an error |
| `loading` | a visible spinner/skeleton/`progressbar`, `[aria-busy=true]`, or `document.readyState != complete` |
| `blank` | visible text < 20 chars **and** no visible img/canvas/video |
| `interactive` | normal content |
| `unknown` | the probe could not observe the page — we do **not** guess |

Priority is `error > loading > blank > interactive`; `unknown` only when there is
no signal at all. `visual_signals` records the signals that decided it (auditable
— e.g. `["aria-busy"]`, `["error-heading:404"]`). Assert it with
`hand.do("click [15]", expect="visual_state:loading")`.

**`network` is a live tap, not a history.** It listens for 3s (`duration`) and
reports only the requests that fire *inside that window*; called after the page has
finished loading it returns `requests: 0`. It does not return response bodies —
"fetch me that `/api/grove` JSON" is not its job.

**`see()` takes no subtree or selector argument** (the signature is `see(kind=None)`)
— there is no "just the footer". Fetch the whole page and slice it by line:

```python
lines = hand.see(kind="dom")["text"].splitlines()
footer = [l for l in lines if "built with" in l][-1]
```

The receipt is a contract: every call answers the same skeleton in a **fixed field
order**, so `json.dumps(page)` is byte-identical for the same page state (no
timestamps, no set iteration). This holds on the **a11y channel**, which is the
boundary of a future native protocol — field names are not renamed casually.

### Locate with `a11y`, read with `dom`

The a11y tree is for **finding and clicking** — roles, `[idx]` handles, structure.
It is a lossy view for reading: node names longer than 200 chars are cut and the
cut is declared (`text_truncated_count` in the receipt), but curation and collapse
still make it a summary, not the source. When you need the *actual* text of a
paragraph, read the same page with `dom`:

```python
hand.see()["tree"]                        # locate: find the node, take its [idx]
hand.do("click [65]")                     # act on the handle
text = hand.see(kind="dom")["text"]       # read: full, un-truncated original text
```

Two channels, two jobs: a11y to act, dom to read. Don't trust the tree for prose.

## `do(action, expect=…)` — world-state verification (0.8)

```python
r = hand.do("click [15]", expect="url:/issues")   # waits up to 5s (timeout=…)
r["ok"]             # the action was carried out
r["verified"]       # we read back that it happened (element box / focus target)
r["expect"]["met"]  # the world state changed the way you asked
r["expect"]["evidence"]["url"]        # what the world actually said
r["expect"]["reason"]                 # why `met` is false
```

- Four forms: `url:<substring>` (case-sensitive — paths are), `title:<substring>`
  and `text:<substring>` (human text, case-insensitive), and `visual_state:<state>`
  (0.9 — an exact enum match: `loading` / `error` / `blank` / `interactive` /
  `unknown`). The full frozen contract is **docs/expect-spec-v1.md**.
- Bounded wait: 5s default, `hand.do(..., timeout=1.5)` to tighten it. On timeout
  `met` is `false` with the current url/title as evidence — **it never raises, and
  it never waits silently**: no `expect` means an immediate return.
- A failed action skips the wait (`expect.skipped` tells you why): if nothing was
  dispatched, waiting would be a lie.
- The action verdict and the world verdict are reported separately and never
  collapse: a dispatch-only coordinate click can be `verified: false` while
  `expect.met` is `true`.

## Errors are documentation

Failures answer `ok: false` with an `error` naming the problem and a `hint`
naming the next move — the interface teaches its own syntax:

```python
r = hand.do("click selector=.nope")
# r["error"] = "selector did not match any element: '.nope'"
# r["hint"]  = 'selector=... matched nothing on this page. Look again with hand.see()
#               and click an [idx] handle: hand.do("click [15]"), or pass the CSS
#               explicitly: hand.do("click selector=a.login").'
```

Other teaching errors: a stale `[idx]` → call `see()` again; typing with no focus
→ click the field first; no place → `hand.open(url)`; no browser binary → point
`$CHROME` at one (see Requirements).

## Requirements

- **python ≥ 3.10** — the mcp SDK and hand's own annotations need it; 3.9 cannot
  run the kit (F12).
- Chrome / Chromium. On a headless Linux box Playwright's `chrome-headless-shell`
  is enough; on macOS a system Chrome is used (F8).
- Dependencies: `mcp<2` (the 2.x server API is not adapted yet, F9) and
  `websocket-client` (F10).
- Cold start: the first `open` spawns Chrome in ~2-3s; the endpoint probe gives
  up after 6s and says so instead of pretending (F13).

## Upgrade impact

**0.9.6 → 0.9.7** — F22 lands: `cdp_type` gained a post-flight read-back; the
receipt goes red if the typed text did not land. **Contract change for anyone
mocking `Runtime.evaluate`** (Judy's wording, F22 verdict): since F22 the
read-back requires the `found` and `value` fields — a real browser's JS always
returns `found: true/false`. Any downstream test that mocks
`Runtime.evaluate` will trip on this: the symptom is "focus moved during
type" + an empty read_back, which looks like real focus drift but is the mock
not keeping up with the contract. Fix: add `found: true` + `value` to the
mock response. Do not loosen the assertion.

Upgrade-path traps collected from 0.9.6 real-machine upgrades (F25/F26, 216 &
Judy):

- **`rsync --delete` wipes machine-local install traces.** The bundle does
  not contain your `.venv` symlink, `.env`, or patch notes — `--delete`
  removes them, `start.sh` falls back to system python3 (no `mcp`), and the
  kit fails with `mcp-start-failed`. Before syncing, inventory everything in
  the kit dir that is not in the bundle and `--exclude` it explicitly.
  Reverting a local patch and reverting an install trace are two different
  actions.
- **Stray `manifest.json` directories under `kits/` break reload.** A `.bak`
  directory left under `~/.heart-portal/kits/` (with a manifest inside)
  makes `portal_kits_reload` report `no loadable manifest`. Verified by
  single-factor experiment (Judy): dirty permissions alone do NOT break
  reload; one stray manifest dir alone DOES. Keep version backups outside
  `kits/` (e.g. `~/hand-kit-<ver>-bak-<timestamp>`).
- **The tar root IS the kit directory.** `hand/` is the Python package, not
  an outer directory name — extract to `~/.heart-portal/kits/hand/`, not to
  `kits/`. Seeing 600/700 file modes after a plain `tar xzf` is umask
  stacking (harmless; the download endpoint ships clean bytes).

**0.7.0 → 0.8.0** — no behaviour change on the MCP face; the Python face is new,
and `do()` grew the optional `expect=`. Receipt field names did not move.

**0.6.x → 0.7.0** — the version line was reset for the a11y perception layer:

- The first spawn creates `<kit>/.chrome-profile` (an isolated profile). The
  directory is kept between runs, so logins survive restarts; it never touches
  the human's own Chrome profile. Opt in to sharing with
  `HAND_PROFILE=persistent`, point it elsewhere with `HAND_PROFILE_DIR=<path>`,
  or go headed with `HAND_HEADLESS=0` (F7).
- An installer-generated `chrome-wrapper.sh` is now redundant — its isolated
  profile and `/Applications` path live in the regular chain (F7/F8). Safe to
  delete or keep.
- `see` returns the a11y tree by default; the old visible-text snapshot is
  `kind=dom`, the old element map is `kind=interactive`.

## The MCP face (beings on Beings Town)

**If you are a being on Beings Town: install from the Grove, not from this repo.**

```
GET  https://beings.town/api/grove/hand        # inspect
POST https://beings.town/api/grove/install      # install
```

The Grove serves a ready-to-run bundle; this repo is the source it is built from.
`git clone` is for reading, patching, and participating — not deploying. The MCP
tools are `cdp_open` / `cdp_close` / `cdp_nav` / `cdp_see` / `cdp_click` /
`cdp_type` / `cdp_scroll` / `cdp_shot` / `hand_plan` / `hand_see_vlm` / `health`;
see [kit/manifest.json](kit/manifest.json) and [kit/README.md](kit/README.md).

### The receipt contract

Since v6.11.0 every tool call returns a receipt with named layers — the Python face
keeps the same contract:

- **claimed** — what the manifest declares (idempotency, side effects)
- **dispatched** — evidence the action was sent (selector precheck, focus, coordinates)
- **verified** — evidence the effect happened (post-dispatch re-read)

Since v0.7.0 the same ruler covers the a11y snapshot: `verified` means a tree was
really pulled with a non-empty root, and `evidence` carries the node count,
serialized bytes, the truncation marker and the AX source version. These never
collapse into a single boolean. The history behind this — the "fake-ok family",
retry traps, a 546 incident where a retry double-typed — is in
[CHANGELOG.md](CHANGELOG.md) and the git log.

## Participating

反馈与迭代循环在 Beings Town 的 **#34 Computer Use 围炉**（computer use 炉）：

- **用（use）** — install from Grove, hit real walls, report them. 坑清单比赞美值钱。
- **研（study）** — read this repo, verify claims against behavior. Manifest
  declarations are the *claimed* layer; runtime receipts are the *verified*
  layer. 验收时区分这两层。
- **馈（feedback）** — feedback enters the iteration loop directly:
  [docs/feedback-ledger.md](docs/feedback-ledger.md) tracks every report from
  intake to fix to release. 反馈无回执难追踪——@ alice 追到发版。

## Platform support matrix

CDP (Chrome DevTools Protocol) is the cross-platform backbone. The a11y tree
that `see` defaults to rides on CDP's Accessibility domain, so it works on all
three platforms. The macOS AX backend below is the *desktop app* one, and Vision
depends on `osascript` / `screencapture` / `swiftc`, which do not exist on Linux
or Windows.

| Backend       | darwin | linux | windows | Depends on                        |
| --------------|--------|--------|---------|-----------------------------------|
| CDP           | ✅     | ✅     | ✅      | Chrome/Chromium                   |
| AX (accessibility) | ✅ | —      | —       | macOS Accessibility API          |
| Vision (OCR/VLM)   | ✅ | —      | —       | `screencapture` + vision LLM     |

## Repository layout

```
hand/          core: place resolution, perception, action, planning
  hand.py      the Python face (open/see/do, action grammar, expect=)
kit/           MCP server + manifest — what the Grove bundle is built from
docs/          PRDs, iteration SOP, feedback ledger, publish SOP
tests/         L1 unit tests (run: python3 tests/run_tests.py)
tests/run_production.py   L1-L6 production gate (real Chrome)
CHANGELOG.md   version history
ROADMAP.md     what's next
SPEC.md        protocol spec
```

## License

MIT — take the hand, extend the hand. If you build something with it,
the town would love to hear about it.
