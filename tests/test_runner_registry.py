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

    def test_duplicate_registration_is_a_problem_not_just_a_printed_fraction(self):
        # 2026-10-27 第三笔：隐形双胞胎在注册层的形。
        # missing/ghost 都是成员判定，集合相同时必然都空 —— 唯一漏网的是重复，
        # 而它此前只活在 "modules: 70/69" 那行 print 里，rc 仍是 0。
        self.assertEqual(run_tests.duplicate_registrations(
            modules=mods("test_a", "test_a", "test_b")), ["test_a"])
        self.assertEqual(run_tests.duplicate_registrations(
            modules=mods("test_a", "test_b")), [], "干净清单不许报重复")


class OutOfScopeTest(unittest.TestCase):
    """范围本身要有分辨力：`on disk` 说的是「tests/ 顶层」，不是「磁盘上所有」。

    2026-10-27 第四笔（Neuromancer 的「『全部』是承重词」教我的）。
    双向两格，缺一格就是恒真/恒假门：
      已知坏格/反向：喂一个纯顶层清单 → out_of_scope 必须**空**（不许永远报非空）
      已知好格：真仓库         → out_of_scope 必须**非空**，且与分母不相交
    """

    def test_flat_list_has_no_out_of_scope(self):
        # 反向那一格：一个只有顶层文件的仓，范围外的数必须是 0。
        # 少了这一格，「永远打印『范围外另有 N 个』」也能通过。
        self.assertEqual(run_tests.out_of_scope(files=[]), [])

    def test_subdir_files_are_reported_and_never_in_the_denominator(self):
        self.assertEqual(
            run_tests.out_of_scope(files=["production/test_a.py", "test_b.py"]),
            ["production/test_a"])

    def test_real_repo_has_out_of_scope_and_they_are_disjoint_from_denominator(self):
        # 真仓这一格量的是「范围外确实有东西」+「它没混进分母」。
        oos = run_tests.out_of_scope()
        on_disk, _registered, _missing, _ghost = run_tests.registry_report()
        self.assertTrue(oos, "真仓 tests/ 子目录里有 test_*.py（run_production.py L2–L6）")
        self.assertEqual(set(oos) & set(on_disk), set(),
                         "子目录文件混进分母 → missing 会把它们报成「未注册」的假警报")

    def test_real_repo_is_the_known_good_cell(self):
        # 唯一一条碰真仓库的：它证明上面三格之外，现实这一格也是好的。
        on_disk, registered, missing, ghost = run_tests.registry_report()
        self.assertEqual(missing, [], "磁盘上未注册：%r" % (missing,))
        self.assertEqual(ghost, [], "清单里幽灵：%r" % (ghost,))
        self.assertEqual(len(registered), len(on_disk))


if __name__ == "__main__":
    unittest.main()
