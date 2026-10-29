"""diag_verdict_shape v3 — 数「判词有没有读者」。

v1/v2（2026-10-28 01:47）只数「同函数内 print 了但没有非零退出路径」，单位是函数。
v3 换单位到文件，并把模块级 print 算进分母 —— v1 里「模块级 print」的文件整个不出现，
那是分母错了，不是漏几行。

三层问题，v1 只答了第一层：
  一 有没有判词        —— 印不印数
  二 判词落在哪种载体  —— 印刷形态 / rc / exit
  三 判词有没有读者    —— **v3 新增，也是承重那条**

读者分三类，判据全部可执行：
  mechanical  MODULES 里登记（tests.run_x 形式转成 tests/run_x.py），
              或本身就是 runner 入口（run_tests.py / run_production.py）
              → 有人被排在队列里跑它
  live-dir    住在 tests/live/ —— 目录约定「人工活体检」
              → 但目录不是读者声明：本类逐条标 unknown（最后一次真跑静态不可知），
                不做「合理」的静默排除
  undetermined 以上都不是，且模块 docstring 里没有读者声明行
              → 读者的存在没写在任何地方。要么登记进 MODULES，要么写一行
                读者声明，说明谁读、怎么刷新。

读者声明的形状（判据，写在这里是给下一个读这份代码的人，不是给本脚本自己）：
  模块 docstring 内，行首就是 "Readers:" 或 "读者："，冒号后必须有内容。
  只看 docstring，不看注释 —— 注释里的示范不算声明。
  ★ 2026-10-28 07:4x 我先踩了这个坑：v3 第一版把「声明」的示范文字写进了自己的
    docstring，于是本文件被自己判成「已自述读者」，从 5 个真嫌疑掉到 4 个。
    判据被自己的说明书触发，是自指陷阱的标准形。所以现在①只扫 docstring ②示范
    文字改成不以声明关键字开头。

口径分歧要印出来，不许我猜：2026-10-28 07:3x 我人工判读的数是
15 印 print / 2 在清单 / 13 不在 / 5 真嫌疑，其中那 5 个的「装置形态」是
我凭名字判的（diag、audit、readback、layer、production）。本脚本不复制那个品味，
它只报机械可判的三类；两者的差逐条具名。

自检：
  · 分母 0 → rc=3
  · unreadable 单列具名 → rc=2
  · 与 2026-10-28 07:3x 快照不一致 → 两侧都印，rc=2（树变了要人看，不自动改数）

用法：python3 tools/diag_verdict_shape.py [root ...]  （默认 tools tests）

Readers: Alice · 手动跑（Hand 就绪清单④）。rc=0 与快照一致 / 2 与快照不一致或
         有文件读不到（树变了要人看）/ 3 分母为 0。没有 CI 调用点；不加进 MODULES，
         因为它假设了「tests/run_tests.py 里有一张 MODULES 字面量表」这个真树形状。
         刷新时机：处置完一个 ⑤ 类文件，或 run_tests.py / run_production.py 的
         登记表改动之后，重跑并把 EXPECT 更新成新读数（更新前先确认差异是我改的还是树改的）。

本装置能查的边界：只查「读者声明存在且格式对」，不查声明是不是真的 ——
一行 `Readers: 没人 · 永不` 也能从 ⑤ 移到 ④。真假由读它的人判。
"""
import ast
import os
import sys

DEFAULT_ROOTS = ['tools', 'tests']
SKIP_DIRS = {'.git', '__pycache__', '.venv', 'node_modules'}

RUNNER_ENTRIES = ('tests/run_tests.py', 'tests/run_production.py')
MODULE_SOURCE = 'tests/run_tests.py'   # 读它的 MODULES 字面量
LIVE_DIR = 'tests/live/'

DECL_KEYS = ('readers:', 'reader:', '读者:', '读者：', 'readers：')

