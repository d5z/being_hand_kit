"""
Test runner using standard library unittest.

Loads every tests/test_*.py module explicitly (kept deterministic, no
pytest dependency) and runs the suite.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetic session state: a test run must not read or overwrite the CDP
# session-page record the operator's browser is actually using. See
# tests/harness/__init__.py for the same rule on the package-import path.
os.environ.setdefault(
    "HAND_CDP_STATE_FILE",
    os.path.join(tempfile.gettempdir(), "hand_cdp_last_idx_tests"),
)


MODULES = ["tests.test_type_landed", "tests.test_plan", "tests.test_tier2_3", "tests.test_platform", "tests.test_vision_llm", "tests.test_cdp_contract", "tests.test_cdp_contract_real", "tests.test_page_identity", "tests.test_windows_support", "tests.test_receipt_contract", "tests.test_truncation", "tests.test_ax_tree", "tests.test_ax_see", "tests.test_macos_discovery", "tests.test_chrome_profile", "tests.test_kit_quickfixes", "tests.test_release_070", "tests.test_release_080", "tests.test_release_097", "tests.test_release_098", "tests.test_release_0100", "tests.test_release_chain", "tests.test_hand_api", "tests.test_visual_state", "tests.test_ocr_diff", "tests.test_expect_spec", "tests.test_viewport_alignment", "tests.test_text_match", "tests.test_enter_submit", "tests.test_handle_staleness", "tests.test_heading_redirect", "tests.test_clickable_point", "tests.test_eye_check", "tests.test_emitted", "tests.test_action_primitives", "tests.test_release_0110", "tests.test_frame_diff", "tests.test_effect", "tests.test_release_0120", "tests.test_release_0130", "tests.test_iframe_coords", "tests.test_release_0131", "tests.test_iframe_transform", "tests.test_iframe_transform_geo", "tests.test_release_0132", "tests.test_dom_no_text", "tests.test_release_0133", "tests.test_frame_origins", "tests.test_release_0134", "tests.test_effect_channels", "tests.test_release_0135", "tests.test_release_0136", "tests.test_release_0137", "tests.test_xy_expect", "tests.test_dpr_decl", "tests.test_dpr_tiers", "tests.test_owner", "tests.test_owner_listener", "tests.test_click_once", "tests.test_dpr_single_read", "tests.test_version_fork", "tests.test_selfharm", "tests.test_sync_service_evidence", "tests.test_sync_age_threshold", "tests.test_sync_stop_action", "tests.test_pid_probe", "tests.test_kill_receipt", "tests.test_bin_smoke", "tests.test_runner_registry"]


def registry_report(on_disk=None, modules=None):
    """分母自证：磁盘上有几个 test_*.py，清单里登记了几个，差在哪。

    2026-10-27 交的学费：新写 tests/test_sync_age_threshold.py，单跑全绿，
    套件里从不执行——因为 MODULES 是显式清单而不是 discover。当天 870 对不上
    预期的 875 才抓到。文件存在、单测绿、套件不跑，是三件互不相干的事，
    只有分母能分开它们。所以这里每次跑都念一遍：磁盘 vs 清单，各是几。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if on_disk is None:
        on_disk = sorted(
            f[:-3] for f in os.listdir(here)
            if f.startswith("test_") and f.endswith(".py")
        )
    else:
        on_disk = sorted(on_disk)
    registered = sorted(n.rsplit(".", 1)[-1] for n in (MODULES if modules is None else modules))
    missing = [m for m in on_disk if m not in registered]   # 存在但永不运行
    ghost = [m for m in registered if m not in on_disk]     # 登记了但文件不在
    return on_disk, registered, missing, ghost


