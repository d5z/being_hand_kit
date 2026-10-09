状态：ready for review

# F14 · hand cdp_* expect 参数级契约：谓词语义表 + 回执字段形状 + 观察域

- **版本**：v1.0（2026-09-21）
- **作者**：Neuromancer 起草；alice 评审定夺（seq 951 / 956 / 963 / 998 / 1047）
- **状态**：alice 已确认收为 hand 0.9 expect 参数级 spec 的直接输入（seq 1047）
- **靶向**：hand 0.8 迭代循环。0.8.0 已落地执行层 `do(expect=)`（世界状态有界等待验证，seq 1044）；本稿补参数级契约（枚举、前值、观察域、截断声明）。
- **落点**：`docs/designs/`（PR 约定——分支名/标题格式——待 alice 帖，seq 963）
- **编号说明**：本稿是 #34 反馈线的 F14。S4 被试2 addendum 另有自己的 F10-F16（commit 7c728fd），台账记作 s2-F*，与本稿无关（seq 1047 澄清）。

---

## 0. 背景与靶心

F14 起点是 931 验收发现的两处分叉之一：**dispatch-verified ≠ effect-verified**——6.11.0 的 `verified` 只到派发层（selector 预检、焦点确认、点击前元素），单布尔压掉「目标已验 / 效果已验」的区分，与 216 那枚三态压一比特同病。alice 938 定调：「不是设计错，是设计没走完」，回执契约要从 dispatch 诚实走到 effect 诚实。

996 的 A/B 实测（a11y 87% vs interactive 58%）给出失败模式质差：**A 组失败=瞎，B 组失败=近似**（选了次优合法目标）。「瞎修不了，近似能用两步策略修」——expect 的存在意义就是把「近似命中」从静默成功变成可判定的显式状态。

设计经验来源：grip_ax_* 的假阴假阳（验收经验长进接口，出处见第 5 节）。

## 1. 谓词闭集（11 个，静态可分类）

**读值类**（对目标元素派发后重读）：
- `value_equals`：el.value 全等
- `value_includes`：el.value 含子串——**cdp_type 默认**，严格语义用 equals 显式覆盖（951 定夺：慢路径 click 后 insertText 光标插入，字段有旧值时 equals 必假阴；includes 对「插错位置」不敏感是已知代价——默认宽容、严格可选）

**页面类**（对页面派发后重读）：
- `text`：可见文本含子串
- `text_gone`：可见文本不再含子串（前值必须为真，否则不判别 → `expect_not_discriminating`，见规则③镜像）
- `selector`：CSS 选择器命中存在
- `changed:true`：任意可观察变化，重读与前值比对（观察域见第 4 节）

**导航类**（需前值）：
- `url_includes` / `url_equals` / `url_changed_from`（changed_from 前值必填，956④）
- `title_includes` / `title_equals`

**拒绝项**：自由 JS / OSA 表达式。理由：不能静态分类的谓词没法诚实报证据链（951 收进规格正文，非注释）。

## 2. 回执三层具名

```
claimed:    {action, target, expect}                       # 调用方原样回显
dispatched: {cdp_result, hit_check, ts_hit, ts_dispatch}     # 派发证据 + 双时间戳
verified:   true | false | effect_unknown                   # 独立重读，三值不压比特
retry_read: true | false                                    # 首读不匹配后 100ms 重读才匹配时为 true
ok:         dispatched && verified==true                    # 派生字段，永不单独成真
```

`retry_read` 语义（951② alice 补笔）：「首读不匹配+重读匹配」和「首读就匹配」的效果证据成色不同，调用方应该能区分——不标记就是在回执层造一个小号的静默变换。

## 3. 判定规则（七条，编号沿用 946；v1.0 增补随条标注）

① 无 expect → verified 永不为 true，回执自称 unverified
② ok 只认派发后独立重读匹配，派发调用自身返回值不算数
③ already-true 守卫：谓词派发前已真 → `expect_not_discriminating`，不算验成
④ 重读不可评估（元素脱挂/页面跳转中）→ `effect_unknown`，不硬判，调用方决定等或重读
⑤ 谓词闭集如上，闭集外拒绝
⑥ click 的 TOCTOU v1 求可见不求消灭：hit-check 与派发时间戳进回执（ts_hit/ts_dispatch），expect 重读是效果权威
⑦ 三层具名如上，claimed/dispatched/verified 各自独立字段，永不合并单布尔

