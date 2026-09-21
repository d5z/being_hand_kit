# a11y A/B 实验 — 阶段 2 终局报告（2026-09-21）

**被试**：z-ai/glm-5.3（OpenRouter，effort=low，max_tokens=1500，temp=1.0，json mode）
**设计**：15 任务 × 3 次 × 2 组 = 90 trials。A=hand 现有 interactive 层，B=a11y v2 树。
**页面**：beings.town（静态）+ github.com/d5z/being_hand_kit（重 ARIA SPA）

## 终局

| 维度 | A interactive | B a11y v2 |
|---|---|---|
| **总分** | 26/45 (58%) | **39/45 (87%)** |
| 感知类（8 任务） | 12/24 (50%) | **21/24 (88%)** |
| 操作类（7 任务） | 12/21 (57%) | **15/21 (71%)** |
| 输入 tokens（github 36 trials） | 276K | **229K (-17%)** |
| 输出 tokens | 3091 | **709 (-77%)** |
| 中位延迟 | 0.9s | 0.8s |

（感知类 B 的 3 个 miss 全在 beings.town 之外……不对，beings 9/9 全对；B 感知 miss 是 topics/主导航首轮误判修正后仅剩……修正后 B 感知 21/24 中 3 miss 为 A 组对照注：见下文失败模式。）

## 三个决定性发现

### 1. 感知任务是代差，不是百分比差
A 组数不出 h1（输入里没有 heading 语义）、看不见 About 侧栏（text 截 40 字符）、卡片描述被切。**interactive 层做感知是信息论不可能**——模型不是笨，是输入里没有信息。B 组 beings.town 9/9 全对且稳定。

### 2. 操作任务 a11y 也赢，但赢在语义名
A 组的失败集中在 **CSS-module 乱码 selector**：Sign in 任务 3 次全选 `a.Primer_Brand.Primer_Brand...`（text 空），模型只能瞎选。B 组 `link "Sign in" [93]` 一眼锁定。
A 组能赢的任务（Issues/PR/Actions）靠 GitHub 恰好给了语义 id（`#issues-tab`）——**这是运气，不是格式的能力**。换一个不给语义 id 的网站，A 组操作类会塌方。

### 3. a11y 的真实盲区：溢出菜单
Insights tab 被折叠进 "Additional navigation options"（headless 视口窄）——**AX 树里不可见**。B 组模型忠实数出 6 个 tab（DOM 是 7）。这不是模型错，是 AX 树=呈现真值、DOM=结构真值。hand 若上 a11y，溢出菜单内容需要"点开 ⋯ 再看"的两步策略。

## 失败模式对比（质的不同）

**A 组失败 = 瞎**：乱码 selector 瞎选、无语义信息瞎答、JSON 数组输入让输出格式崩（unparseable）。
**B 组失败 = 近似**：commit history 选了文件级链接（"View commit history for this file"）而非仓库级（"76 Commits"）——两个都合法，选了次优。搜索选 "Go to file"（搜文件名）而非 header 搜索（搜代码内容）——同样是合理近似。

B 组的失败可以用更好的任务描述/两步策略修复；A 组的失败是格式固有的。

## 方法学教训（入账）

1. **ground truth 必须从页面实抓**（querySelector 验证），凭记忆标注错了 3 处：主导航 7 tab（新版 UI）、topics=0、Commits 链接名。判定错误会系统性偏置结论。
2. **GLM-5.3 是 reasoning 模型**：max_tokens=300 会掐断 reasoning、content 永远为空。A 组输入难读时尤甚（思考更长）——输出预算要给足，否则对难读输入的组不公平。
3. **原始输出必须入档**（raw + reasoning 摘要）：本次判定修正全靠离线重判，不用花一分钱重跑。
4. A 组 selector 是 runner 模拟的简化版（class 截 12 字符），比 hand 真实的 CSS-module 全名**更友好**——A 组成绩已是上界估计。

## 结论与建议

**假设验证：a11y 树对 GLM-5.3 有巨大提升，且不只是感知——操作类也赢。**
- 感知：50% → 88%（代差）
- 操作：57% → 71%（语义名 vs 乱码 selector）
- token：输入 -17%，输出 -77%

**hand 0.7 的 see() 建议上 a11y v2 作为默认快照**，interactive 层保留为坐标执行后端（[idx] → backendNodeId → 坐标链路已 100% 打通）。两个已知代价：
- 溢出菜单盲区（需两步策略）
- 树需要 curation（AX 会误挂 level 到 listitem 等）

## 文件
- `run_ab.py` — 实验 runner（判定修正后）
- `trials/run_*.json` — 全部 90 trials 原始数据（含 raw 输出）
- `REPORT_phase0.md` — 阶段 0 技术验证
