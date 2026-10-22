# Changelog

## [0.13.2] — 2026-10-22

> 0.13.1 修了平移，没修仿射。`iframe{transform:scale(0.5)}` 上实测：`see` 画在 (112, 89)，`click` 派发 (123, 126) —— 平移做了，缩放被静默丢掉。回执仍然是 `landed=true`，页面没动。**同一个 bug 的第二层，同一个回执形状。**
>
> 根因是同一条：`click` 从帧内读了一个点，然后自己想办法把它搬到顶层。只要「搬」是我写的，就永远有下一层没写对的变换。这一版不再搬——派发点直接取元素自己的 border quad（顶层坐标、浏览器已经把 transform 算完），帧内点用双线性映射过去。

### Fixed
- **子 frame 内节点的派发点改由 `DOM.getBoxModel` 的 border quad 决定**。quad 就是 `cdp_see` 画图用的那一次读数：一个来源，一个空间，回执与画面在构造上不可能再各说各话。双线性在平行四边形上对任意仿射变换精确（平移/缩放/旋转/斜切），所以不需要为每种 transform 单独写算式。
- **帧原点降级为诊断信息**。`evidence.frame.origin` 仍在（它说明帧坐在哪里），但不再参与派发；新增 `evidence.frame.mapping` 写明这次用的是哪条路径（`element border quad (bilinear, top-level)` 或 `same space (main frame)`）。帧原点读不到时不再拒绝点击（quad 才是权威读数），quad 读不到才拒绝。
- **回执里的 `bounds`/`center`/`w`/`h` 也从 quad 算**，所以点完看到的框与 `see` 报的框是同一组数——不再有「回执说框在这、画面说框在那」的可能。

### Verified
- `tests/test_iframe_transform.py`（新）：行为证明。0.5 缩放夹具上，`dispatched` 与 `see` 的 centre 相差 ≤1px，且点完**子 frame 真的跳到 B**（不看回执）。另有四条纯数学用例把双线性钉住：平移、缩放、90° 旋转（局部中心映射到 quad 中心）、零尺寸不除零。
- 同一夹具在 0.13.1 上复现失败：`dispatched=[123,126]` vs `see=(112,89)`，`effected=no_change`，frame URL 不变。
- 全套 621 tests 绿。

## [0.13.1] — 2026-10-22

> 一处坐标系错配。0.13.0 把子 frame 的节点并进了 a11y 树，`see` 画对了像素；但 `click` 用另一条读法重新量了一遍那个元素，量出来的是**帧内坐标**，然后按顶层坐标派发。iframe 在 (8, 59.4) 的夹具上，这是一步 61px 的偏差：点落在 frame 自己的 padding 上，frame 不跳转，回执写着 `result=ok / resolved=true / landed=true`。
>
> 这一版没有新增能力，只是让「看见的那个点」和「点下去的那个点」变成同一个点。

### Fixed
- **子 frame 内节点的点击坐标换算**。`getBoundingClientRect`（`_handle_rect`）与 `elementFromPoint` 探针（`_clickable_point`）都在**节点自己那个 frame 的坐标系**里取值；`Input.dispatchMouseEvent` 要的是顶层视口坐标。现在统一在 `cdp_click_handle` 里换算一次：`_dispatch_offset` 读出节点所属 frame，`_frame_content_origin` 用 `DOM.getFrameOwner` + `DOM.getBoxModel` 取该 frame **content box** 的左上角（边框/内边距已排除），提示点加上它再派发。
  - 实测口径：`DOM.getBoxModel` 对 frame owner 返回的**已经是顶层视口坐标**——两级嵌套夹具（frame 在 (100,50) 里再套一个 (20,30) 的 frame）报出的是 (120,80)，不是 (20,30)。所以任意嵌套深度只要查一次，不需要逐级求和。
  - 反过来，`DOM.describeNode` 对元素节点**不返回 `frameId`**（2026-10-22 实测），所以 frame 身份不能现查——由 `cdp_see` 写进 handle map（新增 `frame_id`）。
  - 换算失败时**拒绝派发**并说明原因：「element lives in child frame X but its position could not be read」。宁可不动，不发一个已知错位的点。
- **回执里两套空间分开标**。帧内点击的 `evidence.frame` 带 `frame_id` / `origin` / `local_space` / `dispatch_space` / `local`（帧内的 center 与 bounds）；顶层 `bounds`、`center`、`dispatched`、`click_point` 都是换算后的顶层坐标。`cdp_see` 给某个 handle 报的中心点，与 `click` 的 `dispatched` 现在相等——这条相等关系就是这一版的验收判据。
- **合并 ≠ 可寻址**。两级嵌套 frame 的内层节点回来时**没有 `backendDOMNodeId`**（实测 2026-10-22）：文本可读、没有 `[idx]` 句柄、点不到。此前 hint 只说「N child frame(s) merged」，读起来像整棵 frame 都能用。现在补一条声明，报出有多少个这样的节点。

### Verified
- `tests/test_iframe_coords.py`（新）：行为证明，不看回执——点完**子 frame 的 URL 必须变成 B**。同一夹具上把换算关掉（对照实验）复现 0.13.0：`dispatched` 报 `[36, 20]` 而 `see` 报 `[158, 102]`，差值 (122, 82) 正是 frame 原点到边框的距离。
- 全套 605 tests 绿（含新模块与 `tests/test_release_0131.py`）。

## [0.13.0] — 2026-10-21

> 「看见了」和「摸得到」之间的一层。0.9 起，`see` 只给 interactive 节点解算坐标——这条规则把**看得见但点不着**的那一层整个漏掉了：静态文字在树里有名字、在屏幕上有位置，却没有盒子，于是没有任何一句话能说它在哪、上面压着什么。
>
> 触发是一次 grounding 实测。造了一块被完全覆盖的元素，它在三个系统里同时呈现三种状态：截图里看不见、a11y 树里有名字、`elementFromPoint` 够不着（点在中心，命中的是压在上面的那个）。三个答案都真，但没有一个调用能同时把它们说出来。

### Added
- **`hand/perception/ax_tree.py::hit_test(call, ws, points)`**：可点性判读。每个屏内节点在自己的中心做一次 `DOM.getNodeForLocation`（`elementFromPoint` 的 CDP 形式）。点用 CSS px——那是 CDP 的输入空间，不是 handle map 里存的物理 px。
- **`dom_parents(call, ws)`**：一次 `DOM.getDocument(depth=-1)` 建 `{backendNodeId: parent}` 索引。判读需要它：`elementFromPoint` 返回最深的元素，所以「中心命中自己的子元素」和「中心命中自己的容器」都不是被盖住。
- **`on_same_chain(a, b, parents)`**：同链判定。相等、祖先、后代都算同链——点在子元素上会冒泡，点在容器里还在自己范围内。只有跨分支才是真遮挡。
- **handle 条目新增 `w` / `h`**：中心点只说往哪儿瞄，宽高说这个目标能容忍多少误差（150px 的块宽容 40px，20px 的图标不宽容）。
- **handle 条目新增 `reachable`（bool）与 `covered_by`（backendNodeId）**：`reachable:false` 时 `covered_by` 指向压在上面的那个节点，可在同一份 handle map 里查回来。
- **三条新的 skipped 声明**：坐标超出预算的、中心在视口外的、以及「被覆盖的节点数」进 hint。判不了的部分全部说出来，不留白。

### Changed
- **坐标解算覆盖全部有 backend id 的节点**，不再只限 interactive。预算 `MAX_COORD_NODES = 400`，interactive 优先占用，超出部分如实声明。
- **`backend_ids_to_coords` 返回值从 `{x, y}` 变成 `{x, y, w, h}`**（都是物理 px，与 handle map 同一空间）。
- **视口外的节点只给盒子、不给判读**：`DOM.getNodeForLocation` 对视口外无意义。这部分计入 `reachable for N node(s)` 的 skipped，读法是「先滚过去再 see」。
- **iframe 内容进同一棵树**（新增能力）。`Accessibility.getFullAXTree` 不带 `frameId` 时只答根文档——页面里嵌的一切（视频、支付、OAuth、评论、文档小部件）在 see 里是**黑洞**：单 iframe 夹具实测，frame 内 11 个有名字的节点**一个都没出现**。现在按 `Page.getFrameTree` 广度优先合并每个子 frame 的树（`MAX_FRAMES = 8`，超了声明不合并）。子 frame 的 `backendNodeId` 在顶层 DOM agent 里就能解析，且坐标**已经是顶层坐标**（实测：iframe 在 x=102.7，其内部按钮报 x=120.7，边框偏移已含），不需要手算偏移。hint 里逐次声明「N child frame(s) merged」。真实页实测：MDN `<iframe>` 文档页合并 6 个 frame、600 节点、judged 60、covered 0。

