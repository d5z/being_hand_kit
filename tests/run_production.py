#!/usr/bin/env python3
"""Production gate runner — runs L1-L6 and writes tests/REPORT-production.md.

Usage:
    python3 tests/run_production.py [--repeats N] [--layers L2,L4]

L1 unit modules are the ones tests/run_tests.py already loads. L2-L6 are the
real-Chrome layers. Real-network L3 journeys SKIP (not red) when a host is
unreachable; every skip is reported with its reason.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, "/home/alice/Hand")

# layer -> module list. L1 is kept identical to tests/run_tests.py MODULES.
LAYERS = {
    "L1": ["tests.test_plan", "tests.test_tier2_3", "tests.test_platform",
           "tests.test_vision_llm", "tests.test_cdp_contract",
           "tests.test_cdp_contract_real", "tests.test_windows_support",
           "tests.test_receipt_contract", "tests.test_ax_tree", "tests.test_ax_see",
           "tests.test_macos_discovery", "tests.test_chrome_profile",
           "tests.test_kit_quickfixes", "tests.test_release_070",
           "tests.test_hand_api"],
    "L2": ["tests.integration.test_l2_tools"],
    "L3": ["tests.production.test_scenarios"],
    "L4": ["tests.production.test_receipt_contract"],
    "L5": ["tests.production.test_compat"],
    "L6": ["tests.production.test_stability"],
}
BROWSER_LAYERS = ("L2", "L3", "L4", "L5", "L6")


def ensure_chrome():
    try:
        from hand.perception.cdp_launcher import chrome_running, ensure_chrome as spawn
        if not chrome_running():
            spawn()
        return chrome_running()
    except Exception as e:
        print(f"  ! chrome not available: {type(e).__name__}: {e}")
        return False


def run_layer(layer, modules):
    """Run one layer's modules in an ISOLATED subprocess; return a counts dict.

    Layer isolation matters: an in-process run leaked page/session state from
    one layer into the next (a fixture page left live made a later layer's
    navigation look confirmed on the same host), turning the gate red for
    reasons that are not product failures.
    """
    cmd = [sys.executable, "-m", "tests.harness.layer_runner"] + list(modules)
    try:
        proc = subprocess.run(cmd, cwd="/home/alice/Hand", capture_output=True,
                              text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return {"tests": 0, "passed": 0, "skipped": 0, "failed": 0, "errors": 1,
                "skips": [], "failures": [[layer, "layer timed out after 900s"]],
                "seconds": 900.0}
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("__LAYER_RESULT__"):
            payload = json.loads(line[len("__LAYER_RESULT__"):])
    if payload is None:
        return {"tests": 0, "passed": 0, "skipped": 0, "failed": 0, "errors": 1,
                "skips": [],
                "failures": [[layer, "no result payload; stderr:\n"
                              + proc.stderr[-1500:]]],
                "seconds": 0.0}
    return payload


def build_report(all_runs, repeats, layers):
    """all_runs: list over repeats of {layer: counts}."""
    lines = []
    lines.append("# hand 0.7 生产测试报告（L1-L6 发布硬 gate）")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"重复轮次：{repeats}  ·  层：{', '.join(layers)}  ")
    lines.append(f"环境：Python {sys.version.split()[0]}，headless Chrome via CDP localhost:9222")
    lines.append("")
    lines.append("判定纪律：每任务一个程序化 judge；三态 HIT/NEAR/MISS（NEAR 通过但标注）；"
                 "网络不可达记 SKIP 不算红。")
    lines.append("")
    lines.append("## 汇总表（各轮全量）")
    lines.append("")
    lines.append("| 层 | 用例数 | 通过 | SKIP | 失败 | ERROR | 用时(s) | 结果 |")
    lines.append("|----|-------:|-----:|-----:|-----:|------:|--------:|------|")
    for layer in layers:
        per = [runs.get(layer) for runs in all_runs]
        per = [p for p in per if p]
        if not per:
            lines.append(f"| {layer} | 0 | 0 | 0 | 0 | 0 | - | 未运行 |")
            continue
        tests = max(p["tests"] for p in per)
        passed = min(p["passed"] for p in per)
        skipped = max(p["skipped"] for p in per)
        failed = sum(p["failed"] for p in per)
        errors = sum(p["errors"] for p in per)
        secs = round(sum(p["seconds"] for p in per), 1)
        green = (failed == 0 and errors == 0)
        lines.append(f"| {layer} | {tests} | {passed} | {skipped} | {failed} | {errors} | "
                     f"{secs} | {'✅ 绿' if green else '❌ 红'} |")
    lines.append("")

    # repeat-level verdict
    lines.append("## 逐轮结果")
    lines.append("")
    lines.append("| 轮次 | " + " | ".join(layers) + " | 全绿 |")
    lines.append("|------|" + "|".join(["------"] * (len(layers) + 1)) + "|")
    all_green = True
    for i, runs in enumerate(all_runs, 1):
        cells = []
        green = True
        for layer in layers:
            p = runs.get(layer)
            if not p:
                cells.append("未运行"); continue
            ok = p["failed"] == 0 and p["errors"] == 0
            green = green and ok
            cells.append(f"{p['passed']}P/{p['skipped']}S/{p['failed']}F/{p['errors']}E"
                         f"{' ✅' if ok else ' ❌'}")
        all_green = all_green and green
        lines.append(f"| {i} | " + " | ".join(cells) + f" | {'✅' if green else '❌'} |")
    lines.append("")
    lines.append(f"**发布 gate：{'通过（L1-L6 全绿 × %d 轮）' % repeats if all_green else '阻塞'}**")
    lines.append("")

    # skips
    lines.append("## SKIP 明细（有理由不计红）")
    lines.append("")
    any_skip = False
    for layer in layers:
        for runs in all_runs:
            p = runs.get(layer)
            if not p:
                continue
            for t, reason in p.get("skips", []):
                any_skip = True
                lines.append(f"- [{layer}] {t} — {reason}")
    if not any_skip:
        lines.append("（本轮无 SKIP）")
    lines.append("")

    # failures
    lines.append("## 失败明细（应为空）")
    lines.append("")
    any_fail = False
    for layer in layers:
        for runs in all_runs:
            p = runs.get(layer)
            if not p:
                continue
            for t, tb in p.get("failures", []):
                any_fail = True
                lines.append(f"### [{layer}] {t}")
                lines.append("")
                lines.append("```")
                lines.append(tb.strip()[-1500:])
                lines.append("```")
    if not any_fail:
        lines.append("（无失败）")
    lines.append("")

    # findings
    lines.append("## 发现与已知缺口")
    lines.append("")
    lines.append("1. **route_do 不回退到 cdp_type（`[idx]|text` 不可达）**："
                 "route_do 在第一个 backend 返回失败回执时即返回（`result.get('success', True)` "
                 "对无 success 键的失败回执判真）。回执本身诚实（verified=False + reason），"
                 "非假 ok；公开流程（click 聚焦 → cdp_type）正常。L4 "
                 "`test_route_do_with_text_form_never_silently_passes` 就此设回归护栏。")
    lines.append("2. **cdp_close 曾是假 ok（已修）**：`Browser.enable` 无此方法，异常被吞，"
                 "Browser.close 从未发出却回 closed=ok。已改为关闭后轮询端点 + "
                 "verified 回执（commit da1919a）。L6 崩溃/关闭测试覆盖。")
    lines.append("3. **manifest 与 route_see 的 kind 不完全一致**：route_see 支持 kind='vlm'，"
                 "manifest cdp_see enum 未列；manifest 列了 kind='screenshot' 但 route_see 无显式分支"
                 "（会落到 place 默认）。旧调用者不受影响，L5 `test_unknown_kind_does_not_crash` 兜底。")
    lines.append("4. **回执无 timestamp/status 字段**：本仓库 F14 契约（docs/prd-receipt-contract.md S3）"
                 "定义的回执形状是 verified:bool + evidence:{...} + 结果字段"
                 "（open/method/closed），不含 PRD-test-framework 文字里的 status/timestamp。"
                 "L4 按实际 F14 契约扫描；若需要时间戳，属产品增量而非测试缺口。")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--layers", default="L1,L2,L3,L4,L5,L6")
    ap.add_argument("--report", default=os.path.join(os.path.dirname(__file__),
                                                     "REPORT-production.md"))
    args = ap.parse_args()
    layers = [l.strip() for l in args.layers.split(",") if l.strip()]

    all_runs = []
    exit_code = 0
    for rep in range(1, args.repeats + 1):
        print(f"\n===== repeat {rep}/{args.repeats} =====")
        if any(l in BROWSER_LAYERS for l in layers):
            from tests.harness.runner import ensure_fresh_browser
            fresh = ensure_fresh_browser()
            print(f"   browser preflight: {'fresh' if fresh else 'unavailable — browser layers will SKIP'}")
        runs = {}
        for layer in layers:
            ensure_chrome()
            print(f"-- {layer} ({', '.join(LAYERS[layer])})")
            p = run_layer(layer, LAYERS[layer])
            runs[layer] = p
            print(f"   {p['tests']} tests, {p['passed']} passed, "
                  f"{p['skipped']} skipped, {p['failed']} failed, "
                  f"{p['errors']} errors, {p['seconds']}s")
            for t, tb in p.get("failures", []):
                print(f"   FAIL {t}")
            if p["failed"] or p["errors"]:
                exit_code = 1
        all_runs.append(runs)

    report = build_report(all_runs, args.repeats, layers)
    with open(args.report, "w") as f:
        f.write(report)
    print(f"\nreport -> {args.report}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
