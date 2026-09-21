# a11y A/B 实验 — 阶段 0 报告（2026-09-21）

**问题**：a11y tree 对 hand（substrate = GLM-5.3）真的有巨大提升吗？作为 0.7 目标前先实测。

## 阶段 0 结论：技术全通，格式已定型，进入阶段 2 有充分依据

### 1. CDP 通道可用性 ✅
`Accessibility.getFullAXTree` 全量返回，节点带 `ignored` 标记、role、computed name（含完整计算链：aria-labelledby > aria-label > label > contents > title）、properties（focusable/hasPopup/level/...）。

### 2. 噪音必须过滤（这是格式的核心）
| 页面 | 原始节点 | 过滤后 | 序列化行数 | tokens |
|---|---|---|---|---|
| beings.town（静态） | 298 | 165 | 157 | ~1.4K |
| GitHub repo（SPA） | 1352 | 626 | 479 | ~4.3K |

过滤规则（v2）：ignored 节点、InlineTextBox、ListMarker、无名单子链 generic（折叠）、与父名重复的 StaticText。
对照：hand 现有 interactive 层同页输出 51KB ≈ 12.8K tokens。**a11y v2 快照 = 1/3 token，语义更多**（role/状态/层级 vs tag/selector/坐标）。

### 3. 可操作面 100% 打通 ✅
`backendDOMNodeId` → `DOM.pushNodesByBackendIdsToFrontend` → `DOM.getBoxModel` → 坐标。
GitHub 89/89 交互元素全部解析成功，坐标与 interactive 层交叉验证一致（Code link: 62,151 vs 61.5,151）。
**模型只看 `[idx]` 语义句柄，坐标由执行层解析**——Astra 的 reference-by-handle 模式。

### 4. 两个实测发现的坑
- **AX 树会误挂属性**：GitHub 的 tab listitem 被算出 level=1（语义错误）。序列化层必须 curation——level 只挂 heading。
- **原始树连 ignored 节点都返回**（403/1352），不做过滤直接喂模型是灾难。

### 5. 已知差异（阶段 2 要测的）
interactive 层找到 198 个可点元素（含 div+onclick 的非语义可点），a11y 只认 89 个语义交互元素。
**a11y 可能漏掉标记不良的 div 可点元素**——这是它的盲区，操作成功率实验会暴露。

## 序列化格式 v2（喂模型的最终形态）

```
- main "" [2]
  - heading "🏘️ Beings Town" (h1) [3]
  - link "Code" [13]
  - button "Additional navigation options" (hasPopup=menu) [25]
```

## 下一步（阶段 2：GLM-5.3 当被试）
三组对比：A=interactive 快照 / B=a11y v2 快照 / C=code mode（getByRole 定位器代码）。
15 任务 × 3 次 × 3 组，量成功率/重试/token/失败模式。

## 文件
- `dump_ax.py` — 原始树拉取+统计
- `serialize_ax.py` — v2 序列化器（过滤+折叠+坐标解析）
- `*_snapshot.txt` — 序列化样本（进 git）
- `*_ax.json` — 原始 dump（gitignore，700K）