### Fixed
- **会话页按身份解析，不再按列表下标**。`/tmp` 里的 last-page 记录只存了 index，而 index 会随任何一次关 tab 整体前移——于是记录静默地指向另一个页，之后每一次不带 `page_sel` 的调用都作用在错的 tab 上，读数照样绿。实测形状：全量套件报「handle map 里没有文本框」，当时它其实在问另一个测试遗留的页。现在记录 `{id, url, idx}`，解析按 id → url 前缀 → （只有旧格式才信）idx；**记录过但页已不在时报错，并报出丢的是哪页、现在有几个页**，不再回退 `pages[0]`——回退正是把「我的 tab 被关了」变成「我读了另一个页并且信了它」。同批修测试卫生：mock 型测试不再读开发机上的真实会话记录（`HAND_CDP_STATE_FILE`，每处 pin 到不存在的路径），`tests/test_page_identity.py` 七条锁住三态。
- **盒子取 border box，不再是 content box**。`DOM.getBoxModel` 返回 content / padding / border / margin 四组 quad，原来只取 content——那会把每个带 padding 的控件量小：一个 44px 高、内容 24px 的按钮读成 24px，于是 `w/h` 回答「这个目标能容忍多少误差」时数字是错的（点击区就在 padding 里）。实测 github.com 首页 233 个节点，71 个偏差 >2px，最坏 2 倍。现在按 border → padding → content 依次取。
- **hit test 不再带 `includeUserAgentShadowDOM`**。带上它时，`<input>` 中心点返回的是 input 内部的 UA shadow 编辑器 div——那个节点 `dom_parents`（pierce=false）放不到任何链上，于是**每个输入框都判成「被陌生元素盖住」**。实测 github.com：`textbox "Enter your email"` 报 covered，而真点一下焦点进了这个 input，页面内 `document.elementFromPoint` 也答 input 自己。现在它就是 `elementFromPoint` 的语义：返回一次点击真正会落在的元素。
- **`dom_parents` 走 `shadowRoots` 与 `pseudoElements`**。shadow 内容挂在宿主的 `shadowRoots` 上、`::before`/`::after` 挂在 `pseudoElements` 上，都不在 `children` 里。只走 `children` 的后果是：所有 web component 内部节点、所有图标按钮（点落在 `::before` 上）结构性判成「跨分支」，被判 covered。实测 developer.mozilla.org 那一个页面 6 个 covered 里 4 个是这么来的；修完 0。
- **handle 条目新增 `covered_by_label`**。`covered_by` 只是 backendNodeId，覆盖者自己没挣到 handle 时就读不出来——实测 github.com 10 个覆盖者里 5 个打印成 `?`，等于只说「不能点」不说「是谁挡的」。现在每个覆盖者在 see 时解析一次，带 `role name` 或 `tag.class` 标签。
- **`CDP_HOST` 用 `127.0.0.1` 字面量，不再写 `localhost`**（`cdp_core.py` / `cdp_launcher.py`）。根因来自 Judy 的 Windows 真机实测（D5-NJ-DT-0067）：Windows 上 `localhost` 的 getaddrinfo 同时返回 AF_INET/AF_INET6，TCP 栈先试 `::1`，而 Chrome 调试端口只监听 `127.0.0.1`——`::1` 的拒绝要约 2s 才返回，单帧截图要付两遍（list_pages + ws 握手）。改字面量后 4203ms → 123ms。Linux/macOS 上 `localhost` 只回 `127.0.0.1`，此病在本机完全隐形，`tests/test_windows_support.py` 新增断言守住，不许"优化"回去。
- **滚动后坐标口径**：`hit_test` 现在把页面滚动量加进探测点（`offset=(scrollX, scrollY)`）。`getBoxModel` 与 `getBoundingClientRect` 一样是**视口坐标**，而 `DOM.getNodeForLocation` 要的是**文档坐标**——滚动 0 时两者重合，所以此前每一次检查都是绿的；一旦页面滚动，每个点都答 `No node found at given location`，判读层整层静默清空（MDN，scrollY=900：judged 63 → **0**）。修后同一页面 judged **58**、covered 6，且 6 个都是真的 sticky nav 遮挡。这条是本轮「复杂真实场景」测出来的——不滚动就永远看不见它。
- **父链穿进 `contentDocument`**：iframe 内部节点挂在 `contentDocument` 下，不在 `children` 里；不穿过去，它们在自己页面里也全是「没有祖先」的孤儿，第一个诚实的 hit test 就会把它们全判成「被陌生元素盖住」。现在 contentDocument 的**子节点直接挂到 `<iframe>` 元素上**（document 节点本身通常没有 backend id），那就是一次点击真正冒泡的链。
- **`RootWebArea` 这类文档级节点不再参与判读**：它的「中心」是整个视口的中点，一个点击落在它某个后代身上，于是一直读成「被自己的内容盖住」（夹具上实测 `RootWebArea ← HTML`，纯粹是记账假象）。它保留盒子，只是不再产出判决。

### Verified
**L2 单测**：640 绿（`discover`，2 skipped；标准入口 `run_tests.py` 593 绿）。`tests/test_ax_tree.py` 新增 14 项——hit test 三态 / CSS px 口径 / 滚动偏移（算术 + 接线各一条）/ 父链遍历 / 同链四态 / 覆盖声明 / 后代命中不算被盖 / border box 优先 / 不穿 UA shadow / shadow+pseudo 子节点落链 / iframe 合并。

**L 层真机（HeadlessChrome 151 / dpr 1 / 800×600，2026-10-21）**

| 站点 | 节点 | 有盒子 | 屏内判读 | 判被覆盖 | 耗时 |
|---|---|---|---|---|---|
| github.com | 507 | 350 | 27 | 7 | 0.62s |
| news.ycombinator.com | 600 | 384 | 305 | 0 | 0.41s |
| developer.mozilla.org | 459 | 391 | 63 | 0 | 0.58s |
| en.wikipedia.org/wiki/Bamboo | 600 | 391 | 124 | 2 | 2.63s |
| excalidraw.com | 76 | 72 | 72 | 22 | 0.11s |

**逐条对照真值**（三条独立通道：页面内 `getBoundingClientRect`、`document.elementFromPoint`、`Input.dispatchMouseEvent` 真点一次看 `activeElement`）：
- **坐标**：github 233 个节点、MDN 178 个节点，与 `getBoundingClientRect`（中心口径）偏差 >2px 的：**0**。修复前同一口径 71/233 偏，最坏 2 倍。
- **被判覆盖的 7 个 github 节点全部核实为真**：其中 2 个来自 GitHub 自己的 `SPAN.progress-pjax-loader`（`position:fixed`、`opacity:0`、`z-index:99999`、2px 高、全宽）——一条视觉不可见的进度条会吞掉页面顶部那一带的点击；1 个来自 hero 背景 `CANVAS`；2 个是 floating label 与它的 input 重叠（点 label 中心落到 input 上，功能上正确，结构上确实不是 label）。
- **MDN 修完 0 覆盖**：修前 6 个全是假警报（4 个 `::before` 图标、2 个 shadow/UA shadow）。
- **Wikipedia 的 2 个是真读数**：`Search` 文字被一个 `opacity:0` 的 `<input type=checkbox>`（z-index 1）盖住——那是 Vector 2022 皮肤用来开搜索面板的透明开关。文字不可点，可点的是那个 checkbox。
- **excalidraw 的 22 个是 canvas 应用的结构**：UI 层 `pointer-events:none`，视觉在画布之上但不接指针，点击穿透到 canvas。判读正确，措辞见下条。

### Known limits
- **`covered_by` 混着两种成因**：①真有东西画在上面（z 更高、接指针）；②视觉在上但 `pointer-events:none`，点击穿透（excalidraw 的 UI 层就是）。读数同形，靠 `covered_by_label` 指到具体元素、再看那个元素的 computed style 才能分开。判读答的是「点击会落在谁身上」，不是「谁画在上面」。
- **`reachable` 只对视口内的中心点成立**：滚出视口的节点没有判读，不是 `false`。
- **中心点是必要条件，不是充分条件**：中心可点不等于整个目标可点（边缘可能被压住）。要判边缘得逐点采样，这一版不做。
- **sr-only / visually-hidden 节点会以「被覆盖」出现**：它们的盒子是内容的排布尺寸（可能 84×520），但被容器 clip 成 0 面积，中心点落在外面。技术正确、语义噪声——读的时候先看 `covered_by_label` 是不是普通容器。
- **代价**：`see` 变慢了（Wikipedia 真页 2.63s，主要是 391 次 box model + 124 次 hit test + 一次 pierce=true 的全文 DOM 遍历）。要快的路径仍可用 `resolve_coords=False`。

## [0.12.0] — 2026-10-20

> 变化可判定主线（docs/prd-0.12-change-verifiability.md）。0.11 的每个动作回执都停在 `effected: unknown` + *"compare two frames"*——hand 知道该怎么验，也诚实地告诉了调用方，**但它没替你做**。这一版把那一环装回 hand。
>
> 触发是一次真实的长任务：Excalidraw 从空白画布画 A→B 流程图，23 次调用 / ~15 拍。全程 6 次截图、手工比对，靠我的眼睛补上 hand 缺的那一环。补完之后 hand 的动作回执能自己回答「世界变了吗」——包括它什么都没看见的时候。

### Added
- **`hand/perception/pixels.py::frame_diff(before, after, region=None, ch_delta=12)`**：帧差分原语。`region` 限定只比一块，返回 `{comparable, changed, total, ratio, bbox}`。**第一职责是先回答两帧能不能比**——尺寸/通道数不同返回 `comparable:false` + 原因，把「比不了」和「没变化」分开。`ch_delta` 是三通道绝对差之和的容忍值（默认 12）。
- **`hand/action/effect.py::probe_action(kind, action_fn, verify=True)`**：动作前后各抓一帧、等页面静止、只 diff **预期区域**。`effected` 从 `unknown` 变成三态：`changed` / `no_change` / `unknown`。
- **预期区域（expect region）**：click = 派发点 ±60px（物理像素）；drag = 两端的 bbox 外扩 24px（CSS 像素 × dpr）；key = 全帧（按键没有可作用的元素可缩范围）。
- **`change` 块**：`{verifiable, threshold, region, changed, total, ratio, bbox, waited_ms}`，另带 `whole_frame`（全帧变化）与 `changed_outside_region`。后者是**点歪了的信号**：区域里没变、别处变了——0.9.4 那批「回执绿、任务死」的根因，此前根本看不见。
- **`verify` 参数**（`cdp_click` / `cdp_drag` / `cdp_key`，默认 `True`）：`verify=False` 逐字复现 0.11 的回执，零额外抓帧，给高频批处理路径。

### Changed
- **`effected` 不再一律 `unknown`**。三态语义：`changed`（区域内变了）/ `no_change`（两帧可比、区域内没变——动作很可能没生效）/ `unknown`（抓帧失败、不可比、页面未静止、**或动作压根没派发出去**）。
- **动作没出门 ≠ 没变化**：报错的 click 和什么都没做的 click 在帧上一模一样。回执有 `error` 且无派发证据时一律 `unknown` + `action did not dispatch: ...`，绝不落到 `no_change`。
- **`evidence.reason` 改写**：动作层写的「no readback — verify by comparing two frames」在判定完成后替换为 `no element read-back; the frame diff in \`change\` is the effect evidence (...)`。留着原话，回执就是在建议一件已经做完的事。
- **`verified` 语义不变**：仍是 `resolved and landed`，永不代表世界变了。0.11 的调用方不受影响。

### Fixed
- **区域裁剪 bug**（`pixels.frame_diff`）：先 `max(0, x)` 再 `x + w` 会让负起点区域（点在页面边缘时必然出现）悄悄铺满整帧——正是 `region` 参数要防的那种过宽。改为裁剪**边**而不是起点。

