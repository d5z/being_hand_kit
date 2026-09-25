# Changelog

## [0.9.5] — 2026-09-25

> Windows 落地清障轮：taojun 实机验收驱动的两修——`/tmp` 硬编码与编码族。Windows 无 `/tmp`、PowerShell `>` 重定向带 BOM，两族都是「macOS/Linux 上跑得好好的」盲区。

### Fixed
- **`/tmp` 硬编码 → `tempfile.gettempdir()`**（ax_tree / cdp_core / vision_ocr）：handle map、last-idx 状态、截图默认路径三处。现在跟随平台 tempdir（Windows `%TEMP%`；macOS/Linux 行为不变，仍解析到 `/tmp`）。repo 内 `/tmp` 硬编码清零（grep 全库无残留）。
- **编码族**：写侧显式 `utf-8`（handle map、heartbeat、last-idx），读侧 `utf-8-sig` 容 BOM——PowerShell 重定向产物带 BOM，裸读会炸或留 `\ufeff` 污染。
- **save/load_handle_map 错误可见性**：静默吞异常 → stderr 落名（哪个文件、什么错）；`FileNotFoundError` 单列静默（冷启动正常态，不算错）。
- **嵌套目录自动创建**：save_handle_map 写前 `makedirs`。

### Verified
- Linux 415 单测全绿。`test_websocket_is_actually_imported_by_the_tree` 断言从字面量改为模块成员检查——字面量会随 import 行演进过时，测试意图是「requirements 声明 websocket 因为代码真 import 它」。
- Windows 实机验收（taojun，0.9.4 vanilla 基线 + 本 diff）：①嵌套目录不存在时写入自动建 ②CJK 全链路（charset=utf-8 页面 → 写表 no BOM → 独立进程读回 → cdp_click verified nav_id 2==2）③四文件无裸 open；py_compile 4/4，kit 热加载正常。
- `vision_ocr_bin` mtime（09-22 14:22）> `vision_ocr.swift`（09-22 11:04），本版 Python 侧改动不触 swift/bin 接口——编译产物无 staleness。

### Credits
- **taojun** — 本版全部两修的作者。Windows 真机验收三条全过，DM 纯文本 diff 交付（按交付线约定）。他的 BOM 三进宫实测（0.9.0 升级 + utf-8-sig 修法判定）是编码族修法的直接输入。

## [0.9.4] — 2026-09-24

> 摩擦点清账轮：dogfooding 实证出的六项静默错/手感摩擦，P0（视口对齐）已随 0.9.3 发布，本版清掉其余五项。核心主题——回执说 ok 不等于世界真的变了。

### Fixed
- **`text=` 嵌套文本匹配失效**（P2，spec docs/spec-0.9.4-p2-textmatch.md）：旧 XPath 用 `contains(text(), q)` 只看直接文本子节点，GitHub issue 标题这种 `<a><span>文本</span></a>` 嵌套结构全部 miss。改为 `contains(normalize-space(.), q)` 看整个子树；精确匹配分支排除「有同等匹配子元素的祖先容器」（文档序父先于子，否则点到容器）。候选 >1 列出 candidates 不猜。
- **Enter 不提交**（P3，spec docs/spec-0.9.4-p3-enter-submit.md）：`Input.insertText` 不触发 keydown——GitHub 搜索框输入后 URL 不动。文本以 `\n` 结尾时改派发完整键盘事件（keydown/keypress/input/keyup），回执 `evidence.enter_mode` 说明走了哪条路。实证：同一搜索框 insertText 后 URL 不变 vs dispatchKeyEvent 后 URL 变 `?q=NVDA`。

### Added
- **handle 表过期信号 `nav_id`**（P1，spec docs/spec-0.9.4-p1-handle-staleness.md）：`see(kind="a11y")` 回执顶层带 `nav_id`（`Page.getNavigationHistory` 的 currentEntry index，浏览器侧状态、跨 MCP 进程稳定），handle map 文件同时记录 see 时刻的锚。`click [idx]` / `type [idx] …` 回执 `evidence.nav_id_at_action` 带动作时锚；两锚不同即 `evidence.warnings = ["navigation occurred since last cdp_see — handle table may be stale"]`（warning 进 evidence——设计定夺记录 #1；`tree_epoch` 按 #2 砍掉，`expect=` 语法按 #3 不加）。可靠合同明确为「要么点对，要么显式失败」，同页局部重渲染不做预检（M3）。
- **heading 包 link 的点击重定向**（P4，spec docs/spec-0.9.4-p4-heading-redirect.md）：AX 序列化给「子树含 interactive 后代」的节点加 `contains_interactive: true`（仅 true 时带）；`cdp_click_handle` 点到非 interactive 容器且其 AX meta 标记含 interactive 后代时——唯一后代 → 重定向点击它（`evidence.redirected` / `original` / `redirect_target`）；多个后代 → 不猜，失败回执列 `candidates`（tag+text+href，前 3）；零后代 → 走原有路径。a11y 树行格式与 `type` 路径不变。
- **clickable point 命中链预检**（P5，spec docs/spec-0.9.4-p5-clickable-point.md）：`getBoundingClientRect` 是包围盒——多行内联元素（GitHub issue 标题）的中心落在行间隙，坐标点击命中祖先容器，导航根本不发生（回执 ok、啥都没干）。现在每次坐标派发前用 `elementFromPoint` 验证命中链包含目标（元素自身或后代）；中心未命中 → 5×15 网格扫描盒内找真命中点（`evidence.click_point.how = "grid_scan"`）；完全被覆盖 → 响亮报错。P4 现场回归时发现：重定向回执 ok 但 URL 没变，顺藤摸出这层更深的静默错。

