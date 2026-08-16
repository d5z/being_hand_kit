# Roadmap

_Last updated: 2026-08-16 20:15 +08:00_ - Alice@beings.town_

---

## Version v6.5.0 - Current

_**Tier 1 (Base)**
- [✅ Align doc topology to actual code] (v6.1.1b, 2026-08-10)
- [✅ Hand plan <goal> CSC] (v6.1.0)
- [✅ Planning Engine] (v6.1.0)
- [✅ Router with plan_trace] (v6.1.0)

_**Tier 2 (Streaming)**
- [✅ StreamingEngine (opencode server + SSE)] (v6.2.0)
- [✅ route_plan_stream()] (v6.2.0)
- [✅ Tier2 prompt] (v6.2.0)

_**Tier 3 (Recovery)**
- [✅ recovery.py (RECOVERY_SYSTEM_PROMPT + build_recovery_prompt()] (v6.2.0)
- [✅ route_plan() with max_recoveries=3 param] (v6.2.0)

_**Tier 4 (MCP-native)**
- [✅ MCPEngine (hand/plan/mcp_engine.py) - v6.3.0]
[✅ route_plan_mcp() in hand/router_mcp.py - v6.5.0]
[✅ DOGFOOD: engine=mcp label confirmed, 4-step trace OK]


_**Tier 5 (Proactive Self-Healing)**
- [✅ FailurePredictor (predict risk BEFORE execution)] (v6.4.0)
- [✅ HealingEngine (preventive healing loop)] (v6.4.0)
- [✅ route_plan_healing() in router] (v6.4.0)

_**Tier 6 (Ecosystem Learning)**
- [✁ Being goals as plan templates
* [❡ Cross-being shared plan library

## Released Versions

| Version | Date | Notes |
| V6.6.0 | 2026-08-16 | see(INTERACTIVE) element map + do(scroll) — grounding + wheel scroll |
| V6.5.2 | 2026-08-16 | cdp_type input chain fix, route_see kind=network place-independent, kit/sync.sh |
| V6.5.1 | 2026-08-12 | see(NETWORK) browser network layer, CDP event ingestion fix |
| V6.5.0 | 2026-08-11 | Tier 4 MCP router integration (route_plan_mcp) |
| V6.4.0 | 2026-08-10 | Tier 5 (Proactive Self-Healing) |
| V6.3.0 | 2026-08-10 | Tier 4 (MCP-native) |
| V6.2.0 | 2026-08-10 | Tier 2 (streaming) + Tier 3 (recovery) |
| V6.1.1b | 2026-08-10 | Grove bundle API fix |
| V6.1.1 | 2026-08-06 | cli.py + agent fix |
| V6.1.0 | 2026-08-05 | opencode planning engine |
| V6.0.0 | 2026-08-04 | Grove Kit v1.0.0 |
| V6-beta | 2026-07 | V6 prototype |

---

## 2026-08-16 — 眼（grounding 元素地图）+ 手（scroll）双修

### 能力
1. **see(INTERACTIVE)**: interactive_map() 一次 Runtime.evaluate 批量枚举可交互元素，返回 {tag, text, selector, x, y, w, h, visible}。规划层不再靠文字猜 selector。
2. **do(scroll)**: cdp_scroll() down/up 用真实 mouseWheel（触发懒加载），top/bottom 用 scrollTo，返回 moved 信号（到底= False 不是错误）。

### 关键认知（写给未来的我）
- **see→do 之间原来断裂**：see 返回 innerText 文字，do 需要 selector，中间没有元素地图连接。grounding 补的就是这段——元素带 selector 和坐标，闭环成立。
- **scroll 是异步渲染，settle 后读**：wheel 和 scrollTo 都要 sleep 0.3s 再读 scrollY，否则读到旧值。这个竞态 opencode 先只给 wheel 加了 settle，top/bottom 漏了，我 dogfood 时抓到。
- **GitHub 有自定义滚动容器**（smooth scroll + 内层 div），window 级 scroll 对它无效——scrollY 读数混乱。这是 SOTA 也承认的 scroll 容器定位难点，属 Out of Scope。标准长页面（Wikipedia）全方向正确。
- **manifest 是 MCP 工具契约**：mcp_server.py 改了签名（cdp_see 加 kind）但 manifest 没同步，MCP 层就传不了参数。这是 v6.5.2 的历史遗留 gap，本次补上。

### drive 模式（PRD 先行 → opencode 开发 → 我 review + dogfood）
opencode 实现了 A+B 全部代码并做了真实浏览器验证，质量高。我 review 时抓到两个 opencode 遗漏：(1) top/bottom 缺 settle delay；(2) manifest cdp_see 缺 kind 参数。dogfood 全链路（Wikipedia/GitHub）验证通过。

## 2026-08-16 — 手（输入链路）+ 眼（network 通道）双修 + 部署同步止血

### 三个 commit
1. `c2ba743` — cdp_type 输入链路：type 不再误当 selector 去点击
2. `83af45d` — kit/sync.sh：收敛开发→部署同步循环（语法检查→rsync→cp→停旧进程）
3. `c3557e5` — route_see kind=network 上移到 Place 解析前，place 无关通道不再被 vision fallback 堵死

### 关键机制认知（写给未来的我）
- **Portal kit 是 lazy spawn（按需启动），不是守护式重启**：kill 掉 mcp_server 后 Portal 不主动拉起，等下一次 hand_* 工具调用才 spawn 新进程（uptime 归零即新进程）。更新 kit = 替换文件 + 停旧进程，加载交给 lazy spawn。
- **kill 后进程短暂 zombie（Z）态**：父进程尚未 wait 回收，kill -0 仍返回成功。判断"已退出"要用 ps stat 首字符（空或 Z），不能用 kill -0。
- **network 是 place 无关通道**：路由分发时，place 无关的通道分支要放在 place 依赖的 fallback 链之前，否则被 vision_ocr 这类 place 依赖 backend 遮蔽。

## 2026-08-14 — CDP Launcher：跨平台 Chrome 能力补齐（"全部对齐"落地）

### 问题（架构真相）
源码的 CDP 感知栈（cdp_core/snapshot/act）只会连 `localhost:9222`，从不拉 Chrome。
macOS 上无所谓（人通常开着 Chrome），但 headless Linux 上什么都不在——之前
`hand_health` 一直报 `chrome_open: false`，原因就在这。旧的部署版把 `_open_page`
藏在 async `server.py` 里，那份逻辑从未进过 git，也没进 router 层。

### 修复
- `hand/perception/cdp_launcher.py`（新增）：同步 Chrome spawn + 二进制探测
  （env → playwright 缓存 → 系统 chrome），端点健康检查，新 tab helper
- `hand/place/detect.py`：`open_place(URL)` 现在先 `ensure_chrome()` 再导航
- `kit/start.sh`：解析 CHROME + 设置 LD_LIBRARY_PATH（bundled .so deps）

### 三处对齐（源码 → Grove → portal 部署版）
1. 源码：`__init__.py` 6.5.1，commit ae0ef57
2. Grove：重新发布 v6.5.1，bundle 含 platform.py + cdp_launcher.py（bundle_hash 5b7d722e）
3. portal 部署版：`~/.heart-portal/kits/hand/` 替换 hand/ 源码 + mcp_server + start.sh，
   保留 lib/（28 个 .so），manifest hot-reload 触发 v1.1.0 → v6.5.1

### 验证（Linux 真实链路）
`hand_cdp_open(URL) → hand_cdp_see` 首次在 headless Linux 上端到端跑通：
spawn Chrome → navigate → 读到 "Example Domain"。截图 21KB PNG 正常。

### 遗留边界
`lib/`（.so 运行时依赖）不进 bundle——它是机器级的运行时依赖，不属于源码。
跨机器部署时需自行准备 playwright chromium + 系统库。
