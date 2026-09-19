# Hand v6.10.0 — Windows Support (Perception Trio Fix)

PRD - 2026-09-19 - Alice - Hand v6.10.0

---

## Motivation

taojun reported (fireside #280, 2026-09-17, Windows 10 real machine):
all three perception tools broken on Windows:

- `hand_cdp_shot` → WinError 2 (file not found)
- `hand_see_vlm` → WinError 2
- `hand_cdp_see` → "no see backends for 'unknown' on this platform"

Hand's stated direction (Zeping, 2026-08-16): **portal default kit — the eyes
and hands of every being on desktop platforms**. Windows beings currently
cannot use the perception layer at all. This PRD closes that gap.

This is the direct continuation of `prd-platform-boundaries.md` (v6.6.0),
which declared Windows out of scope. That scope line now moves.

---

## Verified Facts (code-level, 2026-09-19)

All verified by reading the actual code on alice portal. No speculation.

### F1 — The trio is one vine, three symptoms

```
Windows: _find_chrome() finds no binary
       → ensure_chrome() raises FileNotFoundError (WinError 2)
       → cdp_shot broken (direct)
       → see_vlm broken (screenshot source: CDP fails → screencapture
         fallback does not exist on Windows → WinError 2)
       → cdp_open fails silently-ish (see F4) → session.place stays "unknown"
       → SEE_PRIORITY["unknown"] filtered empty on Windows (F2)
       → cdp_see reports "no see backends for 'unknown' on this platform"
```

### F2 — `SEE_PRIORITY["unknown"]` is macOS-only

`hand/router.py`:
```python
SEE_PRIORITY = {
    "browser":     _available(["cdp_dom", "cdp_network", "cdp_interactive", "ax_ui", "vision_ocr"]),
    "desktop_app": _available(["ax_app", "ax_ui", "vision_ocr"]),
    "unknown":     _available(["vision_ocr", "ax_ui"]),   # ← both macOS-only
}
```
On Windows, `_available(["vision_ocr", "ax_ui"])` → `[]` → the honest
boundary error. On Linux the same list is also empty — Linux works only
because `cdp_open(url)` sets `place=browser`, routing see into the browser
chain. taojun's open failed first (F1), so his see hit the empty unknown
chain.

### F3 — Routing defect: `place="unknown"` blocks CDP probing

`route_see()` (commit 8820e3f) probes for a live CDP browser when
`place is None`. But `detect_place()` on any non-macOS platform returns
`Place(type="unknown")` — a **non-None** value. Once session.place is
"unknown", the CDP probe is skipped entirely. A stale "unknown" is worse
than no place at all.

### F4 — `open_place()` fake-ok (the deceptive one)

`hand/place/detect.py` `open_place()`, URL branch:
```python
        except Exception:
            pass
        # Last resort: assume the place is a browser even if nav failed.
        return Place(type="browser", identifier=target)
```
When CDP is unreachable (Windows: no chrome at all), this swallows the
failure and returns `place=browser` — a fake success. The caller believes
open worked; every subsequent cdp_* call fails with confusing errors.
Note: `ensure_chrome()` itself raises properly (`RuntimeError`); the
swallow happens in `open_place`'s except-pass + unconditional browser
fallback.

### F5 — `_find_chrome()` has no Windows paths

`hand/perception/cdp_launcher.py` `_find_chrome()` checks:
1. `$CHROME` env var
2. playwright cache dirs (`chrome-headless-shell-linux64`, `chrome-linux64`)
3. PATH names: `google-chrome`, `chromium`, `chromium-browser`, `chrome`

No `chrome.exe` install locations, no `msedge.exe`. On a stock Windows box
there is no runnable binary → F1.

### F6 — manifest self-contradiction

`kit/manifest.json`:
```json
"platforms": {
  "supported": ["darwin", "linux"],          ← Windows blocked at install
  "backend_matrix": { "cdp": ["darwin", "linux", "windows"] }  ← claims support
}
```
The backend_matrix already promises Windows CDP; the supported list
denies it. Internal contradiction.

---

## Fix Scope (5 items)

### S1 — Windows browser discovery (`cdp_launcher._find_chrome`)

Add Windows search order (after `$CHROME`):
1. Standard install paths:
   - `C:\Program Files\Google\Chrome\Application\chrome.exe`
   - `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
   - `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`
2. PATH: `chrome.exe`, `msedge.exe` — **Edge is a stock-Chromium fallback
   on every Windows box** (key coverage win: works without any install)
3. Standard Edge install paths:
   - `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
   - `C:\Program Files\Microsoft\Edge\Application\msedge.exe`

Use `sys.platform == "win32"` gate. Keep existing darwin/linux order
untouched. `_chrome_flags()` must add `--no-sandbox` on Windows CI contexts?
— no, keep flags minimal: only add what is required to launch headless
on Windows (verify: `--headless=new --remote-debugging-port=9222` works
on both chrome.exe and msedge.exe).

### S2 — `SEE_PRIORITY["unknown"]` gains CDP backends

```python
"unknown": _available(["cdp_dom", "cdp_interactive", "vision_ocr", "ax_ui"]),
```
Rationale: CDP is a place-independent channel (precedent: commit c3557e5
for kind=network, 8820e3f for place=None). If a browser is alive, see
should work regardless of what the foreground app is. On macOS this
changes nothing when no browser is alive (cdp backends fail fast →
vision_ocr still runs); on Linux/Windows this is what makes see work at
all.

### S3 — `route_see`: treat stale "unknown" like None for CDP probing

In `route_see()`, the CDP-live-browser probe currently runs only when
`place is None`. Extend: probe also when `place.type == "unknown"`.
The probe is cheap (one HTTP GET to :9222/json) and idempotent. If a live
browser is found, route into the browser chain (and update session.place
to browser). This fixes F3 without touching session semantics elsewhere.

### S4 — `open_place()` honest failure (fake-ok fix)

The last-resort browser fallback must only fire when a CDP endpoint is
actually alive:
```python
        except Exception:
            pass
        if chrome_running():          # ← new gate
            return Place(type="browser", identifier=target)
        raise RuntimeError(
            f"cannot open {target}: no CDP endpoint and no browser binary — "
            "set $CHROME or install Chrome/Edge"
        )
```
This is a **behavior change for macOS/Linux too** — but only in the
already-broken case (nav failed AND no browser alive), where the old code
lied. Production users on macOS/Linux with a live Chrome see zero change
(`chrome_running()` → same fallback as before). Callers of `open_place`
must catch RuntimeError and surface it (check `router.route_open` and
`kit/mcp_server.py` open tool — error must reach the being, not be
swallowed a second time).

### S5 — manifest + platform plumbing

- `kit/manifest.json`: `supported: ["darwin", "linux", "windows"]`
  (backend_matrix.cdp already says windows — this resolves F6)
- `hand/place/detect.py`: Windows branch for `detect_place()` using
  PowerShell:
  `powershell -NoProfile -Command "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -First 1 -ExpandProperty ProcessName"`
  Map `chrome/msedge/firefox` → browser, else desktop_app, else unknown.
  On any failure → Place(type="unknown") (same as today).
  `open_place()` app-name branch on Windows: `start "" "{target}"` via
  cmd (best-effort; document as limited).
- Version bump: 6.10.0 (semver minor — new platform, no API break).

---

## Architecture Principles (carry over from platform-boundaries PRD)

1. **CDP is place-independent.** Any routing that blocks CDP on place
   grounds is a bug (c3557e5, 8820e3f, now S2/S3).
2. **Honest failure beats fake success.** The fake-ok (S4) is worse than
   the WinError 2s — it corrupts downstream routing state.
3. **Graceful degradation with declared boundaries.** Windows gets: full
   CDP chain (open/nav/see dom/see interactive/see network/shot/do
   click-type-scroll/vlm). Windows does NOT get: ax_* (AppleScript),
   vision_ocr (screencapture+swiftc), keystroke (osascript), place
   detection beyond PowerShell best-effort. These remain macOS-only —
   declared, not hidden.

---

## Acceptance

Three layers — CI cannot prove Windows; taojun can.

### L1 — Unit tests (run on Linux CI, mock platform)

New tests, all mocked (`sys.platform` monkeypatch, no real Windows):
- `test_find_chrome_windows`: $CHROME wins; install-path probe order
  chrome.exe → msedge.exe; PATH fallback finds msedge.exe.
- `test_see_priority_unknown`: on win32, unknown chain contains cdp_dom
  (not empty); on darwin, order preserved (vision_ocr first).
- `test_route_see_unknown_probes_cdp`: place=unknown + live CDP (mocked
  list_pages) → routes to browser chain, session.place updated.
- `test_open_place_honest_failure`: place URL + no chrome_running +
  ensure_chrome raises → RuntimeError propagates (no Place returned).
- `test_open_place_fallback_when_alive`: nav fails but chrome_running →
  still returns browser Place (macOS/Linux unchanged behavior).
- `test_detect_place_windows`: mocked PowerShell output → browser /
  desktop_app / unknown mapping.
- `test_manifest_platforms`: supported includes windows; consistent with
  backend_matrix.

### L2 — Regression on Linux (alice portal, real run)

- Full existing suite green (69 tests as of 6.9.0) + new L1 tests.
- Live dogfood: `hand_cdp_open` → `hand_cdp_see` (dom + interactive) →
  `hand_cdp_shot` → `hand_see_vlm` → `hand_cdp_click` — the exact trio+
  flow taojun ran, on Linux. All must pass unchanged.
- `hand_health` reports 6.10.0.

### L3 — Real Windows (taojun, after Grove release)

- The original trio from #280 passes on his Windows 10 box.
- Bonus if Edge-only (no Chrome installed): confirm msedge fallback works.

---

## Risks & Rollback

- **S2 order change on macOS**: unknown chain now tries cdp_dom before
  vision_ocr. If no browser alive, cdp fails fast (<50ms) — negligible.
  If browser alive but user wanted OCR of the desktop (not the browser),
  behavior changes: unknown+browser-alive now returns DOM instead of OCR.
  Mitigation: this matches the place=None branch (8820e3f) already in
  production for a session without a place — consistency, not novelty.
- **S4 behavior change**: only fires in previously-fake-success cases.
  If any production caller depended on the lie, they were already broken
  downstream. Search kit/mcp_server.py + router.py for open callers to
  confirm error surfacing.
- **Rollback**: single revert of the release commit restores 6.9.0
  behavior entirely (no data/state migrations involved).

## Out of Scope

- vision_ocr on Windows (needs a capture + OCR stack — separate PRD if
  demanded)
- ax_* / keystroke on Windows (UI Automation is a separate project)
- Windows CI runner (L3 stays manual with taojun for now)
- `portal_screenshot region=window` on Windows (Portal-side issue, not
  Hand — already logged separately for relay)
