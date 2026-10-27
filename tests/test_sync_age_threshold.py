"""kit/sync.sh 的年龄闸阈值 —— 这个数不属于这台机器（2026-10-27）。

`[ "$age" -lt 2 ]` 是**裸 tick 数**：只对 HZ=100 成立，却写成了通用阈值。
推导：尺子是 /proc/uptime 两位小数 = 10ms（与 HZ 无关），tick = 1/HZ 秒
⇒ 以 tick 计的尺子不确定度 = ceil(HZ/100)，安全阈值 = 1 + ceil(HZ/100)。

  HZ=100 → 2（这台机器恰好就是这个数，所以它一直绿，看不出问题）
  HZ=250 → 4    HZ=1000 → 11

验法：把函数逐字摘出来（与 test_sync_service_evidence 同一套做法——整份
sync.sh 是 `set -euo pipefail` + 会跑 main 的脚本，source 它会 exit，问不到函数），
再把 getconf 换成假体，把三种 HZ 搬到本机来问。
验不了的：真换个 HZ≠100 的内核跑一遍——那需要另一台机器。
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SYNC = ROOT / "kit" / "sync.sh"


def _fn_source(name="age_threshold_ticks"):
    """从 kit/sync.sh 逐字摘一个函数（起始行到第一个顶格 `}`）。"""
    lines = SYNC.read_text(encoding="utf-8").splitlines(True)
    out, inside = [], False
    for ln in lines:
        if not inside and ln.startswith("%s() {" % name):
            inside = True
        if inside:
            out.append(ln)
            if ln.rstrip("\n") == "}":
                break
    assert out, "kit/sync.sh 里找不到函数 %s" % name
    return "".join(out)


class AgeThresholdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.fn = os.path.join(self.tmp, "fn.sh")
        with open(self.fn, "w", encoding="utf-8") as fh:
            fh.write(_fn_source())

    def _run(self, hz_value):
        """PATH 前置一个 getconf 假体，问阈值是多少。"""
        fake = pathlib.Path(self.tmp) / "getconf"
        if hz_value is None:            # getconf 直接失败：读不到 HZ
            fake.write_text("#!/bin/sh\nexit 1\n")
        else:
            fake.write_text(
                '#!/bin/sh\ncase "$1" in CLK_TCK) echo %s ;; *) exit 1 ;; esac\n'
                % hz_value)
        fake.chmod(0o755)
        env = dict(os.environ, PATH=self.tmp + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; age_threshold_ticks', "_", self.fn],
            capture_output=True, text=True, env=env)
        out = r.stdout.strip()
        self.assertTrue(out, "age_threshold_ticks 没有输出；stderr=%r" % r.stderr[-400:])
        return out

    def test_hz_100_reproduces_the_old_hardcoded_number(self):
        # 旧代码写死的就是 2 —— 这格说明「为什么这个 bug 在开发机上不可见」
        self.assertEqual(self._run(100), "2")

    def test_threshold_scales_with_tick_resolution(self):
        self.assertEqual(self._run(250), "4")
        self.assertEqual(self._run(1000), "11")

    def test_unreadable_hz_falls_on_the_safe_side(self):
        # 读不到 HZ ⇒ 取最严（HZ=1000 的形状）：宁可判不了，不可误杀
        self.assertEqual(self._run(None), "11")

    def test_garbage_hz_does_not_become_an_arithmetic_error(self):
        self.assertEqual(self._run("abc"), "11")
        self.assertEqual(self._run("0"), "11")


class AgeGateWiringTest(unittest.TestCase):
    """函数算对了但调用点没换，是另一种绿灯。"""

    def test_gate_calls_the_threshold_function(self):
        src = SYNC.read_text(encoding="utf-8")
        self.assertIn("_thr=$(age_threshold_ticks)", src)
        self.assertNotIn('[ "$age" -lt 2 ]', src)


if __name__ == "__main__":
    unittest.main()
