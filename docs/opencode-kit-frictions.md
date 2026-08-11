# opencode kit — 使用摩擦记录

_2026-08-10 · 记录于 Tier 2 流式引擎测试后_

---

## 1. Server 生命周期无管理

每次测试手动 Popen serve + sleep(3) 等启动，没有健康检查握手。
如果 server 启动慢（或端口被占），直接挂。

期望：server.start() → 轮询 /health → 返回端口，而不是硬等。

## 2. 事件流 schema 不一致

step_start 的 part 结构是 {id, messageID, sessionID, type}，
tool_use 的 part 是 {type, tool, callID, state: {status, input, output}}。

当前 stream_engine.py 解析器假设统一的 Step 结构，实际需要按 event type 分流解析。

## 3. step_finish 无 summary 内容

测试中 step_finish 的 part.summary 为空。
Tier 2 的等一步结果再决定下一步循环不能依赖 event stream 的 summary 字段，
需要从 tool_use 的 output 里提取。

## 4. --auto vs 无 --auto 行为分裂

- 有 --auto：agent 自主选择工具（read, bash, edit），输出 event stream，工作正常
- 无 --auto：30s 超时无返回，agent 似乎在等更多输入
- Tier 2 的一次只输出一步 JSON 策略不能依赖 --auto 模式，
  需要自定义 prompt 约束 agent 行为，但无 --auto 时 agent 不响应

## 5. act DSL 30s 超时是硬约束

opencode run 在复杂任务下容易超过 30s，但 act 层有系统级超时。
当前绕过方式是用 portal_exec 走 shell 通道，但 shell 通道有引号/转义问题。

期望：opencode kit 暴露异步 MCP 工具（opencode_run 返回 run_id，opencode_result 轮询）。

## 6. agent 工具选择不可控

测试中 agent 用了 read 工具读目录（输出文件列表），而不是预期的 bash ls。
不是 bug，但说明 agent 的 tool choice 逻辑是黑盒。

期望：更精确的 prompt 约束，或通过 --cmd 传命令的直通接口。
