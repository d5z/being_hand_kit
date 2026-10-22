"""0.12.0 — 动作级帧差分：把 `effected` 从 unknown 变成可判定。

0.11 的每个动作回执都停在 `effected: unknown` + "compare two frames"。
这一层替调用方做那件事：动作前抓一帧、动作后抓一帧、只问**预期区域**
变没变。

三条纪律（都来自 2026-10-20 实测）：

1. **不可比 ≠ 没变化**。抓帧失败、尺寸不同、页面还在动 → `unknown`
   加具体原因。任何路径都不得落到 `no_change`。
2. **只问预期区域**。取消选中能让 5930 个像素变化、bbox 铺满大半屏，
   「整页变了」几乎总是真的，等于没信息。
3. **同时报全屏 bbox，但不判**。当区域内 no_change 而全屏 bbox 落在
   区域外，调用方一眼能看出「我以为点这里，结果变在别处」。

0.13.5（2026-10-22 实测撞出来的一条假阴性）：0.12 只有像素一条通道，
于是把「没落墨的变化」判成没发生——点一个把 `document.title` 改掉的按钮，
点击真的发生了（a11y 树里内层帧的名字从 nest inner 变成 INNER CLICKED），
回执却报 `no_change`，整帧变化率 0.000。像素通道看不见标题、URL、aria
状态：它们不落墨。

第 4 条纪律因此是：**一条通道的空不是世界的空。** 现在并报两条通道——
pixel（渲染像素）与 document（title / URL / 语义指纹）——并且各自声明
自己看不见什么。只有**两条都可用且都没变**才判 no_change；一条可用、
另一条不可用时判 unknown，理由里点明是哪条瞎了。盲区的阴性不能当阴性用。
"""

import base64
import hashlib
import time

from hand.perception.pixels import frame_diff

EXPECT_R = 120           # click 预期区域边长（physical px）
EXPECT_PAD = 24          # drag 预期 bbox 外扩
EFFECT_THRESHOLD = 0.002  # 区域内变化率阈值；实测静止帧 0，真实变化远高于此
STABLE_QUIET_MS = 120
STABLE_TIMEOUT_MS = 800

PIXEL_BLIND_TO = ('anything that changes without changing ink: document.title, '
                  'URL, aria state, form values, live-region text that is not '
                  'rendered where we look')


def grab_png():
    """One full-page PNG. Returns (bytes, None) or (None, reason)."""
    try:
        from hand.perception.cdp_core import cdp_screenshot
        shot = cdp_screenshot()
        data = (shot or {}).get('data')
        if not data:
            return None, 'screenshot returned no data'
        return base64.b64decode(data), None
    except Exception as exc:
        return None, 'screenshot failed: %s' % exc


# ── document channel (0.13.5) ───────────────────────────────────────────────
# What it reads: the accessibility tree as text (already merged across child
# frames), plus the URL and the title. What it is blind to: anything that
# changes only in ink — colour, position, a canvas repaint, an image swapping —
# and anything past the printed line budget.
#
# The first cut of this channel fingerprinted the *top document* with a single
# Runtime.evaluate. It could not see the case that started all this: the
# fixture's title changed inside a child frame, which the top document's
# expression cannot reach — both channels would have stayed silent and the
# receipt would have said no_change again, now with two alibis instead of one.
# The a11y tree is the channel that already merges frames, so it is the channel
# that has to answer here.
DOC_MAX_LINES = 160
DOC_BLIND_TO = ('ink only: colour, position, repaint, canvas/image swap; and '
                'anything past the %d-line print budget' % DOC_MAX_LINES)


def grab_document():
    """Semantic fingerprint of the page. Returns (dict, None) or (None, reason).

    The dict keeps the individual facts so a caller can say *which* one moved
    (title / url / content), not just "something did".
    """
    try:
        from hand.perception.ax_tree import ax_snapshot
        snap = ax_snapshot(max_lines=DOC_MAX_LINES, resolve_coords=False)
        if not isinstance(snap, dict) or snap.get('error'):
            why = snap.get('error') if isinstance(snap, dict) else snap
            return None, 'a11y snapshot failed: %s' % (why,)
        tree = snap.get('tree') or ''
        return {'title': snap.get('page_title') or '',
                'url': snap.get('url') or '',
                'tree_sha': hashlib.sha256(tree.encode('utf-8')).hexdigest(),
                'lines': tree.split('\n'),
                'truncated': bool(snap.get('truncated'))}, None
    except Exception as exc:
        return None, 'a11y snapshot failed: %s' % exc


def _document_verdict(before, after):
    """('changed'|'no_change', which) — which facts moved."""
    moved = []
    if before['title'] != after['title']:
        moved.append('title')
    if before['url'] != after['url']:
        moved.append('url')
    if before['tree_sha'] != after['tree_sha']:
        moved.append('content')
    return ('changed' if moved else 'no_change'), moved


