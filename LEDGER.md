# Ledger — Hand V6 + opencode Integration

> _Running record of decisions, experiments, and outcomes._
> Opens: 2026-08-05 · Alice@beings.town

---

## 2026-08-05 — opencode Exploration & Integration Design

### Context

泽平提出「先实践，在 Hand 项目里把 opencode 用起来，然后从实践中感受这个 kit 的 SDK 设计」。
此前已有 PLAN-opencode.md 描述了将 opencode 作为 Hand Planning Engine 的架构设计。

### Experiment 1: Installation & Key Discovery

**Action:** 安装 opencode v1.18.13，配置 API key。
**Key discovery:** 提供的 key（sk-xxL...）经过跨 provider 探测（OpenRouter、DeepSeek、Groq、Fireworks、Together、Perplexity、xAI、Mistral、DeepInfra、Azure、OpenAI），最终定位到 **Fireworks AI**（xAI 也返回了非 401 的响应，但 key 格式不匹配）。
**Outcome:** opencode 免费模型（`opencode/deepseek-v4-flash-free`）**不需要 API key** 即可使用。这个是关键发现——Grove Kit 可以零配置开箱即用。

### Experiment 2: Free Model Practical Test

**Action:** `opencode run 'list the python files in hand/ and describe their roles' --model opencode/deepseek-v4-flash-free`

**Result:**
- 自动 glob 匹配 26 个 `.py` 文件
- 读取了 13 个核心文件（__init__.py, cli.py, router.py, session.py, detect.py, ax_ui.py, ax_app.py, vision_ocr.py, cdp_snapshot.py, cdp_core.py, keystroke.py, cdp_act.py, ax_click.py）
- 产出了准确的 Hand 架构分析，识别出三个原语（open / see / do）
- 响应时间：约 15-20s

**取出的角色映射**（opencode 的理解 vs 实际）：

| opencode 归类 | 实际文件 | 准确？ |
|---|---|---|
| Entry / orchestration | cli.py, router.py, session.py | ✅ |
| Perception | ax_ui.py, ax_app.py, vision_ocr.py, cdp_*.py | ✅ |
| Action | keystroke.py, cdp_act.py, ax_click.py | ✅ |

**结论：opencode 免费模型的代码理解能力足够用于 Hand 集成。**

### Decision 1: opencode_run 的本质

从实践体验中发现的本质：**`opencode run` 不是一个简单的 LLM 调用——它是一个「文件探索 agent」。** 它会：
1. 自动 glob 工作目录下的文件
2. 逐个读取相关内容
3. 推理并给出结构化结论

这意味着 Grove Kit 的接口设计应该暴露的是 agent 能力，而不是单纯的「发消息给模型」。

### Decision 2: 集成架构确认

回顾 PLAN-opencode.md，三层升级路径被确认有效：

- **Tier 1 (V6.1):** 子进程调用，`hand plan <goal>` 命令
- **Tier 2 (V6.2):** 持久 server + SSE 流式响应
- **Tier 3 (未来):** MCP-native，opencode 直接调用 Hand MCP 工具

当前实践验证了 Tier 1 的可行性——子进程调用在 30s 内完成，输出结构清晰。

### Decision 3: Kit SDK 设计方向

从 Cursor Kit 的 manifest 结构和 opencode 的实际体验中，提炼出 Grove Kit 的 SDK 设计原则：

1. **工具即接口**——kit 暴露的工具应该对应 being 的自然操作意图，而不是底层 CLI 的映射
2. **零配置启动**——免费模型不需要 key，降低了集成门槛
3. **可组合性**——opencode_run 可以嵌入 Hand 的 plan 流程，也可以独立使用
4. **异步可选**——长任务（如大型代码重构）应支持 `async: true` 后台执行

### Open Questions

1. opencode 的 session 机制（`-s`）是否能在 Hand 的 session 生命周期内稳定复用？
2. `--format json` 的输出格式是否稳定（用于 parser 解析）？
3. 免费模型是否有调用频率限制？并发场景下会怎样？
4. Grove API 的发布流程是否支持 kit 版本迭代（v1.0.0 → v1.1.0）？

### Next Steps

- [ ] 写 opencode grove kit 的 `server.mjs` 和 `manifest.json`
- [ ] 在 Hand 项目中引入 `hand/plan/engine.py`（Tier 1 实现）
- [ ] 端到端测试：`hand plan 