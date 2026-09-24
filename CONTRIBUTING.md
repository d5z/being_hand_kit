# Contributing

hand 的反馈与迭代入口在 Beings Town 围炉 #34（hand 炉）。修 bug / 提 PR 前先看 `docs/feedback-ledger.md` 里已登记的 F 编号，避免重复。

## PR 规范

### 1. 测试全绿

`python3 tests/run_tests.py` 必须全绿。新增功能配套新增测试。

### 2. 改编译产物源码的 PR（重要）

如果你改了带编译产物的源码（当前唯一一例：`hand/perception/vision_ocr.swift` → `vision_ocr_bin`），**必须二选一**：

- **配套提交重编后的 bin**（macOS：`swiftc -o hand/perception/vision_ocr_bin hand/perception/vision_ocr.swift`），或
- **在 PR 描述里显式声明「bin 需发布时重编」**，让维护者知道。

背景（F18 / Judy 1166-1172）：改源码不重编 bin，运行时走旧逻辑，Python 端 old-format fallback 静默接住旧输出——bounds 丢失无声。发布侧与 PR 侧两边都默认「对方会处理」时，静默降级就发生。0.8.3 曾中招（macOS adopter）。

### 3. 回执契约

hand 的核心原则：**降级必可见，可见在回执里**。任何 fallback / 截断 / 降级路径，警告必须进返回值（`warning` 字段），不能只进 stderr——kit 场景 stderr 只进日志，不进 being 的回执视野。

### 4. 提交信息格式

`type(scope): summary`，例：`fix(perception): vision_ocr stale bin detection`。

## 方法论：存在过 ≠ 发生过

排查 kit 问题时按证据强度分级：

1. **静态产物只当线索。** exe 里的字符串、文件 mtime、日志文案、记忆里的结论，都只证明「存在过」，不证明「这条路径会发生」。用字符串/静态产物推断行为（如从 exe 文案断言某个分支会走），必须补一次行为实验才算证据；未补前，结论标注为「线索」。
2. **升格靠行为实验。** 构造最小触发条件，观察实际行为：克隆同名 kit 目录看 conflicts 是否触发、跑一张真实 UI 图看 OCR 输出格式。有行为实验支撑的结论才可写进文档定稿。阴性结果不能单独当反证，除非同批带正对照。
3. **静态检查有盲区。** 「检查全绿」≠「产物正确」：mtime 比对（bin > 源码）对「从过期 checkout 编译」的形态是盲的（vision-ocr 案例，见 `docs/feedback-ledger.md`）；发布链路的最终护栏是运行时冒烟断言（`tests/test_bin_smoke.py`）。该断言的失败形态已于 2026-09-22 在 PR #3 验证链中观察过一次：已知坏的旧 bin（f4d02b0 版 `vision_ocr_bin`）跑 test_bin_smoke 当场红（`AssertionError: 1 not greater than or equal to 6: line not in tab format`），红在正确位置、非静默绿。该样本来自刻意构造的负对照；野外拦截样本出现时可追加。
4. **引用先对原文。** 转述台账编号、他人结论、日志行之前先读一手原文；记忆与证据冲突时，以证据为准。

## macOS adopter 自检（0.8.3 已知问题）

0.8.3 的 `vision_ocr_bin` 是旧源码编译（bounds 输出缺 tab 分隔坐标）。自检方法：

```bash
./hand/perception/vision_ocr_bin <任意截图路径>
```

- 输出含 **tab 分隔的坐标**（`0.95\ttext`）→ 新 bin，bounds 可用
- 输出是**单冒号格式**（`0.95:text`）→ 旧 bin，bounds 不可用，重跑 `swiftc -o hand/perception/vision_ocr_bin hand/perception/vision_ocr.swift`

0.9 起代码内建 stale 检测（fallback 触发时回执带 `warning` 字段）。0.9.1 起仓库自带运行时冒烟护栏（`tests/test_bin_smoke.py`，含 fixture 图）：macOS 上 `python3 tests/test_bin_smoke.py` 一条命令完成上述自检——mtime 检查对「stale-checkout 编译」（bin 从过期源码编出、mtime 却比源码新）是盲的，运行时格式断言不会说谎（PR #3 案例）。


## Windows adopter 自检（升级/手改 manifest 坑族）

Windows 上升级 kit 或手改 manifest 后，几类坑的症状都是 `Kit 'xxx' has no loadable manifest`（或 kit 不加载），且报错不带原因。逐项自检：

### 0. 先看日志，分型再动手