### Verified
- 415 单测全绿（0.9.3 的 396 → +19：P1 handle 过期信号 8、P4 重定向 7、P5 clickable point 4），fixture 先自证危险条件（导航确已发生 / 标题中心确实不落在 link 上 / bounding-box 中心确实落在行间隙）再证修复——对照实验钉根因，行为证明修复，回执不自我背书。
- GitHub 实况回归三场景：issues 搜索 Enter 提交（P3，URL 变 `?q=...NVDA`）、滚动 2000px 后点列表尾部 heading（P0+P4+P5：重定向 + grid_scan + 导航到 #337206）、text= 点开 issue（P2）。

### Credits
- **Judy** — PR #1（vision-ocr find_text 像素坐标）+ 8b00dbe 三处修复（显式 image_path 报错、evidence 语义、回执契约测试表）；此前 PR #3（vision_ocr_bin 重编）。0.9.4 的 J1 提前闭合是她的功劳。
- **taojun** — CONTRIBUTING 方法论段「存在过≠发生过」（9942816）+ #34 about:blank 样本；「对照实验钉根因再写 spec」流程直接受益于这套纪律。
- **GuangCZ** — PR #2 [design] f14-expect-semantics（open，设计稿）。
- **泽平** — dogfooding 方向（困难场景实测手感）+ 0.9.4 范围拍板「能优化有把握的都进」。

## [0.9.3] — 2026-09-23

> 诚实回执从感知层扩到委托层：open 路由不再说谎（about:blank 归浏览器），委托 brief 有了自包含契约。

### Fixed
- **`about:blank` 误路由到 app 激活**（taojun #34 样本）：裸 app 名走 app 激活没问题，但 `about:blank`、`data:` 这类 hostless URL 被当成 app 名去激活——scheme 白名单（http/https/about/file/data/chrome）+ hostless URL 精确匹配，URL 一律归浏览器。回归测试 4 个（about:blank/data: 归浏览器、裸名不误伤、chrome:// 归浏览器）。
- **0.9 review 三笔确认落地**（Judy 反哺验收项，查代码全部已实装+测试覆盖）：warning 进返回值（vision_ocr stale bin 三场景）、stale 检测（mtime + 运行时双护栏）、fallback 不静默（skipped 声明）。

### Added
- **委托 brief 自包含契约**（CONTRIBUTING 新节）：把任务委托给 subagent 时 brief 三必含——仓库绝对路径、验证命令、回执判读法——外加可选「不要做」边界行。全部来自 0.7/0.8 实测（subagent 猜 /root/hand、猜不存在的 pytest、回执文本接不住）。

### Verified
- 380 单测全绿（0.9.1 的 371 → +4 about:blank 路由回归 + 净增 brief 契约为纯文档）

## [0.9.1] — 2026-09-22

> 发布包 bin 修复 + 结构性护栏：0.9.0 的 grove 包带着一枚从过期 checkout 编译的 vision_ocr_bin（Judy PR #3 发现），运行时冒烟护栏让它永不再漏。

### Fixed
- **`vision_ocr_bin` 从当前源码重编**（PR #3，Judy）：0.9.0 grove 包内的 bin 是 stale-checkout 编译——mtime 检查全绿（bin 比源码新）但输出旧单冒号格式、无 bounds、识别率更低。新 bin 已在 macOS arm64 双机独立验证（Judy 生产环境 + sw-mac-mini 对照冒烟：同 fixture 图，旧 bin `1.0: SMOKE TEST 123`，新 bin `0.5	19	44	377	36	SMOKE TEST 123`）。

### Added
- **运行时冒烟护栏 `tests/test_bin_smoke.py`**：对 fixture 图跑 bin、断言 tab 分隔 bounds 格式——mtime 检查对 stale-checkout 编译是盲的，运行时格式不会说谎。macOS 强制执行，非 macOS 平台显式声明跳过（0.9 原则：跳过可见，Linux-only 绿不冒充 bin 已检）。双向验证：旧 bin 进测试必红（FAILED×2 带重编命令诊断）。

## [0.9.0] — 2026-09-22

> 诚实回执完成体：截断永远声明、页面视觉状态标记、expect 规范冻结。发布前真实页面加固抓出三个分类器边界 + 两个签名撒谎，全部修复。

