# hand 0.7 生产测试报告（L1-L6 发布硬 gate）

生成时间：2026-09-21 20:14:55  
重复轮次：3  ·  层：L1, L2, L3, L4, L5, L6  
环境：Python 3.10.12，headless Chrome via CDP localhost:9222

判定纪律：每任务一个程序化 judge；三态 HIT/NEAR/MISS（NEAR 通过但标注）；网络不可达记 SKIP 不算红。

## 汇总表（各轮全量）

| 层 | 用例数 | 通过 | SKIP | 失败 | ERROR | 用时(s) | 结果 |
|----|-------:|-----:|-----:|-----:|------:|--------:|------|
| L1 | 232 | 232 | 0 | 0 | 0 | 3.4 | ✅ 绿 |
| L2 | 10 | 10 | 0 | 0 | 0 | 45.0 | ✅ 绿 |
| L3 | 3 | 3 | 0 | 0 | 0 | 27.4 | ✅ 绿 |
| L4 | 11 | 11 | 0 | 0 | 0 | 60.0 | ✅ 绿 |
| L5 | 15 | 15 | 0 | 0 | 0 | 16.8 | ✅ 绿 |
| L6 | 6 | 6 | 0 | 0 | 0 | 54.0 | ✅ 绿 |

## 逐轮结果

| 轮次 | L1 | L2 | L3 | L4 | L5 | L6 | 全绿 |
|------|------|------|------|------|------|------|------|
| 1 | 232P/0S/0F/0E ✅ | 10P/0S/0F/0E ✅ | 3P/0S/0F/0E ✅ | 11P/0S/0F/0E ✅ | 15P/0S/0F/0E ✅ | 6P/0S/0F/0E ✅ | ✅ |
| 2 | 232P/0S/0F/0E ✅ | 10P/0S/0F/0E ✅ | 3P/0S/0F/0E ✅ | 11P/0S/0F/0E ✅ | 15P/0S/0F/0E ✅ | 6P/0S/0F/0E ✅ | ✅ |
| 3 | 232P/0S/0F/0E ✅ | 10P/0S/0F/0E ✅ | 3P/0S/0F/0E ✅ | 11P/0S/0F/0E ✅ | 15P/0S/0F/0E ✅ | 6P/0S/0F/0E ✅ | ✅ |

**发布 gate：通过（L1-L6 全绿 × 3 轮）**

## SKIP 明细（有理由不计红）

（本轮无 SKIP）

## 失败明细（应为空）

（无失败）

## 发现与已知缺口

1. **route_do 不回退到 cdp_type（`[idx]|text` 不可达）**：route_do 在第一个 backend 返回失败回执时即返回（`result.get('success', True)` 对无 success 键的失败回执判真）。回执本身诚实（verified=False + reason），非假 ok；公开流程（click 聚焦 → cdp_type）正常。L4 `test_route_do_with_text_form_never_silently_passes` 就此设回归护栏。
2. **cdp_close 曾是假 ok（已修）**：`Browser.enable` 无此方法，异常被吞，Browser.close 从未发出却回 closed=ok。已改为关闭后轮询端点 + verified 回执（commit da1919a）。L6 崩溃/关闭测试覆盖。
3. **manifest 与 route_see 的 kind 不完全一致**：route_see 支持 kind='vlm'，manifest cdp_see enum 未列；manifest 列了 kind='screenshot' 但 route_see 无显式分支（会落到 place 默认）。旧调用者不受影响，L5 `test_unknown_kind_does_not_crash` 兜底。
4. **回执无 timestamp/status 字段**：本仓库 F14 契约（docs/prd-receipt-contract.md S3）定义的回执形状是 verified:bool + evidence:{...} + 结果字段（open/method/closed），不含 PRD-test-framework 文字里的 status/timestamp。L4 按实际 F14 契约扫描；若需要时间戳，属产品增量而非测试缺口。
