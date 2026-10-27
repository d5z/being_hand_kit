"""finally 清扫审计——把「今晚报错的数」变成一段能重跑两次给同一个数的代码。

2026-10-27 我在围炉 #34 报过三个数：8 / 66 / 72，只有最后一个是脚本真打印的 len()，
另两个是我从被截断的列表里"读"出来的。这个文件的全部意义就是：
**每一个要报出去的总数，脚本自己打印它。**

另记几条当晚学到的判据，落在这里而不是注释在别处：

1. 判据若是一张名字表，分母就是那张表的长度，不是世界的长度。
   实测同一棵树：名字集 {kill,terminate} → 2 处；扩到 11 个名字 → 72 处，36 倍。
   所以本脚本对每一组名字集**分别报一个分母**，不做合并。

2. ast.parse 成功 ≠ 是 Python 源码。`{"a": 1}` 是合法的 dict 表达式，
   空文件是合法的空模块，纯注释也是合法模块。真正的对象属性是
   body 里有 FunctionDef / ClassDef / Import —— 有过定义才叫源代码文件。

3. 口味门（kit/ experiments/）不静默排除：数一遍再报出来，
   哪怕答案是 0。"0 是数出来的"和"0 是因为没看"在读数上同形。

4. **读不到 ≠ 没有**（2026-10-28 02:0xZ 实测，本脚本自己的洞）。
   `chmod 000 tests/test_version_fork.py` 之后，脚本照旧印
   `py files 139 / 源码文件 138 / rc=0` —— 我的读失败被印成了关于那个文件的事实
   （"它没有 finally 清扫"）。所以本脚本现在把结果分三类，且**按原因分桶、不按结果分**：
     source       —— 读到了，parse 成功，body 里有定义
     not_source   —— 读到了，parse 成功，body 里没有定义（空文件/纯注释/纯表达式）
     unreadable   —— 读不到/读不全，并带 cause（permission/syntax/is_directory/
                     symlink_loop/os_error_*/unexpected_*）
   unreadable 单列、逐条具名、并且让 rc=2。它不参与「源码文件」分母，
   也不静默算进 finally 清扫的空结果。

5. **分母不是独立证据**。两行分母来自同一趟 iter_py + 同一批 analyse()，
   共享同一个失败面。宽窄只变了名字表，没变读取。所以不许把它们说成
   「两个独立分母」，只许说「两把同一趟读出的尺子，长度不同」。

用法：python3 tools/finally_audit.py [root]
      root 默认 "."；给别的路径就扫别的树（2026-10-28 前它忽略 argv，
      指向 /tmp/fa_gap 与指向不存在的路径输出逐字相同 —— 那时它没有夹具，
      每格「已验」都只是「在唯一那棵树上没翻车」）。

Readers: Alice · 手动跑（Hand 就绪清单②）；rc=0 读数完整 / 2 有文件读不到 /
         3 自检不响或树是空的 —— 这三个值都由跑的人读，没有 CI 调用点。
         刷新时机：改判据、改六样本落点表、或任何一次真树注入之后。
"""
import ast
import os
import sys
import tempfile

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

# 名字表的宽窄——两组分别报分母，不合并
NARROW = ("kill", "terminate")
WIDE = NARROW + ("close", "shutdown", "stop", "cancel",
                 "unlink", "rmtree", "remove", "__exit__", "cleanup")

# 「我的口味」门：这些目录被 out_of_scope 排除，但必须数一遍再报
TASTE_DIRS = ("kit", "experiments")

SOURCE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)

# 三类结果。按原因分桶，不按结果分。
OK_SOURCE = "source"
OK_NOT_SOURCE = "not_source"
UNREADABLE = "unreadable"


def iter_py(root="."):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def read_bytes(path):
    """返回 (data, cause)。cause is None → 读到了。"""
    try:
        with open(path, "rb") as fh:
            return fh.read(), None
    except PermissionError:
        return None, "permission"
    except IsADirectoryError:
        return None, "is_directory"
    except OSError as e:
        if getattr(e, "errno", None) == 40:  # ELOOP
            return None, "symlink_loop"
        return None, "os_error_%s" % getattr(e, "errno", "?")
    except Exception as e:  # 未知失败也必须具名，不许并进"没有"
        return None, "unexpected_%s" % type(e).__name__


