"""零位：这套测试跑之前，先证明「它数的是全部」。

2026-10-27 的学费：`tests/test_sync_age_threshold.py` 写好了、单跑全绿、
从没在套件里跑过——因为 `run_tests.py` 的 `MODULES` 是显式清单，不是 discover。
当时靠「870 对不上预期的 875」抓到。

更早的一笔：`tests/test_bin_smoke.py` 的 docstring 写着「macOS release preflight
会跑这条护栏」，而它根本不在清单里——**一条自称在 macOS 上把关的护栏，从来没跑过**。
它不报错，它只是不存在。

这两笔同一个形状：文件存在、测试绿、套件不跑。三件互不相干的事。
唯一能分开它们的读数是分母（磁盘上有几个 vs 清单里登记了几个），所以这条测试
把分母钉进套件本身——它是这里唯一一条「关于这套测试自己」的测试。
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import run_tests  # noqa: E402


class RegistryCoversDiskTest(unittest.TestCase):
    def test_every_test_file_on_disk_is_registered(self):
        on_disk, registered, missing, ghost = run_tests.registry_report()
        self.assertEqual(
            missing, [],
            "这些文件在磁盘上但不在 MODULES 里，永不会跑：%r" % (missing,),
        )
        self.assertEqual(
            ghost, [],
            "这些在 MODULES 里但磁盘上没有文件：%r" % (ghost,),
        )
        # 分母本身也要报出来：只有一个数字的「全绿」没法判。
        self.assertGreater(len(registered), 0)
        self.assertEqual(len(registered), len(on_disk))


if __name__ == "__main__":
    unittest.main()