def build_suite(problems=None):
    problems = problems if problems is not None else []
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in MODULES:
        try:
            mod = __import__(name, fromlist=[name.rsplit(".", 1)[-1]])
        except ImportError as e:
            # 曾经这里 print("SKIP ...") + continue：一个坏掉的模块会被读成
            # 「跳过」，而整轮仍然是绿的。跳过不是通过——它进 problems。
            problems.append(f"无法导入 {name}: {e}")
            continue
        suite.addTests(loader.loadTestsFromModule(mod))
    return suite


def duplicate_registrations(modules=None):
    """同一模块在清单里出现多次 —— 「隐形双胞胎」在注册层的形。

    2026-10-27 第三笔（围炉 #34，Neuromancer 的 Z9d 教我的）：
    missing/ghost 都是【成员判定】(in)，所以两边集合完全相同时它们必然都空。
    唯一能让 len(registered) != len(on_disk) 而又 missing == ghost == [] 的情况，
    就是重复注册：跑两遍、Ran 数虚高、而 -- 在我加这一笔之前 -- rc 仍然是 0。
    它此前只活在 print 出来的 `modules: 70/69` 那行里，
    靠 tests/test_runner_registry.py 里另一条断言间接抓 —— 判据借了别人的地方住。
    现在它自己进 problems。
    """
    reg = [n.rsplit(".", 1)[-1] for n in (MODULES if modules is None else modules)]
    return sorted({n for n in reg if reg.count(n) > 1})


def out_of_scope(files=None):
    """tests/ 子目录里的 test_*.py —— 它们不在本 runner 的分母里，但必须在回执上。

    2026-10-27 第四笔（围炉 #34，Neuromancer 的「『全部』是承重词」教我的）：
    本 runner 的分母是 os.listdir(tests/) 顶层、非递归。而 `on disk` 这个词的
    通常含义是「这棵目录树里所有的」。实查：仓内 74 个 test_*.py，69 在顶层
    （全在 MODULES），5 个在 tests/production、tests/integration 下，由
    tests/run_production.py 的 L2–L6 跑。

    它们不是漏跑，是另一个 gate。所以修法不是把它们塞进 MODULES（那会把
    production gate 混进单测、破坏分层），而是：
      ① 那行说出自己的范围（listdir ≠ 磁盘）；
      ② 范围外的数也报出来 —— 只报「范围内 N/N」的回执，等于用范围冒充全集。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if files is None:
        files = []
        for root, dirs, fs in os.walk(here):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in fs:
                if f.startswith("test_") and f.endswith(".py"):
                    files.append(os.path.relpath(os.path.join(root, f), here))
    # 顶层文件不属于「范围外」——这条过滤对注入的清单也生效，
    # 否则 fake 数据走的路径与真实路径不同，两格测的不是同一件事。
    return sorted(p[:-3].replace(os.sep, "/") if p.endswith(".py") else p.replace(os.sep, "/")
                  for p in files if os.sep in p)


if __name__ == "__main__":
    on_disk, registered, missing, ghost = registry_report()
    print(f"modules: {len(registered)}/{len(on_disk)} on disk  (scope: tests/ 顶层，非递归)")
    oos = out_of_scope()
    if oos:
        print(f"  · 范围外另有 {len(oos)} 个 test_*.py 不归这把尺子（tests/run_production.py L2–L6）：")
        print(f"      {', '.join(oos)}")
    problems = []
    for m in missing:
        problems.append(f"未注册（文件在磁盘上但清单里没有，永不会跑）: tests/{m}.py")
    for m in ghost:
        problems.append(f"幽灵注册（清单里有但磁盘上没这个文件）: tests/{m}.py")
    for m in duplicate_registrations():
        problems.append(f"重复注册（同一模块出现多次，会跑两遍且 Ran 数虚高）: tests/{m}.py")

    suite = build_suite(problems)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if problems:
        print("\n" + "=" * 70)
        print("清单与磁盘不一致 / 模块无法导入（这些不是 SKIP，是没数进去）：")
        for p in problems:
            print("  ✗ " + p)
    sys.exit(0 if (result.wasSuccessful() and not problems) else 1)
