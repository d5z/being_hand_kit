"""Receipt declarations — the 0.9 honesty fields (S1).

PRD: docs/prd-0.9-receipt-honesty.md S1 — "跳过必留痕". Any output that was
truncated, dropped or skipped must be *declared* in the receipt: what was cut,
why, how much. Absence means complete; there is no `null` placeholder
(缺席=完整，存在=有痕).

Field-name note
---------------
The PRD sketches the unified block as ``"truncated": {field, reason, dropped,
total}``. Since 0.7.0 the a11y receipt has carried a *top-level boolean*
``truncated`` (frozen contract: README, tests, the [idx] protocol and the MCP
face all read it). A rename is a protocol break, so the unified block lands
under a new key, ``truncation``, with exactly the PRD's four keys:

    "truncation": {"field": "tree", "reason": "max_lines",
                   "dropped": 57, "total": 657}

The legacy per-backend booleans/counts (``truncated``, ``nodes_omitted``,
``total_chars``, ``total``) are kept unchanged for one version. Skipped steps
travel through the existing ``hint`` channel as ``skipped: <what> (<why>)``.
"""

# The unified block's keys — a contract (append-only; renaming is a break).
TRUNCATION_KEYS = ("field", "reason", "dropped", "total")

SKIPPED_PREFIX = "skipped: "


def truncation(field, reason, dropped, total):
    """Build the unified truncation block, or None when nothing was dropped.

    `field`   — which receipt field the cut applies to ("tree", "elems", "text")
    `reason`  — why it was cut ("max_lines", "max_elems", "max_chars")
    `dropped` — how many units were dropped
    `total`   — how many units the full result would have had
    """
    try:
        dropped = int(dropped)
        total = int(total)
    except (TypeError, ValueError):
        return None
    if dropped <= 0:
        return None
    return {"field": str(field), "reason": str(reason),
            "dropped": dropped, "total": total}


def skipped(what, why):
    """One skipped-step note: ``skipped: <what> (<why>)``."""
    return f"{SKIPPED_PREFIX}{what} ({why})"


def merge_hints(*parts):
    """Join hint fragments with ', ', dropping empties/None. None if all empty."""
    flat = []
    for p in parts:
        if not p:
            continue
        if isinstance(p, (list, tuple)):
            flat.extend(x for x in p if x)
        else:
            flat.append(p)
    return "; ".join(flat) if flat else None


# ── D1 (0.10): emitted — the first half of the two-part signature ────────────
#
# PRD: docs/prd-delivery-honesty.md D1. The receipt answers "did the action
# happen?" (verified) but historically not "did the evidence reach the caller?".
# On 2026-10-17 those two separated for real: shot was 100% verified, and zero
# images reached the context.
#
# The boundary this block must never cross:
#
#   hand declares what hand PUT ON THE WIRE. It does not declare what the
#   caller RECEIVED — that decision belongs to portal/heart, which appends its
#   own `delivery` block. A hand-side "attached: true" would be a new claimed
#   field masquerading as verified.
#
# So `emitted.channels.X.emitted == true` means exactly one thing: hand placed
# channel X's payload into THIS receipt dict. Not "generated", not "captured",
# not "should have arrived". If hand captured pixels but returned only a file
# path, that is `emitted: false` with `reason: "file_path"` — a positive
# declaration of a gap, per D2 (silence is not completeness).
#
# Absence of the block means "not implemented / not a perception channel", and
# that is a different statement from `emitted: false`. Failure paths keep
# `error` + `evidence.reason` and do not carry `emitted` (nothing was emitted,
# and the error already says so in the caller's own language).

EMITTED_BY = "hand"

# Reason enum for emitted: false. Frozen-ish: the test asserts these values so
# a typo cannot silently become a new semantic.
EMITTED_IMAGE_REASONS = (
    "not_requested",   # data was captured but the caller did not ask for it
    "file_path",       # pixels went to a file, not into the receipt
    "no_image",        # this channel never had an image to emit
)


def _b64_decoded_len(b64):
    """Decoded byte length of a base64 string (padding only at the tail)."""
    n = len(b64)
    if not n:
        return 0
    pad = b64[-2:].count("=")
    return n // 4 * 3 - pad


def emitted_channel(emitted, reason=None, **facts):
    """One channel entry inside the emitted block.

    `emitted` is a bool. When False, `reason` is mandatory (D2: a gap must be
    declared positively, never inferred from absence).
    """
    out = {"emitted": bool(emitted)}
    if not emitted:
        out["reason"] = reason or "unknown"
    for k, v in facts.items():
        if v is not None:
            out[k] = v
    return out


def emitted_block(channels):
    """The D1 emitted block — what hand itself put into this receipt."""
    return {"by": EMITTED_BY,
            "channels": {k: v for k, v in channels.items() if v is not None}}


def image_channel(b64=None, fmt=None, path=None):
    """Image channel: true only when the base64 payload is in this receipt."""
    if b64:
        return emitted_channel(True, bytes=_b64_decoded_len(b64), format=fmt,
                               encoding="base64", data_chars=len(b64))
    if path:
        return emitted_channel(False, "file_path", path=path)
    return emitted_channel(False, "not_requested")


def text_channel(text=None, count=None, unit="chars", key=None, reason=None):
    """Text-ish channel (dom text, a11y tree, vlm description, ocr lines).

    `count`/`unit` describe the payload that actually went into the receipt;
    `key` names the field it rides in, so a consumer can find it.

    `reason` (0.13.3) lets the caller say WHY a channel is empty when that is
    not the caller's choice — "no_text" (the page has none at this level) is a
    different statement from "not_requested" (data existed, nobody asked).
    """
    if text is None:
        return emitted_channel(False, reason or "not_requested")
    n = count if count is not None else len(text)
    return emitted_channel(True, count=n, unit=unit, key=key)