# 2026-10-28 07:5x 实测快照。
# ★ 与 07:3x 那版快照的差：那版把 harness/layer_runner.py 与 production/test_scenarios.py
#   算成「无读者的真嫌疑」——**错了**。它们不在 run_tests.py 的 MODULES 里，但被
#   run_production.py 引用：前者以 `-m tests.harness.layer_runner` 执行（:58），
#   后者在 LAYERS 的 L3 清单里（:31）。
#   错因是判据只读了「一张登记表」（MODULES），而「谁会被跑」这件事有两张表
#   ＋一张 import 图。这正是一条「分母是那张表的长度，不是世界的长度」的活例。
# 2026-10-29 09:0x 更新（新增 tools/zero_stamp.py 入仓：打印者 16→17、已自述 4→5）。
#   门先响过一次并点名 ['tools/zero_stamp.py']，确认真是这次改动、不是回归，才改这里的数。
#   附带实测一条判别力的边界：声明必须「行首键 + 同行非空」；`Readers:` 独占一行会被读成
#   没有读者（我第一版就是这样被自己判成 ⑤ 的）。这不是 bug，是这条判据的形状——
#   但它意味着「拆行写声明」会产出假 ⑤，写的时候得一行写完。
# 2026-10-28 07:3x 实测快照；08:1x 更新一次（新增 tools/diag_label_fork.py 入仓，
# 打印者 15→16、已自述 3→4，其余未变）。门响过一次、我确认真是我改的，才改这里的数。
EXPECT = {
    'print_files': 17,
    'mechanical': 5,      # run_tests / run_production / test_owner / layer_runner / production.test_scenarios
    'live_dir': 7,        # 目录约定且尚未自述读者
    'declared': 5,        # f22（移入 live/ + 声明）、diag_label_fork、finally_audit、diag_verdict_shape、zero_stamp
    'undetermined': 0,    # 处置完 ⑤ 之后应为 0；再涨就是有新装置没写读者
}
EXPECT_UNDETERMINED = set()   # 2026-10-28 08:0x 处置完：三个 ⑤ 类各有归属