引擎每 5s 扫描一轮 `kits\`，所有 loader WARN 都在：`%APPDATA%\portal-desktop\portal-service\<service-id>\portal.log`（`<service-id>` 取最新修改的子目录；`portal.log.previous` 为上一轮滚动）。三种 WARN 对应三类坑：

```
Skipping kit manifest <path>: Parsing kit manifest <path>        ← 解析失败（坑 1 BOM / JSON 语法 / 字段风格不符）
Kit 'xxx' conflicts with another kit name or tool route; ...     ← 同名/路由冲突（坑 2）
kit 'xxx' command binary not found                               ← 命令找不到（坑 3）
```

（「Parsing」不区分语法错误与 schema 不匹配——JSON 合法但字段风格不对（如 tools 写成 MCP `inputSchema` 风格而非 `params` 风格）同样落在这条 WARN 里。第三种签名是启动期 manager 级 WARN，与前两种 loader 级不同层——同族还有 `Kit 'xxx' failed to start: ...` 变体，同在一份日志里。）

### 1. manifest.json 带 BOM（F21）

Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 与旧版记事本默认写出带 BOM 的 UTF8，serde_json 拒收。

诊断（头三字节 `EF BB BF` = 有 BOM）：

```powershell
[System.IO.File]::ReadAllBytes("$PWD\manifest.json")[0..2]
```

修复（ReadAllText 自动剥 BOM，无 BOM 写回）：

```powershell
$p = "$PWD\manifest.json"
$raw = [System.IO.File]::ReadAllText($p)
[System.IO.File]::WriteAllText($p, $raw, (New-Object System.Text.UTF8Encoding($false)))
```

预防：PS 5.1 写 manifest 一律 `[IO.File]::WriteAllText` + `UTF8Encoding($false)`（`-Encoding utf8NoBOM` 是 PS 6+ 才有）；VS Code 用「通过编码保存 → UTF-8（无 BOM）」。

### 2. kits\ 下同名目录冲突（F17/F18）

`kits\` 下任何与 kit 同名（含同名前缀）的目录都会被 scanner 扫到：manifest 解析失败只 WARN Skipping、不影响本尊；**manifest 完整且 name 相同则触发防劫持冲突**——日志每轮报 conflicts，且该 kit 定向 reload 失败（`no loadable manifest`），删除同名目录后立即恢复。

（Windows 0.8.3 实测 2026-09-22：同名完整 kit 单独致死；`kit-retired\`、`kit-archive\` 不在 scan 面，留那里不碍事。Linux 侧 kit-retired 同结论，kit-archive 未测。）

预防：备份目录别放 `kits\` 里，挪去 scan 路径外（如 `~/.heart-portal-backups/`）。

### 3. 裸 `bash` 解析为 `kits\hand\bash`（F20）

引擎按防劫持设计不回落宿主 PATH：Windows 上 manifest command 写裸 `bash` 会落到 `kits\hand\bash` → not found。workaround：command 写绝对路径，如 `C:/Program Files/Git/usr/bin/bash.exe`。

> 三坑根修都在 portal repo（冲突剔除报详情 / 读 manifest 剥 BOM / per-platform command），随 F17/F18 已转 sw。修复落地前，以上 workaround 是现行做法。

## 委托 brief 自包含契约（0.9.3）

把任务委托给 subagent（heart 原生 `portal_subagent_spawn`）时，brief 是它看到的**全部**世界——它看不到你的上下文、你的记忆、你刚跑过的命令。三条必含，缺一即踩坑：

1. **仓库路径**——绝对路径，不是「hand 仓库」这种指称。subagent 没有你的文件记忆，`cd hand` 对它是一句空话。（0.7 实测：subagent 猜了 `/root/hand`，`cd` 失败后静默换目录继续，产出物落错地方才发现。）
2. **验证命令**——怎么算「done」的命令行形态。不写，它会自己猜一个看起来合理的（0.7 实测：猜了不存在的 `python -m pytest`，卡半小时）。
3. **回执判读法**——产出物在哪、成功长什么样、失败长什么样。subagent 的 result 只回一段文本，你得告诉它把什么放进那段文本里你才接得住。

模板：

```
任务：<一句话>
仓库：/home/alice/Hand（绝对路径）
验证：cd /home/alice/Hand && python3 -m unittest tests.test_xxx -v
完成回执：贴出验证命令的 tail -5 + 改动文件列表（git status --short）
不要做：<边界——不 push、不改版本号、不动 manifest 等>
```

「不要做」一行是第四件可选件，但强烈建议：subagent 对边界的默认假设和你不一样，写出来比它猜出来便宜。

## 验收 SOP：四层验收 + fixture 自证（0.9.4）

一个修复「做完了」的判据不是测试绿——测试绿只证明源码对，不证明部署对、不证明世界真的变了。四层验收，一层都不能跳：

1. **测试绿**（源码层）——`python3 tests/run_tests.py` 全绿，新修复有对应测试模块且已注册进 `MODULES`。
2. **sync + 冒烟**（部署层）——`./kit/sync.sh` 后 `hand_health` 活着。测试绿 ≠ 部署对：源码和运行中的进程是两个存在物（0.9.1 的 stale bin 教训）。
3. **实况回归**（世界层）——在真实站点跑一遍触发原始 bug 的动作序列。fixture 复现的是「我们理解的 bug」，真实世界还会还你 fixture 想不到的边界（0.9.4 的 P5 就是 P4 实况回归时发现的：回执 ok 但 URL 没变）。
4. **回执字段核对**（契约层）——新加的 evidence 字段在实况回执里真的出现（`nav_id_at_action`、`click_point.how`、`redirected`……），且 `kit/mcp_server.py` 的工具描述同步更新。

**fixture 自证**：测试 fixture 必须先证明危险条件真的成立（导航确已发生 / 中心点确实不落在目标上），再证明修复有效。不自证危险的测试可能整个在测一个不存在的前提。控制实验（control experiment）先于修复验证——「旧路径靠巧合工作、新路径不靠巧合」要能被测试区分。

**行为证明优先于回执自证**：修复有效的证据是「链接的 click handler 真的触发了 / URL 真的变了」，不是「回执说 ok」。回执说 ok 验证的是输入侧（焦点、几何），行为验证的才是结果侧。

**绿的数量要带环境注脚（0.9.4）**：live 子类测试（需要真 Chrome 的）在无 Chrome 的机器上会 skip——同一份 `run_tests.py`，有 Chrome 的机器上 415 是含 live 的数，无 Chrome 的机器上是 L2-only 的数。回执里报「N 全绿」时注明 live 是否跑过（unittest 有 skip 会标 `(skipped=N)`，看回执末行）。L2 绿证明代码发对了调用，不证明世界接住了——第二层不跑，覆盖就是假的（axiang 的「绿是真的、覆盖是假的」样本）。
