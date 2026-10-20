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
"""

import base64
import time

from hand.perception.pixels import frame_diff

EXPECT_R = 120           # click 预期区域边长（physical px）
EXPECT_PAD = 24          # drag 预期 bbox 外扩
EFFECT_THRESHOLD = 0.002  # 区域内变化率阈值；实测静止帧 0，真实变化远高于此
STABLE_QUIET_MS = 120
STABLE_TIMEOUT_MS = 800


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
            ev['reason'] = ('no element read-back; the frame diff in `change` '
                            'is the effect evidence (%s)' % verdict)


def probe_action(kind, action_fn, verify=True):
    """Run one CDP action with a frame diff around it.

    `verify=False` reproduces the 0.11 receipt byte for byte (no extra
    captures). Any failure to grab or compare leaves `effected: unknown`
    with the reason attached — never `no_change`.
    """
    if not verify:
        return action_fn()

    before, why = grab_png()
    if before is None:
        receipt = action_fn()
        _apply(receipt, 'unknown',
               {'verifiable': False, 'reason': why}, why)
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

    settled = wait_stable()
    if not settled.get('stable'):
        _apply(receipt, 'unknown',
               {'verifiable': False, 'reason': settled.get('reason')},
               settled.get('reason'))
        return receipt

    after = settled['png']
    region = _expect_region(receipt, kind)

    scoped = frame_diff(before, after, region=region)
    if not scoped.get('comparable'):
        _apply(receipt, 'unknown',
               {'verifiable': False, 'reason': scoped.get('why')},
               scoped.get('why'))
        return receipt

    whole = frame_diff(before, after)
    verdict = ('changed' if scoped['ratio'] > EFFECT_THRESHOLD
               else 'no_change')

    change = {
        'verifiable': True,
        'threshold': EFFECT_THRESHOLD,
        'region': scoped['region'],
        'changed': scoped['changed'],
        'total': scoped['total'],
        'ratio': round(scoped['ratio'], 6),
        'bbox': scoped['bbox'],
        'waited_ms': settled.get('waited_ms'),
    }
    if whole.get('comparable'):
        change['whole_frame'] = {
            'changed': whole['changed'],
            'ratio': round(whole['ratio'], 6),
            'bbox': whole['bbox'],
        }
        # 区域没变但别处变了 —— 点歪了的信号。只报，不判。
        if verdict == 'no_change' and whole['changed']:
            change['changed_outside_region'] = True

    reason = None
    if verdict == 'no_change':
        reason = ('region unchanged across two comparable frames '
                  '(%d/%d px, threshold %.4f)'
                  % (scoped['changed'], scoped['total'], EFFECT_THRESHOLD))
    _apply(receipt, verdict, change, reason)
    return receipt
