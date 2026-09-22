# `expect=` spec — v1.0 (frozen)

> Status: **v1.0 frozen** (2026-09-22, hand 0.9). Version constant:
> `hand.hand.EXPECT_SPEC_VERSION = "1.0"`.
> The `expect=` argument of `hand.do(...)` / `hand.open(...)` is a *world-state
> check*, not an action. It was the de-facto standard since hand 0.8; this
> document is the contract.

## 1. Version promise

- **v1 is frozen.** The parser (`hand.hand.parse_expect`) follows this document,
  and `tests/test_expect_spec.py` runs every example below — the doc and the
  code cannot drift silently.
- **Breaking changes bump the major version** (`v2`): removing/renaming a key,
  changing a failure field, or changing match semantics.
- **Additive changes may stay in v1** only when they are (a) a new key that the
  parser rejects cleanly when unknown, and (b) added to this document and to the
  alignment table in the same release. `visual_state` was added this way for 0.9.

## 2. Grammar

```
expect := <kind> <sep> <value>
<sep>  := ":"            preferred
        | "="            alias, only usable when the whole string contains no ":"
<kind> := "url" | "title" | "text" | "visual_state"     (case-insensitive)
```

- The whole argument is stripped first; `<kind>` is lower-cased, `<value>` keeps
  its case (except `visual_state`, which is lower-cased).
- **The separator is chosen by "does the string contain `:` at all"**, then the
  string is split on the *first* occurrence. So `=` is an alias only for values
  that do not contain a colon. `url:https://x/issues` is correct;
  `url=https://x/issues` is **not** (`https:` contains a colon, so it splits at
  the wrong place and is rejected as an unknown kind). Use `:` for URLs.

## 3. Key space

| key | value | match | evidence on the verdict |
|-----|-------|-------|-------------------------|
| `url` | any string | **case-sensitive** substring of `location.href` (paths are case-sensitive) | `evidence.url` |
| `title` | any string | **case-insensitive** substring of `document.title` | `evidence.title` |
| `text` | any string | **case-insensitive** substring of visible page text (first 2000 chars) | `evidence.url`, `evidence.title` |
| `visual_state` | one of `loading` / `error` / `blank` / `interactive` / `unknown` | **exact enum equality** (not a substring) | `evidence.visual_state` |

A check that does not name `visual_state` never pays for the visual probe; only
`visual_state:` reads it.

## 4. Examples

Every row is executed by `tests/test_expect_spec.py`.

<!-- spec-examples:start -->
| example | parses to kind | parses to value | notes |
|---------|----------------|-----------------|-------|
| `url:/issues` | url | /issues | path substring, case-sensitive |
| `url:https://github.com/` | url | https://github.com/ | URLs use `:` |
| `title:Issues` | title | Issues | case-insensitive substring |
| `title=Issues` | title | Issues | `=` alias (no colon in the string) |
| `text:Welcome` | text | Welcome | reads visible text |
| `visual_state:loading` | visual_state | loading | exact enum |
| `visual_state:error` | visual_state | error | exact enum |
| `visual_state:blank` | visual_state | blank | exact enum |
| `visual_state:interactive` | visual_state | interactive | exact enum |
| `visual_state:unknown` | visual_state | unknown | exact enum |
| `visual_state:spinning` | (error) | | not one of the five states |
| `href:foo` | (error) | | unknown kind |
| `url:` | (error) | | empty value |
| `issues` | (error) | | no separator |
<!-- spec-examples:end -->

## 5. Failure / verdict message format

`do()` keeps three separate verdicts — never collapse them:

- `ok` — was the call carried out (a bad spec is `ok: false`).
- `verified` — did the action read itself back.
- `expect.met` — did the world reach the requested state.

The `expect` object is always present; it is `null` unless `expect=` was given.
Its fields, by outcome:

| outcome | `expect` object |
|---------|-----------------|
| met | `{spec, kind, needle, met: true, waited_ms, checks, evidence}` |
| timeout | `{spec, kind, needle, met: false, waited_ms, checks, timeout_s, evidence, reason}` — `reason` is `"<kind> never contained '<needle>' within <timeout>s"` (for `visual_state`: `"'visual_state' was never '<needle>' within <timeout>s"`) |
| action failed first | `{spec, kind, needle, met: false, skipped: true, reason: "action failed: <error>"}` — no 5s stall |
| spec we cannot honour | `{spec, met: false, skipped: true, spec_error: true, reason: "<parse error>", hint: "<forms>"}` — the action still ran, so `ok: false` and `error` is the parse error |

`evidence` carries the observed values that back a verdict (`url`, `title`, and
`visual_state` when that key was checked). A timeout reports the *current* world
in `evidence` — it never raises.

### Parse errors (exact templates)

```
expect must look like 'url:/issues' (got <repr>)
expect kind <kind> is not one of url/title/text/visual_state
expect <spec> has an empty value
visual_state <value> is not one of loading/error/blank/interactive/unknown
```

## 6. Version history

- **v1.0** (hand 0.9) — initial written spec. Keys: `url`, `title`, `text`,
  `visual_state`. Frozen.
