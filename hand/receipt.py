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
    """Join hint fragments with '; ', dropping empties/None. None if all empty."""
    flat = []
    for p in parts:
        if not p:
            continue
        if isinstance(p, (list, tuple)):
            flat.extend(x for x in p if x)
        else:
            flat.append(p)
    return "; ".join(flat) if flat else None
