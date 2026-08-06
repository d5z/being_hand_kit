#!/usr/bin/env python3
"""Hand CLI — command-line entry point for Hand V6.

Usage:
    hand plan "新建一个笔记并写入今天的日期"
    hand plan --model moonshotai/kimi-k2.6 "搜索最近的新闻"
    hand plan --json "打开浏览器并登录"        # machine-readable output
    hand plan --help

Architecture:
    cli.py → hand.plan.PlanningEngine → opencode CLI → parser → Steps → stdout
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure hand/ is importable when running from repo root
_HAND_ROOT = Path(__file__).resolve().parent
if str(_HAND_ROOT) not in sys.path:
    sys.path.insert(0, str(_HAND_ROOT))

from hand.plan import PlanningEngine, Step


# -- CLI definition ----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hand",
        description="Hand V6 — graphical interface framework. Plan GUI sequences from natural language.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # hand plan
    plan_parser = sub.add_parser("plan", help="Convert a natural-language goal into Hand steps")
    plan_parser.add_argument("goal", nargs="+", help="Natural-language goal (e.g. '打开浏览器搜索天气')")
    plan_parser.add_argument("--model", "-m", default=None,
                             help="Model override (e.g. moonshotai/kimi-k2.6)")
    plan_parser.add_argument("--json", action="store_true",
                             help="Output raw JSON instead of pretty-printed steps")
    plan_parser.add_argument("--cwd", default=".",
                             help="Working directory for opencode (default: .)")
    plan_parser.add_argument("--timeout", type=int, default=300,
                             help="Timeout in seconds (default: 300)")
    plan_parser.add_argument("--session", "-s", default=None,
                             help="Resume an existing opencode session")

    return parser


# -- output formatters -------------------------------------------------------

def _icon(kind: str) -> str:
    return {"open": "🌐", "see": "👁️", "do": "✋", "verify": "✅",
            "done": "🏁", "error": "❌"}.get(kind, "❓")


def print_steps(steps: list[Step]) -> None:
    """Pretty-print steps to terminal."""
    if not steps:
        print("(no steps)")
        return
    width = max(len(s.kind) for s in steps) if steps else 4
    for i, s in enumerate(steps, 1):
        icon = _icon(s.kind)
        print(f"  {i:2d}. {icon} [{s.kind:<{width}}] {s.action or '(no description)'}")


def print_json(result) -> None:
    """Machine-readable JSON output."""
    out = {
        "ok": result.ok,
        "goal": result.goal,
        "summary": result.summary,
        "error": result.error,
        "steps": [
            {"kind": s.kind, "action": s.action, "raw": s.raw}
            for s in result.steps
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


# -- main --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan":
        goal = " ".join(args.goal)

        import os
        if args.session:
            os.environ["OPENCODE_PLAN_SESSION"] = args.session

        engine = PlanningEngine(
            cwd=args.cwd,
            model=args.model,
            timeout=args.timeout,
        )

        if not engine.opencode_bin:
            print(f"❌ opencode binary not found.\n"
                  f"   Install with: npm install -g @anthropic/opencode\n"
                  f"   or ensure it's on PATH.", file=sys.stderr)
            return 1

        print(f"🧠 Planning: {goal}\n")
        result = engine.plan(goal)

        if args.json:
            print_json(result)
        else:
            if result.error:
                print(f"❌ Error: {result.error}", file=sys.stderr)
                return 1
            print_steps(result.steps)
            if result.summary:
                print(f"\n📋 {result.summary}")
            if result.ok:
                print(f"\n✅ Plan complete — {len(result.steps)} steps")
            else:
                print(f"\n⚠️  Plan may be incomplete", file=sys.stderr)

        return 0 if result.ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
