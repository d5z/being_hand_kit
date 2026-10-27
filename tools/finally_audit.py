"""finally 清扫审计——把「今晚报错的数」变成一段能重跑两次给同一个数的代码。

2026-10-27 我在围炉 #34 报过三个数：8 / 66 / 72，只有最后一个是脚本真打印的 len()，
另两个是我从被截断的列表里"读"出来的。这个文件的全部意义就是：
**每一个要报出去的总数，脚本自己打印它。**

另记两条当晚学到的判据，落在这里而不是注释在别处：

1. 判据若是一张名字表，分母就是那张表的长度，不是世界的长度。
   实测同一棵树：名字集 {kill,terminate} → 2 处；扩到 11 个名字 → 72 处，36 倍。
   所以本脚本对每一组名字集**分别报一个分母**，不做合并。

2. ast.parse 成功 ≠ 是 Python 源码。`{"a": 1}` 是合法的 dict 表达式，
   空文件是合法的空模块，纯注释也是合法模块。真正的对象属性是
   body 里有 FunctionDef / ClassDef / Import —— 有过定义才叫源代码文件。

3. 口味门（kit/ experiments/）不静默排除：数一遍再报出来，
   哪怕答案是 0。"0 是数出来的"和"0 是因为没看"在读数上同形。

用法：python3 tools/finally_audit.py
"""
import ast
import os
import sys

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

# 名字表的宽窄——两组分别报分母，不合并
NARROW = ("kill", "terminate")
WIDE = NARROW + ("close", "shutdown", "stop", "cancel",
                 "unlink", "rmtree", "remove", "__exit__", "cleanup")

# 「我的口味」门：这些目录被 out_of_scope 排除，但必须数一遍再报
TASTE_DIRS = ("kit", "experiments")

SOURCE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)


def iter_py(root="."):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def is_source_file(path):
    """对象属性判据：body 里有过定义。parse 成功不算。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    except Exception:
        return False
    return any(isinstance(n, SOURCE_NODES) for n in tree.body)


def attr_names_in(nodes):
    out = set()
    for n in nodes:
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            out.add(n.func.attr)
    return out


def finally_sweep(files, names):
    """返回 (命中数, [{file, line, killed, calls}])。"""
    hits = []
    for p in files:
        try:
            tree = ast.parse(open(p, encoding="utf-8", errors="ignore").read())
        except Exception:
            continue
        for t in ast.walk(tree):
            if not isinstance(t, ast.Try) or not t.finalbody:
                continue
            body = []
            for s in t.finalbody:
                body.extend(ast.walk(s))
            calls = attr_names_in(body)
            if calls & set(names):
                hits.append({"file": p, "line": t.lineno,
                             "killed": bool(calls & set(NARROW)),
                             "calls": sorted(calls)})
    return len(hits), hits


FIXTURE = '''import subprocess
def f(p):
    try:
        return 1
    finally:
        p.kill()
'''


def self_test():
    """在门后放一个一定能被数到的东西，再报那个 0。（Neuromancer 2026-10-27 的规则）

    放不进去，那个 0 就不许印出来 —— 所以本函数不通过时 main() 直接拒绝出数。
    """
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="fa_selftest_")
    try:
        p = os.path.join(d, "fixture.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)
        n_narrow, hits = finally_sweep([p], NARROW)
        ok = n_narrow == 1 and hits[0]["killed"]
        return ok, d, n_narrow
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    ok, where, n = self_test()
    print("装置自检（门后放一格必定被数到的东西）: 夹具 finally 命中 %d 处（应 1）→ %s"
          % (n, "会响 ✓" if ok else "不响 ✗"))
    if not ok:
        # 「守卫响了」与「脚本没跑」在回执里必须不同形（Neuromancer 2026-10-27 坑3）。
        # 所以：① 一行可 grep 的标记 ② 期望值/实测值都印 ③ rc=3，与崩溃(rc=1)/正常(rc=0)分开
        print("[GATE] finally_audit: self_test 不响 —— 期望 NARROW 命中 1 处，实测 %d 处" % n)
        print("[GATE] 判据：拒绝印出任何 0（未过自检的门后面，0 不算读数）")
        return 3
    print()

    files = sorted(iter_py("."))
    # —— 每一个数都从这里 print 出来，不靠读列表 ——
    print("py files（排除 .git/__pycache__/.venv/node_modules）: %d" % len(files))
    print("其中是源码文件（body 里有 FunctionDef/ClassDef/Import）: %d"
          % sum(1 for p in files if is_source_file(p)))
    print()

    print("=== finally 清扫，按名字集的宽度分别报分母 ===")
    for label, names in (("NARROW %d 名" % len(NARROW), NARROW),
                         ("WIDE   %d 名" % len(WIDE), WIDE)):
        n, hits = finally_sweep(files, names)
        k = sum(1 for h in hits if h["killed"])
        print("  %s → finally 命中 %d 处；其中 finally 内出现 kill/terminate 的 %d 处"
              % (label, n, k))
        if k:
            for h in hits:
                if h["killed"]:
                    print("       %s:%d  calls=%s" % (h["file"], h["line"], h["calls"]))
    print("  ★ 两个分母都是真的，都关于同一棵树，都不是世界的长度。")
    print()

    print("=== 口味门后面有什么（数一遍再报，不静默排除）===")
    for d in TASTE_DIRS:
        if not os.path.isdir(d):
            print("  %-14s 不存在" % d)
            continue
        sub = sorted(iter_py(d))
        n, hits = finally_sweep(sub, WIDE)
        killed = sum(1 for h in hits if h["killed"])
        print("  %-14s py %d 个，源码文件 %d 个，finally 命中 %d 处，含 kill/terminate %d 处"
              % (d + "/", len(sub), sum(1 for p in sub if is_source_file(p)), n, killed))
    print()

    ok = len(files) > 0
    print("rc=%d" % (0 if ok else 1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