### Verified
**L 层真机（HeadlessChrome 151 / dpr 1 / 800×600 / Excalidraw）**
- **L1 负样本**：无选中状态下点画布死区 → `effected:"no_change"`，区域内 `0/14400`，同时 `whole_frame.changed:6831` + `changed_outside_region:true`（页面加载渲染在动，但点击点周围确实什么都没发生）。0.11 在这里只能给 `unknown`。
- **L2 正样本**：点矩形工具（工具栏高亮切换）→ `effected:"changed"`，区域内 `2877/11760 = 24.5%`，bbox 落在工具栏。
- **L3 拖拽**：`xy:200,200 → xy:350,320` 画出矩形 → `effected:"changed"`，区域内 `2823/33264 = 8.5%`，bbox `{x:191,y:176,w:168,h:153}` 落在拖拽区。
- **L4 失败路径**：点不存在的 selector → `effected:"unknown"` + `action did not dispatch: selector did not match any element`。**不是 no_change**。
- 560 tests green（新增 `tests/test_frame_diff.py` 10 项 + `tests/test_effect.py` 11 项）。

### Known limits
- **`no_change` 的判据是「两帧可比且区域内 0 变化」**，它证明的是「没看见变化」，不是「动作失败了」。慢渲染（懒加载、异步请求）在 `wait_stable` 超时后一律降级为 `unknown`。
- **不做 OCR diff**：文字变化由 `type` 的 readback 覆盖；「读懂了什么」留给后续版本。
- **不做语义判断**：不回答「这个按钮变红了吗」。只回答「这块像素变了吗」。
- **全帧 diff 纯 Python 约 0.9s**：所以 key 走全帧是这一版最贵的一条路径（实测单次动作总耗时 ~650ms，含抓帧）。区域限定的 click/drag 便宜得多。

## [0.11.0] — 2026-10-20

> 动作原语主线（docs/prd-0.11-action-primitives.md）。0.10 让 hand 不说自己不知道的事；0.11 让 hand 能做出更多事、并且说清每件事做到了哪一步。
>
> 背景是方向变了：computer use 的目标要能操作 Blender。Blender 是纯视觉域——没有 DOM、没有 a11y、没有可查元素，hand 现有的「元数据 + selector + 轮询」在那里全部失效，能用的只剩像素和坐标。而 0.10 的坐标路径只支持「点」：点得了，拖不动，按不了组合键。本版补两件原语 + 一套三态回执，不接 VLM、不做帧 diff。

### Added
- **`cdp_drag(from_spec, to_spec, steps=10, interval_ms=16)`**（`hand/action/cdp_act.py`）：`mousePressed` → N×`mouseMoved(buttons=1)` → `mouseReleased`。from/to 各接受 `xy:X,Y`（物理像素）、`[idx]` 句柄或 CSS selector。这是 canvas 应用的可达性前提——实测 Excalidraw 选矩形工具后**单击画布不产生图形**，拖拽才产生；Blender 的轨道旋转 / 拉顶点 / 拖滑块同属这一类。
- **`cdp_key(keys)`**（`hand/action/cdp_act.py`）：修饰键 down → 主键 down/up → 修饰键 up（逆序）。`'Control+z'` / `'Meta+Shift+t'` / `'Enter'` / `'Escape'` / `'ArrowLeft'`。修饰位掩码 Alt=1 / Ctrl=2 / Meta=4 / Shift=8，字符串里的修饰键顺序不影响派发。`cdp_type` 只能插入文本，这一步补的是真实按键事件——应用驱动型 UI（Blender 的 G/R/S + X/Y/Z + 数字）的全部词汇。非法组合（未知修饰键 / 空主键 / 空修饰）显式报错且**一个事件都不派发**。

### Changed
- **三态回执（click / drag / key 统一）**：`resolved`（找到目标了吗）/ `landed`（动作送到它身上了吗）/ `effected`（世界变了吗）并列出现在回执顶层。`verified` 保留但等价于 `resolved and landed`。
  - **`effected` 本版一律 `unknown`** + `effected_reason: no_readback`。没有读回就不许报变化——0.10 的 D3「没有视觉证据不许报 blank」伸到动作层。
  - **`landed: null` 是合法答案**（"判不了"），不等同 `false`。裸 `xy:` 源不声称任何目标元素，因此永远不会得到 `landed: true`；落点事实走 `element_at_start` / `element_at_point`。
- **坐标点击不再盲派**：`xy:` 路径先用 `document.elementFromPoint` 记录落点（`element_at_point`），再派发。仍然不声称 `verified`——落点上确实有元素，不等于它是我想要的那个。
- **`box` 字段语义修正**（PRD F3）：核对确认 `_handle_rect` 返回的 x/y 一直是**中心**，不是左上角——字段名自 0.9.x 起就在说谎。新增 `center` 与 `bounds`（真 BCR：left/top/right/bottom/width/height），`box` 保留一版并附 `box_deprecated` 说明。
- **`cdp_shot` 回执加 `frame`**：`{scrollX, scrollY, viewport{w,h}, dpr}`。此前只有 `img:<sha8>` + 尺寸，一张图对应哪个滚动位置不可问——实测踩中：拿滚动前的坐标点在滚动后的页面上，回执 `ok`，落空。
- **`xy@img:<sha8>:X,Y`** 语法：帧引用解析后写进 `frame_ref`。**未做跨帧校验**（不存历史帧台账），回执显式 `frame_verified: false` + `no_frame_ledger`，不假装验证过。

### Verified
**L3 真机（HeadlessChrome 151 / dpr 1 / 800×600）**
- `cdp_key('r')` 在 Excalidraw 切到矩形工具（工具栏高亮，像素可见）→ `cdp_drag('xy:300,300','xy:500,420')` 画出 200×120 矩形。drag 回执：`resolved:true, landed:null, effected:unknown`——xy 源不声称目标，如实。
- key 事件字段经页面侧监听器逐字核对：`Control+z` → 页面收到 `key:'z', ctrl:true, code:'KeyZ'`；`Shift+Alt+x` → `shift:true, alt:true`；`Escape` → `key:'Escape'`。
- **对照实验**：同一页面 Excalidraw 对 `Control+z` 无反应（事件已正确送达，页面侧不响应）。回执如实报 `effected: unknown`——不把「送达」写成「生效」。
- `geom.html`（BCR = 100,100,200,100）：`center:{x:200,y:150}`、`bounds:{left:100,top:100,right:300,bottom:200,width:200,height:100}`、`box:{x:200,y:150,w:200,h:100}` + deprecated 标注。
- `[idx]` 句柄点击：`resolved:true, landed:true, effected:unknown`，DOM 回执 `CLICK:TARGET`。

**L1/L2**：524 tests 11.5s OK（新增 `test_action_primitives` 27 枚：键解析 11 / 三态 2 / key 派发 5 / drag 序列 6 / 点解析 3）。0.10.0 基线 497。

### Known limits（本版明确不做）
- 跨帧台账与 `xy@img:` 的 stale 拒派发（0.12；本版只如实说"没验"）
- `effected` 自动判定 / 帧 diff（data-gated，0.12）
- `cdp_key_hold` / `cdp_key_release`（长按语义）
- 修饰键 + 点击组合（`Shift+Click` 选范围）
- Blender 本体操作验证（需要真显示器机器）

## [0.10.0] — 2026-10-19

> 交付诚实主线（docs/prd-delivery-honesty.md）：感知的第四轴——证据到达调用方了吗。本版发的是 hand 侧能独自负责的那一半：D1 的 `emitted`（hand 只声明自己放进了什么）+ D3（blank 判据要视觉证据）+ D4（`hand_eye_check`）。`delivery` 归 heart/portal 署名，不在本版——hand 不写自己不知道的事。D5/D6 data-gated，未随本版。

### Added
- **`emitted` 块（回执第一段署名）**（`hand/receipt.py` + `hand/router.py`，D1）：回执正面声明 hand **把什么放进了这份回执**。这是 `verified` 回答不了的另一半——2026-10-17 夜两者真实分离：动作 100% 发生（`verified: true`、`data_length: 123216`），而调用方上下文里的图像为 0。覆盖 `cdp_shot`（image）、`cdp_a11y`（tree/nodes）、`cdp_dom`（text/chars）、`cdp_interactive`、`cdp_network`、`vision_ocr`、`see_vlm`。
  - **边界（不可越）**：hand 只声明 emitted，`delivery` 由 portal/heart 追加。hand 侧写 `delivered`/`attached` 就是新的 claimed 冒充 verified——测试用字面扫描锁死（`test_never_speaks_for_the_caller`）。
  - **缺席 ≠ false**：未知 backend 的 `emitted` 块**缺席**（未实现），`emitted: false` 则必带 `reason`（`not_requested` / `file_path` / `no_elements` / `no_snapshot`）。两种陈述不同，不许互相冒充（D2）。
  - `bytes` 报的是 base64 **解码后**的线上字节数，不是 base64 字符数（`cdp_shot` 实例：`data_chars: 8704` / `bytes: 6528`）。
- **`hand_eye_check`**（`hand/perception/eye_check.py`，D4）：being 侧自证——"像素有没有到达我的 context"。这一层外部判不了，只能用工具把问题变成不可猜的：随机串画进 canvas 像素，回执只给 `challenge_id`（串不进回执、不进 DOM、不进 title、不进页面源——load 后由 `Runtime.evaluate` 注入），`verify` 判字面。8 字符 × 31 符号 ≈ 1/8.5e11 盲猜通过率。空渲染/无墨帧直接拒发题（`challenge not rendered`）；`reason` 区分 `mismatch / expired / unknown-challenge`，过期不吞进"不存在"。
- **像素票模块**（`hand/perception/pixels.py`，D3）：纯标准库 PNG 解码（zlib + 五种行滤波，8-bit 非交错，色彩类型 0/2/4/6）+ `ink_stats`（背景色众数 + 与背景色的曼哈顿距离统计）+ `pixel_vote`（永不抛：`available:false` 是合法答案）。零第三方依赖。

### Changed
- `route_screenshot` 在 `with_data=False` 时不再沉默：图像确实被拍下但这张回执里没有它 → `emitted: false, reason: "not_requested"`（此前调用方只能从"没有 data 字段"去推断）。
- `vision_ocr` 分支（screencapture 落盘）声明 `reason: "file_path"` + `path`——像素在磁盘上可读，不是失败，是没进回执。
- **`visual_state` 的 blank 判据要求视觉证据**（D3，S2 bug 修正）：`blank` 是视觉范畴，DOM 代理在纯文本页/全 canvas 页/慢加载页都会撒谎（0.10 PRD 记录的反例：白底 + 8 个 48px 字符 → 旧判据报 `blank`）。现在 DOM 只给出 blank **候选**，须由一份像素票落定：`ink_ratio ≥ 0.002` → `interactive`（信号 `sparse-text` + `pixel-ink:*`）；票为 0 → `blank`（`pixel-empty:*`）；**拿不到票 → `unknown` + `pixel-unavailable`，绝不报 blank**。
- `probe()` 改为两段式：内容页（长文本 / 有媒体）不取票、不截图；`cdp_shot` 把已在手的 PNG 传入复用（帧过大时才自截 0.25 缩放小图，`PIXEL_FULL_DECODE_MAX=200000`）。

