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
