# PRD: hand 0.9 — 诚实回执完成体（Truncation Honesty + Visual State）

> 状态：v1.0（2026-09-22，泽平拍板「v0.9开」）
> 血统：回执契约（0.6-0.7 verified vs claimed）→ code mode（0.8 expect=）→ 0.9 补「完整 vs 截断」与「文本 vs 视觉」两轴
> 排序原则：用户可见的可靠性优先于内部打磨

## 范围与排序

| 序 | 项 | 一句话 | 状态 |
|---|---|---|---|
| S1 | 截断/丢弃声明原则 | 跳过必留痕：所有截断/跳过/丢弃在回执显式声明 | 本版实现 |
| S2 | 视觉状态标记 | cdp_see/shot 携带 loading/error/blank/interactive 状态 | 本版实现（标记格式先行，py 拍板联动） |
| S3 | OCR diff | 两次 OCR 输出 diff，文本变化区域定位 | 本版实现（依赖 S2 bounds 格式） |
| S4 | expect spec v1.0 | 把 0.8 事实标准写成正式 spec | 本版实现（纯文档+测试对齐） |
| S5 | subagent 摩擦 | task_id/预算/进度三摩擦 | hand 侧文档化；portal 侧修复转 weiguo/sw |
| S6 | 机器级隔离 | Chrome profile 隔离 | **data-gated**：等 taojun D5 Launcher 并存真实样本，本版不做 |

---

## S1: 截断/丢弃声明原则（跳过必留痕）

### 问题
0.7 建立了 verified vs claimed（回执声称的必须验证过），但「没说的」仍是盲区：
- a11y 树截断有 marker，但其他工具的静默截断/跳过不声明
- 调用方无法区分「完整结果」和「被裁剪的结果」——除非恰好撞上缺失

### 目标
任何输出被截断、跳过、丢弃时，回执必须显式声明：**截断了什么、为什么、多少**。

### 设计
1. **统一字段**：回执新增 `truncated` 块（对齐 a11y 已有的 truncation marker 语义，推广到全工具）：
   ```
   "truncated": {
     "field": "tree",           // 哪个字段
     "reason": "max_nodes",     // 为什么截
     "dropped": 42,             // 丢了多少
     "total": 210               // 完整应有多少
   }
   ```
   无截断时字段缺席（不是 `truncated: null`——缺席=完整，存在=有痕）。
2. **跳过声明**：工具内部跳过的步骤（如 cdp_see 对 collapsed menu 的 hint 已是雏形）统一进 hint 通道，格式 `skipped: <what> (<why>)`。
3. **Neo codex-async 1.1.6 模式借鉴**：跳过不是失败，但跳过必须可见。

### 验收
- [ ] 每个工具的截断路径有契约测试（构造超限输入，断言 truncated 块出现且数字对）
- [ ] 无截断路径断言 truncated 缺席
- [ ] a11y 现有 truncation marker 迁移到统一格式（向后兼容：旧字段保留一版）

---

## S2: 视觉状态标记

### 问题
Epoch 失败模式分析：35% 的失败源于**视觉状态不可断言**——页面在 loading、spinner、错误页、空白，DOM 断言看不出「用户此刻看到的是不是成品」。

### 目标
cdp_see / cdp_shot 回执携带视觉状态标记，expect 可断言「页面处于什么视觉状态」。

### 设计
1. **状态枚举**（v1 四态 + unknown）：
   - `loading` — 有可见 loading 指示（spinner/skeleton/进度条）
   - `error` — 错误页特征（大图标+错误文案/HTTP 错误标题）
   - `blank` — 视口实质空白（无文本节点、无图片）
   - `interactive` — 正常可交互内容
   - `unknown` — 判定信号不足（诚实优先，不硬猜）
2. **判定信号**（DOM 侧启发式，不依赖截图）：
   - loading: `[aria-busy=true]`、常见 spinner class、`document.readyState !== 'complete'`
   - error: h1/h2 命中错误词表（error/错误/404/500/not found）、`<img>` 主导且 alt 含 error
   - blank: body 可见文本长度 < 阈值 && 无 img/canvas/video
   - 优先级：error > loading > blank > interactive
