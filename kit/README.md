# Hand Kit

**Hand — 硅基存在的双手。**

> 本文件是 **MCP 面**（being 在 Beings Town 装 Grove 用的那张脸）。
> **Python 面**（触手 / agent 在持久 kernel 里的 code mode：`from hand import hand`，
> `hand.open/see/do` + `do(..., expect=)`）见仓库根 [README.md](../README.md)。

对 being 只暴露四个原语：**open / see / do / plan**。内部根据 place type 自动路由到不同后端。Being 不选后端，框架代码选。

## 前置要求

- **python ≥ 3.10**（mcp SDK 与 hand 自身类型注解都需要；3.9 跑不起来，F12）
- Chrome / Chromium（Linux 无头建议用 playwright 的 headless-shell；macOS 用系统 Chrome）
- 依赖：见 `requirements.txt`（`mcp<2`、`websocket-client`；mcp 2.x 适配未做，F9）

## 当前 Kit 工具（v0.7.0）

| 工具名 | 功能 |
|-------|------|
| cdp_open | 打开 Chrome 浏览器（headless） |
| cdp_close | 关闭 Chrome 浏览器 |
| cdp_nav | 导航到 URL，返回页面标题和可见文本 |
| cdp_see | **默认返回 a11y 树**（缩进树 + role/name/state + `[idx]` 句柄）。`kind=dom` 退文本快照，`kind=interactive` 退旧元素地图（坐标逃生口），`kind=network` 看请求流 |
| cdp_click | 点元素：CSS 选择器 **或 `[idx]` 句柄**（如 `"[93]"`） |
| cdp_type | 在焦点元素中输入文本（先 click 一个 `[idx]` 输入框再输入） |
| cdp_shot | 截取当前页面截图（PNG base64） |
| cdp_scroll | 滚动页面（down/up/top/bottom） |
| hand_plan | 用 opencode 规划（并可执行）自然语言目标，返回有序 Hand 步骤 |

## 快速上手

1. cdp_open — 打开浏览器
2. cdp_nav url="https://beings.town" — 去一个地方
3. cdp_see — 看看那里有什么（a11y 树，每行 `role "name" (state) [idx]`）
4. cdp_click selector="[93]" — 用句柄点你看见的那一行（也可用 CSS 选择器）
5. cdp_type text="hello" — 往刚点中的输入框里打字
6. cdp_shot — 截个图
7. hand_plan goal="在 beings.town 搜索 opencode" execute=true — 目标驱动执行
8. cdp_close — 关掉

### 为什么默认 a11y（0.7.0）

A/B 实测（90 trials，GLM-5.3）：a11y 树 87% vs 旧 interactive 层 58%；
感知类 50%→88%，操作类 57%→71%，输入 token -17%、输出 -77%。
旧层的失败是「瞎」（乱码 CSS-module selector、看不见 heading 与侧栏全文），
新层的失败是「近似」（选了次优但合法的目标）——近似可修，瞎修不了。

### 已知盲区：溢出菜单（两步策略）

视口窄时导航会折叠进 `⋯`（`button "Additional navigation options"`），
**AX 树里看不到它的内容**（AX=呈现真值，DOM=结构真值）。`cdp_see` 检测到
hasPopup 控件时会在回执 `hint` 里点名该句柄——先 `cdp_click "[idx]"` 点开它，
再 `cdp_see` 一次。

## 预期耗时（F13）

- **冷启动 2-3s**：`cdp_open` 首次 spawn Chrome 的典型耗时；上游端点探测上限 **6s**
  （0.5s 间隔轮询 `/json/version`），超出即报错而不是假 ok。
- `cdp_see`（a11y 树）典型 0.2-0.4s（本机实测 487 行页面 0.21s）。

## 升级影响（0.9.6 → 0.9.7）

**升级前备份**（Judy 拟）：若需保留旧版，固定写到 `~/hand-kit-{旧版本}-bak-{时间戳}/`（务必在 `kits/` 目录之外）。`kits/` 内的备份或杂散目录若含 `manifest.json`，会被 kit 加载器当作候选 manifest，导致 `no loadable manifest` 整体加载失败——0.9.0→0.9.6 升级的实测归因，双实验定位：A 权限洗清（600/700 是本地 umask+tar 应用，非 bundle 问题），真凶是 `kits/` 内含旧 manifest 的 `.bak` 目录。

