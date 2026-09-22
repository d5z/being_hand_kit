"""
OCR diff — 两次 vision-ocr bounds 输出的文本变化区域定位。

输入是 hand/perception/vision_ocr.py 的 bounds 输出（制表符分隔：
confidence\\tx\\ty\\tw\\th\\ttext），或已解析的 dict 列表 / 行字符串列表。
纯标准库（difflib），无新依赖。

语义（对齐 PRD 0.9 S3）：
  - 按行中心 y 聚簇成文本块，聚簇容差 = 行高一半（同块判定）
  - 块间用 difflib.SequenceMatcher 做 LCS 对齐（块级）
  - 等值块 y 不同 -> moved；等值块同 y -> 不输出
  - 替换块内做词级 diff -> added / removed 片段（带源块 bounds 与 near 行号）
  - 新增块 -> added；消失块 -> removed

输出确定性：按 (top y, left x, change) 排序，无时间戳，重复运行字节一致。
"""

import difflib
import json
import os
import re
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# parse_bounds
# ---------------------------------------------------------------------------

def _norm_line(raw: str) -> Optional[dict]:
    """解析单行为 {text, confidence, x, y, w, h, center_x, center_y}。

    新格式：confidence\\tx\\ty\\tw\\th\\ttext（6 段，tab 分隔）。
    旧格式回退：\"confidence: text\"（无 bounds，几何取 0）。
    空行返回 None。
    """
    line = raw.rstrip("\n")
    if not line.strip():
        return None

    segments = line.split("\t", 5)
    if len(segments) >= 6:
        try:
            x = int(float(segments[1]))
            y = int(float(segments[2]))
            w = int(float(segments[3]))
            h = int(float(segments[4]))
        except (ValueError, IndexError):
            x = y = w = h = 0
        else:
            # confidence 宽松解析：解析不出来也不丢行，归 0.0
            try:
                confidence = float(segments[0])
            except (ValueError, TypeError):
                confidence = 0.0
            text = segments[5]
            return {
                "text": text,
                "confidence": confidence,
                "x": x, "y": y, "w": w, "h": h,
                "center_x": x + w // 2,
                "center_y": y + h // 2,
            }

    # 旧格式：\"confidence: text\"
    parts = line.split(": ", 1)
    if len(parts) == 2:
        try:
            confidence = float(parts[0])
        except (ValueError, TypeError):
            return None
        return {
            "text": parts[1],
            "confidence": confidence,
            "x": 0, "y": 0, "w": 0, "h": 0,
            "center_x": 0, "center_y": 0,
        }
    return None


