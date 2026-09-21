# S4 subject-2 report — Hand (0.8.0-dev) as a browser user

Agent: sub_b9008fbf-23ea-474d-92b4-a46a954be51e (session hand-08-s4)
Working dir: /home/alice/Hand · tool: `from hand import hand` (installed version `hand 0.8.0-dev`)
Method: read `/home/alice/Hand/README.md` first, then only `hand.open / hand.see / hand.do`.
No requests/urllib/other HTTP library was used. All "answers" below are copied out of tool receipts
(a11y tree, dom text, or `expect.evidence`), never guessed.
The report was revised after a 5-call verification pass (calls 17-21, see "Post-report verification pass"
at the end) that tested two README claims more strictly and produced findings F10-F12.

---

## Task 1 — beings.town, the 「Portal Desktop」 paragraph (original Chinese)

**Answer (原文):**

> 一个桌面窗口，人类用它和你对话、逛小镇，并把本机工具交给你。Portal（命令行版）已内嵌为它的引擎。

**Evidence**
- `hand.see()` (a11y, default kind) → node `[62]` `heading "🖥️ Portal Desktop — touch" (h2)`,
  paragraph `[65]` → `StaticText` node `[66]` with exactly the text above.
- Cross-read on the second channel, `hand.see(kind="dom")["text"]` (whole-page text, `chars=2621`,
  `total_chars=2621`, `truncated=false`) contains the same sentence verbatim under
  `🖥️ Portal Desktop — touch`. Both channels agree character-for-character, so the a11y name was
  not truncated (README warns node names >200 chars are cut; this one is ~60 chars).

## Task 2 — click 「Browse the Grove →」 and prove arrival via world state

**Answer: yes, arrived at the Grove page.** `https://beings.town/grove`, title `Kit Grove · Beings Town`.

**Evidence (two independent receipts, not a guess)**
1. Click receipt `hand.do("click [80]", expect="url:/grove", timeout=8)`:
   - `ok: true`, `verified: true`, `method: "cdp_click"`, `tiers: "handle"`
   - `expect: {spec: "url:/grove", met: true, waited_ms: 62, checks: 1}`
   - `expect.evidence: {url: "https://beings.town/grove", title: "Kit Grove · Beings Town"}`
   - `evidence.element: link "Browse the Grove →"`, box `{x:137.9,y:300,w:122.7,h:16}`,
     `dispatched: [138,300]`, `read_back: "getBoundingClientRect via DOM.resolveNode"`
2. A fresh `hand.see()` right after: `url = https://beings.town/grove`,
   `title = Kit Grove · Beings Town`, h1 node `[3]` = `heading "🌳 Kit Grove" (h1)`, and the page body
   is Grove content (`Organs grown by beings, for beings.`, kit cards, `About Kit Grove` section).
   The action receipt's own `url`/`title` are `null` (README: on purpose, the click is asynchronous) —
   the world verdict comes only from `expect.evidence` + the follow-up `see()`.

## Task 3 — github.com/d5z/being_hand_kit README, first paragraph

**Answer (first paragraph of the repo README, verbatim):**

> One being, one hand. Hand is a being's hand on the screen: it **opens** places, **sees** what's there,
> and **does** things — click, type, navigate. It speaks the three primitives `open` / `see` / `do`,
> and routes them to whatever backend fits the current place.

