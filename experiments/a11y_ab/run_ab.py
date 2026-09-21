#!/usr/bin/env python3
"""阶段 2：A/B 快照格式对比实验 runner。

被试：z-ai/glm-5.3（OpenRouter）。三组：
  A = hand 现有 interactive 层输出（tag/text/selector/coords 表）
  B = a11y v2 快照（role/name/state/层级 + [idx] 句柄）
  （C = code mode 留后续：locator 编译器工作量大，A/B 才是 hand 的真实决策）

每组每任务 3 次，量：成功率 / 重试率 / token / 失败模式。

判定：任务预先标注正确目标（backendNodeId），模型输出映射回元素后比对。
A 组 selector → querySelector 命中元素 → 比对 backendNodeId
B 组 [idx]  → 坐标表反查 backendNodeId → 比对
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from serialize_ax import CDP, get_page, INTERACTIVE_ROLES

OR_URL = "https://openrouter.ai/api/v1/chat/completions"
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.environ.get("EXP_MODEL", "z-ai/glm-5.3")

OUT_DIR = os.path.join(os.path.dirname(__file__), "trials")
os.makedirs(OUT_DIR, exist_ok=True)

# ============================================================
# 任务清单：每任务 = (页面, 指令, 判定函数, 正确目标描述)
# 感知类（count/find/attribute）+ 操作类（click）混合。
# ============================================================

TASKS = [
    # ---- beings.town（静态页）----
    dict(page="beings.town", kind="perceive",
         prompt="这个页面上有几个一级标题（h1）？只回答数字。",
         judge=lambda ans, ctx: str(ctx["h1_count"]) in ans),
    dict(page="beings.town", kind="perceive",
         prompt="页面上列出的工具卡片（scroll、search 等）一共几个？只回答数字。",
         judge=lambda ans, ctx: str(ctx["tool_count"]) in ans),
    dict(page="beings.town", kind="perceive",
         prompt="「Search」卡片的描述语里有没有「see」这个词？回答有或没有。",
         judge=lambda ans, ctx: "有" in ans or "yes" in ans.lower()),
    # ---- github.com/d5z/being_hand_kit（重 ARIA SPA）----
    dict(page="github", kind="act",
         prompt="我要看这个仓库的 issue 列表。输出点击操作，目标用规定格式。",
         target_desc="Issues 导航 tab",
         match=lambda el: el["role"] == "link" and el["name"].strip() == "Issues"),
    dict(page="github", kind="act",
         prompt="我要看这个仓库的 pull request。输出点击操作。",
         target_desc="Pull requests 导航 tab",
         match=lambda el: el["role"] == "link" and "Pull requests" in el["name"]),
    dict(page="github", kind="act",
         prompt="我要查看仓库的 Actions 工作流。输出点击操作。",
         target_desc="Actions 导航 tab",
         match=lambda el: el["role"] == "link" and el["name"].strip() == "Actions"),
    dict(page="github", kind="act",
         prompt="我想看这个仓库的提交历史（commits）。输出点击操作。",
         target_desc="仓库级 Commits 链接（如 \"76 Commits\"）",
         match=lambda el: el["role"] == "link" and "Commits" in el["name"] and "file" not in el["name"].lower()),
    dict(page="github", kind="act",
         prompt="页面右上有「Sign in」。输出点击操作。",
         target_desc="Sign in 链接",
         match=lambda el: el["role"] == "link" and el["name"].strip() == "Sign in"),
    dict(page="github", kind="perceive",
         prompt="这个仓库的 About 侧栏里写了什么 topic 标签？全部列出；如果一个都没有，回答没有。",
         judge=lambda ans, ctx: ("没有" in ans or "no" in ans.lower() or "none" in ans.lower()) and "看不见" not in ans and "无法" not in ans),
    dict(page="github", kind="perceive",
         prompt="主导航（Code/Issues/...）一共有几个 tab？只回答数字。",
         judge=lambda ans, ctx: str(ctx["nav_count"]) in ans),
    dict(page="github", kind="perceive",
         prompt="README 的第一行标题是什么？原样回答。",
         judge=lambda ans, ctx: "Hand" in ans),
    dict(page="github", kind="act",
         prompt="我想给这个项目提 issue。输出点击操作。",
         target_desc="New issue 按钮（Issues 页的快捷入口也是 About 栏的链接）",
         # 接受主导航 Issues（意图第一步）
         match=lambda el: el["role"] == "link" and el["name"].strip() == "Issues"),
    dict(page="github", kind="perceive",
         prompt="这个页面用的开源协议（license）是什么？回答协议名。",
         judge=lambda ans, ctx: "MIT" in ans),
    dict(page="github", kind="act",
         prompt="我想搜索这个仓库里的代码。输出点击操作。",
         target_desc="搜索框/搜索按钮（header 的 search）",
         match=lambda el: el["role"] in ("button", "searchbox", "textbox", "combobox")
                          and ("search" in el["name"].lower() or "搜索" in el["name"])),
    dict(page="github", kind="perceive",
         prompt="About 栏说这个仓库是谁发布的（publisher/owner）？回答名字。",
         judge=lambda ans, ctx: "d5z" in ans.lower() or "alice" in ans.lower()),
]

REPEATS = 3

# ============================================================
# 快照生成（两组）
# ============================================================

PROMPT_A = """你是一个浏览器操作助手。下面是页面的交互元素清单，格式为 JSON 数组，
每个元素有 tag（标签）、text（文字）、selector（CSS 选择器）、x/y/w/h（屏幕坐标）。

