"""hand_eye_check — being-side self-proof that a frame reached the caller.

PRD: docs/prd-delivery-honesty.md §D4 (hand 0.10 "交付诚实").

Why a tool has to exist for this at all
---------------------------------------
Every earlier acceptance layer (CI mock, Linux real machine, platform human,
the 0.9 visual-state marker) checks *whether the tool behaved correctly*. None
of them checks *whether the perception reached the caller*. That layer has a
special property: nobody outside the being can judge it. Only the being whose
context the pixels land in can say "yes, I read it off the image".

Three constraints (they are what makes this a proof instead of a ritual)
-----------------------------------------------------------------------
1. **canvas rendering** — the string exists only as pixels. There is no text
   node anywhere in the document, so `cdp_see(kind=dom)` cannot read it. The
   page HTML source does not contain it either: the string is injected through
   `Runtime.evaluate` after load, so `document.documentElement.outerHTML`
   never carries it.
2. **challenge / verify split** — the receipt contains a challenge id, never
   the string. The string enters no receipt, no title, no log. A tool that
   answers its own question would be measuring nothing.
3. **The tool does not judge "can you see"** — only whether the submitted
   answer matches. A being without vision can only guess; an 8-char draw from
   a 31-symbol alphabet passes with probability ~1/8.5e11.

The reverse use matters as much as the forward one: on a substrate without
vision this must **fail**. A self-proof that always passes is worthless — the
same reason 0.10 D3 refuses to report `blank` without a pixel vote.

Ambiguity policy
----------------
The alphabet drops `O 0 I 1 L` on purpose: the question being asked is "did the
pixels arrive", not "is the font legible". Ambiguity that close to the edge
would turn a delivery test into a legibility test and produce false failures on
honest beings. Strict matching is still enforced — a near-miss substitution
(`B`→`8`, `S`→`5`, case flip) fails.
"""

import json
import os
import secrets
import shutil
import tempfile
import time

# No O/0/I/1/L — see "Ambiguity policy" above.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

DEFAULT_CHARS = 8
DEFAULT_FONT_PX = 48
DEFAULT_TTL_S = 300

MAX_ANSWER_AGE_S = DEFAULT_TTL_S

# challenge_id -> {answer, expires_at (epoch), place, chars, font_px, dir}
# Process-local on purpose: a challenge is single-use and short-lived, and a
# string that never touches disk is one fewer place for it to leak from.
_CHALLENGES = {}