### Verified
- D4 真机端到端（HeadlessChrome 151，640×160 canvas，48px）：DOM `innerText=''` / `title='eye check'` / `RECEIPT_HAS_STRING=False` / `PAGE_SOURCE_HAS_STRING=False` / `ink_ratio=0.03849`；读图得 `XRADEJDH` → `verify pass:true, elapsed_ms:10011`。
- 真机（HeadlessChrome 151，1280×900）：8 字符 48px 纯文本页 → `interactive` / `pixel-ink:0.0088`（阈值 0.2%，余量 4.4×）；真空白页 → `blank` / `pixel-empty:0.0000`；DOM 无文本的全 canvas 页 → `interactive`（`has_media` 短路，不付票）。
- 474 tests 10.8s OK（D3/D4 阶段；`test_visual_state` +11、`test_eye_check` +17：回执/页面源不含串、canvas 渲染、未渲染拒发题、形近替换 fail、单次有效、过期区分、list 不打印串）。
- **D1 实机三通道**（HeadlessChrome 151）：`cdp_shot` → `emitted.channels.image = {emitted: true, bytes: 6528, format: png, encoding: base64, data_chars: 8704}`；`cdp_a11y` → `{emitted: true, count: 240, unit: nodes}`；`cdp_dom` → `{emitted: true, count: 4955, unit: chars}`。同一次实机顺带复核 D3：8 字符 48px 纯文本页的 `visual_state` 由旧判据的 `blank` 变为 `interactive` / `pixel-ink:0.0088`——D3 从单测走到真机行为层。
- 486 tests 10.9s OK（+12 `test_emitted`：base64 线上字节对账、`emitted: false` 必带 reason、未知 backend 缺席≠false、hand 不替 heart 署名、`with_data` 两态、三通道实到）。

## [0.9.8] — 2026-10-12


> Windows 生产化轮：cdp_shot 超时家族判读收束（五格矩阵）+ win32 报错文案修复 + 僵尸测试改造。主题是把「装得上、起得来、报得诚实」在 Windows 面上闭合。

### Fixed
- **win32 报错文案指向真实修法方向**（F27 补刀，cdp_launcher.py）：0.9.7 及之前 `no chrome binary found` 一律建议 "install playwright chromium"——但 win32 查找链（Chrome/Edge 安装路径 + PATH）从不读 Playwright cache，Windows 用户照做也无效（死方向）。win32 分支现在给出真实方向：设 `$CHROME` 指向 chrome.exe/msedge.exe 或安装 Chrome/Edge，并声明跳过 Playwright cache 是有意设计（headless-shell 在 Windows 是 old-headless 渲染管线——五格矩阵判读的超时元凶，#34 2271-2299）。回归锁 `test_open_place_error_direction_win32`（432 全绿新增一枚）。

### Docs
- **Windows 安装已知坑节**进 kit/README.md（Judy ① WSL stub + ②③ venv Scripts/python fallback）：WSL stub P1 的临时修法（manifest command 写 Git Bash 全路径）、修法裁决（主路径 a：Grove 安装器 Windows 探测改写——Town 侧 !176；b：Portal 启动器避 System32——F20 转 sw）、升级影响与备份边界（F25/F26）。
- **feedback ledger 收口三笔**（docs/feedback-ledger.md）：F27 cdp_shot 超时家族五格矩阵判读收束；F28 taojun 句柄表写盘目录主犯按实证覆盖销账；F29 PYTHONUTF8 显式编码现状。

### Tests
- **僵尸测试改造**：test_release_080（0.8.0 断言、从未注册进 run_tests MODULES——僵尸）改造为历史锁（0.8.0 版本事实钉死）+ test_release_097 回填（0.9.7 事实）+ test_release_chain 连环扣新增（每 release 测试文件必须注册 MODULES、当前版本必须有 release test——结构性防再僵尸）。
- 基线 431 → 432 全绿（新增 win32 文案回归锁一枚）。

### Verified
- 五格矩阵（#34 2271-2299）：W1（Win+完整 Chrome 153）绿 n=2（Noah 2277）；macOS 三格（完整 154 / headless-shell 153 / 134）全绿（alice 2274/2278）——超时条件收束为 Windows × headless-shell（old-headless 渲染管线，完整版 ~132 起移除）。0.9.7+ win32 分支结构性不可能选中 headless-shell（系统浏览器全找不到时 return None，Playwright cache 永不触达）。
- taojun 2272 两笔 9/24 老悬账当场收口：主犯判定（路径主犯成立，C:\tmp 目录被撤时句柄表写盘静默失败）+ BOM 复现参数已直发 weiguo（tQOW2YeR）。
- 432 tests 11s OK；Grove 发布验证（tools 列表非空）。

### Credits
- **Noah** — cdp_shot 超时三样本（跨会话稳定复现 + 极简 data:URL 排除页面复杂度 + 通道分离 WinError 10061）+ W1 对偶格真机出数（2277），五格矩阵的 Windows 侧全靠他的真机。
- **taojun** — 主犯判定当场实验（2272，引 seq 2755：路径主犯、句柄表静默失败形态）+ BOM 参数第一手直发 weiguo + 真机验收认领（0.9.8 ①② 两项）。
- **Judy** — 坑①需求落 Town 侧 !176（Grove 安装器 Windows 探测，InstallBody platform+git_bash_path 零破坏契约）+ ②③（PR #4 fe89694 随版带出）。
- **Being** — cdp_shot 复现包三封 DM 送达（XT0Rga1X/kyiyDMFc/kx7CdOil），通道分离样本+极简页样本是五格矩阵判读的两根柱子。

## [0.9.7] — 2026-09-28

> 回执诚实主线第三刀：cdp_type 落点回读。打字后回执如实报告文本是否真的落在目标字段——零落地、落点漂移、SELECT 照收后丢弃，全部从「碰巧绿」变成「如实红」。Judy 从修法到判读走完第一条社区完整闭环（设计→分段投递→矩阵→判读→合并）。

### Fixed
- **cdp_type 三路径落点回读**（F22，P2，Judy f22-type-readback）：`cdp_type` / `cdp_type_handle` / `cdp_type_focused` 全部接上三层——①pre-flight 可编辑性拒绝：SELECT/非文本 INPUT/readonly/disabled 红在门外，回执带 target 证据（tag/type）；②post-flight read-back：typed text 必须是 after-value 子串，`evidence.read_back = {before, after, landed}`，零落地红回执（"text did not land (zero-landing)"）；③Enter 顺序：keyboard 模式 `\n` 先插文本段→回读→再 dispatch Enter，read-back 不被提交清空干扰；textarea（ENTER_MODE_TEXT）全部插完后一次回读。0.9.6 及之前 `ok+verified` 只验 focus/selector 命中不验落点——文本静默丢失时回执仍是绿的（已知病灶：干净页 zero-landing、焦点漂移进搜索框、SELECT 照收文本后丢弃）。

### Docs
- **升级前备份措辞落 kit/README.md 升级节**（Judy seq 1818 原文，0.9.7 发版线前送达）：Grove 面 setup_guide 新增 0.9.6→0.9.7 升级节——备份固定写 `~/hand-kit-{旧版本}-bak-{时间戳}/` 于 `kits/` 之外，杂散 manifest 目录致病（双实验定谳：权限洗清，真凶 `.bak` 目录）。
- **升级路径三坑进 README Upgrade impact**（F25/F26，216 & Judy 0.9.6 实机样本）：①`rsync --delete` 同步 bundle 会删掉 bundle 里没有的本机安装痕迹（.venv 软链、.env、PATCHES.md）→ start.sh 回落系统 python3 报 mcp-start-failed——同步前显式 exclude；②kits/ 下带 manifest.json 的杂散目录（.bak 残留）→ reload 报 no loadable manifest（单因子实验锁定：权限脏不致病，杂散 manifest 才是）——版本备份放 kits/ 之外；③tar 根就是 kit 目录本身，解压到 `~/.heart-portal/kits/hand/`；裸 `tar xzf` 后见 600/700 是 umask 叠加（无害）。

### Verified
- 矩阵 9/9（真 headless Chrome，隔离 profile）：R1/R2 红在 pre-flight not text-editable（exp2 原形状 + exp1 无漂移证明——旁路 input 保持 "BOM" 不动）；R3 红在 post-flight did-not-land（oninput 自清空字段，pre-flight 唯一拦不住的残余形状，after==""）；R4 红在 readonly；G1-G5 全 landed+verified（handle 路径/追加/textarea 换行/keyboard Enter 前回读/contenteditable）。
- Linux 415 回归全绿。初跑 3 败 → 根因判读：mock `Runtime.evaluate` 返回旧形状（无 `found` 字段），新 read-back 判缺失为 focus-moved——真实浏览器 JS 总返回 found:true/false，是 mock 未跟新契约。修 mock 不松判据（补 `found: true` + `value`），复跑全绿。
- Judy 判读通过放行（2026-09-26 12:37）：三处手工修复均在上下文/拼接层（边界空行、manifest 路径、丢换行），不动核心语义，与对账声明字节账一致。

### Credits
- **Judy** — 本版主修的作者。f22-type-readback 分支（d99a037，cdp_act.py +295 行三路径全接）、9/9 矩阵脚本与红样本纪律交付、DM 七段 diff 分段投递、判读放行——从修法到合并的第一条社区完整闭环。setup_guide 契约变更条目（mock 需补 found/value）按她原文转译进 README。升级节备份措辞（seq 1818，发版线前送达）原文落 Grove 面 kit/README.md。
- **216** — F25 升级路径坑样本（rsync --delete 删本机安装痕迹）；0.9.6 实机回执（撤补丁升官方版、diff 零差异、系统代理全开下原故障场景复测通过）。
- **Judy** — F26 杂散 manifest 目录坑（单因子实验锁定真凶）+ 0.9.6 升级反馈（0.9.0→0.9.6 无需重启 Portal 全链验证）。
- F22 病灶发现：Alice dogfood 双实验（2026-09-22，exp1 污染样本 + exp2 干净复现）。

## [0.9.6] — 2026-09-25

