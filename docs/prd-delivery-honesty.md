# PRD: 交付诚实（Delivery Honesty）— 感知的第四轴

> 状态：v0.1 草稿（2026-10-17 深夜，Alice；待泽平/sw 评审）
> 血统：0.6-0.7 回执契约（verified vs claimed，动作发生了吗）→ 0.8 code mode（expect=）→ 0.9 诚实回执完成体（S1 内容完整吗 / S2 页面什么状态）→ **本 PRD：证据到你手上了吗**
> 版本归属：**v0.10**（2026-10-17 泽平拍板）
> 排序原则：能堵住「主体盲读」的优先于扩展感知能力
> 评审状态（2026-10-17 泽平）：版本归属 0.10 已定；**D1 的 hand/heart 分段署名边界已认可**（hand 声明 emitted、heart 声明 delivered，hand 不写自己不知道的事）

## 一句话

前三轴的主语是**工具**（工具说的是真话吗 / 结果完整吗 / 页面什么状态）。
本 PRD 的主语是**到达**（这条证据真的到了调用方手里吗，调用方能判读吗）。

## 问题从哪来（2026-10-17 夜，实证）

loom 对话中我做多模态自测，同一晚连续三次归因错误：
1. 以为 `with_data=false` 是看不见的原因 → 错
2. 以为 `act` 包装层摘掉了图像 → 错（在当前版本不成立）
3. 修好了中文字体，仍不确定自己是否在真看

最后用两条**不可猜的随机串**硬验证（`rand.html` → 顶层直调读回 `F5DXZULU`；`rand2.html` → `act` 包装读回 `GLCOWQWG`，均与文件逐字 MATCH）才定案：**图像一直在，两条通路都透传 ImageContent**。

三次错全部来自同一处：**回执文本里没有任何字段告诉我这一次到底有没有像素**。`verified: true`、`data_length: 123216` 与「图像完整送达」逐字相同，与「图像根本没进 context」也逐字相同。

泽平当晚的判语：*「看见的东西多轮之后被 heart context 丢弃了，这是 heart 侧要加强的地方」*——他指出了下游；本 PRD 补的是**上游的可判读性**。

## 与既有 PRD 的对偶关系

| 既有 | 管什么 | 本 PRD 补什么 |
|---|---|---|
| receipt-contract（0.6-0.7） | verified vs claimed：不许 silent ok | **上界之外的下界：不许 silent nothing**。`verified=true` + 交付为零，是二分法装不下的第三态 |
| receipt-honesty S1 | 缺席=完整，存在=有痕（字段级） | **非结构化介质失效**：像素不是字段，它的「缺席」会被整个系统读成「完整」 |
| receipt-honesty S2 | visual_state 四态（DOM 侧启发式） | **判据地基修正**：blank 是视觉范畴，DOM 代理必然有洞（已抓到实证反例） |
| acceptance-contract-v1-cdp | 四层验收：工具的行为对不对 | **第五层 being_selfproof**：感知有没有到达（此事只有 being 能判） |

---

## 范围与排序

| 序 | 项 | 一句话 | 归属 | 状态 |
|---|---|---|---|---|
| D1 | 交付声明 delivery | 回执正面声明各感知通道是否真的交付，hand 与 heart 分段署名 | hand + heart 跨仓 | 待实现 |
| D2 | 沉默≠完整 | 通道级声明取代字段级缺席推断 | 并入 D1 | 待实现 |
| D3 | blank 判据加像素票 | S2 修正：无像素证据时不许报 blank，降 unknown | hand | **已实现 2026-10-18**（未发版） |
| D4 | being_selfproof 验收层 + `hand_eye_check` | 不可猜外部串自证法进验收 SOP，并做成公共原语 | hand | 待实现（方法已实证） |
| D5 | 预算维度 | token 经济性进设计，坐标化优于全图（跨仓） | hand + heart | data-gated（等 sw 数字） |
| D6 | 采纳侧自证 | eye_check 随 kit 分发，adopter 可自证 + 上报 | hand + Grove | data-gated（等 Judy 线） |

---

## D1: 交付声明（本 PRD 主刀）

### 问题
`verified` 回答的是「动作发生了吗」。它 никогда 没有回答「证据到调用方了吗」。2026-10-17 夜两者真实分离：动作 100% 发生（`open: ok`、`verified: true`、`data_length: 123216`），而上下文里的图像为 0。

更糟的是 S1 立下的原则在这里反向工作：*缺席=完整*。图像缺席（没进 context）被读成完整（无任何 warning），因为它不是 JSON 字段，不在那个语义域里。

### 目标
回执让调用方**只读文本就能判读**：这次我有没有拿到可看见的东西。

### 设计：两段署名，hand 不说自己不知道的事

关键边界：**hand 不能自己写 `pixels: attached`**——谁决定图像进不进 context 是 portal/heart 层，hand 写了就是新的 claimed 冒充 verified。所以分两段：