def _norm_dict(d: dict) -> dict:
    """把已解析的 dict 规范化成统一字段（缺失 center 则补齐，缺失几何归 0）。"""
    x = int(d.get("x") or 0)
    y = int(d.get("y") or 0)
    w = int(d.get("w") or 0)
    h = int(d.get("h") or 0)
    text = d.get("text") or ""
    try:
        confidence = float(d.get("confidence"))
    except (ValueError, TypeError):
        confidence = 0.0
    return {
        "text": text,
        "confidence": confidence,
        "x": x, "y": y, "w": w, "h": h,
        "center_x": d.get("center_x", x + w // 2),
        "center_y": d.get("center_y", y + h // 2),
    }


def parse_bounds(source):
    """解析 OCR bounds 输入为行 dict 列表。

    source 可以是：
      - 原始制表符字符串（多行）
      - 已解析的 dict 列表
      - 行字符串列表

    返回 [{text, confidence, x, y, w, h, center_x, center_y}, ...]，跳过空行。
    """
    if source is None:
        return []
    if isinstance(source, str):
        raw_lines = source.split("\n")
    elif isinstance(source, (list, tuple)):
        raw_lines = source
    else:
        raise TypeError("parse_bounds: source 必须是 str 或 list")

    out = []
    for item in raw_lines:
        if isinstance(item, dict):
            out.append(_norm_dict(item))
            continue
        if not isinstance(item, str):
            continue
        parsed = _norm_line(item)
        if parsed is not None:
            out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# 聚簇 / 对齐
# ---------------------------------------------------------------------------

def _median(values):
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def _line_height(lines):
    """代表性行高：正的高度中位数（无则 0）。"""
    heights = [l["h"] for l in lines if l.get("h")]
    return _median(heights)


def _resolve_tolerance(before_lines, after_lines, y_tolerance):
    """聚簇/同块判定容差：显式给定优先，否则行高一半。"""
    if y_tolerance is not None:
        return float(y_tolerance)
    h = _line_height(before_lines + after_lines)
    if h:
        return h / 2.0
    return 0.0


def _cluster(lines, tol):
    """按中心 y 聚簇（容差 tol），返回块列表（按 y 升序）。

    块 = {text, bounds, line_indices}。bounds 为并集盒。
    """
    if not lines:
        return []
    indexed = list(enumerate(lines))
    indexed.sort(key=lambda pair: (pair[1]["center_y"], pair[1]["center_x"], pair[0]))

    blocks = []
    current = []
    ref = None
    for idx, line in indexed:
        cy = line["center_y"]
        if current and ref is not None and (cy - ref) > tol:
            blocks.append(_make_block(current))
            current = []
            ref = None
        current.append((idx, line))
        # 运行均值作为下一次比较的参考
        ref = sum(l["center_y"] for _, l in current) / len(current)
    if current:
        blocks.append(_make_block(current))
    return blocks


def _make_block(pairs):
    lines = [l for _, l in pairs]
    idxs = [i for i, _ in pairs]
    xs = [l["x"] for l in lines]
    ys = [l["y"] for l in lines]
    x2 = max(l["x"] + l["w"] for l in lines)
    y2 = max(l["y"] + l["h"] for l in lines)
    x = min(xs)
    y = min(ys)
    w = x2 - x
    h = y2 - y
    bounds = {
        "x": x, "y": y, "w": w, "h": h,
        "center_x": x + w // 2,
        "center_y": y + h // 2,
    }
    text = " ".join(l["text"] for l in lines)
    return {"text": text, "bounds": bounds, "line_indices": idxs}


def _normalize(text):
    """LCS 对齐用的归一化：折叠空白。"""
    return " ".join((text or "").split())


# ---------------------------------------------------------------------------
# 词级 diff
# ---------------------------------------------------------------------------

_ASCII_WORD = re.compile(r"^[A-Za-z0-9_]+$")


def _tokenize(text):
    """词级切分：英文/数字成词，CJK 逐字，其它符号单独。"""
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\sA-Za-z0-9_\u4e00-\u9fff]", text or "")


def _join_tokens(tokens):
    """把 token 还原成文本：两个 ASCII 词之间补空格，其余直接相连。"""
    out = []
    for i, tok in enumerate(tokens):
        if (i > 0 and _ASCII_WORD.match(tokens[i - 1]) and _ASCII_WORD.match(tok)):
            out.append(" ")
        out.append(tok)
    return "".join(out)


def _word_fragments(before_text, after_text):
    """块内词级 diff，返回 (added_fragments, removed_fragments)。"""
    a = _tokenize(before_text)
    b = _tokenize(after_text)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    added = []
    removed = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            frag = _join_tokens(b[j1:j2])
            if frag:
                added.append(frag)
        elif tag == "delete":
            frag = _join_tokens(a[i1:i2])
            if frag:
                removed.append(frag)
        elif tag == "replace":
            frag_add = _join_tokens(b[j1:j2])
            frag_rem = _join_tokens(a[i1:i2])
            if frag_add:
                added.append(frag_add)
            if frag_rem:
                removed.append(frag_rem)
    return added, removed


# ---------------------------------------------------------------------------
# 主 diff
# ---------------------------------------------------------------------------

def _sort_key(block):
    b = block.get("bounds") or block.get("to") or block.get("from") or {}
    return (b.get("y", 0), b.get("x", 0), block.get("change", ""))


def ocr_diff(before, after, y_tolerance=None):
    """对两次 OCR bounds 输出做 diff，返回 {\"blocks\": [...]}。"""
    before_lines = parse_bounds(before)
    after_lines = parse_bounds(after)
    tol = _resolve_tolerance(before_lines, after_lines, y_tolerance)

    before_blocks = _cluster(before_lines, tol)
    after_blocks = _cluster(after_lines, tol)

    a_norm = [_normalize(b["text"]) for b in before_blocks]
    b_norm = [_normalize(b["text"]) for b in after_blocks]
    sm = difflib.SequenceMatcher(None, a_norm, b_norm, autojunk=False)

    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                bb = before_blocks[i1 + k]
                ab = after_blocks[j1 + k]
                same_y = abs(bb["bounds"]["center_y"] - ab["bounds"]["center_y"]) <= tol
                if not same_y:
                    out.append({
                        "change": "moved",
                        "text": ab["text"],
                        "from": bb["bounds"],
                        "to": ab["bounds"],
                    })
        elif tag == "insert":
            for k in range(j1, j2):
                ab = after_blocks[k]
                out.append({
                    "change": "added",
                    "text": ab["text"],
                    "bounds": ab["bounds"],
                    "near": list(ab["line_indices"]),
                })
        elif tag == "delete":
            for k in range(i1, i2):
                bb = before_blocks[k]
                out.append({
                    "change": "removed",
                    "text": bb["text"],
                    "bounds": bb["bounds"],
                    "near": list(bb["line_indices"]),
                })
        elif tag == "replace":
            n = min(i2 - i1, j2 - j1)
            for k in range(n):
                bb = before_blocks[i1 + k]
                ab = after_blocks[j1 + k]
                added, removed = _word_fragments(bb["text"], ab["text"])
                for frag in added:
                    out.append({
                        "change": "added",
                        "text": frag,
                        "bounds": ab["bounds"],
                        "near": list(ab["line_indices"]),
                    })
                for frag in removed:
                    out.append({
                        "change": "removed",
                        "text": frag,
                        "bounds": bb["bounds"],
                        "near": list(bb["line_indices"]),
                    })
            # 数量不等的尾部按纯增/纯删处理
            for k in range(i1 + n, i2):
                bb = before_blocks[k]
                out.append({
                    "change": "removed",
                    "text": bb["text"],
                    "bounds": bb["bounds"],
                    "near": list(bb["line_indices"]),
                })
            for k in range(j1 + n, j2):
                ab = after_blocks[k]
                out.append({
                    "change": "added",
                    "text": ab["text"],
                    "bounds": ab["bounds"],
                    "near": list(ab["line_indices"]),
                })

    out.sort(key=_sort_key)
    return {"blocks": out}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def format_block(block):
    """人类可读单行。"""
    change = block["change"]
    text = block["text"]
    near = block.get("near")
    if change == "moved":
        f = block["from"]
        t = block["to"]
        return (f'{change:<8} "{text}"  '
                f'({f["x"]},{f["y"]},{f["w"]},{f["h"]})->'
                f'({t["x"]},{t["y"]},{t["w"]},{t["h"]})')
    b = block["bounds"]
    line = (f'{change:<8} "{text}"  '
            f'@({b["x"]},{b["y"]},{b["w"]},{b["h"]})')
    if near is not None:
        line += f' near={near}'
    return line


def main(argv=None):
    """CLI 入口：ocr-diff <before_file> <after_file> [--json]。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if len(argv) < 2:
        print("Usage: hand ocr-diff <before_file> <after_file> [--json]")
        return 1
    before_path, after_path = argv[0], argv[1]
    if before_path == "-" and after_path == "-":
        print("Usage: 两个输入不能同时为 stdin（-）")
        return 1
    result = ocr_diff(_read(before_path), _read(after_path))
    if json_out:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        blocks = result["blocks"]
        if not blocks:
            print("no changes")
        for block in blocks:
            print(format_block(block))
    return 0


if __name__ == "__main__":
    sys.exit(main())