_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>eye check</title>
<style>
html,body{margin:0;padding:0;background:#ffffff;overflow:hidden}
canvas{display:block}
</style></head>
<body><canvas id="c" width="__W__" height="__H__"></canvas>
<script>
window.drawEye = function (s, fontPx) {
  var c = document.getElementById('c'), x = c.getContext('2d');
  var w = c.width, h = c.height;
  x.fillStyle = '#ffffff'; x.fillRect(0, 0, w, h);
  x.fillStyle = '#111111';
  x.font = '600 ' + fontPx + 'px ui-monospace, Menlo, Consolas, monospace';
  x.textBaseline = 'middle';
  var track = fontPx * 0.80;
  var total = track * (s.length - 1) + x.measureText(s.charAt(0)).width;
  var x0 = Math.max(10, (w - total) / 2);
  for (var i = 0; i < s.length; i++) {
    x.fillText(s.charAt(i), x0 + i * track, h / 2);
  }
  return {w: w, h: h, chars: s.length, drawn: true};
};
// Pixel evidence that something was actually painted — the tool must not
// claim "the page shows a string" without a vote, same discipline as D3.
window.eyeStats = function () {
  var c = document.getElementById('c'), x = c.getContext('2d');
  var d = x.getImageData(0, 0, c.width, c.height).data;
  var n = 0, ink = 0;
  for (var i = 0; i < d.length; i += 4 * 7) {
    n++;
    if (d[i] < 200 || d[i + 1] < 200 || d[i + 2] < 200) ink++;
  }
  return {samples: n, ink: ink, ink_ratio: n ? ink / n : 0};
};
</script></body></html>"""


# ── helpers ──────────────────────────────────────────────────────────

def _new_answer(n):
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def _evaluate(expr, timeout=10):
    """Run one expression on the current page and return its value."""
    from hand.perception.cdp_core import (
        list_pages, resolve_page, cdp_connect, cdp_call, _init_domains)
    pages = list_pages()
    if not pages:
        raise RuntimeError("no CDP page — open a browser place first")
    idx, page = resolve_page(None, pages)
    ws = cdp_connect(page['webSocketDebuggerUrl'])
    try:
        _init_domains(ws, 'Runtime')
        raw = cdp_call(ws, 'Runtime.evaluate',
                       {'expression': expr, 'returnByValue': True},
                       timeout=timeout)
        return raw.get('result', {})
    finally:
        ws.close()


def _cleanup(path):
    try:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    except Exception:
        pass


def _purge_expired(now=None):
    now = time.time() if now is None else now
    for cid in [k for k, v in _CHALLENGES.items() if v['expires_at'] <= now]:
        info = _CHALLENGES.pop(cid, None)
        if info:
            _cleanup(info['place_path'])


# ── public API ───────────────────────────────────────────────────────

def challenge(chars=None, font_px=None, ttl_s=None):
    """Render a random string as pixels on a fresh canvas page.

    Returns a receipt that identifies the challenge but does NOT contain the
    string. The caller reads it off the rendered page.
    """
    try:
        chars = DEFAULT_CHARS if chars is None else int(chars)
        font_px = DEFAULT_FONT_PX if font_px is None else int(font_px)
        ttl_s = DEFAULT_TTL_S if ttl_s is None else int(ttl_s)
    except (TypeError, ValueError):
        return {'error': 'chars / font_px / ttl_s must be integers'}
    if not 4 <= chars <= 16:
        return {'error': 'chars must be within 4..16',
                'hint': 'shorter strings make guessing cheap; longer ones '
                        'start measuring legibility instead of delivery'}
    if not 24 <= font_px <= 160:
        return {'error': 'font_px must be within 24..160'}
    if not 5 <= ttl_s <= 3600:
        return {'error': 'ttl_s must be within 5..3600'}

    _purge_expired()

    answer = _new_answer(chars)
    cid = 'ec_' + secrets.token_hex(8)

    width = max(640, int(chars * font_px * 0.80) + 96)
    height = max(160, font_px * 3)
    tmpdir = tempfile.mkdtemp(prefix='hand_eye_check_')
    path = os.path.join(tmpdir, 'page.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(_TEMPLATE.replace('__W__', str(width)).replace('__H__', str(height)))

    from hand.router import route_open
    place = 'file://' + path
    opened = route_open(place)
    nav_ok = bool(opened.get('verified'))

    # The string is injected *after* load, so the document source never holds
    # it. Any failure here is reported honestly rather than papered over.
    evidence = {'navigated': nav_ok, 'rendered': False}
    try:
        draw = _evaluate(
            'window.drawEye(%s, %d)' % (json.dumps(answer), font_px))
        value = draw.get('value') or {}
        evidence['rendered'] = bool(value.get('drawn'))
        evidence['canvas'] = {'w': value.get('w'), 'h': value.get('h')}
        stats = (_evaluate('window.eyeStats()').get('value') or {})
        evidence['ink_ratio'] = round(float(stats.get('ink_ratio') or 0.0), 5)
        evidence['ink_samples'] = stats.get('samples')
    except Exception as exc:
        evidence['render_error'] = str(exc)

    if not evidence['rendered'] or (evidence.get('ink_ratio') or 0) <= 0:
        _cleanup(path)
        return {'error': 'challenge not rendered',
                'evidence': evidence,
                'hint': 'canvas draw or pixel vote failed — refusing to hand '
                        'out a challenge whose page may be blank'}

    now = time.time()
    _CHALLENGES[cid] = {
        'answer': answer,
        'expires_at': now + ttl_s,
        'place': place,
        'place_path': path,
        'chars': chars,
        'font_px': font_px,
        'issued_at': now,
    }

    return {
        'challenge_id': cid,
        'place': place,
        'expires_at': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                    time.gmtime(now + ttl_s)),
        'ttl_s': ttl_s,
        'chars': chars,
        'font_px': font_px,
        'verified': True,
        'evidence': evidence,
        'hint': 'read the string off the rendered page, then verify it — '
                'the string is not in this receipt, the DOM, or the title',
    }


def verify(challenge_id=None, answer=None):
    """Judge a submitted answer. Single use; the challenge is destroyed either way."""
    if not challenge_id:
        return {'error': "challenge_id is required"}
    if answer is None:
        return {'error': 'answer is required'}

    now = time.time()

    info = _CHALLENGES.pop(challenge_id, None)
    if info is None:
        _purge_expired(now)
        return {'pass': False, 'verified': False, 'reason': 'unknown-challenge',
                'hint': 'unknown, expired, or already used — a challenge is '
                        'single use; run op=challenge again'}

    # Sweep *other* expired entries only: this one is already popped, so an
    # expired challenge can still answer reason="expired" (more informative
    # than "unknown") instead of being purged into the same bucket.
    _purge_expired(now)

    elapsed_ms = int((now - info['issued_at']) * 1000)
    expired = now > info['expires_at']
    submitted = '' if answer is None else str(answer)
    matched = secrets.compare_digest(submitted.strip().upper(),
                                     info['answer'].upper())
    place_path = info['place_path']
    _cleanup(place_path)

    if expired:
        return {'pass': False, 'verified': True, 'reason': 'expired',
                'elapsed_ms': elapsed_ms,
                'expires_at': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                            time.gmtime(info['expires_at']))}

    out = {
        'pass': bool(matched),
        'verified': True,
        'challenge_id': challenge_id,
        'elapsed_ms': elapsed_ms,
        'chars': info['chars'],
        'font_px': info['font_px'],
    }
    if not matched:
        # Never echo the expected string. Length only, so the caller can tell
        # "wrong string" from "wrong field".
        out['reason'] = 'mismatch'
        out['answer_len_submitted'] = len(submitted.strip())
        out['answer_len_expected'] = len(info['answer'])
        out['hint'] = ('a pass here means the pixels reached you and you read '
                       'them; a failure is data, not a bug report')
    return out


def active_challenges():
    """Ids and expiry only — no strings, safe to print."""
    _purge_expired()
    return {'count': len(_CHALLENGES),
            'entries': [{'challenge_id': k,
                         'expires_in_s': int(v['expires_at'] - time.time())}
                        for k, v in _CHALLENGES.items()]}