def analyse(path):
    """单趟分类。返回 dict(kind, cause, tree)。

    读在 classify 里只发生一次 —— 旧版 is_source_file() 与 finally_sweep()
    各 open/parse 一遍同一文件，「139 == 139」是死等式：两个数来自同一趟
    过滤的同一次失败，彼此不可能不一致，所以那个相等不证明任何事。
    """
    data, cause = read_bytes(path)
    if cause is not None:
        return {"kind": UNREADABLE, "cause": cause, "tree": None}
    try:
        tree = ast.parse(data)
    except SyntaxError:
        return {"kind": UNREADABLE, "cause": "syntax", "tree": None}
    except ValueError as e:
        return {"kind": UNREADABLE, "cause": "value_%s" % type(e).__name__, "tree": None}
    except Exception as e:
        return {"kind": UNREADABLE, "cause": "parse_%s" % type(e).__name__, "tree": None}
    kind = OK_SOURCE if any(isinstance(n, SOURCE_NODES) for n in tree.body) else OK_NOT_SOURCE
    return {"kind": kind, "cause": None, "tree": tree}


def attr_names_in(nodes):
    out = set()
    for n in nodes:
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            out.add(n.func.attr)
    return out


def finally_sweep(infolist, names):
    """infolist: [(path, info)]，info 来自 analyse()。返回 (命中数, hits)。

    读不到的条目在调用侧已单列，这里只遍历 tree 非空的。
    """
    hits = []
    for p, info in infolist:
        tree = info["tree"]
        if tree is None:
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


# —— 自检夹具：门后放一定被数到的东西 ——
FIXTURE = '''import subprocess
def f(p):
    try:
        return 1
    finally:
        p.kill()
'''

# 六样本落点表。落错一格 = 折叠（把"读不到"读成"没有"）。
SAMPLE_EXPECT = {
    "empty.py": (OK_NOT_SOURCE, None),        # 空文件：合法空模块，读到了
    "only_comment.py": (OK_NOT_SOURCE, None),  # 纯注释：合法模块，读到了
    "syntax_bad.py": (UNREADABLE, "syntax"),
    "perm0.py": (UNREADABLE, "permission"),
    "loop.py": (UNREADABLE, "symlink_loop"),   # 指向自身的符号链接
    "isdir.py": (UNREADABLE, "is_directory"),  # 名字是 *.py 的目录
}


def build_samples(d):
    """在 d 里造六样本。返回 {name: path}。"""
    paths = {}
    for name, content in (("empty.py", ""),
                          ("only_comment.py", "# nothing here\n"),
                          ("syntax_bad.py", "def f(:\n"),
                          ("perm0.py", "def f():\n    pass\n")):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        paths[name] = p

    os.chmod(paths["perm0.py"], 0o000)

    loop = os.path.join(d, "loop.py")
    if not os.path.lexists(loop):
        os.symlink(loop, loop)
    paths["loop.py"] = loop

    isdir = os.path.join(d, "isdir.py")
    os.makedirs(isdir, exist_ok=True)
    paths["isdir.py"] = isdir
    return paths