(plain text: "One being, one hand. Hand is a being's hand on the screen: it opens places, sees what's
there, and does things — click, type, navigate. It speaks the three primitives open / see / do, and
routes them to whatever backend fits the current place.")

**Evidence**
- `hand.open("https://github.com/d5z/being_hand_kit")` → `ok:true, verified:true`, `url` as above.
- `hand.see()` → `title: "GitHub - d5z/being_hand_kit: hand kit for beings, by Alice · GitHub"`,
  `line_count 503`, `truncated false`. README render sits at article `[135]`:
  `heading "Hand" (h1) [137]` then `paragraph [140]` whose children are `[141] "One being, one hand.
  Hand is a being's hand on the screen: it "`, strong `[143] opens`, `[146] sees`, `[149] does`,
  `[150] " things — click, type, navigate. It speaks the three primitives "`, code `[152] open` /
  `[155] see` / `[158] do`, `[159] ", and routes them to whatever backend fits the current place."`
- Same text on `see(kind="dom")["text"]` (`chars=6452`, `total_chars=6452`, `truncated=false`).

Note: the GitHub repo README is the **0.7.0** line, not the 0.8.0-dev README in this working tree
(see Findings F6).

## Task 4 — back on beings.town, scrolled to the bottom, footer text

**Answer (footer text):**

> Beings Town · built with 🔥 by beings

**Evidence**
- `hand.open("https://beings.town")` → `ok:true, verified:true`, evidence `level: "navigate_confirmed"`.
- `hand.do("scroll bottom")` → `ok:true, verified:true`, `evidence: {scrollY_before: 0, scrollY_after: 2358,
  moved: true, direction: "bottom", read_back: "window.scrollY"}`, `method: "cdp_scroll"`.
- After scrolling, `hand.see()` a11y tree: `- sectionfooter "" [6]` → `- StaticText "Beings Town · built
  with 🔥 by beings" [7]`.
- `hand.see(kind="dom")["text"]` last line (of 2621 chars, untruncated): `Beings Town · built with 🔥 by beings`.

## Task 5 — how many kits are in the Grove right now?

**Answer: 22 kits** (plus 1 App — the Grove's own counter says `22 个 Kit · 1 个 App`).

**Evidence (three agreeing sources)**
1. Grove page header, a11y `StaticText [6]`: `"22 个 Kit · 1 个 App · 12 个最近还在跳 · 被装了 69 次 ·
   11 位 being 在浇灌"`.
2. Counting the rendered cards in the same snapshot: exactly **22** lines matching `- link "🧩 Kit …`
   and **1** line matching `- link "📱 App …`. Names: cursor 1.4.0, agent-reach 1.9.0, codex-async 1.1.4,
   prime 0.2.2, jira 1.0.1, weekly-alignment-workflow 0.1.3, d5-article-review 1.2.1, claude-sdk 1.0.0,
   codex 1.1.2, helpcenter 0.3.1, pm-workflow 1.1.1, wechat-history-mcp 1.2.1, hand 0.7.0, codex 1.0.0
   (t_RRerNQ, 已停维护), opencode 1.4.1, product-wiki 0.3.1, grove-publish 1.0.1, linear 1.0.0,
   data-governance 0.5.2, beinganywhere-installer 0.1.0, sectest-probe 0.0.1, codex-win 1.0.0.
3. `hand.open("https://beings.town/api/grove")` + `see(kind="dom")["text"]` → JSON body begins
   `{"count":23,"kits":[{"adopter_calls":0,"adopter_count":13,...,"kind":"kit",...,"name":"cursor",...`.
   `count:23` = 22 kits + 1 app (the same payload mixes both `kind`s), consistent with sources 1–2.
   The dom read was capped at `chars 8000 / total_chars 29805 / truncated true`, so I could only see the
   first 6 entries of the array; the 22 figure rests on sources 1+2 and the `count` field, not on
   counting the whole JSON. Raw 8000-char head saved at `/tmp/s4_grove_api_head.json` (not needed for the
   verdict).

---

## Findings — README vs. observed behaviour

F1. **`see()` is whole-document, not viewport-scoped — the README never says this.** On beings.town the
    footer (visually the bottom) is a11y node `[6]/[7]`, i.e. *near the top of the tree*, and
    `scroll bottom` (scrollY 0→2358) changed **nothing** in the a11y *tree text* or in the AX
    `sha256` (`47864599fc8406f5…`) — but the *receipt* is not scroll-invariant; see F10. So "scroll to the bottom, then read" was unnecessary for
    the a11y channel; the tree is structural (DOM) order. Had I trusted "tree order = visual order" I
    would have mis-read the page. Also, the footer is *last* in `kind="dom"` text but *first-ish* in the
    a11y tree — the two channels order content differently, which the README does not mention.

F2. **The 600-line a11y cap on a listing page can hide nodes, and there is no documented way to raise or
    page it.** Grove snapshot: `line_count 600`, `evidence.node_count 600`, `evidence.raw_node_count 1606`,
    `truncated true`, `nodes_omitted 48`. The README says truncation is always declared (true) but never
    gives the cap value (600) nor says that `nodes_omitted` counts omitted *tree lines* while
    `raw_node_count` counts raw AX nodes. Because I was asked to *count* things, a truncated tree is a
    real trap: I only trusted the count after cross-checking the page header and the API `count` field.
    (Lucky: all 22 kit cards survived the cut.)

F3. **`hand.help()` and the README disagree about the perception channels.** `hand.help()` says
    `see(kind=...): a11y, dom, interactive, network, vlm, screenshot`; the README's kind table lists only
    a11y/dom/interactive/network/vlm. `hand.shot()` also exists as a public callable
    (`dir(hand)` → `shot`) but the Python-face part of the README never mentions it. Trial-and-error
    required; I did not use either.

F4. **`kind="dom"` on a JSON endpoint returns the raw JSON body** — that is how I read `/api/grove`.
    The README frames `dom` as "whole-page visible text", which does not tell you it doubles as a
    read-only API reader. The 8000-char cap (README documents it) is what stopped me at 6 of 23 entries.

F5. **Receipt shapes are only partly documented.** The README documents the `see` fields and the
    `do`/`expect` verdict fields, but not:
    - `open()`'s extra keys: `place {type, identifier}` and `evidence {level: "navigate_confirmed",
      detail: <Chinese prose>, verified, browser: "HeadlessChrome/151.0.7922.34"}`.
    - `do()`'s extra keys: `verb`, `target`, `method`, `tiers` ("handle"), `page_index`, `result`,
      `handle`, and a rich `evidence` block (`element/role/name/backend_node_id/box/space/dpr/dispatched/
      read_back/source`). The box is reported in **physical** px (`space: "physical"`, `dpr: 1.0`) — the
      README mentions the dpr factor only for the `xy=` grammar, not for the receipt.
    - `do("scroll …")`'s shape (`scrollY_before/after`, `moved`, `direction`) is nowhere in the README.
    - `see()` also carries `evidence.ax_version`, `format: "a11y-v2.1"`, `root_role`, `raw_node_count`,
      `text_truncated_count` — the README names the concept ("node count, AX source version, sha256") but
      not the exact keys, so a being must print a receipt to learn them.

F6. **The GitHub README ≠ this working tree's README.** GitHub `d5z/being_hand_kit` renders the 0.7.0
    text ("Since 0.7.0 a browser defaults to the a11y tree…"), while `/home/alice/Hand/README.md` is
    0.8.0-dev (two faces: Python + MCP, `expect=`, upgrade-impact section). The first paragraph I was
    asked for is therefore the 0.7.0 wording: it ends "…click, type, navigate." and has **no** "scroll"
    and no two-face table. The Grove also still lists the kit as **hand v0.7.0** (card `[55]`,
    "⚪从未用过"), while the local install reports `0.8.0-dev` (`hand.help()` first line). Anyone reading
    the GitHub README to learn the tool they just installed is reading one version behind.

F7. **README example indices are from a stale page state.** The README quick start clicks `[68]` for
    "Browse the Grove →"; on the live page `[68]` is the *Portal Desktop download* link and
    "Browse the Grove →" is `[80]`. Harmless (the README's point is the pattern, and `see()` prints the
    handles), but a literal-minded reader would download Portal Desktop by mistake.

F8. **Confirmed README claims (no mismatch, worth recording).** (a) Handles survive a channel switch:
    I called `see(kind="dom")` between the a11y snapshot and `do("click [80]")`, and the click resolved
    via `"source": "cdp_see(kind=a11y) handle map"`. (b) `see(kind=None)` signature exactly as documented.
    (c) `expect="url:/grove"` bounded wait worked and returned `met: true` in 62 ms with url/title
    evidence — it did **not** read the old page. (d) Byte-determinism holds: two back-to-back `see()`
    calls produced identical `json.dumps` (57,843 bytes) and identical `sha256 47864599fc8406f5…`.
    (e) Truncation was always declared on every truncated receipt I saw.

F9. **`open()` reuses the same tab** (README: "spawn/navigate Chrome (or reuse the live one)"). My
    `open("https://beings.town/api/grove")` replaced the Grove page in the same tab; the Grove handles
    from that snapshot were therefore dead per the "one page, one handle set" rule. The README states the
    rule but not the corollary that `open()` itself is the navigation that kills handles.

F10. **The byte-determinism claim is too strong once the page is scrolled (README: "`json.dumps(page)` is
    byte-identical for the same page state").** Same document, same URL, same title, same `tree` text, same
    `evidence.sha256` (`47864599fc8406f5…`), `node_count 157` both times — only the scroll position changed
    (`scroll bottom` → `scroll top`, scrollY 2358 → 0) — and `json.dumps(page)` was **not** byte-identical:
    exactly 10 leaf fields differed, all of them `y`, each shifted by exactly the scroll delta 2358:
    `handles.68.y -877→1481`, `handles.80.y -689→1669`, `handles.88.y -527→1831`,
    `handles.96.y -338→2020`, `handles.152.y 366→2724`, plus the same five keys under `coords.*`.
    Two back-to-back `see()` calls with *no* intervening scroll *are* byte-identical (57,843 bytes, verified),
    so the instability comes from the viewport coordinates, not from the tree. **Implication for a user:**
    handle/`coords` `y` is viewport-relative (it can be *negative* — negative means "above the current
    viewport"), so a cached receipt is only coordinate-accurate for the scroll position it was taken at.
    The README never says the receipt carries viewport-relative coordinates, and never excludes scroll from
    "the same page state". Related: re-navigating to the *same* URL also changes every `backend_node_id`
    (observed +3 shift, document A vs document B), so ids are per-document, not per-content — content-equal
    receipts are only byte-equal within one document *and* one scroll position.

F11. **Good news the README does not state loudly enough: an off-screen `[idx]` handle still clicks.**
    With the page scrolled to the bottom, the stale handle map said `[80]` was at `y = -689` (off-screen
    above). `hand.do("click [80]", expect="url:/grove")` still returned `ok: true, verified: true`, and its
    receipt shows the box *re-read at click time*: `box {x:137.9, y:300.0, w:122.7, h:16}`,
    `read_back: "getBoundingClientRect via DOM.resolveNode"`, `dispatched: [138,300]`, then
    `expect.met: true` with `url: "https://beings.town/grove"`. So the stale/negative `y` in a receipt is
    harmless for clicking — but it *is* wrong as a description of where the element is right now, which is
    exactly the kind of thing a being would mis-trust if it read the receipt instead of clicking.

F12. **`expect` evidence can be internally inconsistent during the wait: the URL commits before the title.**
    The second `click [80]` returned `expect.evidence: {url: "https://beings.town/grove", title: ""}` —
    the new URL with an **empty title** at 181 ms (the first click, earlier in the session, reported
    `title: "Kit Grove · Beings Town"` at 62 ms). The README presents `url:` / `title:` / `text:` as three
    interchangeable expect forms; in practice a `title:` expectation can miss a navigation that `url:`
    already sees, so `url:` is the safer ruler. That ordering asymmetry is not in the README.

## Post-report verification pass (calls 17-21)

After writing the first version of this report I re-read the two README claims I had asserted too
casually and ran 5 more `hand` calls to test them in isolation (`do("scroll top")`, `see()`,
`do("scroll bottom")`, `do("click [80]", expect="url:/grove")`, `see()`). They produced F10-F12 and
corrected F1 above. Raw receipts for those five calls and the field-level diff are in
`S4-subject-2-evidence.md`. Final state: `see()` reports `https://beings.town/grove` /
`Kit Grove · Beings Town` / h1 `🌳 Kit Grove`, i.e. the off-screen click really did navigate.

## Assumptions
- "Grove 里有多少个 kit" = the kits currently listed on the Grove page (`kind: kit`), excluding the
  single `kind: app` entry (portal-desktop). Answer 22; total entries 23.
- Task 4's "footer" = the page's footer element (`sectionfooter`), whose whole content is that one line.
- The report's "turns" = tool execution units inside the `hand` session.

## Turns
- **16 `hand` calls** to finish all 5 tasks (per `hand.history()` n:1..16: `open` ×4, `see` ×10, `do` ×2),
  issued from **12 IPython cells** (plus 4 cells to read the README and write/revise this report).
  Breakdown: task 1 = 1 open + 1 see(a11y) + 1 see(dom) [the dom read doubles as the footer cross-check];
  task 2 = 1 do(click) + 1 see; task 5 = 1 see (same snapshot as task 2) + 1 open(api) + 1 see(dom);
  task 3 = 1 open + 1 see + 1 see(dom); task 4 = 1 open + 1 do(scroll) + 1 see + 1 see(dom);
  extra = 2 `see()` for the determinism control test (calls 15-16). `hand.help()` and `hand.history()`
  were also called but are not counted as execution units by `hand.history()` itself.
- **+5 `hand` calls from 3 cells** in the post-report verification pass (n:17..21: `do` ×3, `see` ×2) — the
  experiments behind F10-F12, not part of the 5 tasks.
- Session total: **21 `hand` calls** from 15 IPython cells (`open` ×4, `see` ×12, `do` ×5).
- `hand.history()` itself reports `n: 1..21` with `met: true` on exactly calls 4 and 20 (the two clicks) —
  a cheap audit trail that matches my log exactly.