> macOS 代理盲区轮：216 实机根因 + 补丁。系统级代理（Clash 类）把 localhost CDP 流量送进代理回 502，探针瞎了误杀活 Chrome——回环恒直连，外网恒走系统代理。

### Fixed
- **回环 CDP 流量绕过系统代理**（F23，P1）：macOS 系统代理（scutil --proxy 全开 127.0.0.1:6789）下 urllib 默认 opener 把 `localhost:9222` 送进代理，代理对回环流量回 502——`endpoint_info` 探针瞎 → `cdp_open` 误杀健康 Chrome 循环重启，see/nav/click 全系不可用。修法：CDP_HOST 恒回环的三处调用（`endpoint_info` / `open_new_tab` / `_json_get`）换模块级无代理 opener（`ProxyHandler({})`，每进程构造一次）；外网两处（vision_llm → OpenRouter、kit 心跳 → Grove）保留系统代理。边界完备性：CDP_HOST 恒为 localhost，不存在「CDP 流量走外网」场景——不是碰巧没漏。
- **cdp_type 指针诚实化**（纯文档三处）：`[idx]|text` 管道形式的入口是 `cdp_click` 不是 `cdp_type`——描述与实际路由对齐。

### Verified
- Linux 415 单测全绿。一处测试调和：probe 测试 mock 目标从 `urllib.request.urlopen` 跟随调用点改为 `_NO_PROXY_OPENER.open`——旧 mock 在补丁后失效，测试静默直连真实 Chrome（Linux 侧发现，macOS 实机验证测不到 mock 层）。
- macOS 实机根因三连（216）：curl 9222 → 200；urllib 默认 opener → 502；空 opener → 200。本地补丁实测通过后按同款 diff 上游化。
- 9/6「9222 十秒不可达」旧案（当时怀疑 IPv6 未验证）根因落定：系统代理。

### Credits
- **216** — 本版主修的作者。根因定位（证据三连）、边界完备性论证（全 kit urlopen 盘点）、补丁与 macOS 实机验证（#34 seq 1721）。Linux 侧测试调和与 415 由 alice 完成。

## [0.9.5] — 2026-09-25

> Windows 落地清障轮：taojun 实机验收驱动的两修——`/tmp` 硬编码与编码族。Windows 无 `/tmp`、PowerShell `>` 重定向带 BOM，两族都是「macOS/Linux 上跑得好好的」盲区。

### Fixed
- **`/tmp` 硬编码 → `tempfile.gettempdir()`**（ax_tree / cdp_core / vision_ocr）：handle map、last-idx 状态、截图默认路径三处。现在跟随平台 tempdir（Windows `%TEMP%`；macOS/Linux 行为不变，仍解析到 `/tmp`）。repo 内 `/tmp` 硬编码清零（grep 全库无残留）。
- **编码族**：写侧显式 `utf-8`（handle map、heartbeat、last-idx），读侧 `utf-8-sig` 容 BOM——PowerShell 重定向产物带 BOM，裸读会炸或留 `\ufeff` 污染。
- **save/load_handle_map 错误可见性**：静默吞异常 → stderr 落名（哪个文件、什么错）；`FileNotFoundError` 单列静默（冷启动正常态，不算错）。
- **嵌套目录自动创建**：save_handle_map 写前 `makedirs`。

### Verified
- Linux 415 单测全绿。`test_websocket_is_actually_imported_by_the_tree` 断言从字面量改为模块成员检查——字面量会随 import 行演进过时，测试意图是「requirements 声明 websocket 因为代码真 import 它」。
- Windows 实机验收（taojun，0.9.4 vanilla 基线 + 本 diff）：①嵌套目录不存在时写入自动建 ②CJK 全链路（charset=utf-8 页面 → 写表 no BOM → 独立进程读回 → cdp_click verified nav_id 2==2）③四文件无裸 open；py_compile 4/4，kit 热加载正常。
- `vision_ocr_bin` mtime（09-22 14:22）> `vision_ocr.swift`（09-22 11:04），本版 Python 侧改动不触 swift/bin 接口——编译产物无 staleness。

### Credits
- **taojun** — 本版全部两修的作者。Windows 真机验收三条全过，DM 纯文本 diff 交付（按交付线约定）。他的 BOM 三进宫实测（0.9.0 升级 + utf-8-sig 修法判定）是编码族修法的直接输入。

## [0.9.4] — 2026-09-24

> 摩擦点清账轮：dogfooding 实证出的六项静默错/手感摩擦，P0（视口对齐）已随 0.9.3 发布，本版清掉其余五项。核心主题——回执说 ok 不等于世界真的变了。

### Fixed
- **`text=` 嵌套文本匹配失效**（P2，spec docs/spec-0.9.4-p2-textmatch.md）：旧 XPath 用 `contains(text(), q)` 只看直接文本子节点，GitHub issue 标题这种 `<a><span>文本</span></a>` 嵌套结构全部 miss。改为 `contains(normalize-space(.), q)` 看整个子树；精确匹配分支排除「有同等匹配子元素的祖先容器」（文档序父先于子，否则点到容器）。候选 >1 列出 candidates 不猜。
- **Enter 不提交**（P3，spec docs/spec-0.9.4-p3-enter-submit.md）：`Input.insertText` 不触发 keydown——GitHub 搜索框输入后 URL 不动。文本以 `\n` 结尾时改派发完整键盘事件（keydown/keypress/input/keyup），回执 `evidence.enter_mode` 说明走了哪条路。实证：同一搜索框 insertText 后 URL 不变 vs dispatchKeyEvent 后 URL 变 `?q=NVDA`。

### Added
- **handle 表过期信号 `nav_id`**（P1，spec docs/spec-0.9.4-p1-handle-staleness.md）：`see(kind="a11y")` 回执顶层带 `nav_id`（`Page.getNavigationHistory` 的 currentEntry index，浏览器侧状态、跨 MCP 进程稳定），handle map 文件同时记录 see 时刻的锚。`click [idx]` / `type [idx] …` 回执 `evidence.nav_id_at_action` 带动作时锚；两锚不同即 `evidence.warnings = ["navigation occurred since last cdp_see — handle table may be stale"]`（warning 进 evidence——设计定夺记录 #1；`tree_epoch` 按 #2 砍掉，`expect=` 语法按 #3 不加）。可靠合同明确为「要么点对，要么显式失败」，同页局部重渲染不做预检（M3）。
- **heading 包 link 的点击重定向**（P4，spec docs/spec-0.9.4-p4-heading-redirect.md）：AX 序列化给「子树含 interactive 后代」的节点加 `contains_interactive: true`（仅 true 时带）；`cdp_click_handle` 点到非 interactive 容器且其 AX meta 标记含 interactive 后代时——唯一后代 → 重定向点击它（`evidence.redirected` / `original` / `redirect_target`）；多个后代 → 不猜，失败回执列 `candidates`（tag+text+href，前 3）；零后代 → 走原有路径。a11y 树行格式与 `type` 路径不变。
- **clickable point 命中链预检**（P5，spec docs/spec-0.9.4-p5-clickable-point.md）：`getBoundingClientRect` 是包围盒——多行内联元素（GitHub issue 标题）的中心落在行间隙，坐标点击命中祖先容器，导航根本不发生（回执 ok、啥都没干）。现在每次坐标派发前用 `elementFromPoint` 验证命中链包含目标（元素自身或后代）；中心未命中 → 5×15 网格扫描盒内找真命中点（`evidence.click_point.how = "grid_scan"`）；完全被覆盖 → 响亮报错。P4 现场回归时发现：重定向回执 ok 但 URL 没变，顺藤摸出这层更深的静默错。

### Verified
- 415 单测全绿（0.9.3 的 396 → +19：P1 handle 过期信号 8、P4 重定向 7、P5 clickable point 4），fixture 先自证危险条件（导航确已发生 / 标题中心确实不落在 link 上 / bounding-box 中心确实落在行间隙）再证修复——对照实验钉根因，行为证明修复，回执不自我背书。
- GitHub 实况回归三场景：issues 搜索 Enter 提交（P3，URL 变 `?q=...NVDA`）、滚动 2000px 后点列表尾部 heading（P0+P4+P5：重定向 + grid_scan + 导航到 #337206）、text= 点开 issue（P2）。

### Credits
- **Judy** — PR #1（vision-ocr find_text 像素坐标）+ 8b00dbe 三处修复（显式 image_path 报错、evidence 语义、回执契约测试表）；此前 PR #3（vision_ocr_bin 重编）。0.9.4 的 J1 提前闭合是她的功劳。
- **taojun** — CONTRIBUTING 方法论段「存在过≠发生过」（9942816）+ #34 about:blank 样本；「对照实验钉根因再写 spec」流程直接受益于这套纪律。
- **GuangCZ** — PR #2 [design] f14-expect-semantics（open，设计稿）。
- **泽平** — dogfooding 方向（困难场景实测手感）+ 0.9.4 范围拍板「能优化有把握的都进」。

## [0.9.3] — 2026-09-23

> 诚实回执从感知层扩到委托层：open 路由不再说谎（about:blank 归浏览器），委托 brief 有了自包含契约。

### Fixed
- **`about:blank` 误路由到 app 激活**（taojun #34 样本）：裸 app 名走 app 激活没问题，但 `about:blank`、`data:` 这类 hostless URL 被当成 app 名去激活——scheme 白名单（http/https/about/file/data/chrome）+ hostless URL 精确匹配，URL 一律归浏览器。回归测试 4 个（about:blank/data: 归浏览器、裸名不误伤、chrome:// 归浏览器）。
- **0.9 review 三笔确认落地**（Judy 反哺验收项，查代码全部已实装+测试覆盖）：warning 进返回值（vision_ocr stale bin 三场景）、stale 检测（mtime + 运行时双护栏）、fallback 不静默（skipped 声明）。

### Added
- **委托 brief 自包含契约**（CONTRIBUTING 新节）：把任务委托给 subagent 时 brief 三必含——仓库绝对路径、验证命令、回执判读法——外加可选「不要做」边界行。全部来自 0.7/0.8 实测（subagent 猜 /root/hand、猜不存在的 pytest、回执文本接不住）。

### Verified
- 380 单测全绿（0.9.1 的 371 → +4 about:blank 路由回归 + 净增 brief 契约为纯文档）

## [0.9.1] — 2026-09-22

> 发布包 bin 修复 + 结构性护栏：0.9.0 的 grove 包带着一枚从过期 checkout 编译的 vision_ocr_bin（Judy PR #3 发现），运行时冒烟护栏让它永不再漏。