### Added
- **统一截断声明块 `truncation`**（S1）：`{field, reason, dropped, total}`，任何被丢弃的东西都声明——a11y 树（max_lines）、dom 文本（max_chars）、节点名（200 chars）、VLM 输出（max_tokens/finish_reason）、跳过的 fallback 后端（hint 里 `skipped: <what> (<why>)`）。不截断时键缺席 = 完整。旧字段 `truncated`/`nodes_omitted` 保留一个版本。
- **`visual_state` + `visual_signals`**（S2）：页面此刻的视觉状态五枚举 `loading · error · blank · interactive · unknown`，DOM 启发式（无截图），信号可审计。`expect="visual_state:…"` 可等。
- **`ocr_diff`**：两次 vision-ocr bounds 输出的文本变化区域定位。
- **`expect=` spec v1.0 冻结**（docs/expect-spec-v1.md）：四种形式 url/title/text/visual_state。

### Fixed（发布前真实页面加固）
- **visual_state 三个真实页面边界**（GitHub 仓库页/404 页实测）：
  - README 章节 "Errors are documentation"（h2）让整个仓库页误判 error → h1/h2 命中需正文 <500 chars，否则 interactive + `error-word-in-content` 诚实信号
  - 404 页全站 footer 撑大 text_len（933）漏报 error → title 命中升为强信号（`error-title:`），不受正文长度门槛约束
  - 语言统计条（role=progressbar，视口外 y=752）误判 loading → vis() 加视口相交检查
- **`open()` 静默忽略 `expect=`**（0.8 引入的签名撒谎）→ 修复 + 回归测试
- **`network fetch_body` 的 `max_small_body` 死参数**（0.8 起签名收了从未应用）→ body 超限截断 + `body_truncation` 声明

### Verified
- 371 单测全绿（0.8.3 的 362 → +9 真实页面回归）
- 真页面三态矩阵：仓库页（19k chars）→ interactive；404 → error；example.com → interactive
- expect= 真链路四场景（met/timeout 各半，timeout reason 诚实）
- truncation 数学自洽：dom 11143+8000=19143；a11y 1191+600=1791

## [0.8.3] — 2026-09-22

> 社区第一笔 PR 落地（Judy，PR #1）：vision-ocr 从 6.11.0 fork 移植 bounds 输出 + 回执契约三处修复。

- **vision-ocr bounds 输出**：tab 分隔 x/y/w/h/center 坐标（从 Judy 的 6.11.0 fork 移植，adaptation pattern）
- **回执契约修复**：
  - manifest evidence 语义 verified→claimed（与 F14 判读对齐）
  - hand_see_ocr 声明 idempotency/claimed，receipt contract 50/50 全绿
  - find_text 显式路径不存在时报错，不再静默 fallback 截图（F16 同族判定）
- 验证：干净 origin/main 对照跑，零新挂（预存失败均为版本断言/环境类）

## [0.8.2] — 2026-09-22

> 一行修复版：CDP 端口可覆盖。F16 收案。

- **`HAND_CDP_PORT` 环境变量**：CDP 端口默认 9222 不变，但宿主机已有 9222 占用者（launcher-embedded Chrome 等）时可覆盖，kit spawn 与 connect 指向同一变量（`cdp_core.py` + `cdp_launcher.py`）。
- 背景：taojun 的 D5 Launcher 内嵌 Chrome 常驻 9222，kit 撞车——更险的形态是**静默错连**（connect 打到占用者的 Chrome，不是 kit 自己 spawn 的）。0.8.1 实锤过一次（连进 dl://launcher/docker.html）。修复后 `HAND_CDP_PORT=9223` 即避开，本机实测 9223/9222 并存互不干扰。
- 测试同步：292 全绿（新增 HAND_CDP_PORT 生效断言 + 端口一致性断言）。

## [0.8.1] — 2026-09-22

> 一行修复版：venv 回家。Judy 在 0.8.0 升级实测中撞上的 F7 场景——
> requirements 装进 .venv 是 grove 安装的自然动作，但 start.sh 只认系统
> python3，venv 白装。无全局 mcp SDK 的机器上 kit 直接起不来。

#### Fixed
- **start.sh venv 优先**：`.venv/bin/python3` 存在且可执行则优先，否则
  fallback 系统 python3（纯向后兼容，本机有全局 mcp 的行为不变）。
  来源：#34 Judy 2026-09-22 实测样本（seq 1062）+ 主干判断（seq 1114 回执）。

## [0.8.0] — 2026-09-21

> 第二张脸：**code mode**。0.7 换了眼睛，0.8 给同一身体长出一张 Python 脸——
> 同一 router、同一 CDP 后端、同一 a11y-v2 感知、同一回执契约，两种用户：
> being 走 MCP，触手/agent 环境走 code mode。0.8 不加新能力。