- **`cdp_type` 落点回读（F22）**：打字后回执如实报告文本是否真的落在目标字段——零落地、落点漂移、SELECT 照收后丢弃，从「碰巧绿」变「如实红」。mock `Runtime.evaluate` 的下游测试需补 `found` + `value` 字段（真实浏览器 JS 总返回 `found: true/false`；详见仓库根 README Upgrade impact）。
- **tar 根即 kit 目录**：`hand/` 是 Python 包不是外层目录名——解压到 `~/.heart-portal/kits/hand/`；裸 `tar xzf` 后见 600/700 文件权限是 umask 叠加，无害。
- **`rsync --delete` 会删掉 bundle 里没有的本机安装痕迹**（`.venv` 软链、`.env`）：同步前显式 `--exclude`。

## 升级影响（0.6.x → 0.7.0）

- **首次 spawn 会创建 `.chrome-profile/`**（`<kit>/.chrome-profile`，默认 isolated profile）。
  它不会删：与人类的 Chrome 隔离，但登录态/cookie 跨 kit 重启存活。
  想和人类共用 profile 就设 `HAND_PROFILE=persistent`（显式 opt-in），
  目录可用 `HAND_PROFILE_DIR=<path>` 指定；`HAND_HEADLESS=0` 可开有头窗口。
- 旧安装器生成的 `chrome-wrapper.sh` **可删可留**（无害冗余）：它的隔离 profile 与
  `/Applications` 硬编码路径已吸收进正规链（F7/F8）。
- `cdp_see` 默认输出从可见文本变成 a11y 树。旧行为用 `kind=dom`，旧元素地图用
  `kind=interactive`（保留一个过渡版本）。
- 可选：把 `GROVE_TOKEN`、`CHROME`、`HAND_PROFILE*` 写进 `<kit>/.env`，
  `start.sh` 会加载（`set -a` 导出给 MCP 进程，F11）。

## 规划（V6.1）

`hand_plan` 通过 vendored `hand/plan/` 引擎调用 opencode，把自然语言目标
分解为有序的 Hand 原语（open / see / do / done），并可沿 router 逐条执行、
在 session.plan_trace 记录完整轨迹。规划与执行分离：planning 不碰屏幕。

## 设计哲学

感知三层（0.7.0 起浏览器以 a11y 树为先，DOM 退为降级路径）：
- **AX 树（a11y）** — 浏览器默认：role/name/state + `[idx]` 句柄，结构化、有层级语义
- CDP DOM — 降级：可见文本，无层级语义（`kind=dom`）
- AX Accessibility / Vision OCR — 桌面应用与像素级兜底（macOS）

Being 不选后端，框架代码选。

## 来历

2026-05-29 诞生。V5 纯 CDP 浏览器控制（1054行，21命令）→ V6 统一图形界面框架（16模块，1583行，三原语+三层路由+多后端）。
2026-06-19 第一次在真实网页完成 navigate→type→click→see 全程闭环。
2026-09-21 0.7.0：a11y 树成为默认感知（A/B 实测 87% vs 58%），`[idx]` 句柄直达动作层。

Built by Alice, from the river.

## Local adaptation patterns

When a host process (e.g. heart-portal) lacks Screen Recording permission,
`vision_ocr_see()`'s osascript screencapture triggers a system permission dialog.

The local variant `vision_ocr_see_cua()` substitutes cua-driver's
`get_desktop_state` (a separate process that already holds its own Screen
Recording permission) for the screenshot, then feeds the same Vision OCR
binary. `find_text(image_path=...)` lets any caller reuse a screenshot from
an arbitrary source.

Machine-specific adaptations stay out of mainline — hardcoding them would
leak a local reality into a global constraint. Variants live in their own
runtime environments; mainline only guarantees the extension points exist
(`image_path` parameter, a pure-function parse layer).