3. **回执字段**：`visual_state: "loading"` + `visual_signals: ["aria-busy", "spinner-class"]`（信号留痕，可审计）。
4. **py 拍板联动**（data-gated 部分）：修复前 v2.1 现状标记 vs 修复后标记的映射表，等拍板后补。标记格式本身先行。

### 验收
- [ ] 四态各有端到端测试页（本地 fixture HTML）
- [ ] unknown 路径有测试（信号不足时诚实报 unknown，不猜）
- [ ] expect 支持 `visual_state=loading` 断言
- [ ] visual_signals 留痕可审计

---

## S3: OCR diff

### 问题
0.8.3 落了 vision-ocr bounds 输出（tab 分隔 x/y/w/h/center），但两次 OCR 只能全文比对——「哪里变了」要人眼找。

### 目标
`ocr_diff(before, after)` 输出文本变化区域：新增/消失/移动的词块，带 bounds。

### 设计
1. 输入：两次 vision-ocr 的 bounds 输出（tab 格式）
2. 对齐：按行中心 y 聚簇成文本块 → 块间 LCS 对齐 → 块内词级 diff
3. 输出：
   ```
   {"blocks": [
     {"change": "added",   "text": "登录成功", "bounds": {...}, "near": [行号]},
     {"change": "removed", "text": "正在加载", "bounds": {...},
     {"change": "moved",   "text": "提交", "from": {...}, "to": {...}}
   ]}
   ```
4. 纯 Python 标准库（difflib），不引新依赖。

### 验收
- [ ] added/removed/moved 三类各有 fixture 测试
- [ ] bounds 对齐误差 ≤ 行高一半（同块判定）
- [ ] 无变化时输出空 blocks（不是全文重复）

---

## S4: expect spec v1.0

### 问题
0.8 code mode 的 `expect=` 是事实标准——在跑、没人写下来。格式漂移风险随使用者增加上升。

### 目标
`docs/expect-spec-v1.md`：语法、语义、版本承诺。解析器按 spec 走，测试对齐 spec。

### 设计
1. spec 内容：expect 键空间（text/selector/visual_state/network/...）、值语法、失败消息格式、版本号承诺（v1 冻结，破坏性变更升 v2）
2. 解析器与 spec 的对齐测试：spec 里每个例子进测试
3. S2 的 visual_state 断言进 spec v1（发布前补齐，不算破坏）

### 验收
- [ ] spec 文档落地，含完整键空间表
- [ ] spec 例子 100% 有对应测试
- [ ] 版本承诺写明

---

## S5: subagent 摩擦（hand 侧文档化）

### 问题
0.7 实现期撞的四摩擦：task_id 必须完整 UUID、预算语义不透明（max_tokens/max_turns/timeout_secs 实际含义）、进度靠 git log 旁路推断。

### 目标
hand 侧：`docs/subagent-guide.md` 写清三摩擦的规避法与判读法。portal 侧修复（task_id 短前缀容错、预算字段文档化、进度事件）转 weiguo/sw，不占 hand 0.9 账面。

### 验收
- [ ] guide 落地，含 0.7 实战案例（sub_3a2ced15 的 task_id 教训）
- [ ] 转交清单给 weiguo（portal repo issue 形态或 DM）

---

## S6: 机器级隔离（data-gated，本版不做）

Chrome profile 隔离（user-data-dir per instance）。等 taojun D5 Launcher 并存场景的真实样本再设计。F16 的 HAND_CDP_PORT 已是第一步。**不提前设计**——data-gated 纪律。

---

## 发布计划

1. PRD 落定（本文档）
2. subagent 实现 S1 → S2 → S3 → S4（S5 文档可并行）
3. 逐 commit review + dogfood 双态验证
4. 292+ 测试全绿 ×3
5. sync → Grove 发布 0.9.0 → #34 公告

## 非目标

- 不做 C 组 code mode 扩展（0.8 遗留，等 a11y 数据回灌后再判）
- 不动 mcp_server 契约层（0.8.3 刚稳）
- 不做 S6（data-gated）
