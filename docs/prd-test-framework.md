# PRD: hand 0.7 生产测试框架（发布硬 gate）

**背景**：hand 0.7 是给全镇 beings 的生产环境 kit。L1 单元测试绿 ≠ 生产可用。今天 a11y A/B 实验证明了一件事：**判定必须程序化**（judge 函数），不能靠人眼「看起来对了」。测试框架就是这个纪律在发布侧的落地。

**核心资产复用**：`experiments/a11y_ab/` 的 runner 已经验证了「真实 Chrome + 程序判定 + 可复现」这条路——把它从「模型答题评测」改造成「kit 功能验证」。

## 分层设计

### L1 单元（已有，S1-S7 各块自带）
模块级，mock 依赖。跑得快，commit 前。

### L2 集成 — 真实 Chrome 单工具全链路
每工具一个场景，真实 Chrome（headless），验证完整调用链：
- `open` → navigate_confirmed 回执带证据链（URL 命中）
- `see(kind=a11y)` → 树结构合法（有根、有 [idx]、截断标记正确）
- `see(kind=interactive)` → 旧格式仍工作（向后兼容）
- `click` → 回执带 target 命中证据（不是假 ok）
- `type` → 回执带输入内容验证
- `shot` → 返回真实 PNG
- `close` → 资源释放，无残留进程

### L3 场景 — 真实站点端到端用户旅程
模拟 being 真实用法，跨工具组合：
- **beings.town 旅程**：open → see(a11y) → 找到篝火入口 → click → see 验证页面切换
- **github 旅程**：open repo → see → 找 Issues tab → click → see 验证
- **表单旅程**：type 进输入框 → 回读验证内容真实落进去
- **判定**：每步一个 judge 函数（从 a11y_ab 移植），程序判定三态

### L4 契约 — 回执契约全量扫描
0.7 的核心是回执契约（F14）。这层验证每个回执：
- 必填字段齐全（status, evidence, timestamp）
- 证据链真实（navigate_confirmed 的 URL 必须真的命中目标域；click 的 selector 必须真的存在于当前 AX 树）
- 三态判定正确（命中/近似命中/失败，失败必须带原因）
- **假 ok 检测**：故意制造失败场景（坏域名、不存在元素、超时），验证回执不撒谎——这是 3339b7f 教训的制度化

### L5 兼容 — 升级路径
现有用户（taojun、cz_being 等装了 6.11 的）升级到 0.7：
- 旧调用形状（不带 kind 参数）→ 应 fallback 到新默认并给出提示，不 break
- profile 策略切换：isolated 默认下，旧 persistent 用户行为变化是否有清晰报错/提示
- manifest 升级路径：6.11 → 0.7 版本线重置，grove 更新是否干净

### L6 稳定性 — 边界与恢复
- Chrome 崩溃恢复：kill Chrome 后再 open，应能重新拉起
- 页面超时：慢页面不挂死，超时回执要诚实
- 重 SPA 大树：AX 树截断策略生效（>N 节点触发截断标记）
- 连续 20 次调用无泄漏（进程数、内存）

## 判定纪律（从 a11y 实验继承）

1. **每任务一个 judge 函数**，程序判定，不靠人眼
2. **三态输出**：命中 / 近似命中（带证据）/ 失败（带原因）
3. **可复现**：同场景同结果，跑 3 次全绿才算绿
4. **失败即证据**：任何 L2-L6 失败，报告必须带完整调用链和回执原文

## 执行结构

```
tests/
  run_tests.py              # L1（现有）
  integration/              # L2
  production/               # L3-L6
    test_scenarios.py       # L3 真实站点旅程
    test_receipt_contract.py # L4 契约扫描
    test_compat.py          # L5 升级路径
    test_stability.py       # L6 边界恢复
  harness/
    judge.py                # judge 函数库（a11y_ab 移植）
    scenarios.py            # 场景定义（数据驱动）
    runner.py               # 统一 runner：跑场景 → judge → 三态报告
```

## 发布 gate

0.7 发布条件：**L1-L6 全绿 × 3 次重复**。任何一层红，发布阻塞，红点进 feedback ledger。

## 与 astra 线的呼应

这个框架本身就是 expect 契约的最大用户——用程序判定验证程序判定，自举。而且 L3 场景积累的 (state, action, judge_result) 就是后训练要的轨迹数据雏形：测试框架跑的每一步都是可复现的 (s, a, r) 样本。
