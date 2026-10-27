"""找「判据与回执标签是两个各自独立的表达式」这个形状。

他 3922 的原例：
  L1463:  _ok19b = _ok_self and _ok_rc and _ok_bad        ← 判据
  L1470:  f"... {'完整' if (_ok_rc and _ok_bad) else '★ 残缺'}"  ← 标签，自己重新算了一遍
两个表达式只是【碰巧】现在同值。

语法签名（三个条件同时成立才报）：
  A. 某 bool 变量 V 由 BoolOp(and) 合取 ≥2 个成分得出 → 成分结构集 S
  B. 同一函数内另一处表达式 E（不是那个赋值本身），其成分结构集 T 与 S 交 ≥2
  C. E 里【不出现 V】—— 一出现就是说 E 复用了判据，那没问题

不含 V 是全部要害：含 V 的叫复用，不含 V 的叫二次书写。

Readers: Alice · 手动跑（`python3 tools/diag_label_fork.py [root ...]`，默认扫当前目录）。
         rc=0 出数 / 3 等式不闭合（「本装置不出数」）。
         不进 MODULES：它默认扫一棵真树，进套件会把「扫哪棵树」变成一个隐式依赖。
         2026-10-28 08:0x 从 /home/alice/tools/ 搬进仓 —— 搬家前它是今夜唯一带真反例的
         装置，却住在仓外，零读者（清单㉓）。

已知漏格（写在这里，不静默）：本装置的签名 C 要求「同一函数内」，所以
「判据在 A 函数、标签在 B 函数」这类跨函数二次书写它看不见。要补这一格，
需要把成分结构集提升到模块层；未实现。⇒ 本轴目前只对「同函数」这一形态有判别力，
报出的 0 是「同函数形态的 0」，不是「没有二次书写」。
"""
import ast
import os
import sys
from collections import Counter

SKIP = {".git", "__pycache__", ".venv", "node_modules"}


def norm(node):
    return ast.dump(node)


def and_operands(node):
    """把一个 and 链拍平成成分列表。"""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        out = []
        for v in node.values:
            out.extend(and_operands(v))
        return out
    return [node]


def scan(path):
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
        tree = ast.parse(src)
    except Exception as e:
        return [], ("parse_fail", type(e).__name__)
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # A: 找 bool 变量 = 合取
        verdicts = {}  # 变量名 -> (成分结构集, lineno)
        for n in ast.walk(fn):
            if not isinstance(n, (ast.Assign, ast.AnnAssign)):
                continue
            val = n.value
            if val is None:
                continue
            ops = and_operands(val)
            if len(ops) < 2:
                continue
            targets = []
            if isinstance(n, ast.Assign):
                targets = [t.id for t in n.targets if isinstance(t, ast.Name)]
            elif isinstance(n.target, ast.Name):
                targets = [n.target.id]
            for t in targets:
                verdicts[t] = ({norm(o) for o in ops}, n.lineno)
        if not verdicts:
            continue
        # B+C: 同一函数内，别处表达式重算 ≥2 个成分且不含 V
        for n in ast.walk(fn):
            # 只看「会产生标签文本」的上下文：f-string / 三元 / 比较 / print 参数
            is_label_ctx = (
                isinstance(n, ast.IfExp)
                or isinstance(n, ast.FormattedValue)
                or (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("print", "format"))
            )
            if not is_label_ctx:
                continue
            names_here = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
            struct_here = {norm(x) for x in ast.walk(n) if isinstance(x, (ast.Compare, ast.BoolOp, ast.UnaryOp, ast.Name))}
            for v, (comps, vline) in verdicts.items():
                if v in names_here:
                    continue  # 复用了判据 —— 不是缺陷
                inter = comps & struct_here
                if len(inter) >= 2:
                    hits.append((path, fn.name, vline, n.lineno, v, len(inter)))
    # 去重：同一行同时落在 FormattedValue / IfExp / Call 三种上下文里，
    # 会被数 2~3 遍（实测 pos.py 一个缺点报了 3 次）。按 (文件,标签行,判据变量) 只留一条。
    seen = set()
    uniq = []
    for h in hits:
        k = (h[0], h[3], h[4])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    return uniq, None


def main():
    roots = sys.argv[1:] or ["."]
    all_hits = []
    stats = Counter()
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP]
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dp, fn)
                stats["walked"] += 1
                hits, err = scan(p)
                if err:
                    stats["parse_fail"] += 1
                    print(f"  [PARSE_FAIL] {p}: {err[1]}")
                    continue
                stats["parsed"] += 1
                all_hits.extend(hits)
    print()
    print("=" * 60)
    print(f"walk 到 .py              = {stats['walked']}")
    print(f"  解析成功               = {stats['parsed']}")
    print(f"  解析失败（计入上式）   = {stats['parse_fail']}")
    # 等式必须闭合
    if stats["parsed"] + stats["parse_fail"] != stats["walked"]:
        print("  ★ 等式不闭合 —— 本装置不出数")
        return 3
    print(f"命中「判据/标签二次书写」 = {len(all_hits)}")
    for p, fn, vl, el, v, k in all_hits:
        print(f"  {p}:{el} in {fn}()   判据 {v}@{vl}，标签重算 {k} 个成分")
    return 0


if __name__ == "__main__":
    sys.exit(main())