#### Added
- **S1 Python face**：`from hand import hand` → `hand.open(url)` / `hand.see()` /
  `hand.do(action)`（另有 `shot/close/handles/resolve/history/help/reset`），
  进程级懒单例 `hand.browser()`：持久 kernel 里变量、句柄、Chrome 进程跨调用存活。
  - 回执归一：MCP 面的 `"open": "ok"` → `ok: true`，统一骨架
    `ok / action / kind / method / url / title / verified / error / hint`
    （`ok`=调用判定，`verified`=证据判定，不合并）。
  - **序列化确定性**：`FIELD_ORDER` 固定字段顺序、无时间戳/无 set 迭代 →
    同页面状态 `json.dumps` 字节可复现。这是未来原生化协议的边界，字段名不轻改。
  - 动作语法一条规则：`click [15]` / `click selector=a.login` / `click text=Sign in` /
    `click xy=100,200` / `type hello` / `type [3] hello` / `scroll down`；无动词=点该目标。
  - **教学式错误**（错误消息即文档）：selector 未命中 → 指向 `[idx]` 句柄或 `selector=`；
    句柄过期 → 指向 `see()`；type 无焦点 → 指向先 click 字段；无 place → 指向 `hand.open`。
  - 点击后不猜世界状态：`do()` 的 `url`/`title` 恒为 None（点击是异步的）。
- **S2 `expect=` 世界状态验证**：`hand.do("click [15]", expect="url:/issues")`。
  动作验证（`verified`/`evidence`）与世界状态验证（`expect.met`）分开报告；
  有界等待默认 5s（`timeout=` 可调），超时 `met:false` 带当前 url/title 证据、不抛异常；
  无 `expect` 立即返回且不读世界；动作失败则跳过等待（`expect.skipped`）。
  形态：`url:`（大小写敏感）/`title:`/`text:`（忽略大小写）；非法形态是调用方错误
  （`ok=false` + 命名问题 + 合法形态提示），动作层结果仍如实报告。
- **S3 文档**：README 重写为 Python-first（Python 入口置顶、动作语法一页纸、
  `see()` 返回 schema、持久性一句话、点击后重 see 确认 URL、`expect` 语义），
  MCP 面退为第二视角。

#### Fixed
- **a11y-v2.1（S4 被试抓到的契约洞）**：v2 的 StaticText 名字在 60 字符处静默截断——
  回执 `truncated=False`、`nodes_omitted=0`，但中文长句读到半句话不自知（被试 task 1
  被坑，被迫用 dom 复核，直接推高 turns）。「截断永远声明」对行数成立、对单节点文本
  不成立。v2.1：`MAX_NAME` 60→200（覆盖 Chrome AX 实际给出的绝大多数名字），超限
  截断**声明**——回执 `text_truncated_count`、每节点 meta `text_truncated` flag。
  格式即契约，版本号 a11y-v2 → a11y-v2.1；golden file 换
  `github_snapshot_v2_1.txt`（v2 快照保留为历史）。
- **README 7 条文档洞**（被试 findings #1/#3-#8）：kind 各自返回形态表（dom 无
  `tree`）、click 后立刻 see 有竞态（~0.4s 滞后）→ `expect=` 为推荐姿势、句柄存活
  语义（kind 切换不死、跨页导航死）、dom 8000 字符上限、network 现场监听式（非历史、
  无响应体）、see 无子树参数、a11y 定位 + dom 读原文配合姿势。

#### Dev
- 版本：`hand.__version__ = "0.8.0-dev"`（dev 周期），`kit/manifest.json` 保持已发布的
  0.7.0，发布 commit 统一改。相关版本断言改为「dev 周期规则」：semver 允许 `-dev`、
  包版本不落后于已发布版本、manifest 永不带 `-dev`。
- 测试：`tests/test_hand_api.py` 58 例（S1 42 + S2 16），注册进 `tests/run_tests.py`
  与 `tests/run_production.py` 的 L1 列表。
- live 冒烟（真 Chrome）：open → see（157 行 a11y 树/157 句柄）→ 教学提示 →
  `do("click [68]")` 端到端 → `expect="url:github"` met=true；超时 case met=false
  带证据；无 expect 0.01s 返回。

## [0.7.0] - 2026-09-21

> **版本线重置**：0.7.0 不是 6.11.0 的渐进迭代，而是**感知层范式切换**——`cdp_see` 默认从
> 可见文本/元素地图换成 a11y 树。Grove 按版本号排序时 0.7.0 会排在 6.x 之后，这是有意的：
> 这条线从「浏览器控制」重开为「AX 感知」。升级前请读「升级影响」。