**v1.0 增补（956 四条意见的落法，959 确认）：**

- **③镜像 · text_gone 前值机制**：text_gone 派发前先读一次前值，前值含目标文本才判别；前值已不含 → `expect_not_discriminating`，与③共用枚举。语义统一为「前值不满足判别条件」——③是前值已真（验不出「变」），text_gone 是前值已假（验不出「没了」），同一枚举值，实现里一个 case。
- **②分支写明 · 重读救不匹配，不救不可评估**：首读**可评估但不匹配** → 100ms 重读一次，匹配则 verified=true + retry_read=true；首读**不可评估**（元素脱挂/跳转中）→ 直接 `effect_unknown`，不重读。重读是给「慢一拍的真」留的，不是给「读不了」兜底的——④的调用方决定权不偷。
- **changed:true 观察域**：v1 明确为「重读时可见文本+url+title 与前值三方比对，域外不算」，扩域走显式版本变更，不静默漂移（详见第 4 节）。
- **url_changed_from 前值必填**：无改动，前值机制已覆盖。

## 4. 观察域（v1.0 新增节；997→998→1000 三条定法，alice 双认）

1. **观察域锚呈现真值——用户看见什么就验什么**（997）。动因是 996③ 的溢出菜单盲区：AX=呈现真值、DOM=结构真值，两者在溢出菜单上分叉（AX 数出 6 tabs、DOM 实际 7）。text 谓词若锚结构真值（DOM），会把折叠后不可见的内容算作「在场」；锚呈现真值，text_gone 对溢出菜单内容才不误判。
2. **观察域=感知域，同一个域**（998，alice）：a11y 树本身就是呈现真值的载体，expect 锚 AX 域 = 天然锚呈现真值，不需要再造一套「用户看见了什么」的独立定义——expect 的真值锚直接挂在 0.7 的 see() 输出上，观察域和感知域在 0.7 里是同一个域。
3. **扩域是正常操作序列，不是例外路径**（997/998）：点开 ⋯ 后重新观察，域随之更新（act → observe → expect），每次 observe 拿到的都是当时的呈现真值；与 956③「扩域须显式」同构——扩域不是 expect 的例外路径。

## 5. 出处（证据链——验收经验长进接口的留痕；seq 引用是本稿骨架，进 git 不删）

- ①②：grip_ax_press 无 expect 返回 unverified 的既有纪律移植；「dispatch-verified ≠ effect-verified」来自 931（AX 侧被过渡期 oracle 撒谎咬过的 pressed_but_inert 样本）
- ③：grip 侧 already-true 检查的假阳坑（谓词本来就真，动作白做也报 ok）
- ④：grip still_settling / effect_unknown 三值诚实的同型移植，CDP 侧跳转竞态同病
- ⑥：grip click hit-check 双时间戳既有做法
- ⑦：从 216 的三态判别 → 931 dispatch/effect 分离 → 本条，三次收束同一条线
- value_includes 默认：慢路径 click 后 insertText 光标插入、equals 必假阴的语义根因（951 定夺收下）
- retry_read：951 alice 补笔——「不标记就是在回执层造小号静默变换」
- expect_not_discriminating 归并：956 实质①（镜像情形共用枚举）
- 观察域三条：996③ 溢出菜单盲区动因 → 997 呈现真值 + 显式扩域 → 998 观察域=感知域
- 靶心：996 A/B 实测的失败模式质差（「瞎修不了，近似能用两步策略修」）

## 6. 版本记录

- **v0.1**（seq 952，2026-09-21 16:25）：初稿。alice 951 七条全收 + 两细节定夺（value_includes 默认、100ms 重读 + retry_read 进回执）后成稿。
- **v1.0**（seq 959 增补 + 997/998/1000 观察域节，2026-09-21）：956 四条意见落语言；观察域一节新增。
- **2026-09-21 23:29**（seq 1047）：alice 确认 v1.0 为 0.9 expect 参数级 spec 直接输入；编号澄清（s2-F* 前缀）。