def self_test():
    """返回 (ok, lines)。ok=False 时 main() 拒绝出数（rc=3）。

    判据：每一格都要能与期望不同 —— 只测「会响」不够，还要测
    「响在正确的那一格」。所以落点表逐格比对，不是数总数。
    """
    lines = []
    ok = True
    d = tempfile.mkdtemp(prefix="fa_selftest_")
    try:
        # 格 1：finally 夹具被数到
        p = os.path.join(d, "fixture.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)
        n_narrow, hits = finally_sweep([(p, analyse(p))], NARROW)
        g1 = n_narrow == 1 and hits[0]["killed"]
        lines.append("格1 finally 夹具命中 %d 处（应 1）→ %s"
                     % (n_narrow, "会响 ✓" if g1 else "不响 ✗"))
        ok = ok and g1

        # 格 2-7：六样本落点表
        paths = build_samples(d)
        for name in sorted(SAMPLE_EXPECT):
            exp_kind, exp_cause = SAMPLE_EXPECT[name]
            info = analyse(paths[name])
            got = (info["kind"], info["cause"])
            good = got == (exp_kind, exp_cause)
            note = ""
            if name == "perm0.py" and hasattr(os, "geteuid") and os.geteuid() == 0:
                note = "（euid=0：本格权限位不生效，判据不可判，不算绿）"
                good = False
            lines.append("格  %-16s 期望 %-24s 实测 %-24s → %s%s"
                         % (name, "%s/%s" % (exp_kind, exp_cause),
                            "%s/%s" % got, "落对 ✓" if good else "落错 ✗", note))
            ok = ok and good

        # 格：unreadable 不许进「源码文件」分母，也不许算作命中
        infos = [(p, analyse(p)) for p in paths.values()]
        unread = [pp for pp, i in infos if i["kind"] == UNREADABLE]
        src = [pp for pp, i in infos if i["kind"] == OK_SOURCE]
        g2 = len(unread) == 4 and len(src) == 0
        lines.append("格  ⓒ unreadable %d 个（应 4）、源码 %d 个（应 0）→ %s"
                     % (len(unread), len(src), "分桶 ✓" if g2 else "折叠 ✗"))
        ok = ok and g2
    finally:
        # 权限位会挡住 rmtree 的读取，但删除本身不受影响；仍显式恢复一遍
        try:
            os.chmod(os.path.join(d, "perm0.py"), 0o644)
        except Exception:
            pass
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    return ok, lines


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print("root: %r  （本脚本只看这一棵树；argv[1] 可指向别处）" % root)
    if not os.path.isdir(root):
        print("[GATE] 目标不是目录：%r —— 拒绝出数（不存在 ≠ 空树）" % root)
        return 3

    ok, lines = self_test()
    print("装置自检（门后放一定被数到的东西 + 六样本落点表）:")
    for ln in lines:
        print("  " + ln)
    if not ok:
        # 「守卫响了」与「脚本没跑」在回执里必须不同形（Neuromancer 2026-10-27 坑3）。
        print("[GATE] finally_audit: self_test 不响 —— 见上面 ✗ 行；拒绝印出任何读数")
        print("[GATE] 判据：未过自检的门后面，0 不算读数")
        return 3
    print()

    files = sorted(iter_py(root))
    infos = [(p, analyse(p)) for p in files]

    by_kind = {}
    unreadable = []
    for p, i in infos:
        if i["kind"] == UNREADABLE:
            unreadable.append((p, i["cause"]))
        else:
            by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1

    # —— 每一个数都从这里 print 出来，不靠读列表 ——
    print("py files（排除 .git/__pycache__/.venv/node_modules）: %d" % len(files))
    print("  其中 source（读到了 · parse 成功 · body 里有定义）: %d"
          % by_kind.get(OK_SOURCE, 0))
    print("  其中 not_source（读到了 · 只是 body 里没有定义：空/纯注释/纯表达式）: %d"
          % by_kind.get(OK_NOT_SOURCE, 0))
    print("  其中 unreadable（读不到/读不全）: %d" % len(unreadable))
    if unreadable:
        print("  ↓ 逐条具名（这些文件没有出现在任何下面的分母里，不是「它们没有」，")
        print("    是「我没读到」——所以本脚本 rc=2）:")
        for p, cause in unreadable:
            print("       [UNREADABLE] %-16s %s" % (cause, p))
    print()

    print("=== finally 清扫，按名字集的宽度分别报分母 ===")
    for label, names in (("NARROW %d 名" % len(NARROW), NARROW),
                         ("WIDE   %d 名" % len(WIDE), WIDE)):
        n, hits = finally_sweep(infos, names)
        k = sum(1 for h in hits if h["killed"])
        print("  %s → finally 命中 %d 处；其中 finally 内出现 kill/terminate 的 %d 处"
              % (label, n, k))
        if k:
            for h in hits:
                if h["killed"]:
                    print("       %s:%d  calls=%s" % (h["file"], h["line"], h["calls"]))
    if unreadable:
        print("  注意：以上两行的分母都缺 %d 个读不到的文件；它们不是「没问题」，"
              "是「没看」。" % len(unreadable))
    else:
        print("  同源声明：以上两行来自同一趟 iter_py + 同一批 analyse()，"
              "共享同一个失败面（本次该失败面为空）。")
        print("  它们不是两条独立证据；宽窄只变了名字表，没变读取——"
              "所以它们不是「两个都真的分母」，是同一次读取被两把尺子量了。")
    print()

    print("=== 口味门后面有什么（数一遍再报，不静默排除）===")
    for d in TASTE_DIRS:
        sub = sorted(iter_py(os.path.join(root, d)))
        if not os.path.isdir(os.path.join(root, d)):
            print("  %-14s 不存在" % d)
            continue
        sub_infos = [(p, analyse(p)) for p in sub]
        sub_unread = [(p, i["cause"]) for p, i in sub_infos if i["kind"] == UNREADABLE]
        n, hits = finally_sweep(sub_infos, WIDE)
        killed = sum(1 for h in hits if h["killed"])
        print("  %-14s py %d 个，源码文件 %d 个，finally 命中 %d 处，含 kill/terminate %d 处，"
              "unreadable %d 个"
              % (d + "/", len(sub),
                 sum(1 for _, i in sub_infos if i["kind"] == OK_SOURCE), n, killed,
                 len(sub_unread)))
        for p, cause in sub_unread:
            print("       [UNREADABLE] %-16s %s" % (cause, p))
    print()

    if not files:
        print("[GATE] 这棵树里一个 .py 都没有：不存在 ≠ 空树，拒绝出数")
        return 3
    if unreadable:
        print("rc=2（读数不全：有 %d 个文件读不到，见上）" % len(unreadable))
        return 2
    print("rc=0（读数完整：本树所有 *.py 都被读到了）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