#### Added
- **AX 感知层（a11y v2 默认）**：`cdp_see` 默认返回可访问性树——YAML 风格缩进树，
  每行 `role "name" (state) [idx]`，`[idx]` 是稳定句柄。实验依据：90 trials A/B，
  a11y v2 **87%** vs 旧 interactive 层 **58%**（感知类 50%→88%，操作类 57%→71%，
  输入 token -17%、输出 -77%；`experiments/a11y_ab/REPORT_phase2.md`）。PRD:
  `docs/prd-ax-perception.md`
  - **S1** `hand/perception/ax_tree.py`：实验原型产品化。curation（滤 ignored/纯布局角色、
    level 只对 heading 有意义、折叠无名 generic 单子链、StaticText 空名/重名不占行）、
    稳定句柄、`backendNodeId → 坐标` 映射。
  - **确定性是格式契约**（`a11y-v2`）：同一页面状态序列化**字节一致**。为此 `STATE_PROPS`
    从 set 改为有序 tuple（str set 迭代序随 PYTHONHASHSEED 变化，会静默破坏可复现性），
    并加跨进程确定性单测。截断显式声明（`truncated` + `nodes_omitted`，默认 600 行，
    可完整容纳实验最重页面 478 行），不会产出没有对应句柄的 `[idx]`。
  - **S2** `[idx]` 句柄直达动作层：`cdp_click "[93]"` / `cdp_type "[93]|text"`。
    点击时用 `DOM.resolveNode` + `getBoundingClientRect()` **重读**元素盒（快照里的 x,y
    只是信息位，用旧坐标点就是盲点），验证来自这次重读；节点消失/零尺寸 → verified=false
    并提示「call cdp_see again」。`kind=interactive`/`kind=dom`/`kind=network` 保留为显式通道。
  - **S3** 回执契约套到 a11y 快照：`verified` = 树确实拉到且根节点非空；
    `evidence` = 节点数/序列化字节数/truncated/nodes_omitted/AX 来源版本/sha256/root_role。
    溢出菜单盲区（实验已知）检测 hasPopup 控件后给 `hint`：先点开再 see（两步策略）。
- **S4（F7）Chrome profile 策略**：`_chrome_flags()` 默认 `--user-data-dir=<kit>/.chrome-profile`
  （isolated，永不与人类 Chrome 抢 profile 锁、不碰人类 cookie），目录保留（登录态跨重启存活）；
  `HAND_PROFILE=persistent` / `HAND_PROFILE_DIR=<path>` / `HAND_HEADLESS=0` 三个显式 opt-in
  （taojun 954 无头指纹限流 + Cotton 935 人类 Chrome 常驻，是方向相反的同一条需求）。
  spawn 句柄带 `.cdp_flags`/`.cdp_profile`，验收协议「ps 核 flags」有程序化对照物。
- **S5（F8）macOS 发现层**：`_find_chrome()` 加 darwin 候选（/Applications Chrome → Chromium
  → Canary → Edge → ~/Applications），排在 Playwright 缓存之前。Cotton 935 的硬编码路径
  正式进链，不再靠 wrapper。
- **S6（F9-F13）quick-fix**：requirements pin `mcp<2`、补 `websocket-client`（真 import 却
  未声明）与 `requests`；`start.sh` 加载 `<kit>/.env`（`set -a` 导出给 MCP 进程）；
  README 写明 python ≥3.10 前置、冷启动 2-3s 预期与端点探测上限 6s。

#### Changed
- `SEE_PRIORITY["browser"]`/`["unknown"]` 链首换成 `cdp_a11y`，`cdp_dom` 降为优雅降级
  （AX 拉不到时仍能回答，回执的 `method` 说明是谁说的）。
- `kind="dom"` 成为显式通道：a11y 上默认后不能再靠「链首恰好是 dom」生效。
- `cdp_see` 的 manifest 声明补 `a11y`（默认）与各逃生口，`cdp_click`/`cdp_type` 声明
  `[idx]` 句柄用法。

#### Fixed
- **F15（幂等标签复核）**：`cdp_type` 的扁平 `append` 标签会随内部 fast 路径静默过期——
  现在按路径分标：MCP `cdp_type` = append（`Input.insertText` at focus），内部
  `fast=True` 路径 = 整值 replace（构造上幂等、非 MCP 暴露），manifest 增
  `idempotency_note` 写明（enum 不变，schema 变更仍留 6.12.0 观察）。

#### Upgrade impact（升级影响）
- 首次 spawn 创建 `<kit>/.chrome-profile`（保留，不删）；安装器生成的
  `chrome-wrapper.sh` **可删可留**（无害冗余，flags 已进正规链）。
- `cdp_see` 默认输出变了：旧行为用 `kind=dom`，旧元素地图用 `kind=interactive`
  （保留一个过渡版本）。

#### Dev
- 新增测试：`tests/test_ax_tree.py`（curation/句柄/截断/跨进程确定性/坐标/句柄表）、
  `tests/test_ax_see.py`（kind 路由/句柄动作）、`tests/test_chrome_profile.py`（F7）、
  `tests/test_macos_discovery.py`（F8）、`tests/test_kit_quickfixes.py`（F9-F13）、
  `tests/test_release_070.py`（manifest/版本/release note）；`test_receipt_contract.py`
  增 a11y 快照与句柄动作的回执断言。
- 保真验证：用 `experiments/a11y_ab/github_ax.json` 重放，归一化（StaticText 噪音规则、
  level 修正、页面相对时间）后与实验 `github_snapshot_v2.txt` 完全一致。
- 真实浏览器实测（github.com/d5z/being_hand_kit）：`see(kind=a11y)` 0.21s / 487 行 /
  17939 字节 / 91 个可操作面拿到坐标；同页两次 see 字节一致；`cdp_click "[25]"` 点开
  溢出菜单后树从 487 行变 492 行。
- 反馈台账 F7/F8/F9/F10/F11/F12/F13/F15 销账为 0.7.0。