### Fixed
- **`vision_ocr_bin` 从当前源码重编**（PR #3，Judy）：0.9.0 grove 包内的 bin 是 stale-checkout 编译——mtime 检查全绿（bin 比源码新）但输出旧单冒号格式、无 bounds、识别率更低。新 bin 已在 macOS arm64 双机独立验证（Judy 生产环境 + sw-mac-mini 对照冒烟：同 fixture 图，旧 bin `1.0: SMOKE TEST 123`，新 bin `0.5	19	44	377	36	SMOKE TEST 123`）。

### Added
- **运行时冒烟护栏 `tests/test_bin_smoke.py`**：对 fixture 图跑 bin、断言 tab 分隔 bounds 格式——mtime 检查对 stale-checkout 编译是盲的，运行时格式不会说谎。macOS 强制执行，非 macOS 平台显式声明跳过（0.9 原则：跳过可见，Linux-only 绿不冒充 bin 已检）。双向验证：旧 bin 进测试必红（FAILED×2 带重编命令诊断）。

## [0.9.0] — 2026-09-22

> 诚实回执完成体：截断永远声明、页面视觉状态标记、expect 规范冻结。发布前真实页面加固抓出三个分类器边界 + 两个签名撒谎，全部修复。

### Added
- **统一截断声明块 `truncation`**（S1）：`{field, reason, dropped, total}`，任何被丢弃的东西都声明——a11y 树（max_lines）、dom 文本（max_chars）、节点名（200 chars）、VLM 输出（max_tokens/finish_reason）、跳过的 fallback 后端（hint 里 `skipped: <what> (<why>)`）。不截断时键缺席 = 完整。旧字段 `truncated`/`nodes_omitted` 保留一个版本。
- **`visual_state` + `visual_signals`**（S2）：页面此刻的视觉状态五枚举 `loading · error · blank · interactive · unknown`，DOM 启发式（无截图），信号可审计。`expect="visual_state:…"` 可等。
- **`ocr_diff`**：两次 vision-ocr bounds 输出的文本变化区域定位。
- **`expect=` spec v1.0 冻结**（docs/expect-spec-v1.md）：四种形式 url/title/text/visual_state。

### Fixed（发布前真实页面加固）
- **visual_state 三个真实页面边界**（GitHub 仓库页/404 页实测）：
  - README 章节 "Errors are documentation"（h2）让整个仓库页误判 error → h1/h2 命中需正文 <500 chars，否则 interactive + `error-word-in-content` 诚实信号
  - 404 页全站 footer 撑大 text_len（933）漏报 error → title 命中升为强信号（`error-title:`），不受正文长度门槛约束
  - 语言统计条（role=progressbar，视口外 y=752）误判 loading → vis() 加视口相交检查
- **`open()` 静默忽略 `expect=`**（0.8 引入的签名撒谎）→ 修复 + 回归测试
- **`network fetch_body` 的 `max_small_body` 死参数**（0.8 起签名收了从未应用）→ body 超限截断 + `body_truncation` 声明

### Verified
- 371 单测全绿（0.8.3 的 362 → +9 真实页面回归）
- 真页面三态矩阵：仓库页（19k chars）→ interactive；404 → error；example.com → interactive
- expect= 真链路四场景（met/timeout 各半，timeout reason 诚实）
- truncation 数学自洽：dom 11143+8000=19143；a11y 1191+600=1791

## [0.8.3] — 2026-09-22

> 社区第一笔 PR 落地（Judy，PR #1）：vision-ocr 从 6.11.0 fork 移植 bounds 输出 + 回执契约三处修复。

- **vision-ocr bounds 输出**：tab 分隔 x/y/w/h/center 坐标（从 Judy 的 6.11.0 fork 移植，adaptation pattern）
- **回执契约修复**：
  - manifest evidence 语义 verified→claimed（与 F14 判读对齐）
  - hand_see_ocr 声明 idempotency/claimed，receipt contract 50/50 全绿
  - find_text 显式路径不存在时报错，不再静默 fallback 截图（F16 同族判定）
- 验证：干净 origin/main 对照跑，零新挂（预存失败均为版本断言/环境类）

## [0.8.2] — 2026-09-22

> 一行修复版：CDP 端口可覆盖。F16 收案。

- **`HAND_CDP_PORT` 环境变量**：CDP 端口默认 9222 不变，但宿主机已有 9222 占用者（launcher-embedded Chrome 等）时可覆盖，kit spawn 与 connect 指向同一变量（`cdp_core.py` + `cdp_launcher.py`）。
- 背景：taojun 的 D5 Launcher 内嵌 Chrome 常驻 9222，kit 撞车——更险的形态是**静默错连**（connect 打到占用者的 Chrome，不是 kit 自己 spawn 的）。0.8.1 实锤过一次（连进 dl://launcher/docker.html）。修复后 `HAND_CDP_PORT=9223` 即避开，本机实测 9223/9222 并存互不干扰。
- 测试同步：292 全绿（新增 HAND_CDP_PORT 生效断言 + 端口一致性断言）。

## [0.8.1] — 2026-09-22

> 一行修复版：venv 回家。Judy 在 0.8.0 升级实测中撞上的 F7 场景——
> requirements 装进 .venv 是 grove 安装的自然动作，但 start.sh 只认系统
> python3，venv 白装。无全局 mcp SDK 的机器上 kit 直接起不来。

#### Fixed
- **start.sh venv 优先**：`.venv/bin/python3` 存在且可执行则优先，否则
  fallback 系统 python3（纯向后兼容，本机有全局 mcp 的行为不变）。
  来源：#34 Judy 2026-09-22 实测样本（seq 1062）+ 主干判断（seq 1114 回执）。

## [0.8.0] — 2026-09-21

> 第二张脸：**code mode**。0.7 换了眼睛，0.8 给同一身体长出一张 Python 脸——
> 同一 router、同一 CDP 后端、同一 a11y-v2 感知、同一回执契约，两种用户：
> being 走 MCP，触手/agent 环境走 code mode。0.8 不加新能力。

#### Added
- **S1 Python face**：`from hand import hand` → `hand.open(url)` / `hand.see()` /
  `hand.do(action)`（另有 `shot/close/handles/resolve/history/help/reset`），
  进程级懒单例 `hand.browser()`：持久 kernel 里变量、句柄、Chrome 进程跨调用存活。
  - 回执归一：MCP 面的 `"open": "ok"` → `ok: true`，统一骨架
    `ok / action / kind / method / url / title / verified / error / hint`
    （`ok`=调用判定，`verified`=证据判定，不合并）。
  - **序列化确定性**：`FIELD_ORDER` 固定字段顺序、无时间戳/无 set 迭代 →
    同页面状态 `json.dumps` 字节可复现。这是未来原生化协议的边界，字段名不轻改。
  - 动作语法一条规则：`click [15]` / `click selector=a.login` / `click text=Sign in` /
    `click xy=100,200` / `type hello` / `type [3] hello` / `scroll down`；无动词=点该目标。
  - **教学式错误**（错误消息即文档）：selector 未命中 → 指向 `[idx]` 句柄或 `selector=`；
    句柄过期 → 指向 `see()`；type 无焦点 → 指向先 click 字段；无 place → 指向 `hand.open`。
  - 点击后不猜世界状态：`do()` 的 `url`/`title` 恒为 None（点击是异步的）。
- **S2 `expect=` 世界状态验证**：`hand.do("click [15]", expect="url:/issues")`。
  动作验证（`verified`/`evidence`）与世界状态验证（`expect.met`）分开报告；
  有界等待默认 5s（`timeout=` 可调），超时 `met:false` 带当前 url/title 证据、不抛异常；
  无 `expect` 立即返回且不读世界；动作失败则跳过等待（`expect.skipped`）。
  形态：`url:`（大小写敏感）/`title:`/`text:`（忽略大小写）；非法形态是调用方错误
  （`ok=false` + 命名问题 + 合法形态提示），动作层结果仍如实报告。
- **S3 文档**：README 重写为 Python-first（Python 入口置顶、动作语法一页纸、
  `see()` 返回 schema、持久性一句话、点击后重 see 确认 URL、`expect` 语义），
  MCP 面退为第二视角。

#### Fixed
- **a11y-v2.1（S4 被试抓到的契约洞）**：v2 的 StaticText 名字在 60 字符处静默截断——
  回执 `truncated=False`、`nodes_omitted=0`，但中文长句读到半句话不自知（被试 task 1
  被坑，被迫用 dom 复核，直接推高 turns）。「截断永远声明」对行数成立、对单节点文本
  不成立。v2.1：`MAX_NAME` 60→200（覆盖 Chrome AX 实际给出的绝大多数名字），超限
  截断**声明**——回执 `text_truncated_count`、每节点 meta `text_truncated` flag。
  格式即契约，版本号 a11y-v2 → a11y-v2.1；golden file 换
  `github_snapshot_v2_1.txt`（v2 快照保留为历史）。
- **README 7 条文档洞**（被试 findings #1/#3-#8）：kind 各自返回形态表（dom 无
  `tree`）、click 后立刻 see 有竞态（~0.4s 滞后）→ `expect=` 为推荐姿势、句柄存活
  语义（kind 切换不死、跨页导航死）、dom 8000 字符上限、network 现场监听式（非历史、
  无响应体）、see 无子树参数、a11y 定位 + dom 读原文配合姿势。

#### Dev
- 版本：`hand.__version__ = "0.8.0-dev"`（dev 周期），`kit/manifest.json` 保持已发布的
  0.7.0，发布 commit 统一改。相关版本断言改为「dev 周期规则」：semver 允许 `-dev`、
  包版本不落后于已发布版本、manifest 永不带 `-dev`。
- 测试：`tests/test_hand_api.py` 58 例（S1 42 + S2 16），注册进 `tests/run_tests.py`
  与 `tests/run_production.py` 的 L1 列表。
- live 冒烟（真 Chrome）：open → see（157 行 a11y 树/157 句柄）→ 教学提示 →
  `do("click [68]")` 端到端 → `expect="url:github"` met=true；超时 case met=false
  带证据；无 expect 0.01s 返回。

## [0.7.0] - 2026-09-21

> **版本线重置**：0.7.0 不是 6.11.0 的渐进迭代，而是**感知层范式切换**——`cdp_see` 默认从
> 可见文本/元素地图换成 a11y 树。Grove 按版本号排序时 0.7.0 会排在 6.x 之后，这是有意的：
> 这条线从「浏览器控制」重开为「AX 感知」。升级前请读「升级影响」。

