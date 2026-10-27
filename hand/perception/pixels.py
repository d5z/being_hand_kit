"""Pixel vote for the visual-state marker — hand 0.10 D3.

PRD: docs/prd-delivery-honesty.md D3「blank 判据加像素票」.

S2 (0.9) classified page state from the DOM only. That proxy lies exactly where
the state matters: `rand2.html` — white background, eight 48px monospace
characters, 1280x900 viewport — has `text_len=8` (< BLANK_TEXT_THRESHOLD=20) and
no img/canvas/video, so the DOM-only rule reported `blank` while the screen was
plainly not empty. Same hole for all-canvas pages and slow-loading pages.

D3 rule: **blank is a visual claim and needs a visual witness.** Before saying
"blank" we take one pixel vote — a downscaled screenshot, decoded with the
standard library only, reduced to `ink_ratio` (share of sampled pixels that
differ from the dominant background colour).

Design constraints (from the PRD):

* cost — the vote runs only when the DOM rule has already produced a blank
  candidate, and it decodes a 0.25-scale frame (320x225 px for a 1280x900
  viewport), not the full screenshot.
* honesty — a failed vote is not evidence of emptiness. It comes back as
  `{"available": False}` and the caller must downgrade to `unknown`, never
  report `blank`.

No third-party dependency: PNG decode is zlib + the five PNG filters.
"""

import base64
import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"

# Downscale before decoding: the vote is about "is there ink", not fidelity.
PIXEL_SCALE = 0.25

# A snapshot bigger than this is re-taken downscaled instead of decoded: a full
# 1280x900 RGBA frame is 4.6 MB of raw bytes and pure-Python unfiltering it
# would cost more than the second capture.
PIXEL_FULL_DECODE_MAX = 200000

# Share of the frame that must differ from the background colour before the
# page counts as "has ink". 0.2% is deliberately small: at 0.25 scale the eight
# 48px characters of the S2 counterexample cover roughly 1% of the frame, while
# a genuinely blank page sits at exactly 0.0.
INK_MIN_RATIO = 0.002

# RGB manhattan distance from the background colour that counts as ink.
INK_DISTANCE = 24

# Quantise to 16 levels per channel when voting for the background colour, so
# JPEG-free PNG gradients and antialiasing do not split the vote.
INK_QUANT_SHIFT = 4

_VOTE_MSG_ID = 89
_CAPTURE_MSG_ID = 90


class PngUnsupported(ValueError):
    """The bytes are a PNG this decoder does not read (bit depth / interlace /
    colour type). Never a silent guess: the caller downgrades to unknown."""