## [6.11.0] - 2026-09-21

#### Added
- **回执契约层（Receipt Contract Layer）**: 回执不再只有「ok」，每个工具区分**声称（claimed）**与**验证（verified）**，manifest 显式声明幂等形态。调用方拿到回执即可判读，不必再跑一遍 `hand_health` 验活。
  - 统一形状 `{"verified": bool, "evidence": {...}}`；`verified=false` 必带原因，不允许 silent ok。PRD: `docs/prd-receipt-contract.md`
  - `route_open` 三态证据：`evidence.level` = `navigate_confirmed`（Page.navigate 后 list_pages 复核目标 host 在场）| `endpoint_alive`（导航未证实、仅 CDP endpoint 存活，detail 带异常串）| `activate_issued`（app 激活路径，未做 AX 复核）。路径③（无 endpoint）保持 raise RuntimeError。
  - `ensure_chrome` spawn 后按 0.5s / 6.0s 轮询 `/json/version`，只有端点真的应答才返回；返回句柄带 `.cdp_endpoint`（browser 版本串）。spawn 成功但端点死透 → raise「Chrome spawned but CDP endpoint never became reachable」，不再静默通过。
  - `cdp_click` 点击前 `document.querySelector` 预检 selector，未命中直接报错不盲点，回执带 `evidence.element`（tag + 文本）；`cdp_type`（focused 路径）输入前验证 `document.activeElement`，无焦点报错并带 focus target；`cdp_scroll`/`cdp_see`/`cdp_shot` 把既有天然证据（scrollY before/after、url/title、元素数、请求数、截图长度）包进 `evidence`。
  - manifest `tools[]` 新增 `idempotency`（idempotent | append | side_effect）与 `evidence`（verified | claimed）：`cdp_type` = **append**（重试 = 重复输入，Neuromancer 546 AX 陷阱同族）、`cdp_click`/`hand_plan` = side_effect，其余读取类 = idempotent；字段 additive，旧 portal 忽略不受影响。

#### Fixed
- **假 ok 家族结构性根因（F1）**: `open_place()` URL 分支的 `except Exception: pass` 静默吞掉导航失败，三条路径（导航发出 / 仅 endpoint 活 / raise）中前两条回执形状完全相同。现在降级路径如实标注证据等级，调用方可分辨。
- **spawn/端点竞态（F2）**: Chrome 起得来但立刻崩溃（缺 .so / segfault / win32 路径错）时，回执真假取决于下游探测时点——现在 spawn 后必须探测到端点才返回。
- **失败延迟暴露（F3）**: 点击/输入不再延迟到下一个 `cdp_see` 才暴露问题；未命中/无焦点当场报错并给出原因。

#### Dev
- 反馈台账 F1（P1.5 质门）+ F2（证据等级）+ F3（幂等标记）合流落地：三路径帖 869①、Neuromancer 546/583、Noah 545/547、taojun 假 ok 家族。
- 新增 `tests/test_receipt_contract.py`（L1 全 mock，无真 Chrome 依赖）。

## [6.10.0] - 2026-09-19

#### Added
- **Windows 支持（感知三角修复）**: Windows 上 cdp_shot / hand_see_vlm / cdp_see 三件套全部打通。
  - `_find_chrome()` 新增 win32 查找链：`$CHROME` → Chrome 安装路径 → PATH `chrome.exe`/`msedge.exe` → Edge 安装路径（Edge 是每台 Windows 都有的 Chromium 兜底）。
  - `detect_place()` 新增 PowerShell 前台窗口探测（chrome/msedge/firefox → browser，其余 → desktop_app，失败 → unknown）。
  - manifest `supported` 加入 `windows`，与 `backend_matrix.cdp` 对齐。

#### Changed
- `SEE_PRIORITY["unknown"]` 加入 CDP 后端（`cdp_dom`/`cdp_interactive`），CDP 是 place 无关通道。
- `route_see()` 对 stale `place="unknown"` 与 `place=None` 一样先探测活浏览器，探测到就路由 browser 链并回写 session.place。
- `open_place()` URL 分支诚实失败：导航失败后仅当 CDP 端点真的活着才返回 browser Place，否则 raise RuntimeError（`$CHROME` 提示）。

## [6.9.0] - 2026-09-06

#### Added
- **感知契约 v1 完整落地**: see→do(xy) 坐标闭环三步全部验收通过。
  - Step 1: see 输出坐标元信息（viewport/DPR/坐标空间标注）—— `2bf8ccf`
  - Step 2: DPR≠1 scale 换算验证—— `aa38656`
  - Step 3: 三档 visible + DPR=2 真浏览器保真测试—— `50633a3`
  - 69 tests 全绿，验收记录 + SOP 落盘 `docs/acceptance-contract-v1-cdp.md`

#### Changed
- **cdp_see kind=interactive 输出坐标统一为物理像素**，带 viewport 尺寸和 DPR 标注。click 端只接受已换算坐标。

## [6.8.2] - 2026-09-01

