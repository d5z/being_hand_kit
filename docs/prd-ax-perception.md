# PRD: hand 0.7.0 — AX 感知层（a11y v2 默认）

**版本**: 0.7.0（版本线重置：感知层范式切换，非 6.x 渐进迭代）
**日期**: 2026-09-21
**状态**: approved（泽平 17:51 拍板 go）
**实验依据**: experiments/a11y_ab/REPORT_phase2.md（90 trials，B 组 a11y 87% vs A 组 interactive 58%）

## 背景

Astra 报告 a11y 表示对其 computer use agent 是巨大提升。hand 已在语义层（interactive：role/text/selector/coords），问题是「a11y 对 GLM-5.3 级模型好不好」——实测答案是决定性的：

- **感知类 50% → 88%（代差）**：interactive 层数不出 heading、看不见侧栏全文（text 截 40 字符）、无层级语义——模型不是笨，是输入里没有信息
- **操作类 57% → 71%**：`link "Sign in" [93]` vs CSS-module 乱码 selector `a.Primer_Brand.Primer_Brand...`；A 组能赢的任务靠网站恰好给语义 id，是运气不是格式能力
- **token 输入 -17% / 输出 -77%**，延迟持平
- A 组失败=瞎（乱码瞎选、无信息瞎答）；B 组失败=近似（选了次优合法目标）——近似可修，瞎修不了

**已知盲区（写进文档，不藏）**：视口窄时导航折叠进溢出菜单（"Additional navigation options"），AX 树不可见其内容（Insights 案例：AX=6 tabs，DOM=7）。需两步策略：点开 ⋯ 再 see。

## 目标

1. `cdp_see` 默认返回 a11y v2 树（缩进树 + role/name/state + [idx] 句柄）
2. interactive 层降级为坐标执行后端（[idx] → backendNodeId → 坐标，实验已 100% 打通）
3. F7/F8 物理基础并批：Chrome profile 策略 + macOS 发现层
4. F9-F13 quick-fix 并批
5. 回执契约（6.11.0 verified/evidence）套到 a11y 快照上——新眼睛过同一把尺

## 非目标（推 0.8+）

- F14 dispatch→effect 效果验证（expect 参数、派发后回读）
- code mode / getByRole 定位器通道（实验 C 组，未测）
- F4 do 内建验证粒度、F5 接力原语

## 设计

### S1 · a11y 序列化产品化
`experiments/a11y_ab/serialize_ax.py` → `hand/perception/ax_tree.py`：
- CDP `Accessibility.getFullAXTree` 拉取，curation 规则（滤不可见/纯布局节点，AX 误挂 level 到 listitem 的修正）
- 序列化：YAML 风格缩进树，`role "name" (state) [idx]`，idx 为稳定句柄
- `backendNodeId → 坐标` 映射表（DOM.getBoxModel），供 click/type 执行
- **训练数据友好约束**：序列化格式确定性（同页面同输入→同输出字节）、句柄稳定、截断规则显式（超长树截断时标记 truncated: true + 保留策略）——此格式可能是 being LLM 后训练 computer use 数据的表示基础（泽平 2026-09-21 信号），格式即数据契约，变更需版本化

### S2 · see() 接线
- `cdp_see(kind=...)`：`a11y`（新默认）/ `interactive`（legacy 逃生口，保留一个过渡版本）/ `dom` / `network` 不动
- `cdp_see` 返回头部带溢出菜单提示（检测到 "Additional navigation options" 类 hasPopup 按钮时附 hint 行）
- `cdp_click`/`cdp_type` 接受 `[idx]` 句柄（解析走 S1 映射表），selector 路径保留

### S3 · 回执契约套 a11y
a11y 快照回执带 `verified`（树确实拉到、根节点非空）/ `evidence`（节点数、序列化字节数、truncated 标记、树来源 AX 版本）

### S4 · F7 Chrome profile 策略
- `_chrome_flags()` 加 `--user-data-dir=<kit>/.chrome-profile`（isolated 默认）
- `HAND_PROFILE=persistent` env 显式 opt-in 共享/持久 profile（taojun 954：无头指纹限流 + 持久 profile 放行）
- `HAND_HEADLESS=0` env 可配（同上旁证）
- 吸收 wrapper flags 进正规链，不复活 wrapper（Cotton 935：机制在、线没接）

### S5 · F8 macOS 发现层
`_find_chrome()` 加 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` 候选

### S6 · F9-F13 quick-fix
- requirements.txt pin `mcp<2`（F9）+ 补 websocket/requests（F10）
- start.sh source .env 若存在（F11）
- README：python ≥3.10 前置（F12）、冷启动 2-3s 预期 + S2 端点探测上限 6s（F13）、升级影响栏（profile 目录首次创建，旧 wrapper 可删可留）

### S7 · manifest + 版本
manifest.json version 0.7.0；idempotency 标签复核（F15 顺手：cdp_type fast 路径 replace 语义按路径分标或删）；Grove 发布 + release note

## 验收标准

1. 全测试绿（a11y 序列化单测：curation/句柄/映射/确定性；see 集成；profile flags）
2. dogfood：`see(kind=a11y)` 在 beings.town + github.com/d5z/being_hand_kit 实跑，树结构与实验快照一致
3. `see(kind=interactive)` 仍可用（兼容逃生口）
4. spawn 后 `ps` 核 `--user-data-dir` 在 flags 里（F7 验收协议四步）
5. `[idx]` 句柄 click/type 端到端（beings.town 上点一个真实链接）
6. 同页面两次 see 输出字节一致（确定性，训练数据前置）

## 风险

- AX 树在重 SPA 上可能很大 → 截断策略 + truncated 标记（S1）
- mcp 2.x 适配未做（pin <2 是止血，2.x 适配推后）
- 版本线重置对 Grove 排序的影响 → 发布时 release note 首行说明
