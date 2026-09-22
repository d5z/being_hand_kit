# Contributing

hand 的反馈与迭代入口在 Beings Town 围炉 #34（hand 炉）。修 bug / 提 PR 前先看 `docs/feedback-ledger.md` 里已登记的 F 编号，避免重复。

## PR 规范

### 1. 测试全绿

`python3 tests/run_tests.py` 必须全绿。新增功能配套新增测试。

### 2. 改编译产物源码的 PR（重要）

如果你改了带编译产物的源码（当前唯一一例：`hand/perception/vision_ocr.swift` → `vision_ocr_bin`），**必须二选一**：

- **配套提交重编后的 bin**（macOS：`swiftc -o hand/perception/vision_ocr_bin hand/perception/vision_ocr.swift`），或
- **在 PR 描述里显式声明「bin 需发布时重编」**，让维护者知道。

背景（F18 / Judy 1166-1172）：改源码不重编 bin，运行时走旧逻辑，Python 端 old-format fallback 静默接住旧输出——bounds 丢失无声。发布侧与 PR 侧两边都默认「对方会处理」时，静默降级就发生。0.8.3 曾中招（macOS adopter）。

### 3. 回执契约

hand 的核心原则：**降级必可见，可见在回执里**。任何 fallback / 截断 / 降级路径，警告必须进返回值（`warning` 字段），不能只进 stderr——kit 场景 stderr 只进日志，不进 being 的回执视野。

### 4. 提交信息格式

`type(scope): summary`，例：`fix(perception): vision_ocr stale bin detection`。

## macOS adopter 自检（0.8.3 已知问题）

0.8.3 的 `vision_ocr_bin` 是旧源码编译（bounds 输出缺 tab 分隔坐标）。自检方法：

```bash
./hand/perception/vision_ocr_bin <任意截图路径>
```

- 输出含 **tab 分隔的坐标**（`0.95\ttext`）→ 新 bin，bounds 可用
- 输出是**单冒号格式**（`0.95:text`）→ 旧 bin，bounds 不可用，重跑 `swiftc -o hand/perception/vision_ocr_bin hand/perception/vision_ocr.swift`

0.9 起代码内建 stale 检测（fallback 触发时回执带 `warning` 字段）。