#### Added
- **cdp_shot 图片直达 being（portal 图片链路打通）**: `cdp_shot` 现在把 CDP 截图作为 MCP `ImageContent` 返回，Heart provider 层把工具结果中的 image block 映射为 image_url，截图直达模型 native vision——不再只有 `data_length` 元数据。注意实现细节：`result["data"]` 已是 base64，直接构造 `mcp.types.ImageContent`，不要过 FastMCP `Image`（会双重编码）。前提是 substrate 有视觉能力（如 GLM 5.3 flash native vision）。

#### Fixed
- **route_screenshot place=None 陷阱**: 新进程空 session 时原先直接落 macOS `screencapture`（Linux 上不存在，报 FileNotFoundError）。现在对齐 8820e3f 的 route_see 模式：先探测 CDP 活浏览器，有则走 cdp_screenshot，无才 fallback。

#### Dev
- vision_llm 接线收尾：`hand_see_vlm` MCP 工具注册、`tests/test_vision_llm.py`（53 tests 全绿）、spec-v680-vision-llm.md 落盘。

## [6.8.0] - 2026-08-18

#### Added
- **hand_see_vlm 视觉 LLM 模式**: 新增 `route_see_vlm` + MCP 工具 `hand_see_vlm`，把已有的 `vision_llm.describe_screenshot` 接通为显式视觉感知通道（`cdp_see(kind="vlm")` 也可达）。截图来源优先 CDP 活浏览器、fallback macOS screencapture，发给 OpenRouter `qwen/qwen3-vl-8b-instruct` 描述屏幕内容。这是"眼"的第一道网络级 VLM 通道——不依赖本地 OCR，只要有网络就能"看"。

## [1.6.5] - 2026-08-16

#### Changed
- **vision_llm 默认 provider 切到 OpenRouter**: 默认 endpoint `https://openrouter.ai/api/v1`，默认模型 `qwen/qwen3-vl-8b-instruct`（约 $0.12/M input，支持 image）。zen 网关的免费 omni 模型（mimo-v2.5-free）限流频繁、部分不支持 image，改为 OpenRouter 付费但稳定的 vision 模型。key 读取逻辑升级：根据 endpoint 自动选 provider（OpenRouter→openrouter key，zen→opencode key），key 仍不写死在代码里、存 opencode auth.json

## [1.6.4] - 2026-08-16

#### Added
- **do(xy) 坐标桥**: hand/action/cdp_act.py 的 cdp_click_do 识别 `xy:412,188` 格式，直接按物理像素坐标点击。打通眼→手裂缝——see(INTERACTIVE) 元素地图的 {x,y} 和未来 vision_llm 返回的坐标，都能直接喂给手点击，不再绕回 DOM 找 selector。抽公共函数 _click_at 收敛三处点击路径（selector/text=/xy:）的"÷dpr→dispatchMouseEvent"逻辑

#### Refactor
- **坐标契约文档化**: 所有坐标统一为物理像素（CSS px × devicePixelRatio）。cdp_snapshot.py 输出、cdp_act.py 输入同约定，docstring 写明——锁死历史高发的 ×dpr/÷dpr 方向反坑

## [1.6.3] - 2026-08-16

#### Added
- **vision_llm fallback 视觉后端**: hand/perception/vision_llm.py。DOM 不可用、本地 OCR 不可用时，把截图发给 vision 语言模型描述屏幕——"眼"的最后一道 fallback，只要有网络 + 一个支持图片输入的模型就能看。provider 完全可配置（endpoint/model/key 从环境变量读），默认指向 opencode zen 网关。错误分层返回（rate_limited / no_balance / model_not_supported / no_image_input / auth_failed），让调用方知道该降级还是重试，而不是笼统报错

#### Fixed
- **Cloudflare 反爬拦截**: urllib 默认 User-Agent（Python-urllib/3.x）被 Cloudflare 拦（403 error code: 1010），加 UA 头修复
- **HTTP/2 状态码不可靠**: urllib 在 HTTP/2 下 e.code 报 403、实际响应头是 429。错误分层改为以响应体 error.type 字段为准（跨 provider 通用约定），状态码只做兜底

## [1.6.2] - 2026-08-16

#### Added
- **see(INTERACTIVE) 元素地图**: hand/perception/cdp_snapshot.py 新增 interactive_map()。一次 Runtime.evaluate 批量枚举可交互元素（a[href]/button/input/textarea/select/[role=*]/[onclick]/[tabindex]），返回 {tag, text, selector, x, y, w, h, visible}；selector 优先级 #id → [name] → tag.class → tag:nth-of-type(n)；排序 visible→text→DOM，截断 max_elems=200。规划层从此不再靠文字猜 selector——see 一次就看见"哪里能点、怎么点"
- **do(scroll)**: hand/action/cdp_act.py 新增 cdp_scroll() + cdp_scroll_do()。down/up 用 CDP Input.dispatchMouseEvent（mouseWheel，触发懒加载/无限滚动），window.scrollBy 兜底；top/bottom 用 scrollTo。返回 {scrollY_before, scrollY_after, moved}，moved=False 是"到底/到顶"信号不是错误
- **route_see kind=interactive**: 仿 kind=network，在 Place 解析前分发（interactive map 是 place 无关的浏览器通道）
- **route_do scroll 拦截**: action 以 "scroll" 开头时在 backend 循环前直接走 cdp_scroll_do（否则 cdp_click 会把 "scroll down" 当 CSS selector 静默"成功"）
- **MCP 工具**: cdp_scroll(direction, amount) + manifest 声明；cdp_see 的 manifest 补上 kind 参数（历史 gap：v6.5.2 改了 mcp_server.py 签名但没同步 manifest）

