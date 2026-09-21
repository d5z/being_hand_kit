"""Judge library for the production test framework (L2-L6).

Discipline inherited from experiments/a11y_ab (PRD docs/prd-test-framework.md):

  1. every task has a *judge function* — programmatic, not eyeballed;
  2. three-state output: HIT (命中) / NEAR (近似命中, with evidence) /
     MISS (失败, with reason); plus SKIP for environment/network absence;
  3. reproducible: same scenario same verdict;
  4. failure is evidence: a MISS carries the raw receipt.

This library judges *kit receipts*, not model answers. It never raises on a bad
receipt — it returns a Verdict so the caller (unittest or runner) decides.
"""

from dataclasses import dataclass, field, asdict

HIT = "hit"          # 命中
NEAR = "near"        # 近似命中（带证据）
MISS = "miss"        # 失败（带原因）
SKIP = "skip"        # 环境不可用（不算红）


@dataclass
class Verdict:
    state: str
    task: str = ""
    reason: str = ""
    evidence: dict = field(default_factory=dict)

    def ok(self):
        """True for HIT and NEAR (NEAR passes but is flagged)."""
        return self.state in (HIT, NEAR)

    def as_dict(self):
        return asdict(self)


def hit(task="", reason="", **evidence):
    return Verdict(HIT, task, reason, dict(evidence))


def near(task="", reason="", **evidence):
    return Verdict(NEAR, task, reason, dict(evidence))


def miss(task="", reason="", **evidence):
    return Verdict(MISS, task, reason, dict(evidence))


def skip(task="", reason="", **evidence):
    return Verdict(SKIP, task, reason, dict(evidence))


def _ev(receipt):
    """The evidence dict of a receipt (never raises)."""
    if not isinstance(receipt, dict):
        return {}
    ev = receipt.get("evidence")
    return ev if isinstance(ev, dict) else {}


def _reason_of(receipt):
    ev = _ev(receipt)
    return str(ev.get("reason") or receipt.get("error")
               or ev.get("detail") or receipt.get("detail") or "")


# ── open ─────────────────────────────────────────────────────────────

def judge_open(receipt, expect_host=None, task="open"):
    """A navigate-confirmed open whose live document hit `expect_host`."""
    if not isinstance(receipt, dict):
        return miss(task, f"receipt is not a dict: {type(receipt).__name__}", receipt=receipt)
    if receipt.get("open") != "ok":
        return miss(task, f"open field != 'ok': {receipt.get('open')!r}", receipt=receipt)
    if receipt.get("verified") is True and _ev(receipt).get("level") == "navigate_confirmed":
        detail = _ev(receipt).get("detail", "")
        if expect_host and expect_host not in str(receipt.get("place", {}).get("identifier", "")):
            return near(task, f"navigate_confirmed but target identifier missed host {expect_host}",
                        receipt=receipt)
        return hit(task, detail, receipt=receipt)
    return miss(task,
                f"open not verified (level={_ev(receipt).get('level')!r}): {_reason_of(receipt)[:200]}",
                receipt=receipt)


# ── see ──────────────────────────────────────────────────────────────

def judge_a11y(receipt, task="see(a11y)"):
    """Kind=a11y receipt whose tree is structurally valid and real."""
    if not isinstance(receipt, dict) or receipt.get("method") != "cdp_a11y":
        return miss(task, f"method != cdp_a11y: {receipt.get('method') if isinstance(receipt, dict) else receipt!r}",
                    receipt=receipt)
    if receipt.get("verified") is not True:
        return miss(task, f"a11y receipt unverified: {_reason_of(receipt)[:200]}", receipt=receipt)
    if not receipt.get("root_role"):
        return miss(task, "no root_role in a11y receipt", receipt=receipt)
    if not receipt.get("node_count"):
        return miss(task, "node_count is 0/None in a11y receipt", receipt=receipt)
    tree = receipt.get("tree") or ""
    if "[1]" not in tree:
        return miss(task, "tree carries no [1] root handle", receipt=receipt)
    if not isinstance(receipt.get("truncated"), bool):
        return miss(task, "truncated marker is not a bool", receipt=receipt)
    if receipt.get("truncated") and receipt.get("nodes_omitted", 0) <= 0:
        return miss(task, "truncated=True but nodes_omitted <= 0", receipt=receipt)
    return hit(task, f"{receipt['node_count']} lines, root={receipt['root_role']}, format={receipt.get('format')}",
               node_count=receipt["node_count"], sha256=receipt.get("sha256"))


def judge_legacy_channel(receipt, method, task="see(legacy)"):
    """kind=dom / kind=interactive still answer on the old method names."""
    if not isinstance(receipt, dict):
        return miss(task, f"not a dict: {receipt!r}", receipt=receipt)
    if receipt.get("method") != method:
        return miss(task, f"method != {method}: {receipt.get('method')!r}", receipt=receipt)
    if receipt.get("verified") is not True:
        return miss(task, f"legacy {method} unverified: {_reason_of(receipt)[:200]}", receipt=receipt)
    if method == "cdp_interactive" and not receipt.get("count"):
        return miss(task, "interactive map count is 0", receipt=receipt)
    return hit(task, f"{method} answered (verified)", detail=_ev(receipt))