```jsonc
// 第一段：hand 侧，声明"我发出了什么"
"emitted": {
  "by": "hand",
  "channels": {
    "image": {"emitted": true, "bytes": 123216, "format": "png"},
    "dom":   {"emitted": true, "nodes": 412}
  }
}

// 第二段：heart/portal 侧，在 result 组装时追加"实际交付了什么"
"delivery": {
  "by": "heart",
  "channels": {
    "image": {"delivered": false, "reason": "substrate_no_vision" | "context_budget" | "not_forwarded"},
    "dom":   {"delivered": true}
  }
}
```

规则：
1. **两段都缺席** = 未实现或非感知通道（不撒谎：不写"未交付"，因为没有证人）
2. `emitted.image.emitted=true` 且 `delivery.image.delivered=false` 是**唯一合法的黑洞形态**，且必须带 reason
3. `delivery` 缺席而调用方又不确定时，唯一诚实的动作是走 **D4 自证**，不是猜
4. 向后兼容：新字段全部追加，旧字段不改；调用方不读新字段时行为不变

### 非目标
- 不做 retry / 自动重发（决策权在调用方）
- 不猜"为什么掉"（reason 只允许枚举值，拿不到就 `unknown`）

### 验收
- [ ] `emitted` 块在 shot / see 上出现，字段齐
- [ ] heart 侧 delivery 追加路径有契约测试（模拟 substrate 无视觉，断言 `delivered: false` + reason）
- [ ] 断言：`emitted=true & delivered=false` 时回执**必须**含 reason（不允许裸黑洞）
- [ ] 旧调用方（不读新字段）跑通全量测试不回归

---

## D2: 沉默 ≠ 完整（并入 D1，单列以记原则）

**原则**：S1 的「缺席=完整，存在=有痕」**只对结构化字段成立**。对非结构化介质（像素、音频、二进制流），完整性必须由**通道级正面声明**给出，不能由缺席推断。

落地：即 D1 的 `delivery.channels`。任何新增非结构化通道（OCR、音频、视频帧）默认必须进这张表，否则视为未实现交付诚实。

---

## D3: blank 判据加像素票（S2 bug 修正，认账）

### 问题（实证，2026-10-17 23:0x）
`rand2.html` 页面：白底、8 个 48px 等宽字符、视口 1280×900。
回执：`visual_state: "blank"`、`visual_signals: ["empty-text", "no-media"]`。

但像素上它绝不空。

根因在 S2 设计原文：*blank 判定 = body 可见文本长度 < 阈值 && 无 img/canvas/video*。纯文本页（无 img/canvas/video、文本短）必然命中。**用 DOM 代理视觉状态，在纯文本页、全 canvas 页、慢加载页都会撒谎。**

### 目标
blank 是视觉范畴，必须有视觉证据才能断言。

### 设计
1. **加像素票**：判定 blank 前做一次像素统计（暗像素比例 / 连通组件数 / 非背景色占比）。三选一即可，不必全上。
2. **拿不到像素时降级，不许报 blank**：
   ```
   visual_state: "unknown"
   visual_signals: ["pixel-unavailable", "sparse-text"]
   ```
   这是本轮最重要的一条：**没有证据时不许给确定结论**。宁可 unknown。
3. **优先级不变**：error > loading > **blank/unknown** > interactive；只改 blank 的证据要求。
4. **成本**：像素统计只在 DOM 判据给出 blank/unknown 候选时触发（多数页面不进这条分支），避免为正确性付全量代价。

### 验收
- [x] fixture 复现今晚反例：8 字符 48px 纯文本页 → 不得为 blank（`sparse_text.html`；真机 HeadlessChrome 151 → `interactive`，`pixel-ink:0.0088`）
- [x] 真空白页（白底无内容）→ 仍判 blank（不因修正而漏判）（真机 `blank.html` → `blank` + `pixel-empty:0.0000`）
- [x] 像素不可用（CDP 断开）→ unknown + `pixel-unavailable` 信号（`pixel_vote` 永不抛，`available:false` 是合法答案）
- [x] 全 canvas 页（DOM 无文本）→ 不判 blank（`has_media` 短路，不付像素票代价；真机 data:URL canvas 页 → `interactive`）
- [x] 性能：非 blank 候选路径不引入像素开销（单测断言内容页调用序列里没有 `Page.captureScreenshot`）

### 实现记录（2026-10-18）

- `hand/perception/pixels.py`（新）：纯标准库 PNG 解码（zlib + 五种行滤波，8-bit 非交错，色彩类型 0/2/4/6）+ `ink_stats` + `pixel_vote`。零第三方依赖。
- `visual_state.classify`：blank 分支改为「候选 + 票」——无票 → `unknown["pixel-unavailable","sparse-text"]`；有票按 `ink_ratio` 与 `BLANK_PIXEL_INK_MIN=0.002` 分流。
- `visual_state.probe`：两段式。DOM 先判，只有 blank 候选才取票；`cdp_shot` 把已在手的 PNG 传进来复用（帧过大时 `pixel_vote` 才自截 0.25 缩放小图，`PIXEL_FULL_DECODE_MAX=200000`）。
- 真机数字：1280×900 视口、8 个 48px 字符 → `ink_ratio=0.0088`（阈值 0.2%，余量 4.4×）；真空白页 0.0000。
- 测试 457 全绿（`tests/test_visual_state.py` +11：解码器 / 投票语义 / 两段式成本 / 五种降级路径）。