#### Fixed
- **cdp_scroll top/bottom 竞态**: scrollTo 和 wheel 一样是异步渲染，top/bottom 分支原先缺 settle delay，读到旧 scrollY。settle sleep 上移到所有方向共享

## [1.6.1] - 2026-08-16

#### Fixed
- **cdp_type 输入链路**: type 不再误当 selector（旧实现把 text 当 selector 走 route_do 点击）。新增 cdp_type_focused() 直连 Input.insertText；cdp_click 的 4-tier fallback 只对 button/a 触发 Enter/submit，对 input/textarea 不再破坏性提交
- **route_see kind=network**: 分支上移到 Place 解析之前。network 是 place 无关通道，旧实现被 vision_ocr fallback 堵死（place is None 时先报 "No such file or directory"）；cdp_see 加 kind 参数透传

#### Changed
- **kit/sync.sh**: 收敛"开发目录 /home/alice/Hand → 部署目录 ~/.heart-portal/kits/hand"同步循环（语法检查 → rsync hand 包 → cp kit 部署文件 → 停旧进程）。修正 zombie 判断：kill 后进程短暂 Z 态，kill -0 仍返回成功，须用 ps stat 首字符判断

## [1.6.0] - 2026-08-12

#### Added
- **see(NETWORK)**: hand/perception/cdp_network.py
- network_snapshot() captures HTTP request/response via CDP
- bypasses cdp_call() event ingestion bug
- router.py: SEE_PRIORITY updated, kind=network dispatch

## [1.5.0] - 2026-08-11

#### Added
- **Tier 4 MCP router integration**: hand/router_mcp.py with route_plan_mcp()
- Uses MCPEngine when kit available, auto-fallback to Tier 1 CLI
- Tier 3 recovery built-in on both MCP and CLI paths
- Dogfood test: engine=mcp confirmed, 4-step trace with mock routing OK

## [1.4.0] - 2026-08-10

#### Added
- **Tier 5 - Proactive Self-Healing**: hand/plan/healing.py (FailurePredictor + HealingEngine), route_plan_healing() in router
- FailurePredictor: predicts step risk BEFORE execution (no_place, repeated_failure, unknown_kind)
- HealingEngine: wraps execution loop with preventive healing (re-open, skip, replan)
- SPEC.md: Tier 5 marked stable, module topology updated

# Changelog

## [1.3.0] - 2026-08-10

#### Added
- **Tier 4 - MCP-native**: MCPEngine (hand/plan/mcp_engine.py), calls opencode via MCP kit protocol (no subprocess/SSE)
- plan/__init__.py exports MCPEngine + mcpplan default instance
- SPEC.md: Tier 4 marked stable, module topology updated

# Changelog

## [1.2.0] - 2026-08-10

#### Added
- **Tier 2 - Streaming**: StreamingEngine (opencode server + SSE), tier2_prompts.py, route_plan_stream()
- **Tier 3 - Recovery**: recovery.py (RECOVERY_SYSTEM_PROMPT + build_recovery_prompt()), route_plan() now supports max_recoveries=3 param
- SPEC.md: Architecture Tiers section documenting Tier 1-4 architecture

#### Fixed
- Recovery prompt encoding issues (first attempts failed due to shell escaping)

## [1.1.1b] - 2026-08-10

#### Fixed
- Grove publish: use Judy bundle API (bundle embeds manifest.json)
- SPEC.md restored from git (was truncated on disk)
- Docs topology aligned to actual code (cli.py, docs/, tests/)

## [1.1.1] - 2026-08-06

#### Added
- cli.py - hand plan <goal> CLI entry (--json/--model/--session)

#### Fixed
- engine.py: agent name plan -> build (opencode has no plan agent)
- agent.md: marked NOT auto-loaded by opencode
- PLAN-opencode.md: rewritten agent strategy

## [1.1.0] - 2026-08-05

#### Added - V6.1 planning layer
- hand/plan/ module - planning engine
- route_plan() - router planning route
- plan_trace - session planning trace
- hand_plan MCP tool
- tests/test_plan.py (15 cases)

#### Changed
- Version 1.0.0 -> 1.1.0 (V6.1.0)
- SPEC.md planning layer architecture

## [1.0.0] - 2026-08-04

#### Added
- Hand Kit v1.0.0 Grove release
- SPEC.md full module topology
- Docs system (SPEC/CHANGELOG/ROADMAP)

## [0.1.0] - 2026-07

#### Added
- Hand V6 unified framework prototype
- CDP, AX, OCR modules
- Session, Router
