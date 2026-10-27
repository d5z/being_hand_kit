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
    for fn in ("proc_is_listening", "proc_service_evidence"):
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


if __name__ == "__main__":
    unittest.main()