def iter_py(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn.endswith('.py'):
                yield os.path.join(dp, fn)


def norm(p):
    p = os.path.normpath(p)
    return p[2:] if p.startswith('./') else p


def read_src(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read().decode('utf-8', 'replace'), None
    except PermissionError:
        return None, 'permission'
    except IsADirectoryError:
        return None, 'is_directory'
    except OSError as e:
        if getattr(e, 'errno', None) == 40:
            return None, 'symlink_loop'
        return None, 'os_error_%s' % getattr(e, 'errno', '?')
    except Exception as e:
        return None, 'unexpected_%s' % type(e).__name__


def reader_decl(docstring):
    """只认模块 docstring 内的声明行；注释不算。返回声明原文或 None。"""
    if not docstring:
        return None
    for line in docstring.splitlines():
        s = line.strip()
        low = s.lower()
        for k in DECL_KEYS:
            if low.startswith(k) and len(s) > len(k):
                rest = s[len(k):].strip()
                if rest:
                    return s
    return None


def is_print_call(n):
    if not isinstance(n, ast.Call):
        return False
    f = n.func
    return ((isinstance(f, ast.Name) and f.id == 'print')
            or (isinstance(f, ast.Attribute) and f.attr == 'print'))


def has_nonzero_exit(node):
    """同函数内是否有一条非零退出路径。"""
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            is_exit = ((isinstance(f, ast.Attribute) and f.attr == 'exit')
                       or (isinstance(f, ast.Name) and f.id == 'exit'))
            if is_exit and n.args:
                a = n.args[0]
                if not (isinstance(a, ast.Constant) and a.value == 0):
                    return True
        if isinstance(n, ast.Raise):
            exc = n.exc
            nm = None
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                nm = exc.func.id
            elif isinstance(exc, ast.Name):
                nm = exc.id
            if nm == 'SystemExit':
                return True
        if isinstance(n, ast.Return) and n.value is not None:
            v = n.value
            if isinstance(v, ast.Constant) and v.value == 0:
                continue
            return True
    return False


def module_refs_in(src):
    """从源码的字符串字面量里抽出能解析到现存文件的模块引用。

    覆盖两种形态（都是 run_production.py 真在用的）：
      ["-m", "tests.harness.layer_runner"]      → -m 目标
      "L3": ["tests.production.test_scenarios"] → 登记表值
    """
    out = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
            continue
        s = n.value.strip()
        if not s.startswith('tests'):
            continue
        if s.endswith('.py'):
            out.add(norm(s))
        elif '/' in s:
            out.add(norm(s) + '.py')
        elif '.' in s:
            out.add(norm(s.replace('.', '/')) + '.py')
    return {p for p in out if os.path.exists(p)}


def imported_modules(files):
    """全仓 import 图：{被 import 的路径}。"""
    out = set()
    for p in files:
        src, _ = read_src(p)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                names = [n.module]
            for nm in names:
                if not nm.startswith('tests'):
                    continue
                cand = norm(nm.replace('.', '/')) + '.py'
                if os.path.exists(cand):
                    out.add(cand)
    return out


def mechanical_readers(files):
    """两类机械读者，分开返回，不合并成一个数。

    direct   —— 出现在任一 runner 文件（run_tests / run_production）的字符串字面量里
                （MODULES 登记、LAYERS 表、-m 目标都算）
    imported —— 被仓内某个文件 import（有下游，但下游不一定是队列）
    """
    direct = set(RUNNER_ENTRIES)
    for rf in RUNNER_ENTRIES:
        if os.path.exists(rf):
            src, _ = read_src(rf)
            if src:
                direct |= module_refs_in(src)
    return direct, imported_modules(files)


def main(argv):
    roots = argv[1:] or DEFAULT_ROOTS
    print('roots: %s  （argv 可指定别的树）' % roots)

    files = sorted({norm(p) for r in roots if os.path.isdir(r) for p in iter_py(r)})
    if not files:
        print('[GATE] 锚点命中 0 个 .py 文件，本装置不出数')
        return 3

    direct, imported = mechanical_readers(files)
    mech = direct | imported
    print('机械读者：runner 字面量直引 %d 项（%s）；import 图 %d 项；并集 %d 项'
          % (len(direct), ', '.join(RUNNER_ENTRIES), len(imported), len(mech)))
    print('扫描 .py 文件: %d' % len(files))
    print()

    rows, unreadable = [], []
    for p in files:
        src, cause = read_src(p)
        if src is None:
            unreadable.append((p, cause))
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            unreadable.append((p, 'syntax'))
            continue
        except ValueError:
            unreadable.append((p, 'value_error'))
            continue
        prints = [n for n in ast.walk(tree) if is_print_call(n)]
        if not prints:
            continue
        funcs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fp = [n for n in ast.walk(node) if is_print_call(n)]
                if fp:
                    funcs.append((node.name, node.lineno, len(fp), has_nonzero_exit(node)))
        rows.append({
            'path': p, 'prints': len(prints), 'funcs': funcs,
            'decl': reader_decl(ast.get_docstring(tree)),
        })

    for p, cause in unreadable:
        print('  [UNREADABLE] %-16s %s' % (cause, p))
    if unreadable:
        print()

    mechanical = [r for r in rows if r['path'] in mech]
    live = [r for r in rows if r['path'] not in mech
            and r['path'].startswith(LIVE_DIR) and not r['decl']]
    declared = [r for r in rows if r['path'] not in mech and r['decl']]
    undet = [r for r in rows if r['path'] not in mech
             and not r['path'].startswith(LIVE_DIR) and not r['decl']]
    # 互斥性自证：四类相加必须等于 ①，否则有文件被数了两次或漏了
    assert len(mechanical) + len(live) + len(declared) + len(undet) == len(rows), \
        '分桶不互斥/不全：%d+%d+%d+%d != %d' % (
            len(mechanical), len(live), len(declared), len(undet), len(rows))

    print('① 印了 print 的文件（含模块级 print）: %d' % len(rows))
    print('② mechanical 读者: %d' % len(mechanical))
    for r in mechanical:
        print('     %-45s prints=%d' % (r['path'], r['prints']))
    print('③ live-dir（目录约定；读者未自述，最后一次真跑 静态不可知）: %d' % len(live))
    for r in live:
        print('     %-45s prints=%d' % (r['path'], r['prints']))
    print('④ docstring 里写了读者声明: %d' % len(declared))
    for r in declared:
        print('     %-45s prints=%d  「%s」'
              % (r['path'], r['prints'], r['decl'].replace('`', '')))
    print('⑤ 读者的存在没写在任何地方（= 真嫌疑）: %d' % len(undet))
    for r in undet:
        print('     %-45s prints=%d' % (r['path'], r['prints']))
    print()
    print('   处置（清单⑤）：每个 ⑤ 类要么登记进 MODULES，要么在模块 docstring 里')
    print('   行首写一行声明，说明谁读、怎么刷新。写了就从 ⑤ 移到 ④。')
    print()

    print('=== 函数层（v1 的视角，保留作对照）===')
    allfuncs = [f for r in rows for f in r['funcs']]
    # 测试方法的判词是 assert，不是退出码 —— 分开数，不静默混进"结论形态"
    tfuncs = [f for f in allfuncs if f[0].startswith('test')]
    dfuncs = [f for f in allfuncs if not f[0].startswith('test')]
    conc = [f for f in dfuncs if not f[3]]
    print('有 print 的函数: %d（其中测试方法 %d，判词为 assert，不计入下游比例）'
          % (len(allfuncs), len(tfuncs)))
    print('非测试函数: %d；结论形态（无非零退出路径）: %d（%.1f%%）'
          % (len(dfuncs), len(conc),
             (len(conc) / len(dfuncs) * 100) if dfuncs else 0.0))
    for r in rows:
        for name, ln, npr, act in r['funcs']:
            if name.startswith('test'):
                continue
            if not act:
                print('     %s:%d  %s  prints=%d' % (r['path'], ln, name, npr))
    print()

    got = {'print_files': len(rows), 'mechanical': len(mechanical),
           'live_dir': len(live), 'declared': len(declared),
           'undetermined': len(undet)}
    drift = {k: (EXPECT[k], got[k]) for k in EXPECT if EXPECT[k] != got[k]}
    got_names = {r['path'] for r in undet}
    missing = sorted(EXPECT_UNDETERMINED - got_names)
    extra = sorted(got_names - EXPECT_UNDETERMINED)

    if drift or missing or extra:
        print('[GATE] 与 2026-10-28 07:3x 快照不同 —— 树变了，要人看，不自动改数')
        for k, (e, g) in drift.items():
            print('     %-14s expect=%s actual=%s' % (k, e, g))
        if missing:
            print('     快照里有、这次没了: %s' % (missing,))
        if extra:
            print('     这次新出现、快照里没有: %s' % (extra,))
        print('[GATE] rc=2：读数与快照不一致（不是崩溃，也不是通过）')
        return 2

    # 这一行不许手抄数字：07:5x 我改 EXPECT 后忘了改这里的字面量，印出来的
    # 「自检一致 ✓」旁边挂着旧的 3/7/5 —— 判词与数据又分了两个源。现在从 EXPECT 取。
    print('自检：与快照逐项一致 ✓（print %(print_files)d / mechanical %(mechanical)d '
          '/ live %(live_dir)d / 未定 %(undetermined)d）' % EXPECT)
    if unreadable:
        print('rc=2（读数不全：%d 个文件读不到）' % len(unreadable))
        return 2
    print('rc=0')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