任务：{prompt}

输出严格 JSON：{{"action": "click", "selector": "<CSS选择器>"}} 或 {{"answer": "<文字回答>"}}"""

PROMPT_B = """你是一个浏览器操作助手。下面是页面的无障碍树快照，缩进表示层级。
每个节点格式：角色 "名称" (状态) [编号]。可交互元素（link/button/textbox等）有编号。

任务：{prompt}

输出严格 JSON：{{"action": "click", "target": <编号>}} 或 {{"answer": "<文字回答>"}}"""


def snap_interactive(cdp):
    """A 组：模拟 hand 现有 interactive 层的输出。"""
    res = cdp.call("Runtime.evaluate", dict(
        expression="""(() => {
  const sel = 'a, button, input, select, textarea, [role], [onclick], [tabindex]';
  const els = [...document.querySelectorAll(sel)];
  return JSON.stringify(els.slice(0, 200).map(e => {
    const r = e.getBoundingClientRect();
    return {tag: e.tagName, text: (e.innerText || e.value || '').slice(0, 40),
            selector: (() => {
              if (e.id) return '#' + e.id;
              let s = e.tagName.toLowerCase();
              for (const c of e.classList) s += '.' + c.split('-')[0].slice(0,12);
              return s;
            })(),
            x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
  }).filter(e => e.w > 0 && e.h > 0));
})()""", returnByValue=True))
    return json.loads(res["result"]["value"])


def snap_a11y(cdp):
    """B 组：serialize_ax v2 快照 + 交互元素表（编号→backendNodeId）。"""
    from serialize_ax import build_snapshot
    tree, kept, lines, coords, interactive_meta = build_snapshot(cdp)
    return "\n".join(lines), interactive_meta


# ============================================================
# OpenRouter 调用
# ============================================================

def call_llm(prompt, temperature=1.0):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "reasoning": {"effort": "low"},
    }).encode()
    req = urllib.request.Request(OR_URL, data=body, headers={
        "Authorization": f"Bearer {OR_KEY}",
        "Content-Type": "application/json",
    })
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    dt = time.time() - t0
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning") or ""
    usage = data.get("usage", {})
    return content, reasoning, usage, dt


def parse_action(text):
    """从回复中抠 JSON（宽容：模型可能带 markdown 围栏；None 安全）。"""
    if not text or not isinstance(text, str):
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ============================================================
# 主流程
# ============================================================

def main():
    if not OR_KEY:
        sys.exit("OPENROUTER_API_KEY 未设置")

    page = get_page()
    cdp = CDP(page)
    url = page["url"]
    site = "github" if "github.com" in url else "beings.town"
    print(f"当前页面: {url} → 任务组: {site}")

    # 生成两组快照（同一页面状态）
    inter = snap_interactive(cdp)
    snap_b_lines, interactive_meta = snap_a11y(cdp)

    # 交互元素语义表（B 组判定用：idx → role/name）
    el_by_idx = {m[0]: {"role": m[2], "name": m[3], "bid": m[1]} for m in interactive_meta}

    # A 组 selector → 元素文本映射（判定用）
    sel_to_text = {e["selector"]: e["text"] for e in inter}

    # 感知类任务的 ground truth（手动标注值，从快照预计算）
    ctx = {}
    if site == "github":
        ctx["nav_count"] = 7  # Code/Issues/PR/Actions/Projects/Security and quality/Insights（2026-09 新版 UI）
        ctx["h1_count"] = 1
    else:
        ctx["h1_count"] = 1
        ctx["tool_count"] = 13  # Scroll/Search/Browse/Bonfire/Beings/Messages/Fireside/Portal/Grove/Seed/Ember/Workspace/Channel

    tasks = [t for t in TASKS if t["page"] == site]
    print(f"任务数: {len(tasks)} × {REPEATS} 次 × 2 组 = {len(tasks)*REPEATS*2} trials")

    results = []
    for t in tasks:
        for group, prompt_tmpl, snap in (
            ("A", PROMPT_A, json.dumps(inter, ensure_ascii=False)),
            ("B", PROMPT_B, snap_b_lines),
        ):
            for rep in range(REPEATS):
                prompt = prompt_tmpl.format(prompt=t["prompt"]) + "\n\n=== 页面 ===\n" + snap
                label = f"{t['page']}|{t['prompt'][:18]}|{group}|{rep}"
                try:
                    raw, reasoning, usage, dt = call_llm(prompt)
                except Exception as e:
                    results.append({"label": label, "ok": False, "err": str(e)[:100], "group": group})
                    print(f"  ✗ {label}: API {e}")
                    continue
                act = parse_action(raw) or parse_action(reasoning)
                # ---- 判定 ----
                ok, detail = False, ""
                if act is None:
                    detail = f"unparseable: {raw[:60]}"
                elif "answer" in act:
                    if t["kind"] == "perceive":
                        ok = t["judge"](act["answer"], ctx)
                        detail = f"answer={act['answer'][:50]}"
                    else:
                        detail = "act 任务给了 answer"
                elif "action" in act:
                    if t["kind"] != "act":
                        detail = "perceive 任务给了 action"
                    elif group == "A":
                        sel = act.get("selector", "")
                        hit = sel_to_text.get(sel, "")
                        ok = bool(hit) and bool(re.search(r"issues|pull|actions|commits|sign in",
                                              hit.lower() or ""))  # 粗判，最终人工复核
                        detail = f"selector={sel[:50]} text={hit[:30]}"
                    else:  # B
                        tgt = act.get("target")
                        if isinstance(tgt, str):
                            tgt = int(re.sub(r"\D", "", tgt) or 0)
                        el = el_by_idx.get(tgt)
                        if el is None:
                            detail = f"target {tgt} 不在交互表"
                        else:
                            ok = t["match"](el)
                            detail = f"[{tgt}] {el['role']} \"{el['name'][:30]}\""
                rec = {"label": label, "ok": ok, "group": group, "detail": detail,
                       "raw": raw[:200], "raw_reasoning": reasoning[:300],
                       "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
                       "latency_s": round(dt, 1)}
                results.append(rec)
                print(f"  {'✓' if ok else '✗'} {label}: {detail}")

    # ---- 汇总 ----
    out = {"model": MODEL, "page": url, "ts": time.strftime("%F %T"), "results": results}
    fn = os.path.join(OUT_DIR, f"run_{site}_{int(time.time())}.json")
    with open(fn, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    for g in "AB":
        rs = [r for r in results if r["group"] == g]
        n = len(rs)
        succ = sum(1 for r in rs if r["ok"])
        tin = sum(r.get("tokens_in") or 0 for r in rs)
        tout = sum(r.get("tokens_out") or 0 for r in rs)
        lat = sorted(r.get("latency_s") or 0 for r in rs)
        print(f"\n== {g} 组: {succ}/{n} ({succ/max(n,1)*100:.0f}%)  "
              f"in={tin} out={tout} 中位延迟={lat[n//2] if n else 0}s")
    print(f"\n明细已存 {fn}")


if __name__ == "__main__":
    main()
