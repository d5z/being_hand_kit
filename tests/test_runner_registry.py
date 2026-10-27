"""零位本身也要被拨：把「数得全」这条判据喂假数据，看它会不会红。

2026-10-27 第二笔（Neuromancer 的 N6 教我的）：一条从没被拨过的零位，
绿一年也说明不了什么——它可能永远不会红。所以这里不测「真仓库是齐的」
（那是第一条测试的事），这里测**这条判据在两格里响得不一样**：

  已知好格：磁盘与清单一致       → missing/ghost 都空
  已知坏格：磁盘比清单多一个      → missing 必须点名
  已知坏格：清单比磁盘多一个      → ghost 必须点名
  已知坏格：两边完全不相交        → 两边都要报全，不许只报一个

不碰真仓库：on_disk / modules 由这里注入。
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import run_tests  # noqa: E402


def mods(*names):
    return ["tests." + n for n in names]


class RegistryDetectionTest(unittest.TestCase):
    def test_agreeing_inputs_are_silent(self):
        on_disk, reg, missing, ghost = run_tests.registry_report(
            on_disk=["test_a", "test_b"], modules=mods("test_a", "test_b"))
        self.assertEqual((missing, ghost), ([], []))

    def test_file_on_disk_but_not_registered_is_named(self):
        # 已知坏格：这正是 2026-10-27 真实发生过的那格（test_bin_smoke / age_threshold）
        on_disk, reg, missing, ghost = run_tests.registry_report(
            on_disk=["test_a", "test_never_runs"], modules=mods("test_a"))
        self.assertEqual(missing, ["test_never_runs"])
        self.assertEqual(ghost, [])

    def test_registered_without_file_is_named(self):
        on_disk, reg, missing, ghost = run_tests.registry_report(
            on_disk=["test_a"], modules=mods("test_a", "test_ghost"))
        self.assertEqual(missing, [])
        self.assertEqual(ghost, ["test_ghost"])

    def test_disjoint_sets_report_both_sides(self):
        # 只报一边的实现会在这格上绿——那正是「回执只报一个数」的病
        on_disk, reg, missing, ghost = run_tests.registry_report(
            on_disk=["test_a"], modules=mods("test_b"))
        self.assertEqual(missing, ["test_a"])
        self.assertEqual(ghost, ["test_b"])

    def test_real_repo_is_the_known_good_cell(self):
        # 唯一一条碰真仓库的：它证明上面三格之外，现实这一格也是好的。
        on_disk, registered, missing, ghost = run_tests.registry_report()
        self.assertEqual(missing, [], "磁盘上未注册：%r" % (missing,))
        self.assertEqual(ghost, [], "清单里幽灵：%r" % (ghost,))
        self.assertEqual(len(registered), len(on_disk))


if __name__ == "__main__":
    unittest.main()