# ── click / type ─────────────────────────────────────────────────────

def judge_click(receipt, expect_name=None, task="click"):
    """A verified click whose evidence names the element it landed on."""
    if not isinstance(receipt, dict):
        return miss(task, f"not a dict: {receipt!r}", receipt=receipt)
    if receipt.get("verified") is not True:
        return miss(task, f"click unverified: {_reason_of(receipt)[:200]}", receipt=receipt)
    ev = _ev(receipt)
    element = str(ev.get("element") or ev.get("text") or "")
    if not element:
        return miss(task, "verified click carries no element evidence", receipt=receipt)
    if expect_name and expect_name.lower() not in element.lower():
        return near(task, f"click landed on {element!r}, expected ~{expect_name!r}", receipt=receipt)
    return hit(task, f"clicked {element!r}", element=element, box=ev.get("box"))


def judge_type(receipt, text, read_back=None, task="type"):
    """A verified type; optionally the DOM read-back must equal `text`."""
    if not isinstance(receipt, dict):
        return miss(task, f"not a dict: {receipt!r}", receipt=receipt)
    if receipt.get("verified") is not True:
        return miss(task, f"type unverified: {_reason_of(receipt)[:200]}", receipt=receipt)
    if receipt.get("text") != text:
        return miss(task, f"receipt text {receipt.get('text')!r} != sent {text!r}", receipt=receipt)
    if read_back is not None:
        if read_back == text:
            return hit(task, f"typed {text!r} and read back {read_back!r}", read_back=read_back)
        return miss(task, f"typed {text!r} but DOM read back {read_back!r}", receipt=receipt,
                    read_back=read_back)
    return near(task, f"typed {text!r} (no DOM read-back performed)", receipt=receipt)


def judge_screenshot(receipt, task="shot"):
    if not isinstance(receipt, dict):
        return miss(task, f"not a dict: {receipt!r}", receipt=receipt)
    if not receipt.get("data_length"):
        return miss(task, "screenshot has no data_length", receipt=receipt)
    return hit(task, f"{receipt.get('format')} {receipt['data_length']} b64 chars", receipt=receipt)


def judge_close(receipt, task="close"):
    """cdp_close is `evidence: claimed` in the manifest — judge it honestly."""
    if not isinstance(receipt, dict):
        return miss(task, f"not a dict: {receipt!r}", receipt=receipt)
    if receipt.get("closed") == "ok":
        return hit(task, f"closed ok, pages_closed={receipt.get('pages_closed')}", receipt=receipt)
    if receipt.get("closed") == "partial":
        return near(task, f"close partial: {receipt.get('error')}", receipt=receipt)
    return miss(task, f"close receipt unknown: {receipt!r}", receipt=receipt)


# ── failure honesty (L4 假 ok 检测) ──────────────────────────────────

def judge_honest_failure(receipt, expect_reason=None, task="failure-honesty"):
    """The receipt MUST NOT claim ok/verified — it must carry a reason.

    This is the anti-fake-ok judge (feedback-ledger 3339b7f lesson): a failed
    operation reported as ok is a bug; reported as verified=False + reason is
    correct behaviour.
    """
    if not isinstance(receipt, dict):
        return miss(task, f"not a dict: {receipt!r}", receipt=receipt)
    if receipt.get("verified") is True:
        return miss(task, "FAKE OK: receipt claims verified=True for a failing scenario",
                    receipt=receipt)
    reason = _reason_of(receipt)
    if not reason:
        return miss(task, "receipt is unverified but carries no reason (silent failure)",
                    receipt=receipt)
    if expect_reason and expect_reason.lower() not in reason.lower():
        return near(task, f"honest failure, but reason {reason[:120]!r} lacks {expect_reason!r}",
                    receipt=receipt)
    return hit(task, f"honest failure: verified=False, reason={reason[:160]!r}", receipt=receipt)


def judge_error_receipt(receipt, task="error-receipt"):
    """route_see-style error receipts: {'error': ..., 'verified': False, 'evidence': {...}}."""
    if not isinstance(receipt, dict) or not receipt.get("error"):
        return miss(task, f"no error field: {receipt!r}", receipt=receipt)
    if receipt.get("verified") is not False:
        return miss(task, "error receipt must carry verified=False", receipt=receipt)
    if not _ev(receipt).get("verified") is False:
        return near(task, "error receipt evidence.verified is not exactly False", receipt=receipt)
    return hit(task, f"error receipt: {str(receipt['error'])[:140]!r}", receipt=receipt)


def assert_verdict(tc, verdict):
    """Turn a Verdict into a unittest outcome (HIT/NEAR pass, MISS fail, SKIP skip)."""
    if verdict.state == SKIP:
        tc.skipTest(verdict.reason or "skipped by environment")
    if not verdict.ok():
        tc.fail(f"[{verdict.state.upper()}] {verdict.task}: {verdict.reason}\n"
                f"evidence={verdict.evidence}")