def png_size(data):
    """(width, height) from the IHDR head, or None. Cheap — no decode."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 24:
        return None
    if bytes(data[:8]) != PNG_SIG:
        return None
    try:
        return struct.unpack("!II", bytes(data[16:24]))
    except struct.error:
        return None


def decode_png(data):
    """PNG bytes -> (width, height, channels, unfiltered rows).

    Supports 8-bit, non-interlaced, colour types 0/2/4/6 — what Chrome's
    Page.captureScreenshot emits. Anything else raises PngUnsupported.
    """
    if not isinstance(data, (bytes, bytearray)) or bytes(data[:8]) != PNG_SIG:
        raise PngUnsupported("not a png")
    pos = 8
    width = height = depth = ctype = interlace = None
    idat = []
    while pos + 8 <= len(data):
        (length,) = struct.unpack("!I", bytes(data[pos:pos + 4]))
        ctype_tag = bytes(data[pos + 4:pos + 8])
        chunk = bytes(data[pos + 8:pos + 8 + length])
        pos += 12 + length
        if ctype_tag == b"IHDR":
            if len(chunk) < 13:
                raise PngUnsupported("short IHDR")
            (width, height, depth, ctype,
             _comp, _filt, interlace) = struct.unpack("!IIBBBBB", chunk[:13])
        elif ctype_tag == b"IDAT":
            idat.append(chunk)
        elif ctype_tag == b"IEND":
            break
    if not width or not height:
        raise PngUnsupported("no IHDR")
    if depth != 8 or interlace != 0:
        raise PngUnsupported("bit depth %s / interlace %s" % (depth, interlace))
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise PngUnsupported("colour type %s" % ctype)
    if not idat:
        raise PngUnsupported("no IDAT")
    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    if len(raw) < (stride + 1) * height:
        raise PngUnsupported("truncated IDAT")
    return width, height, channels, _unfilter(raw, width, height, channels, stride)


def _unfilter(raw, width, height, channels, stride):
    """Undo the five PNG row filters. bytes in, bytearray out."""
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ftype == 1:                      # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:                    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:                    # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:                    # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            raise PngUnsupported("row filter %s" % ftype)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def ink_stats(png_bytes, step=1):
    """Pixel vote over a PNG.

    Returns {"width", "height", "pixels", "ink_ratio", "background",
    "distinct_colors"}. `ink_ratio` is the share of sampled pixels whose
    colour sits further than INK_DISTANCE from the dominant background colour.
    """
    width, height, channels, buf = decode_png(png_bytes)
    step = max(1, int(step))
    samples = []
    counts = {}
    for y in range(0, height, step):
        base = y * width * channels
        for x in range(0, width, step):
            off = base + x * channels
            if channels >= 3:
                r, g, b = buf[off], buf[off + 1], buf[off + 2]
            else:
                r = g = b = buf[off]
            samples.append((r, g, b))
            key = (r >> INK_QUANT_SHIFT, g >> INK_QUANT_SHIFT,
                   b >> INK_QUANT_SHIFT)
            counts[key] = counts.get(key, 0) + 1
    total = len(samples) or 1
    # 并列（2026-10-27）：max() 在两个桶计数相同时，赢家由 dict 迭代序静默决定——
    # 那是「谁先进 counts 谁赢」，不是任何关于画面的判断。背景色照旧给一个（下游要它），
    # 但把并列的事实带出去：background_tie = 与赢家同票的桶数（1 = 无并列）。
    _top = max(counts.values())
    _tied = [k for k, v in counts.items() if v == _top]
    bg_key = _tied[0]
    # Compare against the centre of the winning bucket, not its floor: with
    # floor-only centres a pure white frame (255 -> bucket 15 -> 240) would be
    # 45 away from its own background and count as ink.
    half = 1 << (INK_QUANT_SHIFT - 1)
    centre = tuple((int(k) << INK_QUANT_SHIFT) + half for k in bg_key)
    ink = 0
    for r, g, b in samples:
        if (abs(r - centre[0]) + abs(g - centre[1])
                + abs(b - centre[2])) > INK_DISTANCE:
            ink += 1
    return {
        "width": width,
        "height": height,
        "pixels": total,
        "ink_ratio": ink / float(total),
        "background": "#%02x%02x%02x" % centre,
        "background_tie": len(_tied),
        "distinct_colors": len(counts),
    }


def capture_downscaled(ws, call, scale=PIXEL_SCALE):
    """One downscaled screenshot over an existing CDP socket. Raises on failure."""
    metrics = call(ws, "Page.getLayoutMetrics", {}, msg_id=_VOTE_MSG_ID,
                   timeout=5) or {}
    viewport = metrics.get("cssLayoutViewport") or {}
    vw = int(viewport.get("clientWidth") or 0)
    vh = int(viewport.get("clientHeight") or 0)
    if vw <= 0 or vh <= 0:
        raise ValueError("no viewport metrics")
    clip = {"x": 0, "y": 0, "width": vw, "height": vh, "scale": scale}
    res = call(ws, "Page.captureScreenshot",
               {"format": "png", "clip": clip},
               msg_id=_CAPTURE_MSG_ID, timeout=10) or {}
    data_b64 = res.get("data") or ""
    if not data_b64:
        raise ValueError("empty screenshot")
    return base64.b64decode(data_b64)


def pixel_vote(ws=None, call=None, png_b64=None):
    """The vote, never raising. `available: False` is a valid answer and means
    "no evidence" — the caller must not read it as emptiness."""
    try:
        png = None
        if png_b64:
            try:
                raw = base64.b64decode(png_b64)
            except Exception:
                raw = b""
            size = png_size(raw)
            if size and size[0] * size[1] <= PIXEL_FULL_DECODE_MAX:
                png = raw
        if png is None:
            if ws is None or call is None:
                raise ValueError("no pixel source")
            png = capture_downscaled(ws, call)
        stats = ink_stats(png)
        return {
            "available": True,
            "ink_ratio": round(stats["ink_ratio"], 5),
            "width": stats["width"],
            "height": stats["height"],
            "background": stats["background"],
            "colors": stats["distinct_colors"],
        }
    except Exception:
        return {"available": False, "reason": "pixel-unavailable"}


# ── 0.12.0 变化可判定：帧差分 ──────────────────────────────────────────
#
# 0.11 的动作回执统一停在 `effected: unknown` + "compare two frames".
# 这一层把「比两帧」变成 hand 自己的动作而不是调用方的体力活。
#
# 设计依据（2026-10-20 实测，Excalidraw 800x600）：
#   · 静止页面连抓两帧 = 0 像素差 —— 「没变」可以被强判定
#   · 取消选中 = 5930 像素差，bbox 覆盖大半屏 —— 变化量不等于动作对
#   · 全屏双循环纯 Python ~0.9s —— 产品化必须区域限定
#
# 因此 frame_diff 的第一职责不是「算出变了多少」，而是**先回答两帧能不能比**。
# 不可比时返回 comparable:false，绝不把「比不了」算成「没变化」。

FRAME_CH_DELTA = 12      # 三通道绝对差之和的容忍值；静止帧实测 0，真实变化远超此值


def frame_diff(before, after, region=None, ch_delta=FRAME_CH_DELTA):
    """Pixel diff of two PNGs.

    region: {'x','y','w','h'} in image pixels; None = whole frame.
    Returns {comparable, changed, total, ratio, region, bbox?, why?}.

    `comparable: False` means the two frames cannot be compared at all
    (unsupported PNG, different geometry). Callers MUST NOT read that as
    "nothing changed" — that is exactly the substitution this function
    exists to prevent.
    """
    try:
        w1, h1, c1, buf1 = decode_png(before)
    except PngUnsupported as exc:
        return {'comparable': False, 'why': 'before: unsupported png (%s)' % exc}
    try:
        w2, h2, c2, buf2 = decode_png(after)
    except PngUnsupported as exc:
        return {'comparable': False, 'why': 'after: unsupported png (%s)' % exc}

    if (w1, h1, c1) != (w2, h2, c2):
        return {'comparable': False,
                'why': 'geometry %dx%dx%d vs %dx%dx%d'
                       % (w1, h1, c1, w2, h2, c2)}

    if region:
        # Clip the *edges*, not the origin: a region that starts off-image
        # (a click near the border asks for x-60) must keep its full width
        # inside the frame, otherwise the scope silently widens to the whole
        # image — the exact over-scoping this parameter exists to avoid.
        rx = int(region.get('x', 0))
        ry = int(region.get('y', 0))
        rw = int(region.get('w', w1))
        rh = int(region.get('h', h1))
        x0 = max(0, rx)
        y0 = max(0, ry)
        x1 = min(w1, rx + rw)
        y1 = min(h1, ry + rh)
    else:
        x0, y0, x1, y1 = 0, 0, w1, h1

    if x1 <= x0 or y1 <= y0:
        return {'comparable': False,
                'why': 'empty region %r inside %dx%d' % (region, w1, h1)}

    ch = 3 if c1 >= 3 else c1
    stride = w1 * c1
    changed = 0
    minx, miny, maxx, maxy = x1, y1, -1, -1

    for y in range(y0, y1):
        base = y * stride
        for x in range(x0, x1):
            off = base + x * c1
            d = 0
            for k in range(ch):
                d += abs(buf1[off + k] - buf2[off + k])
                if d > ch_delta:
                    break
            if d > ch_delta:
                changed += 1
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y

    total = (x1 - x0) * (y1 - y0)
    out = {
        'comparable': True,
        'changed': changed,
        'total': total,
        'ratio': (changed / float(total)) if total else 0.0,
        'region': {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0},
        'ch_delta': ch_delta,
    }
    if changed:
        out['bbox'] = {'x': minx, 'y': miny,
                       'w': maxx - minx + 1, 'h': maxy - miny + 1}
    else:
        out['bbox'] = None
    return out