def wait_stable(timeout_ms=STABLE_TIMEOUT_MS, quiet_ms=STABLE_QUIET_MS):
    """Poll until two consecutive frames are identical.

    Returns {'stable': True, 'png': bytes, 'waited_ms': int} on success, or
    {'stable': False, 'reason': str}. The returned png is the settled frame,
    so callers need not grab again.
    """
    started = time.time()
    first, why = grab_png()
    if first is None:
        return {'stable': False, 'reason': why}
    prev = first
    while (time.time() - started) * 1000 < timeout_ms:
        time.sleep(quiet_ms / 1000.0)
        cur, why = grab_png()
        if cur is None:
            return {'stable': False, 'reason': why}
        delta = frame_diff(prev, cur)
        if not delta.get('comparable'):
            return {'stable': False,
                    'reason': 'frames not comparable: %s' % delta.get('why')}
        if delta['changed'] == 0:
            return {'stable': True, 'png': cur,
                    'waited_ms': int((time.time() - started) * 1000)}
        prev = cur
    return {'stable': False,
            'reason': 'page did not settle within %dms' % timeout_ms,
            'waited_ms': int((time.time() - started) * 1000)}


def _expect_region(receipt, kind):
    """Where we expected the world to change. None = full screen."""
    ev = receipt.get('evidence') or {}
    dpr = ev.get('dpr') or 1.0
    try:
        dpr = float(dpr) or 1.0
    except (TypeError, ValueError):
        dpr = 1.0

    if kind == 'click':
        pt = None
        dispatched = ev.get('dispatched')
        if isinstance(dispatched, (list, tuple)) and len(dispatched) >= 2:
            # click dispatches in physical px (evidence.space == 'physical')
            pt = (float(dispatched[0]), float(dispatched[1]))
        else:
            cp = ev.get('click_point') or {}
            if 'x' in cp and 'y' in cp:
                pt = (float(cp['x']) * dpr, float(cp['y']) * dpr)
        if pt is None:
            return None
        half = EXPECT_R / 2.0
        return {'x': pt[0] - half, 'y': pt[1] - half,
                'w': EXPECT_R, 'h': EXPECT_R}

    if kind == 'drag':
        frm = receipt.get('from') or {}
        to = receipt.get('to') or {}
        try:
            # drag dispatches in CSS px (evidence.space == 'css_px')
            xs = [float(frm['x']) * dpr, float(to['x']) * dpr]
            ys = [float(frm['y']) * dpr, float(to['y']) * dpr]
        except (KeyError, TypeError, ValueError):
            return None
        x0, x1 = min(xs) - EXPECT_PAD, max(xs) + EXPECT_PAD
        y0, y1 = min(ys) - EXPECT_PAD, max(ys) + EXPECT_PAD
        return {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0}

    return None          # key / other: whole frame


def _apply(receipt, verdict, change, extra_reason=None):
    """Write the verdict into both top level and evidence.three_state."""
    if not isinstance(receipt, dict):
        return
    receipt['effected'] = verdict
    receipt['change'] = change
    ev = receipt.get('evidence')
    if isinstance(ev, dict):
        ts = ev.get('three_state')
        if isinstance(ts, dict):
            ts['effected'] = verdict
            if verdict == 'unknown':
                ts['effected_reason'] = extra_reason or 'unverifiable'
            else:
                ts.pop('effected_reason', None)
        # 动作层写的 reason 是「我没有 read-back，你自己去比两帧」。这一层
        # 已经比了，原话留在回执里就成了自相矛盾的建议，必须改写成事实。
        if verdict in ('changed', 'no_change') and isinstance(ev.get('reason'), str):
            ev['reason'] = ('no element read-back; the channel verdicts in `change` '
                            'are the effect evidence (%s)' % verdict)