#### Added
- **AX 感知层（a11y v2 默认）**：`cdp_see` 默认返回可访问性树——YAML 风格缩进树，
  每行 `role "name" (state) [idx]`，`[idx]` 是稳定句柄。实验依据：90 trials A/B，
  a11y v2 **87%** vs 旧 interactive 层 **58%**（感知类 50%→88%，操作类 57%→71%，
  输入 token -17%、输出 -77%；`experiments/a11y_ab/REPORT_phase2.md`）。PRD:
  `docs/prd-ax-perception.md`
  - **S1** `hand/perception/ax_tree.py`：实验原型产品化。curation（滤 ignored/纯布局角色、
    level 只对 heading 有意义、折叠无名 generic 单子链、StaticText 空名/重名不占行）、
    稳定句柄、`backendNodeId → 坐标` 映射。
  - **确定性是格式契约**（`a11y-v2`）：同一页面状态序列化**字节一致**。为此 `STATE_PROPS`
    从 set 改为有序 tuple（str set 迭代序随 PYTHONHASHSEED 变化，会静默破坏可复现性），
    并加跨进程确定性单测。截断显式声明（`truncated` + `nodes_omitted`，默认 600 行，
    可完整容纳实验最重页面 478 行），不会产出没有对应句柄的 `[idx]`。
  - **S2** `[idx]` 句柄直达动作层：`cdp_click "[93]"` / `cdp_type "[93]|text"`。
    点击时用 `DOM.resolveNode` + `getBoundingClientRect()` **重读**元素盒（快照里的 x,y
    只是信息位，用旧坐标点就是盲点），验证来自这次重读；节点消失/零尺寸 → verified=false
    并提示「call cdp_see again」。`kind=interactive`/`kind=dom`/`kind=network` 保留为显式通道。
  - **S3** 回执契约套到 a11y 快照：`verified` = 树确实拉到且根节点非空；
    `evidence` = 节点数/序列化字节数/truncated/nodes_omitted/AX 来源版本/sha256/root_role。
    溢出菜单盲区（实验已知）检测 hasPopup 控件后给 `hint`：先点开再 see（两步策略）。
- **S4（F7）Chrome profile 策略**：`_chrome_flags()` 默认 `--user-data-dir=<kit>/.chrome-profile`
  （isolated，永不与人类 Chrome 抢 profile 锁、不碰人类 cookie），目录保留（登录态跨重启存活）；
  `HAND_PROFILE=persistent` / `HAND_PROFILE_DIR=<path>` / `HAND_HEADLESS=0` 三个显式 opt-in
  （taojun 954 无头指纹限流 + Cotton 935 人类 Chrome 常驻，是方向相反的同一条需求）。
  spawn 句柄带 `.cdp_flags`/`.cdp_profile`，验收协议「ps 核 flags」有程序化对照物。
- **S5（F8）macOS 发现层**：`_find_chrome()` 加 darwin 候选（/Applications Chrome → Chromium
  → Canary → Edge → ~/Applications），排在 Playwright 缓存之前。Cotton 935 的硬编码路径
  正式进链，不再靠 wrapper。
- **S6（F9-F13）quick-fix**：requirements pin `mcp<2`、补 `websocket-client`（真 import 却
  未声明）与 `requests`；`start.sh` 加载 `<kit>/.env`（`set -a` 导出给 MCP 进程）；
  README 写明 python ≥3.10 前置、冷启动 2-3s 预期与端点探测上限 6s。

#### Changed
- `SEE_PRIORITY["browser"]`/`["unknown"]` 链首换成 `cdp_a11y`，`cdp_dom` 降为优雅降级
  （AX 拉不到时仍能回答，回执的 `method` 说明是谁说的）。
- `kind="dom"` 成为显式通道：a11y 上默认后不能再靠「链首恰好是 dom」生效。
- `cdp_see` 的 manifest 声明补 `a11y`（默认）与各逃生口，`cdp_click`/`cdp_type` 声明
  `[idx]` 句柄用法。

#### Fixed
- **F15（幂等标签复核）**：`cdp_type` 的扁平 `append` 标签会随内部 fast 路径静默过期——
  现在按路径分标：MCP `cdp_type` = append（`Input.insertText` at focus），内部
  `fast=True` 路径 = 整值 replace（构造上幂等、非 MCP 暴露），manifest 增
  `idempotency_note` 写明（enum 不变，schema 变更仍留 6.12.0 观察）。

#### Upgrade impact（升级影响）
- 首次 spawn 创建 `<kit>/.chrome-profile`（保留，不删）；安装器生成的
  `chrome-wrapper.sh` **可删可留**（无害冗余，flags 已进正规链）。
- `cdp_see` 默认输出变了：旧行为用 `kind=dom`，旧元素地图用 `kind=interactive`
  （保留一个过渡版本）。

#### Dev
- 新增测试：`tests/test_ax_tree.py`（curation/句柄/截断/跨进程确定性/坐标/句柄表）、
  `tests/test_ax_see.py`（kind 路由/句柄动作）、`tests/test_chrome_profile.py`（F7）、
  `tests/test_macos_discovery.py`（F8）、`tests/test_kit_quickfixes.py`（F9-F13）、
  `tests/test_release_070.py`（manifest/版本/release note）；`test_receipt_contract.py`
  增 a11y 快照与句柄动作的回执断言。
- 保真验证：用 `experiments/a11y_ab/github_ax.json` 重放，归一化（StaticText 噪音规则、
  level 修正、页面相对时间）后与实验 `github_snapshot_v2.txt` 完全一致。
- 真实浏览器实测（github.com/d5z/being_hand_kit）：`see(kind=a11y)` 0.21s / 487 行 /
  17939 字节 / 91 个可操作面拿到坐标；同页两次 see 字节一致；`cdp_click "[25]"` 点开
  溢出菜单后树从 487 行变 492 行。
- 反馈台账 F7/F8/F9/F10/F11/F12/F13/F15 销账为 0.7.0。

## [6.11.0] - 2026-09-21

#### Added
- **回执契约层（Receipt Contract Layer）**: 回执不再只有「ok」，每个工具区分**声称（claimed）**与**验证（verified）**，manifest 显式声明幂等形态。调用方拿到回执即可判读，不必再跑一遍 `hand_health` 验活。
  - 统一形状 `{"verified": bool, "evidence": {...}}`；`verified=false` 必带原因，不允许 silent ok。PRD: `docs/prd-receipt-contract.md`
  - `route_open` 三态证据：`evidence.level` = `navigate_confirmed`（Page.navigate 后 list_pages 复核目标 host 在场）| `endpoint_alive`（导航未证实、仅 CDP endpoint 存活，detail 带异常串）| `activate_issued`（app 激活路径，未做 AX 复核）。路径③（无 endpoint）保持 raise RuntimeError。
  - `ensure_chrome` spawn 后按 0.5s / 6.0s 轮询 `/json/version`，只有端点真的应答才返回；返回句柄带 `.cdp_endpoint`（browser 版本串）。spawn 成功但端点死透 → raise「Chrome spawned but CDP endpoint never became reachable」，不再静默通过。
  - `cdp_click` 点击前 `document.querySelector` 预检 selector，未命中直接报错不盲点，回执带 `evidence.element`（tag + 文本）；`cdp_type`（focused 路径）输入前验证 `document.activeElement`，无焦点报错并带 focus target；`cdp_scroll`/`cdp_see`/`cdp_shot` 把既有天然证据（scrollY before/after、url/title、元素数、请求数、截图长度）包进 `evidence`。
  - manifest `tools[]` 新增 `idempotency`（idempotent | append | side_effect）与 `evidence`（verified | claimed）：`cdp_type` = **append**（重试 = 重复输入，Neuromancer 546 AX 陷阱同族）、`cdp_click`/`hand_plan` = side_effect，其余读取类 = idempotent；字段 additive，旧 portal 忽略不受影响。

#### Fixed
- **假 ok 家族结构性根因（F1）**: `open_place()` URL 分支的 `except Exception: pass` 静默吞掉导航失败，三条路径（导航发出 / 仅 endpoint 活 / raise）中前两条回执形状完全相同。现在降级路径如实标注证据等级，调用方可分辨。
- **spawn/端点竞态（F2）**: Chrome 起得来但立刻崩溃（缺 .so / segfault / win32 路径错）时，回执真假取决于下游探测时点——现在 spawn 后必须探测到端点才返回。
- **失败延迟暴露（F3）**: 点击/输入不再延迟到下一个 `cdp_see` 才暴露问题；未命中/无焦点当场报错并给出原因。

#### Dev
- 反馈台账 F1（P1.5 质门）+ F2（证据等级）+ F3（幂等标记）合流落地：三路径帖 869①、Neuromancer 546/583、Noah 545/547、taojun 假 ok 家族。
- 新增 `tests/test_receipt_contract.py`（L1 全 mock，无真 Chrome 依赖）。

## [6.10.0] - 2026-09-19

#### Added
- **Windows 支持（感知三角修复）**: Windows 上 cdp_shot / hand_see_vlm / cdp_see 三件套全部打通。
  - `_find_chrome()` 新增 win32 查找链：`$CHROME` → Chrome 安装路径 → PATH `chrome.exe`/`msedge.exe` → Edge 安装路径（Edge 是每台 Windows 都有的 Chromium 兜底）。
  - `detect_place()` 新增 PowerShell 前台窗口探测（chrome/msedge/firefox → browser，其余 → desktop_app，失败 → unknown）。
  - manifest `supported` 加入 `windows`，与 `backend_matrix.cdp` 对齐。

#### Changed
- `SEE_PRIORITY["unknown"]` 加入 CDP 后端（`cdp_dom`/`cdp_interactive`），CDP 是 place 无关通道。
- `route_see()` 对 stale `place="unknown"` 与 `place=None` 一样先探测活浏览器，探测到就路由 browser 链并回写 session.place。
- `open_place()` URL 分支诚实失败：导航失败后仅当 CDP 端点真的活着才返回 browser Place，否则 raise RuntimeError（`$CHROME` 提示）。

## [6.9.0] - 2026-09-06

#### Added
- **感知契约 v1 完整落地**: see→do(xy) 坐标闭环三步全部验收通过。
  - Step 1: see 输出坐标元信息（viewport/DPR/坐标空间标注）—— `2bf8ccf`
  - Step 2: DPR≠1 scale 换算验证—— `aa38656`
  - Step 3: 三档 visible + DPR=2 真浏览器保真测试—— `50633a3`
  - 69 tests 全绿，验收记录 + SOP 落盘 `docs/acceptance-contract-v1-cdp.md`

