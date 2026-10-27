"""kit/sync.sh 的服务证据判据 —— 在 Linux 上用 lsof 假体覆盖 macOS 分支。

为什么要有这份：macOS 分支在我这台（Linux，无 BSD lsof）永远走不到，
「代码对称、无真机读数」是 2026-10-27 一直挂着的未验格。用 PATH 假体把
lsof 的**列形状**搬过来，就能在本机验读法本身（列位置、裸 FD、rc 语义），
验不了的是 BSD lsof 的实现细节——那部分仍归平台方实测。

2026-10-27 Neuromancer 递来的两个形状都钉在这里：
  ① PIPE 行的 $4 是**裸** 0/1（无 r/w 后缀），CHR/REG 行才是 0r/1w
     ⇒ 任何按 $4 判读/写方向的写法在 pipe 上是零信息；本实现的 $4 只做前缀锚定
  ② 半个 server：stdin 是 PIPE、stdout 是 /dev/null —— 形状造得出来，且门必须排掉
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SYNC = ROOT / "kit" / "sync.sh"

# BSD lsof 的列：COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
T_PIPE_PIPE = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
python3 10730 alice 0    PIPE 0x7f00        0t0      ->0x7f01
python3 10730 alice 1    PIPE 0x7f02        0t0      ->0x7f03
"""
T_PIPE_FILE = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
python3 11000 alice 0    PIPE 0x7f10        0t0      ->0x7f11
python3 11000 alice 1w   REG  253,1     1024   1234 /tmp/D.log
"""
T_PIPE_NULL = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
sleep   12000 alice 0    PIPE 0x7f20        0t0      ->0x7f21
sleep   12000 alice 1w   CHR    3,2     0t0      512 /dev/null
"""
T_NULL_NULL = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
python3 13000 alice 0r   CHR    1,3     0t0      512 /dev/null
python3 13000 alice 1w   CHR    1,3     0t0      512 /dev/null
"""
# socketpair 驱动的 stdio（macOS 26.4.1 实测形状，2026-10-27 Neuromancer 造）：
# $4=0u/1u、$5=unix/unix。这正是「-Fn 的 n 行与 PIPE 同构」的那一形。
T_SOCK_SOCK = """COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
sleep   16152  d5c    0u  unix 0x4221590212a2d867      0t0      ->0xd40de06d9e2c58ba
sleep   16152  d5c    1u  unix 0x4221590212a2d867      0t0      ->0xd40de06d9e2c58ba
"""
# socket 的半个形状：stdin 被 socketpair 驱动，stdout 给 /dev/null
T_SOCK_NULL = """COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
sleep   16153  d5c    0u  unix 0x4221590212a2d867      0t0      ->0xd40de06d9e2c58ba
sleep   16153  d5c    1w   CHR    3,2               0t0      512 /dev/null
"""


def _fn_source():
    """把要测的两个函数段切出来，不跑整脚本。"""
    text = SYNC.read_text(encoding="utf-8")
    out = []
    for fn in ("proc_runner", "proc_runner_ok", "proc_stdio_any", "proc_listening_by_lsof",
               "proc_is_listening", "proc_service_evidence"):
        start = text.index("%s() {" % fn)
        end = text.index("\n}\n", start) + 3
        out.append(text[start:end])
    return "\n".join(out)


class ServiceEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="svcev-")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        # 假 pid：/proc/<pid>/fd 必须不存在，才会走到 lsof 分支
        self.fake_pid = "999998"
        while os.path.isdir("/proc/%s/fd" % self.fake_pid):
            self.fake_pid = str(int(self.fake_pid) - 1)
        self.fn = os.path.join(self.tmp, "fn.sh")
        with open(self.fn, "w", encoding="utf-8") as fh:
            fh.write(_fn_source())
        # lsof 假体
        self.lsof = os.path.join(self.tmp, "lsof")
        with open(self.lsof, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\n[ -n "$FAKE_RC" ] && exit "$FAKE_RC"\ncat "$FAKE_TABLE"\n')
        os.chmod(self.lsof, 0o755)
        # ps 假体：只服务 proc_listening_by_lsof 的归属判别（ps -o uid= -p N）
        self.ps = os.path.join(self.tmp, "ps")
        with open(self.ps, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\n[ -z "$FAKE_PS_UID" ] && exit 1\n'
                     'if [ -n "$FAKE_PS_RC" ]; then exit "$FAKE_PS_RC"; fi\n'
                     'echo "$FAKE_PS_UID"\n')
        os.chmod(self.ps, 0o755)
        # ss 假体：不给表就吐空（proc_is_listening 会落 unknown，不影响 lsof 分支的题）
        self.ss = os.path.join(self.tmp, "ss")
        with open(self.ss, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\n[ -n "$FAKE_SS_RC" ] && exit "$FAKE_SS_RC"\n'
                     '[ -n "$FAKE_SS_TABLE" ] && cat "$FAKE_SS_TABLE"\nexit 0\n')
        os.chmod(self.ss, 0o755)

    def _ask_listening(self, ss_table=None, ss_rc=None, lsof_table=None, lsof_rc=None):
        """只问 proc_is_listening：三值纪律最容易假阴的那一格。"""
        env = dict(os.environ)
        env["PATH"] = self.tmp + os.pathsep + env["PATH"]
        for var, val in (("FAKE_SS_TABLE", ss_table), ("FAKE_SS_RC", ss_rc),
                         ("FAKE_TABLE", lsof_table), ("FAKE_RC", lsof_rc)):
            if val is not None:
                if var.endswith("TABLE"):
                    path = os.path.join(self.tmp, var + ".txt")
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(str(val))
                    env[var] = path
                else:
                    env[var] = str(val)
        r = subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; proc_is_listening "$2"',
             "_", self.fn, self.fake_pid],
            capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def _ask_lsof(self, table=None, rc=None, uid=None, ps_rc=None):
        """只问 proc_listening_by_lsof：macOS 那条 rc=1 同形两义的格子。"""
        env = dict(os.environ)
        env["PATH"] = self.tmp + os.pathsep + env["PATH"]
        for var, val in (("FAKE_TABLE", table), ("FAKE_RC", rc),
                         ("FAKE_PS_UID", uid), ("FAKE_PS_RC", ps_rc)):
            if val is None:
                continue
            if var == "FAKE_TABLE":
                path = os.path.join(self.tmp, "lsof_table.txt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(str(val))
                env[var] = path
            else:
                env[var] = str(val)
        r = subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; proc_listening_by_lsof "$2"',
             "_", self.fn, self.fake_pid],
            capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def _ask(self, table=None, rc=None):
        env = dict(os.environ)
        env["PATH"] = self.tmp + os.pathsep + env["PATH"]
        if table is not None:
            path = os.path.join(self.tmp, "table.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(table)
            env["FAKE_TABLE"] = path
        if rc is not None:
            env["FAKE_RC"] = str(rc)
        r = subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; proc_service_evidence "$2"',
             "_", self.fn, self.fake_pid],
            capture_output=True, text=True, env=env)
        return r.stdout.strip()

    # ---- 执行者闸：argv 里有同名文件 ≠ 它是 server（2026-10-27 Neuromancer 的 vim 负例）----
    def test_runner_extracts_interpreter(self):
        cases = {
            "python3 mcp_server.py": "python3",
            "python3 -": "python3",
            "/usr/bin/python3.11 -m x": "python3.11",
            # macOS CPython re-exec 后 argv[0] 是 Python.app 的绝对路径、首字母大写
            "/Applications/Xcode.app/Contents/Developer/usr/bin/Python -": "python",
            "tail -f mcp_server.py": "tail",
            "vim -R mcp_server.py": "vim",
        }
        for argv, want in cases.items():
            with self.subTest(argv=argv):
                r = subprocess.run(["bash", "-c", '. "$1" >/dev/null 2>&1; proc_runner "$2"',
                                    "_", self.fn, argv], capture_output=True, text=True)
                self.assertEqual(r.stdout, want)

    # ---- 白名单要精确：尾通配 python3.* 的过宽实例是 python3.14-config ----
    #
    # ★ 证人只有一个（2026-10-27 Neuromancer 用真 bash case 跑出来的，我原来写错了）：
    #   bash case 的 `python3.*` 里 `.` 是字面点、`*` 是通配 ⇒ python3-config【本来就不过】，
    #   它不证明任何事——它是装饰。真证人 python3.14-config（旧写法过、新写法不过）。
    #   下面 test_whitelist_has_exactly_one_witness 把这件事本身钉住：
    #   谁把 witness 换成一个两版都不过的名字，那条测试会红。
    #   （我 3709 那帖里就是这么写的——没跑，凭 glob 长什么样断的。）
    def test_runner_whitelist_exact(self):
        cases = {
            "python": "yes", "python3": "yes", "python3.14": "yes",
            "node": "yes", "nodejs": "yes",
            # 尾通配时代会误放行的那一个（真证人）
            "python3.14-config": "no",
            # 非证人：旧写法下本来就不过，留着只为覆盖形状，不证明收紧有效
            "python3-config": "no",
            # 编辑器 / 检视器 / Electron（Neuromancer 那台 desktop kit 的运行时；没验过就不放行）
            "tail": "no", "vim": "no", "electron": "no", "less": "no",
        }
        for runner, want in cases.items():
            with self.subTest(runner=runner):
                r = subprocess.run(["bash", "-c", '. "$1" >/dev/null 2>&1; proc_runner_ok "$2"',
                                    "_", self.fn, runner], capture_output=True, text=True)
                self.assertEqual(r.stdout.strip(), want)

    # ---- 收紧这一刀必须有一个真证人：旧写法说 yes、新写法说 no ----
    def test_whitelist_has_exactly_one_witness(self):
        import fnmatch
        names = ["python", "python3", "python3.12", "python3.14",
                 "python3-config", "python3.14-config",
                 "node", "nodejs", "tail", "vim", "electron", "less"]
        # 旧写法的语义 = bash case 的整串分支 = 每个 glob 都要试（只翻一个分支就是我第一版犯的错，
        # 那版把 node/nodejs/python3 都判成「变化」，测试自己当场咬住了我）。不是 grep ERE。
        OLD_GLOBS = ("python", "python3", "python3.*", "node", "nodejs")
        old = {n: any(fnmatch.fnmatchcase(n, g) for g in OLD_GLOBS) for n in names}
        differing = set()
        for n in names:
            r = subprocess.run(["bash", "-c", '. "$1" >/dev/null 2>&1; proc_runner_ok "$2"',
                                "_", self.fn, n], capture_output=True, text=True)
            new = r.stdout.strip() == "yes"
            if old[n] != new:
                differing.add(n)
        self.assertEqual(differing, {"python3.14-config"},
                         "收紧的证人集变了：要么白名单放松了，要么测试里那个证人被换成了装饰")

    # ---- 宽门：一条头被驱动就算「有人喂着」（半个 server）----
    def _ask_any(self, fd0, fd1):
        d = os.path.join(self.tmp, "proc", self.fake_pid, "fd")
        if fd0 is None and fd1 is None:
            shutil.rmtree(os.path.join(self.tmp, "proc"), ignore_errors=True)
        else:
            os.makedirs(d, exist_ok=True)
        for n, target in ((0, fd0), (1, fd1)):
            path = os.path.join(d, str(n))
            if os.path.islink(path) or os.path.exists(path):
                os.unlink(path)
            if target is not None:
                os.symlink(target, path)
        env = dict(os.environ)
        env["PROC_ROOT"] = os.path.join(self.tmp, "proc")
        r = subprocess.run(["bash", "-c", '. "$1" >/dev/null 2>&1; proc_stdio_any "$2"',
                            "_", self.fn, self.fake_pid], capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def test_half_pipe_is_driven(self):
        """Neuromancer 递的半个 server（fd0=PIPE、fd1=文件）：宽门要认，且门仍是 none。"""
        self.assertEqual(self._ask_any("pipe:[777]", "/tmp/out.log"), "driven")
        self.assertEqual(self._ask_any("socket:[778]", "/dev/null"), "driven")

    def test_both_files_is_none(self):
        self.assertEqual(self._ask_any("/dev/null", "/tmp/out.log"), "none")

    def test_pipe_both_is_driven(self):
        self.assertEqual(self._ask_any("pipe:[1]", "pipe:[2]"), "driven")

    def test_no_fd_dir_is_unknown(self):
        self.assertEqual(self._ask_any(None, None), "unknown")

    # ---- macOS：lsof rc=1 的两义（2026-10-27 真机负样本）----
    def test_lsof_rc1_own_process_is_not(self):
        """自家进程：rc=1 零行 ⇒ 真的没在监听 ⇒ not。"""
        self.assertEqual(self._ask_lsof(rc=1, uid=os.getuid()), "not")

    def test_lsof_rc1_other_owner_is_unknown(self):
        """别人的 socket：rc=1 零行可能是「我读不到」（root socket 真机形状）⇒ unknown。

        真机原件（Darwin uid=502）：pid 1666 uid=0、pid 269 uid=24，
        lsof 都是 rc=1 / stdout 0 字节 / stderr 0 字节 —— 和「自家没监听」在输出上同形。
        """
        other = "0" if os.getuid() != 0 else "502"
        self.assertEqual(self._ask_lsof(rc=1, uid=other), "unknown")

    def test_lsof_rc1_unreadable_owner_is_unknown(self):
        """连归属都读不到（进程没了 / ps 失败）⇒ unknown。"""
        self.assertEqual(self._ask_lsof(rc=1, uid=None), "unknown")

    def test_lsof_rc0_one_row_is_listening(self):
        table = ("COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
                 "python3 %s alice    3u  IPv4 0x1      0t0      TCP 127.0.0.1:18923 (LISTEN)\n"
                 % self.fake_pid)
        # rc 不设：假体「不给 rc 就 cat 表并退 0」——设 FAKE_RC=0 会走 exit 0 分支、不吐表
        self.assertEqual(self._ask_lsof(table=table, uid=os.getuid()), "listening")

    # ---- ss 侧的能力闸（2026-10-27 Neuromancer 逼出来的一格）----
    def test_ss_listeners_but_no_pid_anywhere_is_unknown(self):
        """表里有监听行、却一个 pid= 都读不到 ⇒ unknown，不是 not。

        这正是非 root 读别人 socket 的形状：ss 有行、没有 users:(...)。
        旧写法会在这里说「not」——把「我看不见」当成「它不在」。
        """
        table = ("State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
                 "LISTEN 0      128          0.0.0.0:22        0.0.0.0:*\n"
                 "LISTEN 0      5          127.0.0.1:18923     0.0.0.0:*\n")
        self.assertEqual(self._ask_listening(ss_table=table), "unknown")

    def test_ss_other_pids_visible_mine_absent_is_not(self):
        """看得见 pid、就是没有我这个 ⇒ not（这一格才是真的「不是」）。"""
        table = ("State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
                 "LISTEN 0      128          0.0.0.0:22        0.0.0.0:*    "
                 "users:((\"sshd\",pid=4711,fd=3))\n")
        self.assertEqual(self._ask_listening(ss_table=table), "not")

    def test_ss_pid_at_end_of_users_list_still_matches(self):
        """回归：pid 收在行尾（`pid=999998))` 后面没逗号）也要算 listening。

        旧写法 `case ... *\"pid=$_pid,\"*` 依赖后随逗号，这个形状会假阴。
        """
        table = ("State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
                 "LISTEN 0      5          127.0.0.1:18923     0.0.0.0:*    "
                 "users:((\"python3\",pid=%s,fd=3))\n" % self.fake_pid)
        self.assertEqual(self._ask_listening(ss_table=table), "listening")

    def test_ss_failure_is_unknown(self):
        """ss 自己非零退出 ⇒ unknown（命令成败不许被读成「没有」）。"""
        self.assertEqual(self._ask_listening(ss_table="", ss_rc=1), "unknown")

    # ---- 四个真形状 ----
    def test_both_pipes_is_stdio(self):
        """两行都是 TYPE=PIPE 才算服务 —— 真 server 的形状（$4 是裸 0/1）。"""
        self.assertEqual(self._ask(T_PIPE_PIPE), "stdio")

    def test_pipe_then_file_is_none(self):
        """Neuromancer 那格：stdout 被重定向到文件，只有 stdin 是管道。"""
        self.assertEqual(self._ask(T_PIPE_FILE), "none")

    def test_half_server_is_none(self):
        """半个 server：stdin 被驱动、stdout 给 /dev/null —— 形状能造，且门排掉。"""
        self.assertEqual(self._ask(T_PIPE_NULL), "none")

    def test_devnull_both_is_none(self):
        self.assertEqual(self._ask(T_NULL_NULL), "none")

    def test_missing_pid_is_unknown_not_none(self):
        """rc≠0 ⇒ unknown。旧写法 `lsof | tail -n +2` 会把不存在的 pid 读成 none。"""
        self.assertEqual(self._ask(rc=1), "unknown")

    # ---- 零行 / 单行 / 子串冒充（2026-10-27 第七把尺的对侧） ----
    def test_header_only_is_unknown_not_none(self):
        """rc=0 但一行数据都没有 ⇒ unknown。

        Neuromancer 那侧 all([]) 让空集合说「是」（假阳）；
        我这版原来让它说「不是」（假阴）。两边都在从「什么都没有」里挤一个确定值。
        """
        table = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n")
        self.assertEqual(self._ask(table), "unknown")

    def test_one_row_is_unknown_not_none(self):
        """只读到一头（另一头 fd 缺失）⇒ 判不了，不是「不是」。"""
        table = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
                 "sleep   15000 alice 0 PIPE 0x100 0t0 ->0x101\n")
        self.assertEqual(self._ask(table), "unknown")

    def test_fd_substring_does_not_masquerade(self):
        """fd 10 不能冒充 fd 1：fd0=PIPE + 只有 fd10=PIPE ⇒ unknown（不是 stdio）。"""
        table = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
                 "sleep   16000 alice 0  PIPE 0x200 0t0 ->0x201\n"
                 "sleep   16000 alice 10 PIPE 0x300 0t0 ->0x301\n")
        self.assertEqual(self._ask(table), "unknown")

    # ---- socket 形（2026-10-27 Neuromancer 造的形状；我这边补的格） ----
    def test_socketpair_is_stdio(self):
        """$5=unix/unix：socketpair 驱动的 stdio 仍是「两头被驱动」，判据落 stdio。

        为什么收它：判据问的是「有人从两头驱动我」，不问传输介质。
        拒它会把 socketpair 起的 server 判成 none —— 阴性误判让旧进程活着，
        在停旧进程这条路上代价比误杀低，但仍然是错。
        """
        self.assertEqual(self._ask(T_SOCK_SOCK), "stdio")

    def test_half_socket_is_none(self):
        """socket 的半个形状（stdin 被驱动、stdout 给 /dev/null）必须落 none。"""
        self.assertEqual(self._ask(T_SOCK_NULL), "none")

    def test_mixed_pipe_unix_is_stdio(self):
        """且门只看「两头都在被驱动集合里」，不要求两头同形（pipe|unix 混搭也算）。"""
        table = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
                 "sleep   14000 alice 0    PIPE 0x7f30        0t0      ->0x7f31\n"
                 "sleep   14000 alice 1u   unix 0x4221         0t0      ->0x4222\n")
        self.assertEqual(self._ask(table), "stdio")

    # ---- 混搭两方向（Neuromancer 2026-10-27 造的形；口径分歧就露在这两格里） ----
    def test_unix_then_pipe_is_stdio(self):
        """fd0=unix(0u), fd1=PIPE(1)：我这版落 stdio，PIPE-only 实现落 none。"""
        table = ("COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
                 "sleep   19451  d5c    0u  unix 0x6f25               0t0      ->0x6f26\n"
                 "sleep   19451  d5c    1    PIPE 0x98a7               0t0      ->0x98a8\n")
        self.assertEqual(self._ask(table), "stdio")

    def test_pipe_then_unix_is_stdio(self):
        """fd0=PIPE, fd1=unix(1u)：反方向同样落 stdio。"""
        table = ("COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
                 "sleep   19452  d5c    0    PIPE 0x98a7               0t0      ->0x98a8\n"
                 "sleep   19452  d5c    1u  unix 0x6f25               0t0      ->0x6f26\n")
        self.assertEqual(self._ask(table), "stdio")

    def test_reg_then_pipe_is_none(self):
        """他没造的那格：fd0=REG（重定向到文件）+ fd1=PIPE —— 只有一头被驱动，落 none。

        REG/CHR 不是「有人在驱动我」的证据：`cmd > out 2>&1 | tee` 的左边就是这形状。
        """
        table = ("COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
                 "sleep   19453  d5c    0r   REG    8,1     1234     99 /tmp/out.log\n"
                 "sleep   19453  d5c    1    PIPE 0x98a7      0t0      ->0x98a8\n")
        self.assertEqual(self._ask(table), "none")

    def test_bare_fd_anchor(self):
        """回归点：$4 在 PIPE 行是裸 `0`/`1`。

        2026-10-27 Neuromancer 实测：PIPE 行无 r/w 后缀，CHR/REG 行才有。
        本实现的 $4 只做前缀锚定（index($4,f)==1），所以两种形状都锚得上；
        若有人把它改成精确匹配 "0r|1w"，裸 0 那行会静默锚空 —— 这条测试就红。
        """
        self.assertEqual(self._ask(T_PIPE_PIPE), "stdio")
        self.assertEqual(self._ask(T_PIPE_FILE), "none")

    # ── 以下是**真机原件**，不是造的形状 ──────────────────────────────
    # 2026-10-27 16:5xZ 在 macOS（Darwin）上直接跑 lsof 抓下来的三张表，
    # 只把用户名/家目录换成长度相同的假名，列宽与空白**原样保留**——
    # 这张表的形状本身就是被测对象，改对齐就等于换成另一道题。

    def test_mac_real_stdio_mcp_server(self):
        """真机原件：pid 4182 = Python mcp_server.py，fd0/fd1 都是 PIPE ⇒ stdio。

        这一格此前只有「代码对称」的假体，没有真机。2026-10-27 16:5xZ
        在 Darwin 上用同一段判据跑真进程得到 `stdio ( fd0=PIPE fd1=PIPE)`。
        与造的形状的差别：PIPE 行的 SIZEOFF/NODE 列被 `->0x…` 顶掉，
        整行比 CHR/REG 行短一截 —— 造的形状里那一格是 `0t0`，比真的宽松。
        """
        table = ("COMMAND  PID USER   FD   TYPE             DEVICE SIZE/OFF      NODE NAME\n"
                 "Python  4182   xx    0   PIPE 0xc8e57b661acad3b1    16384      ->0x5c5c8cbbdc3b7f09\n"
                 "Python  4182   xx    1   PIPE 0x5e79d7597318863c    65536      ->0x13120502789c05ff\n")
        self.assertEqual(self._ask(table), "stdio")

    def test_mac_real_devnull_then_log_is_none(self):
        """真机原件：pid 676，0r=CHR(/dev/null)、1u=REG(日志) ⇒ none。

        这是这台 mac 上最常见的「后台常驻但不是服务」形状：输出追加到日志文件。
        """
        table = ("COMMAND PID USER   FD   TYPE DEVICE SIZE/OFF      NODE NAME\n"
                 "Python  676   xx    0r   CHR    3,2      0t0       336 /dev/null\n"
                 "Python  676   xx    1u   REG   1,16        0 181504786 /private/tmp/keyword-extract.log\n")
        self.assertEqual(self._ask(table), "none")

    def test_mac_real_half_server_pipe_then_log(self):
        """真机原件：pid 2087，fd0=PIPE（被父进程驱动）、fd1=REG(日志) ⇒ none。

        半个 server：只有 stdin 是管道。门必须排掉它——只读一头的人不是服务。
        注意这张表的 REG 行 DEVICE 列被空白推到 $6，造的形状里没这形。
        """
        table = ("COMMAND  PID USER   FD   TYPE             DEVICE SIZE/OFF      NODE NAME\n"
                 "Python  2087   xx    0   PIPE 0x13354660f6855d94    16384           \n"
                 "Python  2087   xx    1w   REG               1,16        0 181544850 /Users/xx/.heart-portal/runtime/portal-supervisor.log\n")
        self.assertEqual(self._ask(table), "none")


if __name__ == "__main__":
    unittest.main()