def probe_action(kind, action_fn, verify=True):
    """Run one CDP action and judge the world from two channels.

    `verify=False` reproduces the 0.11 receipt byte for byte (no extra
    captures). Each channel reports its own verdict and declares what it is
    blind to; the combined verdict is `changed` if either saw something,
    `no_change` only if every channel that could look looked and saw nothing,
    and `unknown` when a channel that could not look is the reason the others
    are silent.
    """
    if not verify:
        return action_fn()

    px_before, px_why = grab_png()
    doc_before, doc_why = grab_document()

    if px_before is None and doc_before is None:
        receipt = action_fn()
        reason = 'no baseline from any channel: pixel(%s) document(%s)' % (
            px_why, doc_why)
        _apply(receipt, 'unknown',
               {'verifiable': False, 'reason': reason}, reason)
        return receipt

    receipt = action_fn()
    if not isinstance(receipt, dict):
        return receipt

    # 没派发出去的动作没有「没变化」可言：一个失败的 click 和一个什么都
    # 没做的 click，在帧上长得一模一样。先问它出没出门，再问世界变没变。
    err = receipt.get('error') or receipt.get('failure')
    dispatched = (receipt.get('evidence') or {}).get('dispatched')
    if err and not dispatched:
        reason = 'action did not dispatch: %s' % err
        _apply(receipt, 'unknown',
               {'verifiable': False, 'reason': reason}, reason)
        return receipt

    if px_before is not None:
        settled = wait_stable()
    else:
        # 没有像素通道可等，就给它一段固定的安静时间再做语义读数。
        time.sleep(STABLE_QUIET_MS / 1000.0)
        settled = {'stable': True, 'png': None, 'waited_ms': STABLE_QUIET_MS}

    doc_after, doc_after_why = grab_document()

    change = {'verifiable': True, 'threshold': EFFECT_THRESHOLD}
    channels = {
        'pixel': {'blind_to': PIXEL_BLIND_TO},
        'document': {'blind_to': DOC_BLIND_TO},
    }

    # ── pixel channel ──
    px_verdict = 'unavailable'
    if px_before is None:
        channels['pixel'].update(
            {'verdict': 'unavailable',
             'reason': 'no before frame: %s' % px_why})
    elif not settled.get('stable'):
        channels['pixel'].update(
            {'verdict': 'unavailable',
             'reason': 'page did not settle: %s' % settled.get('reason')})
    else:
        after = settled['png']
        region = _expect_region(receipt, kind)
        scoped = frame_diff(px_before, after, region=region)
        if not scoped.get('comparable'):
            channels['pixel'].update(
                {'verdict': 'unavailable',
                 'reason': 'frames not comparable: %s' % scoped.get('why')})
        else:
            whole = frame_diff(px_before, after)
            px_verdict = ('changed' if scoped['ratio'] > EFFECT_THRESHOLD
                          else 'no_change')
            channels['pixel'].update({
                'verdict': px_verdict,
                'region': scoped['region'],
                'changed': scoped['changed'],
                'total': scoped['total'],
                'ratio': round(scoped['ratio'], 6),
                'bbox': scoped['bbox'],
            })
            change.update({
                'region': scoped['region'],
                'changed': scoped['changed'],
                'total': scoped['total'],
                'ratio': round(scoped['ratio'], 6),
                'bbox': scoped['bbox'],
            })
            if whole.get('comparable'):
                channels['pixel']['whole_frame'] = {
                    'changed': whole['changed'],
                    'ratio': round(whole['ratio'], 6),
                    'bbox': whole['bbox'],
                }
                change['whole_frame'] = dict(channels['pixel']['whole_frame'])
                # 区域没变但别处变了 —— 点歪了的信号。只报，不判。
                if px_verdict == 'no_change' and whole['changed']:
                    change['changed_outside_region'] = True
    change['waited_ms'] = settled.get('waited_ms')

    # ── document channel ──
    doc_verdict = 'unavailable'
    if doc_before is None:
        channels['document'].update(
            {'verdict': 'unavailable',
             'reason': 'no before reading: %s' % doc_why})
    elif doc_after is None:
        channels['document'].update(
            {'verdict': 'unavailable',
             'reason': 'no after reading: %s' % doc_after_why})
    else:
        doc_verdict, moved = _document_verdict(doc_before, doc_after)
        channels['document'].update({
            'verdict': doc_verdict,
            'moved': moved,
            'title_before': doc_before['title'],
            'title_after': doc_after['title'],
            'url_after': doc_after['url'],
        })

    change['channels'] = channels

    # ── combined ──
    verdicts = {channels['pixel']['verdict'], channels['document']['verdict']}
    if 'changed' in verdicts:
        verdict = 'changed'
    elif verdicts == {'no_change'}:
        verdict = 'no_change'
    else:
        verdict = 'unknown'

    reason = None
    if verdict == 'changed':
        seen = [name for name, ch in channels.items()
                if ch.get('verdict') == 'changed']
        reason = 'seen by: %s' % ' + '.join(seen)
        if 'document' in seen and channels['document'].get('moved'):
            reason += ' (%s)' % ', '.join(channels['document']['moved'])
    elif verdict == 'no_change':
        reason = ('both channels looked and saw nothing: pixel region %d/%d px '
                  '(threshold %.4f) unchanged, document title/url/content '
                  'unchanged'
                  % (change.get('changed', 0), change.get('total', 0),
                     EFFECT_THRESHOLD))
    else:
        blind = [name for name, ch in channels.items()
                 if ch.get('verdict') == 'unavailable']
        quiet = [name for name, ch in channels.items()
                 if ch.get('verdict') == 'no_change']
        why_blind = '; '.join('%s: %s' % (name, channels[name].get('reason'))
                              for name in blind)
        reason = ('%s saw no change, %s could not look — a blind channel\'s '
                  'silence is not a negative (%s)'
                  % (' + '.join(quiet) or 'nothing', ' + '.join(blind),
                     why_blind))
    if reason is not None:
        change['reason'] = reason
    _apply(receipt, verdict, change, reason)
    return receipt