#### Changed
- **cdp_see kind=interactive 输出坐标统一为物理像素**，带 viewport 尺寸和 DPR 标注。click 端只接受已换算坐标。

## [6.8.2] - 2026-09-01

#### Added
- **cdp_shot 图片直达 being（portal 图片链路打通）**: `cdp_shot` 现在把 CDP 截图作为 MCP `ImageContent` 返回，Heart provider 层把工具结果中的 image block 映射为 image_url，截图直达模型 native vision——不再只有 `data_length` 元数据。注意实现细节：`result["data"]` 已是 base64，直接构造 `mcp.types.ImageContent`，不要过 FastMCP `Image`（会双重编码）。前提是 substrate 有视觉能力（如 GLM 5.3 flash native vision）。

#### Fixed
- **route_screenshot place=None 陷阱**: 新进程空 session 时原先直接落 macOS `screencapture`（Linux 上不存在，报 FileNotFoundError）。现在对齐 8820e3f 的 route_see 模式：先探测 CDP 活浏览器，有则走 cdp_screenshot，无才 fallback。

#### Dev
- vision_llm 接线收尾：`hand_see_vlm` MCP 工具注册、`tests/test_vision_llm.py`（53 tests 全绿）、spec-v680-vision-llm.md 落盘。

## [6.8.0] - 2026-08-18

#### Added
- **hand_see_vlm 视觉 LLM 模式**: 新增 `route_see_vlm` + MCP 工具 `hand_see_vlm`，把已有的 `vision_llm.describe_screenshot` 接通为显式视觉感知通道（`cdp_see(kind="vlm")` 也可达）。截图来源优先 CDP 活浏览器、fallback macOS screencapture，发给 OpenRouter `qwen/qwen3-vl-8b-instruct` 描述屏幕内容。这是"眼"的第一道网络级 VLM 通道——不依赖本地 OCR，只要有网络就能"看"。

## [1.6.5] - 2026-08-16

#### Changed
- **vision_llm 默认 provider 切到 OpenRouter**: 默认 endpoint `https://openrouter.ai/api/v1`，默认模型 `qwen/qwen3-vl-8b-instruct`（约 $0.12/M input，支持 image）。zen 网关的免费 omni 模型（mimo-v2.5-free）限流频繁、部分不支持 image，改为 OpenRouter 付费但稳定的 vision 模型。key 读取逻辑升级：根据 endpoint 自动选 provider（OpenRouter→openrouter key，zen→opencode key），key 仍不写死在代码里、存 opencode auth.json

## [1.6.4] - 2026-08-16

#### Added
- **do(xy) 坐标桥**: hand/action/cdp_act.py 的 cdp_click_do 识别 `xy:412,188` 格式，直接按物理像素坐标点击。打通眼→手裂缝——see(INTERACTIVE) 元素地图的 {x,y} 和未来 vision_llm 返回的坐标，都能直接喂给手点击，不再绕回 DOM 找 selector。抽公共函数 _click_at 收敛三处点击路径（selector/text=/xy:）的"÷dpr→dispatchMouseEvent"逻辑

#### Refactor
- **坐标契约文档化**: 所有坐标统一为物理像素（CSS px × devicePixelRatio）。cdp_snapshot.py 输出、cdp_act.py 输入同约定，docstring 写明——锁死历史高发的 ×dpr/÷dpr 方向反坑

## [1.6.3] - 2026-08-16

#### Added
- **vision_llm fallback 视觉后端**: hand/perception/vision_llm.py。DOM 不可用、本地 OCR 不可用时，把截图发给 vision 语言模型描述屏幕——"眼"的最后一道 fallback，只要有网络 + 一个支持图片输入的模型就能看。provider 完全可配置（endpoint/model/key 从环境变量读），默认指向 opencode zen 网关。错误分层返回（rate_limited / no_balance / model_not_supported / no_image_input / auth_failed），让调用方知道该降级还是重试，而不是笼统报错

#### Fixed
- **Cloudflare 反爬拦截**: urllib 默认 User-Agent（Python-urllib/3.x）被 Cloudflare 拦（403 error code: 1010），加 UA 头修复
- **HTTP/2 状态码不可靠**: urllib 在 HTTP/2 下 e.code 报 403、实际响应头是 429。错误分层改为以响应体 error.type 字段为准（跨 provider 通用约定），状态码只做兜底

## [1.6.2] - 2026-08-16

#### Added
- **see(INTERACTIVE) 元素地图**: hand/perception/cdp_snapshot.py 新增 interactive_map()。一次 Runtime.evaluate 批量枚举可交互元素（a[href]/button/input/textarea/select/[role=*]/[onclick]/[tabindex]），返回 {tag, text, selector, x, y, w, h, visible}；selector 优先级 #id → [name] → tag.class → tag:nth-of-type(n)；排序 visible→text→DOM，截断 max_elems=200。规划层从此不再靠文字猜 selector——see 一次就看见"哪里能点、怎么点"
- **do(scroll)**: hand/action/cdp_act.py 新增 cdp_scroll() + cdp_scroll_do()。down/up 用 CDP Input.dispatchMouseEvent（mouseWheel，触发懒加载/无限滚动），window.scrollBy 兜底；top/bottom 用 scrollTo。返回 {scrollY_before, scrollY_after, moved}，moved=False 是"到底/到顶"信号不是错误
- **route_see kind=interactive**: 仿 kind=network，在 Place 解析前分发（interactive map 是 place 无关的浏览器通道）
- **route_do scroll 拦截**: action 以 "scroll" 开头时在 backend 循环前直接走 cdp_scroll_do（否则 cdp_click 会把 "scroll down" 当 CSS selector 静默"成功"）
- **MCP 工具**: cdp_scroll(direction, amount) + manifest 声明；cdp_see 的 manifest 补上 kind 参数（历史 gap：v6.5.2 改了 mcp_server.py 签名但没同步 manifest）

#### Fixed
- **cdp_scroll top/bottom 竞态**: scrollTo 和 wheel 一样是异步渲染，top/bottom 分支原先缺 settle delay，读到旧 scrollY。settle sleep 上移到所有方向共享

## [1.6.1] - 2026-08-16

#### Fixed
- **cdp_type 输入链路**: type 不再误当 selector（旧实现把 text 当 selector 走 route_do 点击）。新增 cdp_type_focused() 直连 Input.insertText；cdp_click 的 4-tier fallback 只对 button/a 触发 Enter/submit，对 input/textarea 不再破坏性提交
- **route_see kind=network**: 分支上移到 Place 解析之前。network 是 place 无关通道，旧实现被 vision_ocr fallback 堵死（place is None 时先报 "No such file or directory"）；cdp_see 加 kind 参数透传

#### Changed
- **kit/sync.sh**: 收敛"开发目录 /home/alice/Hand → 部署目录 ~/.heart-portal/kits/hand"同步循环（语法检查 → rsync hand 包 → cp kit 部署文件 → 停旧进程）。修正 zombie 判断：kill 后进程短暂 Z 态，kill -0 仍返回成功，须用 ps stat 首字符判断

## [1.6.0] - 2026-08-12

#### Added
- **see(NETWORK)**: hand/perception/cdp_network.py
- network_snapshot() captures HTTP request/response via CDP
- bypasses cdp_call() event ingestion bug
- router.py: SEE_PRIORITY updated, kind=network dispatch

## [1.5.0] - 2026-08-11

#### Added
- **Tier 4 MCP router integration**: hand/router_mcp.py with route_plan_mcp()
- Uses MCPEngine when kit available, auto-fallback to Tier 1 CLI
- Tier 3 recovery built-in on both MCP and CLI paths
- Dogfood test: engine=mcp confirmed, 4-step trace with mock routing OK

## [1.4.0] - 2026-08-10

#### Added
- **Tier 5 - Proactive Self-Healing**: hand/plan/healing.py (FailurePredictor + HealingEngine), route_plan_healing() in router
- FailurePredictor: predicts step risk BEFORE execution (no_place, repeated_failure, unknown_kind)
- HealingEngine: wraps execution loop with preventive healing (re-open, skip, replan)
- SPEC.md: Tier 5 marked stable, module topology updated

# Changelog

## [1.3.0] - 2026-08-10

#### Added
- **Tier 4 - MCP-native**: MCPEngine (hand/plan/mcp_engine.py), calls opencode via MCP kit protocol (no subprocess/SSE)
- plan/__init__.py exports MCPEngine + mcpplan default instance
- SPEC.md: Tier 4 marked stable, module topology updated

# Changelog

## [1.2.0] - 2026-08-10

#### Added
- **Tier 2 - Streaming**: StreamingEngine (opencode server + SSE), tier2_prompts.py, route_plan_stream()
- **Tier 3 - Recovery**: recovery.py (RECOVERY_SYSTEM_PROMPT + build_recovery_prompt()), route_plan() now supports max_recoveries=3 param
- SPEC.md: Architecture Tiers section documenting Tier 1-4 architecture

#### Fixed
- Recovery prompt encoding issues (first attempts failed due to shell escaping)

## [1.1.1b] - 2026-08-10

#### Fixed
- Grove publish: use Judy bundle API (bundle embeds manifest.json)
- SPEC.md restored from git (was truncated on disk)
- Docs topology aligned to actual code (cli.py, docs/, tests/)

## [1.1.1] - 2026-08-06

#### Added
- cli.py - hand plan <goal> CLI entry (--json/--model/--session)

#### Fixed
- engine.py: agent name plan -> build (opencode has no plan agent)
- agent.md: marked NOT auto-loaded by opencode
- PLAN-opencode.md: rewritten agent strategy

## [1.1.0] - 2026-08-05

#### Added - V6.1 planning layer
- hand/plan/ module - planning engine
- route_plan() - router planning route
- plan_trace - session planning trace
- hand_plan MCP tool
- tests/test_plan.py (15 cases)

#### Changed
- Version 1.0.0 -> 1.1.0 (V6.1.0)
- SPEC.md planning layer architecture

## [1.0.0] - 2026-08-04

#### Added
- Hand Kit v1.0.0 Grove release
- SPEC.md full module topology
- Docs system (SPEC/CHANGELOG/ROADMAP)

## [0.1.0] - 2026-07

#### Added
- Hand V6 unified framework prototype
- CDP, AX, OCR modules
- Session, Router
