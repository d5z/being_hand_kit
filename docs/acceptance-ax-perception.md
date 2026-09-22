# AX 感知层验收记录 — hand 0.7.0（a11y v2 默认）

日期：2026-09-21
验收人：Alice（触手 sub_3a2ced15，PRD 82e4611 执行）
PRD：`docs/prd-ax-perception.md`
实现 commits：S1 `27a9405` / S2 `81d533f` / S3 `713dd4c` / S5 `d0456e1` / S4 `a5d6748` /
S6 `29dc7ef` / S7 `7f34223`

## 验收项与结果

| # | 验收项（PRD 验收标准） | 方法 | 结果 |
|---|------------------------|------|------|
| 1 | 全测试绿（a11y 序列化单测 / see 集成 / profile flags） | `python3 tests/run_tests.py` | ✅ **232 tests OK**（0.7.0 新增 115 例：ax_tree 34 / ax_see 23 / chrome_profile 16 / macos_discovery 6 / kit_quickfixes 13 / release_070 15 / receipt_contract 新增 9） |
| 2 | dogfood `see(kind=a11y)` 实跑，树结构与实验快照一致 | 真机 Chrome 9222，beings.town + github.com/d5z/being_hand_kit | ✅ beings.town 157 行 / 6129 字节 / verified；github 487 行 / 17895 字节 / verified。**序列化保真**用实验原始 AX payload 重放：归一化后与 `github_snapshot_v2.txt` 完全一致（单测 `TestFixtureFidelity`）。实跑与 17:20 快照的差异全部是页面内容漂移（实验后又提交了 commit、相对时间、语言占比 98.1%→98.2%） |
| 3 | `see(kind=interactive)` 仍可用（兼容逃生口） | 真机 | ✅ `method=cdp_interactive count=129 verified=true`；`kind=dom` 亦可用（chars=955） |
| 4 | spawn 后 `ps` 核 `--user-data-dir` 在 flags 里（F7 四步协议） | `ensure_chrome()` 真路径，临时端口 9333（不碰实验浏览器） | ✅ spawn 0.50s 端点应答；`ps` argv 含 `--user-data-dir=/home/alice/Hand/kit/.chrome-profile` 与 `--headless`；kill 后目录保留（含 `Default/`）→ 第 5 步「profile 续用而非静默重建」 |
| 5 | `[idx]` 句柄 click 端到端（beings.town 点真实链接） | `route_do("[68]")` | ✅ 回执 verified=true，element=`link "下载 Portal Desktop →"`，box=(135.5,299.6,118,16)，dispatched=[136,300]；URL `beings.town/` → `github.com/d5z/portal-desktop/releases/tag/v0.1.4`（真实导航发生） |
| 6 | 同页面两次 see 输出字节一致（确定性） | 连续两次 `route_see(kind=a11y)` | ✅ beings.town：bytes_equal=true / sha_equal=true；github：bytes_equal=true。跨进程确定性另有单测（PYTHONHASHSEED 0/1/12345 三进程输出一致） |

### 附加现场证据

- `see(kind=a11y)` 在 github 上命中实验报告的已知盲区并给出提示：
  `hint: button "Additional navigation options" [25] opens a collapsed menu (hasPopup) — click [25] then see again`。
  点开 [25] 后树从 487 行变 492 行（菜单内容出现）——两步策略有效。
- 延迟：beings.town `see(kind=a11y)` 2.76s（含首次导航后的渲染等待）；github 单独 see 0.21s。
- `open` 回执：`evidence.level=navigate_confirmed`（活文档命中目标 host）。

## 与 PRD 的偏差（如实记录，非静默改设计）

1. **STATE_PROPS 由 set 改有序 tuple**（S1）：实验原型用 set 迭代序输出状态，str set 序随
   `PYTHONHASHSEED` 变化 → 会静默破坏 PRD 要求的「同页面两次序列化字节一致」。这是修原型
   的潜在 bug，不是改设计。
2. **坐标是物理像素**（S1）：实验原型返回 `getBoxModel` 的 CSS px（静态测量工具够用）；
   生产层按 hand 全局坐标契约乘以 dpr 存物理像素（`coords_space=physical`）。已在模块
   docstring 标注。