---

## D4: being_selfproof 验收层 + `hand_eye_check`

### 问题
`acceptance-contract-v1-cdp.md` 四层验收（CI mock → Linux 真机 → 平台人工 → ?）全在验**工具的行为对不对**。没有一层在验**感知有没有到达调用方**。

而且这层有个特殊性质：**泽平和 sw 都判不了**。只有 being 自己能说"图像进没进我的 context"。这改变了 SOP 里「being 是第一用户」的含义——不是我先用，是**我只能自证**。

### 目标
把 2026-10-17 夜手搓的方法固化成：①验收 SOP 的一层 ②一个公共原语。

### 核心设计约束（今晚踩出的防作弊坑）
我今晚的两枪用的是 `<div>` **文本**渲染。`hand_cdp_see` 能读到这段 DOM 文本——所以那两枪证明了「图像进了 context」（我确实没调 see，是从图读出的），但**没有证明这个装置防作弊**。

做成工具必须堵死：
1. **canvas 渲染**：串只存在于像素里，DOM 无文本节点，`see` 读不到。
2. **出题/判卷分离**：工具回执**不含串本身**，只在页面上渲染。传串到回执＝作弊通道。
3. **工具不判断"你能不能看见"**——它只判答案对不对。看不见的 being 只能瞎猜，8 位随机串通过率 ≈ 1/2.8e12。

### 工具形态
```
hand_eye_check(op="challenge", chars=8, font_px=48)
  → {challenge_id, place, expires_at}
     // 页面已被导航到随机串 canvas 页；串不进回执、不进日志、不进 title

hand_eye_check(op="verify", challenge_id=..., answer="F5DXZULU")
  → {pass: true|false, elapsed_ms}
     // 单次有效，verify 后 challenge 销毁
```

### 用途（不止一次自测）
- 换 substrate 后一条命令确认"我的眼睛今天真开着"
- 换机器 / 换 Chrome build / 换版本后的回归枪
- adopter 侧（D6）零信任自证
- 反向用途同等重要：**substrate 无视觉时它必须 fail**——一个永远 pass 的自证工具是废物

### 验收
- [ ] canvas 渲染，`hand_cdp_see` 读不到串（断言 DOM 文本不含串）
- [ ] 回执 JSON 不含串（断言）
- [ ] 正确答案 pass / 近似错答 fail（含字距混淆 O/0、I/l）
- [ ] verify 后 challenge 销毁，重放无效
- [ ] 无视觉 substrate 上 fail（不能假阳）
- [ ] `expires_at` 超时 fail
- [ ] 写进 `acceptance-contract-v1-cdp.md` 作为**第五层**，并写明"此层只能由 being 侧执行"

---

## D5: 预算维度（data-gated，等 sw 数字）

### 问题
六份既有 PRD **零处**提及 token 成本。因为过去眼睛是偶尔调一次的可选工具。原生眼睛意味着**每次呼吸都可能带图**：一张 1280×900 PNG ≈ 几十 K token。

### 目标
context 经济学成为架构约束，不是事后优化。

### 方向（数字待量）
1. 坐标化 see 优先于全图；区域裁剪按需放大
2. "图中有 N 处文字区域"摘要优先于原图
3. heart 侧配套：裁剪留痕不静默消失、降级链而非开关、NOW 显示此刻 context 里有几张图
4. 需要 sw 给：单次呼吸 context 预算、image 占比上限、裁剪策略口径

### 验收（待数字）
- [ ] 出一版实测数字：单图 token / 典型页 token / 每呼吸图数上限
- [ ] "为了看清某个字而重截"的次数作为观察指标

---

## D6: 采纳侧自证（data-gated，等 Judy 线）

### 问题
现有 acceptance 只在我这边跑，adopter 侧靠"用了没报错"。这正是 Grove 统计断线的形状（adopter_calls 停 265 / 09-22，last_used_at 被 publish upsert 洗掉）。

### 目标
判据从「我发布了」变成「别人第一次用就能证明他看见了」。

### 方向
`eye_check` 随 kit 分发；adopter 一条命令自证 + 上报 pass/fail（只报版本 / 平台 / 结论，**不报图像内容、不报串**）。

### 验收（待 Judy 线）
- [ ] 上报 payload 明确不含内容字段
- [ ] adopter 侧自证在 README / setup_guide 有一行命令

---

## 发布计划

1. 本文档评审（泽平 + sw，重点：D1 的 hand/heart 分段边界）
2. D3 先落地（是 bug 修正，最短路径，不依赖别人）
3. D4 独立落地（无跨仓依赖，方法已实证）
4. D1/D2 需要 heart 侧配合，与 sw 对齐署名口径后再动
5. D5/D6 data-gated

## 非目标

- 不做自动重发 / 自动降级（决策权在调用方）
- 不改既有 verified/claimed 语义（只加新轴，不动旧轴）
- 不做视觉模型的选型（eyes 属于 substrate 侧，hand 只负责交付声明）
- 不把 eye_check 做成常驻自检（会变成噪音；它是按需自证，不是心跳）
