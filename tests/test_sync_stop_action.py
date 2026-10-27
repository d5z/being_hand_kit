"""kit/sync.sh 的「状态 → 动作」映射 —— 没见过的值不许动手（2026-10-27）。

形状来自 Neuromancer 那格 `v == "unreachable"`：**判据按见过的值列分支，就是一张黑名单，
失效方向永远是 fail-open。** 他那格漏掉的值 → 假绿（一个真缺陷被判通过）。

我这格是同一个形状、更坏的方向：停机循环原来写

    case "$STATE" in
      gone|reused|zombie) 已退出 ;;
      unknown)            判不了 ;;
      *)                  kill -9 ;;      ← 没见过的值都落这里
    esac

proc_state 今天有 5 个值，一晚上涨过两次（加僵尸、加年龄闸）。第 6 个值只要意思是
「判不了」，就会在 `*)` 里被读成「仍活跃」，然后 kill -9 一个我从未判别过的进程。
假绿是少做一件事，误杀是做错一件事。

修法：抽出 stop_action()（纯映射、无副作用），只有明确 alive → kill，其余一律 unknown。
这套测试问的就是那句「其余」。

验法说明（两条都不是装饰）：
  · 枚举 proc_state 的值域用的是「扒函数体里的 echo 字面量」，不是 ast.literal_eval
    ——他那边的教训：literal_eval 只读 Constant 节点，IfExp / f-string 里的分支会被
    静默漏掉，枚举器报 n=2、其实有 4 支，而唯一该放行的那支根本不在场。
  · 所以本文件自带一条「枚举器在场检」：它报出来的值必须真有 5 个、且 alive 必须在里面。
    枚举器自己漏了，后面的格子全是过场。
"""
import os
import re
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC = os.path.join(ROOT, "kit", "sync.sh")

# proc_state 今天能说的所有话。新增值会在这里拦住——这也是白名单：
# 「该有却没有」这类问题，配一个通配符的测试永远答不了。
KNOWN_STATES = {"gone", "reused", "zombie", "alive", "unknown"}


def _fn_source(name):
    """把 sync.sh 里某个函数逐字摘出来（整份 sync.sh 会跑 main，source 它会 exit）。"""
    with open(SYNC, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"^%s\(\)\s*\{.*?^\}" % re.escape(name), src, re.S | re.M)
    if not m:
        raise AssertionError("sync.sh 里找不到函数 %s" % name)
    return m.group(0)


def _enumerate_states():
    """从 proc_state 的函数体里扒出它可能 echo 出来的值。"""
    body = _fn_source("proc_state")
    vals = set(re.findall(r"echo\s+([a-z]+)", body))
    # 末尾那句裸 `echo unknown`（不带 ; return）已在上面命中；这里只做形状兜底。
    return vals


class EnumeratorInTheRoomTest(unittest.TestCase):
    """枚举器自己也要被验：它报 n 的时候，n 必须等于它该看到的支路数。"""

    def test_enumerator_finds_all_five_and_includes_alive(self):
        vals = _enumerate_states()
        self.assertEqual(
            len(vals), len(KNOWN_STATES),
            "枚举器报 %d 个值 %s，预期 %d 个 —— 要么 proc_state 换代了，要么枚举器漏支路"
            % (len(vals), sorted(vals), len(KNOWN_STATES)))
        self.assertIn("alive", vals, "唯一该放行的那一支不在枚举里，后面的格子全是过场")
        self.assertEqual(vals, KNOWN_STATES)


class StopActionTest(unittest.TestCase):
    """只有明确 alive 才动手。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.fn = os.path.join(self.tmp, "fns.sh")
        with open(self.fn, "w", encoding="utf-8") as fh:
            fh.write(_fn_source("stop_action") + "\n")

    def _act(self, value):
        r = subprocess.run(
            ["bash", "-c", '. "$1" >/dev/null 2>&1; stop_action "$2"', "_", self.fn, value],
            capture_output=True, text=True)
        return r.stdout.strip()

    def test_alive_is_the_only_value_that_acts(self):
        acts = {v: self._act(v) for v in KNOWN_STATES}
        self.assertEqual(acts["alive"], "kill")
        for v in KNOWN_STATES - {"alive"}:
            self.assertNotEqual(acts[v], "kill", "%s 不该触发动手" % v)
        self.assertEqual(acts["gone"], "stopped")
        self.assertEqual(acts["reused"], "stopped")
        self.assertEqual(acts["zombie"], "stopped")
        self.assertEqual(acts["unknown"], "unknown")

    def test_a_value_i_have_never_seen_does_not_kill(self):
        # 这一格是修法本身：proc_state 明天多一个值（比如 "unreadable"），
        # 它必须落进「不动手」，而不是落进 `*)` 被当成活着。
        for future in ("unreadable", "gone-ish", "", "ALIVE", "alive2"):
            self.assertEqual(self._act(future), "unknown",
                             "未见过/空/大小写不同的值 %r 被判成了要动手" % future)


if __name__ == "__main__":
    unittest.main()