3. **StaticText curation 收紧**（S1）：空名 与 与最近祖先行同名（忽略空白差异）的 StaticText
   都不占行（仍消耗 idx）。原型保留了空名的那些；磁盘上的 `github_snapshot_v2.txt` 更早，
   连「重名」都保留了。差异是噪音减少，已在 docstring 与 CHANGELOG 写明。
4. **level 只对 heading 有意义**（S1）：按 PRD curation 规则实现，因此与磁盘快照里
   `listitem "" (h1)` 的旧输出不同（PRD 明确要求修这个）。
5. **`verified`/`evidence` 由 router 统一给**（S2/S3）：`ax_snapshot()` 只报天然证据，
   回执外壳走 `hand.router._with_receipt`（PRD S3「新眼睛过同一把尺」= 同一个尺子实现）。
   因此 S1 提交里的两例测试在 S3 提交中改写（断言天然字段，不再断言自带 verified）。
6. **`kind="dom"` 成为显式通道**（S2）：a11y 上默认后，`kind=dom` 不能再靠「链首恰好是 dom」
   生效；同时它不再在无浏览器时静默回落 vision_ocr，而是返回带 reason 的 error 回执
   （与 kind=network/interactive 的显式通道口径一致）。
7. **F15 采用「按路径分标」而非删 fast 路径**（S7）：MCP `cdp_type`=append（insertText at
   focus），内部 `fast=True` 路径=整值 replace（构造上幂等、无 MCP 调用方），manifest 新增
   `idempotency_note` 写明。idempotency enum 未变，schema 变更仍留 6.12.0 观察（与台账原计划
   一致）。
8. **`requests` 进 requirements**（S6）：hand 全库只 import websocket（已补声明），
   `requests` 按 PRD/Cotton 报告补上并在文件里注明「hand 自身只用 urllib，严格安装可删」。
9. **两个既有测试改为显式钉住 a11y 失败**（S2）：开发机 9222 上有活 Chrome（实验遗留），
   否则 `route_see(place=browser)` 会真的走 a11y 后端，测试结果由环境决定。改为
   `ax_snapshot` side_effect 失败，让 DOM 降级路径成为被测对象。
10. **S4/S5 拆成两个 commit**（PRD 原文是「F7/F8 物理基础并批」）：为了「每块一个 commit」的
    交付要求，S5（macOS 发现层）先提交、S4（profile 策略）后提交，各自测试独立成文件。

## 边界（本次未做，按任务硬约束）

- 未 `git push`；未跑 `kit/sync.sh` 部署；未做 Grove 发布（S7 的 release note 已写好待发）。
- 未动 `experiments/` 下任何实验数据（仅读取 `github_ax.json` 做保真回归测试，测试在文件缺失时
  自动 skip）。
- 未做 F14（dispatch→effect 验证）、code mode/getByRole、F4/F5 —— PRD 明列为 0.8+ 非目标。
- `mcp` 2.x 适配未做（F9 只 pin，止血）。

## 运行时副作用（需知）

- 本机验证时创建了 `kit/.chrome-profile/`（isolated profile，运行时状态，已 gitignore；
  Cotton 协议第 5 步要求保留，故未删）。
- 验证用的临时 Chrome（端口 9333）已 kill；实验遗留的 9222 Chrome 未动（它现在停在
  github.com/d5z/being_hand_kit）。

## Field Notes（发布后现场观察）

1. **语义稀疏页的 a11y 边界（taojun 1123，Windows/D5 Launcher）**：自绘 UI（D5 Launcher
   自绘页）的 a11y 树几乎全是 `generic ""`——a11y 默认的收益强依赖页面语义质量，语义稀疏页
   dom 快照反而更有用。与 90 trials 的静态页/SPA 样本正好互补，是 a11y-default 决策的边界
   条件，也是 kind=dom escape hatch 存在的现场理由。0.9 设计输入：是否值得做语义稀疏检测
   （如 generic 占比阈值）并在回执里建议切换 kind。
