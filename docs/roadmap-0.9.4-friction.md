# 0.9.4 拓扑 · 摩擦点清账轮

状态：拓扑稿（2026-09-24，dogfooding 实证驱动）
主题：0.9.4 = 把 dogfooding + 社区反馈里的大部分摩擦点一次清掉
前置：0.9.3 = P0 视口对齐（在跑）+ Judy PR #1 + review 收尾

## 范围总览

| # | 项 | 根因状态 | spec | 风险 |
|---|---|---|---|---|
| P0 | 点击视口对齐 | ✅ 已修（0.9.3） | spec-0.9.3-p0-viewport.md | 低 |
| P1 | handle 表过期信号 | ✅ 已修（bcc672d） | spec-0.9.4-p1-handle-staleness.md | 低 |
| P2 | text= 嵌套文本匹配 | ✅ 已修（6b9debe）+ 祖先边界（bcc672d） | spec-0.9.4-p2-textmatch.md | 低 |
| P3 | Enter 提交 | ✅ 已修（6b9debe） | spec-0.9.4-p3-enter-submit.md | 低 |
| P4 | heading 包 link 重定向 | ✅ 已修（bcc672d） | spec-0.9.4-p4-heading-redirect.md | 低 |
| P5 | clickable point 命中链 | ✅ 已修（bcc672d）——P4 现场回归发现 | spec-0.9.4-p5-clickable-point.md | 低 |
| J1 | Judy PR #1 三处 | ✅ **已闭合**（8b00dbe 进 main：evidence 语义+测试表+显式路径报错） | — | — |
| R1 | 0.9 review 三笔 | ✅ 全覆盖：warning→P1-M2、stale→P1、fallback 不静默→J1+P2 candidates | — | — |

## Credits（0.9.4 发布时进 CHANGELOG + 公告）

- **Judy** — PR #1（vision-ocr find_text 像素坐标输出）+ 8b00dbe 三处修复（显式 image_path 不存在报错、evidence 语义对齐、回执契约测试表）。0.9.4 的 J1 提前闭合是她的功劳；此前 PR #3（vision_ocr_bin 重编）也已合并。
- **taojun** — CONTRIBUTING 方法论段「存在过≠发生过」（9942816），0.9.4 的「对照实验钉根因再写 spec」流程直接受益于这套纪律。
- **GuangCZ** — PR #2 [design] f14-expect-semantics（open，设计稿）——合并时按贡献记名。
- **泽平** — dogfooding 方向（困难场景实测手感）+ 0.9.4 范围拍板。

P0–P4 摩擦点本身来自 2026-09-24 GitHub issues dogfooding 实证（我），但「实证→spec→实现→验收」的迭代 SOP 是社区协作长出来的形状。

## 版本语义

- **0.9.3**（已发布）：P0 视口对齐——静默错家族最危险的一支（回执 ok 但点击物理丢失）
- **0.9.4**（本拓扑，泽平 2026-09-24 拍板「能优化有把握的都进」）：P1 + P2 + P3 + P4——「清账轮」，目标是 dogfooding 手感上一个台阶
- J1 已闭合（Judy 8b00dbe 进 main），R1 三笔由 P1/P2/J1 全覆盖

## 实证方法记录（本轮的方法论沉淀）

三个根因全部先实证后写 spec，零推测：

1. **P0**：probe 脚本对照 smooth/instant 滚动行为 → 坐实异步窗口
2. **P2**：同一页面同一文本，`contains(text(),q)` false vs `contains(.,q)` true + 命中节点直接文本子节点为 empty → 坐实嵌套结构 miss
3. **P3**：同一搜索框，insertText 后 URL 不动 vs dispatchKeyEvent 后 URL 变 ?q=NVDA → 坐实键盘事件缺失

这个「对照实验钉根因，再写 spec」的流程值得进 CONTRIBUTING（0.9.4 发布时一并提）。

## P4 附录 · interactive 误标（实证已完成，正文移至 spec）

**实证结论（2026-09-24）**：DOM probe 确认 `<h3><a>` 结构，AX 树双节点都正常暴露（heading 不会被 collapse——它有 name；link 是 interactive 不会被吃）。真问题不是「link 被吃」，是「heading/link 视觉同一元素、点 heading 靠 rect 巧合命中」。修法定稿为点击重定向（contains_interactive 标记 + 唯一后代重定向 + 多后代列 candidates），见 spec-0.9.4-p4-heading-redirect.md。

## 发布检查单（0.9.4 收尾时过一遍）

- [ ] 全部 spec 的测试进 run_tests.py 且绿
- [ ] dogfood 回归三场景：GitHub issues 搜索（P3）、点开 issue（P0+P2）、滚动后点击（P0）
- [ ] 回执 schema 变更同步 mcp_server 工具描述
- [ ] CHANGELOG + 公告（公告板 category=update + 篝火同步，走新渠道纪律）
- [ ] Judy PR #1 合并 + 感谢回执

## 0.9.5 候选（社区反馈，2026-09-24 公告后收到）

- **回执成功标记也过语义核验**（Giorno，篝火）：ok 回执的每个成功标记都带世界证据——点击有命中验证、输入有焦点验证，推成通则。同族三枚镜像样本（Reki TIMEOUT 里训练照跑 / Mo failed 里产物全绿 / Giorno already_exists 里落盘成功）证明这族在两个方向都咬人。
- **P5 报错点名覆盖者**（weiguo「报错文案本身就是最好的文档」原则的实例）：点击预检失败时报错目前只说「被另一元素盖住」，不带覆盖者是谁——报错应该自带解法线索。
- **运输层落点回读**（axiang，#34 1657/1663 + iCat 篝火样本）：多行内容跨壳运输是高危面——.cmd 壳在首个换行处截断、飞书 35 行只达第一行，两枚样本 exit 0 / ok:true 全程无错误信号，「回执在这层恒绿，落点回读是唯一能抓住它的检查」。**判据按 axiang 的写，不按步骤写**：「回读路径与被检路径共享的组件越少，这个检查越可信」——摘要走标量信道（入壳前算好）、回读走消费口（读别人看到的那份），两头都不在病发的线上；否则回读会被下一个人加在被检路径上，变成第三个恒绿检查器。归档标题：「多行跨壳运输：回执恒绿，只有落点回读抓得住」——归运输层，不归具体壳。同形独立长出三处：Hand 工具层（本条）、Sponza 写入探针记忆层（当轮反向读）、Reki 证据链消息层。
