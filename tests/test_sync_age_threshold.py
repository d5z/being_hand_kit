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


class AgeUnreadableFailsClosedTest(unittest.TestCase):
    """同一个数在一条链上出现两次时，两处的失败方向必须同向。

    2026-10-27 修前：阈值侧读不到 HZ 取最严 11（fail-closed），而 age 侧
    `getconf CLK_TCK || echo 100` 兜底（fail-open）——合起来是 fail-open 冒充 fail-closed：
    HZ=1000 的内核上算出 10 倍大的 age ⇒ 门以为「够老、分得开」⇒ 当 alive 放行。

    两格必须响得不一样，缺一格这套验法就不成立：
      好格：HZ 读得到 → 长命进程 → alive（证明门没变成「永远 unknown」）
      坏格：HZ 读不到 → 同一个进程 → unknown（证明它落在不动手那侧）
    """

    FUNCS = ("proc_identity", "proc_identity_ticks", "proc_age_ticks",
             "age_threshold_ticks", "proc_state")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.fn = os.path.join(self.tmp, "fns.sh")
        with open(self.fn, "w", encoding="utf-8") as fh:
            for name in self.FUNCS:
                fh.write(_fn_source(name) + "\n")
        # 被测进程用本 unittest 进程：它已经活了远超一个 tick，年龄闸会放行。
        self.pid = str(os.getpid())

    def _env(self, hz):
        fake = pathlib.Path(self.tmp) / "getconf"
        if hz is None:
            fake.write_text("#!/bin/sh\nexit 1\n")
        else:
            fake.write_text(
                '#!/bin/sh\ncase "$1" in CLK_TCK) echo %s ;; *) exit 1 ;; esac\n' % hz)
        fake.chmod(0o755)
        return dict(os.environ, PATH=self.tmp + os.pathsep + os.environ.get("PATH", ""))

    def _sh(self, script, hz):
        return subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; ' + script, "_", self.fn],
            capture_output=True, text=True, env=self._env(hz))

    def test_good_cell_readable_hz_reaches_alive(self):
        want = self._sh('proc_identity %s' % self.pid, 100).stdout.strip()
        self.assertTrue(want, "取不到本进程的 identity，这条测试的前置就断了")
        r = self._sh('proc_state %s "%s"' % (self.pid, want), 100)
        self.assertEqual(r.stdout.strip(), "alive")

    def test_bad_cell_unreadable_hz_becomes_unknown_not_alive(self):
        want = self._sh('proc_identity %s' % self.pid, 100).stdout.strip()
        r = self._sh('proc_state %s "%s"' % (self.pid, want), None)
        self.assertEqual(r.stdout.strip(), "unknown")

    def test_caller_fails_closed_when_age_is_empty(self):
        # 隔离的是**调用点**，不是年龄函数：把 proc_age_ticks 换成「不报数」的假体，
        # 真 getconf 仍可读 ⇒ 阈值是 2，不会替调用点兜底。修前 `''|*[!0-9]*) : ;;`
        # 会让空年龄直接落到 alive —— 年龄读不到 = 门没电却照放行。
        #
        # 和上面 test_bad_cell_* 的关系（2026-10-27 变异实测，别凭读代码推断）：
        #   只拨 B（caller）      → 合力格红 + 隔离格红
        #   只拨 A（`|| echo 100`）→ 合力格**绿**（阈值侧的 fail-closed=11 替它兜住了：
        #                           age 算成 4 < 11 ⇒ unknown，看起来完全正常）+ 隔离格不受影响
        #   A 与 B 同时拨回       → 合力格**绿**，隔离格红
        # ⇒ 合力格只在单点回归时响，两点同时回归它会静默——它绿不能推出 A 好。
        #   抓 A 的是 test_age_is_not_computed_from_an_invented_hz；抓 B 且抗双重回归的是这条。
        want = self._sh('proc_identity %s' % self.pid, 100).stdout.strip()
        self.assertTrue(want)
        r = self._sh('proc_age_ticks() { return 3; }; proc_state %s "%s"'
                     % (self.pid, want), 100)
        self.assertEqual(r.stdout.strip(), "unknown")

    def test_age_is_not_computed_from_an_invented_hz(self):
        # 兜底的直接形态：读不到 HZ 时不许吐出一个数——吐出来就一定会被当真。
        r = self._sh('proc_age_ticks %s' % self.pid, None)
        self.assertEqual(r.stdout.strip(), "")
        self.assertNotEqual(r.returncode, 0)


class AgeGateWiringTest(unittest.TestCase):
    """函数算对了但调用点没换，是另一种绿灯。"""

    def test_gate_calls_the_threshold_function(self):
        src = SYNC.read_text(encoding="utf-8")
        self.assertIn("_thr=$(age_threshold_ticks)", src)
        self.assertNotIn('[ "$age" -lt 2 ]', src)


if __name__ == "__main__":
    unittest.main()
