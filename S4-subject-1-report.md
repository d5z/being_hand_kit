# S4 subject-1 report (browser user test of hand 0.8.0-dev)

Kernel: persistent IPython; `from hand import hand`. All perception/action done through hand only
(no requests/urllib anywhere in this session).

## Task 1 — beings.town "Portal Desktop" 段落下方中文描述（原文）
来源: hand.see(kind="a11y") node [65]/[66], 并用 hand.see(kind="dom") 复核（同一字符串，未被截断）

  一个桌面窗口，人类用它和你对话、逛小镇，并把本机工具交给你。Portal（命令行版）已内嵌为它的引擎。

（该段下方一行是：`下载 Portal Desktop → · GET /api/portal 看完整安装引导`）

## Task 2 — 点击 "Browse the Grove →" 并用世界状态验证
- 从 hand.see() 的 a11y 树取句柄: link "Browse the Grove →" [80]
- hand.do("click [80]", expect="url:/grove")
  -> ok=True, verified=True, expect.met=True, waited_ms=60
     evidence.url = https://beings.town/grove , title = "Kit Grove · Beings Town"
- 再用 hand.see() 独立复核（不依赖 expect）: url=https://beings.town/grove,
  title="Kit Grove · Beings Town", verified=True, node_count=600
  树首行: heading "🌳 Kit Grove" (h1) [3]
=> 确认到达 Grove 页面（两个独立来源一致）。

## Task 3 — github.com/d5z/being_hand_kit README 第一段
来源: hand.open(...) 后 hand.see(kind="dom")（a11y 会把该段每行截断到 60 字符，见 findings）

  One being, one hand. Hand is a being's hand on the screen: it opens places, sees what's
  there, and does things — click, type, navigate. It speaks the three primitives open / see / do,
  and routes them to whatever backend fits the current place.

（a11y 版本里强强调词是分开的节点: strong "opens" / "sees" / "does"，代码词是 code 节点 open / see / do。
注意：仓库 README 是 0.7.0 版本，写的是 "click, type, navigate"，本地检出的是 "click, type, navigate, scroll"。）

## Task 4 — beings.town 滚到底部的 footer 文字
- hand.open("https://beings.town"); hand.do("scroll bottom")
  evidence: {'scrollY_before': 0, 'scrollY_after': 2358, 'moved': True, 'direction': 'bottom', 'read_back': 'window.scrollY', 'verified': True}
- hand.see(kind="dom") 末行 = footer 文字:
  Beings Town · built with 🔥 by beings
- a11y 树里对应节点: `  - sectionfooter "" [6]` -> `    - StaticText "Beings Town · built with 🔥 by beings" [7]`（页面上只有这一个 footer 元素）

## Task 5 — 现在有多少个 kit
- https://beings.town/grove 没有 404，直接渲染出了页面（无需回退到 /api/grove）。
- 页面 header: "22 个 Kit · 1 个 App · 12 个最近还在跳 · 被装了 69 次 · 11 位 being 在浇灌"
- 我自己在 a11y 树里数: link "🧩 Kit …" = 22 条, link "📱 App …" = 1 条 —— 与 header 一致。
- 交叉验证（仍只用 hand 打开页面）: https://beings.town/api/grove -> {"count":23,...}；
  https://beings.town/api/grove?kind=kit -> {"count":22,...}。
  即 API 的 count=23 = 22 kits + 1 app。
=> 答案：22 个 kit（另有 1 个 app）。

## findings — README 没写清楚 / 必须试错才知道的东西
1. see(kind="dom") 不返回 `tree`。README 的返回字段表只描述了 a11y 的形态；dom 实际返回
   `text` / `chars` / `total_chars`（+ page_index/coord/page_title）。我第一次写
   `hand.see(kind="dom")["tree"]` 直接 KeyError。network 同理返回 `requests`/`total_requests`/`duration`。
   "固定字段序、byte-identical 回执" 的承诺只在 a11y 频道成立。
2. a11y 的 StaticText 节点会被硬截断到 60 个字符，而且是词中间截断
   （例: "…on the screen: i"、"…read web pag"、"…organize thought"）。关键点：这种"文本级截断"
   在任何地方都没有被声明 —— 当时回执是 truncated=False、nodes_omitted=0。README 说
   "truncation is always declared, never silent"，对节点数成立，对单节点文本不成立。
   后果：只靠默认 a11y 树读中文段落/长句，会拿到半句话而不自知，必须用 kind="dom" 复核。
3. 裸 do() 之后立刻 see() 可能仍然看到旧 URL（导航是异步的）。README 说 "call see() again to
   confirm the URL"，但我实测：click 后紧接着 see() 仍显示 https://beings.town/，sleep 0.4s 后
   才是 /grove。可靠做法是 expect=（或等一小会儿）——"再 see 一次" 本身是有竞态的。
4. kind 切换不会作废 [idx]（INFO，但与直觉相反）：a11y see 拿到 [80] 后再做一次 see(kind="dom")，
   再 click [80] 依然成功（回执里 backend_node_id 已从 64 变成 1355）。README 说句柄"来自最近一次
   快照的 handle map"，暗示换频道会失效，实测不会。（真正的失效是跨页面导航：click 旧 [7] 报
   "handle [7] element is gone (backendNodeId … does not resolve) — call cdp_see again"，教学式报错很好。）
5. dom 文本最多给 8000 字符（truncated=true, total_chars≈29805）。截断被声明了，但 8000 这个上限
   README 没写。读 /api/grove 这种 JSON 时只能看到前 12 个条目。
6. see(kind="network") 是"现场监听"式的：在页面已经加载完之后再调用，只等到 duration≈3s、
   requests=0。它大概只捕获调用窗口内发出的请求；这一点 README 完全没提（我本想用它拿
   /api/grove 的完整响应体，没成功）。
7. see() 没有子树/选择器参数（signature 是 see(kind=None)）。想"只看 footer 的文字"或"只看某个
   段落"做不到，只能整页取文本再按行切 —— 任务 4 就是这样做的。
8. 读长文本的正确姿势在 README 里没有交叉引用：a11y 用于定位与点击，dom 用于读原文；两者要配合。

## 轮次（turns）
共 25 个工具执行单元（IPython cell / turn）完成全部 5 个任务 + 4 项额外试错验证。


---

# ADDENDUM — 源码层验证（把 findings 从"推测"升级为"已证实"）

下面每条都在 /home/alice/Hand 的当前检出里核对过源码（本文件只读源码，未改任何 hand 代码）。

F1. **60 字符静默截断 —— 已证实，且是设计层面的事实，不只是文档缺口**
   - `hand/perception/ax_tree.py:68`: `MAX_NAME = 60   # chars of accessible name kept per line`
   - `ax_tree.py:144-148`: `def sanitize_name(name, limit=MAX_NAME): ... return (name or "").replace("\n", " ")[:limit]`
     —— 直接裸切片，**不加省略号、不加任何标记**。
   - 模块 docstring 的 "Truncation is explicit" 一节只承诺了 `max_lines`：
     "beyond `max_lines` the tree is cut, `truncated` is True and `nodes_omitted` counts the dropped lines"。
   - 实测回执里 a11y 会带 `max_lines: 600`（我在 Grove 页拿到的就是 600），
     但**任何地方都没有一个字段声明单节点名被截到 60**。
   - 结论：README（"truncation is always declared, never silent (truncated / nodes_omitted)"）和
     hand.py:30 的同句承诺，在"单节点文本"这一层不成立。这是一个可复现的契约漏洞。
   - 对照证据（同一页、同一段话）：
       a11y:  StaticText "Send a private note — you have an inbox, and anything that p"  [140]
       dom :  "Send a private note — you have an inbox, and anything that points to you
               will find its way there: POST /api/messages {…}."
   - **给用户的检测启发式**：a11y 行里某个 name 长度恰好 == 60 就是被截断的信号；要读原文一律用 `see(kind="dom")`。

F2. **8000 字符的 dom 上限是硬编码且不可调 —— 已证实**
   - `hand/perception/cdp_snapshot.py:16`: `def cdp_snapshot(max_chars=8000, page_sel=None)`
   - 全仓库只有这一处出现 `max_chars`：**没有** CLI flag、没有 MCP 参数、Python 面 `see(kind=None)` 也不透传。
     kit/manifest.json 的 `cdp_see` params 只有 `{"kind": enum[a11y,dom,interactive,network,screenshot]}`。
   - 所以两个 face 都无法把 8000 调大；读 `/api/grove` 这类 JSON 只能看到前 12 个条目（total_chars≈29805）。

F3. **network 频道是"现场监听 3 秒" —— 已证实，并发现一处死代码**
   - `hand/perception/cdp_network.py:5`: `def network_snapshot(page_sel=None, duration=3.0, ...)`；
     `hand/router.py:251-258`: `kind == "network"` 时调 `network_snapshot()`（无参数，即默认 3s 监听窗口）。
   - 它只报告**调用窗口内**发生的请求；页面加载完再调用 → `total_requests: 0`（我实测如此）。
   - `fetch_network_body`（cdp_network.py:132）确实实现了"按 request_id 取响应体"，
     在 cdp_snapshot.py:172 被 import，但**没有任何公开动词/工具/CLI 会调用它** —— 死代码。
     也就是说：从两个 face 都拿不到响应体。

F4. **换 kind 不作废 [idx] —— 已证实（源码解释）**
   - 句柄按 `backendNodeId` 存储并在点击时重新解析（`resolve_handle`，ax_tree.py:349；
     回执 evidence.read_back = "getBoundingClientRect via DOM.resolveNode"）。
   - 我实测：a11y see 得 `[80]` → 插一次 `see(kind="dom")` → `click [80]` 成功
     （回执 backend_node_id 由 64 变 1355，说明解析的是新快照的节点，而 idx 编号规则一致）。
   - 真正失效的是"元素已不在页面上"：跨页后点旧 `[7]` 得到
     `handle [7] element is gone (backendNodeId 1515 does not resolve) — call cdp_see again`
     （报错 + hint 都是教学式的，这点体验很好）。

F5. **裸 do() 后立刻 see() 有竞态 —— 已证实**
   无 `expect=` 时 `do()` 立即返回（README 明说），导航仍在进行；我实测 click 后紧接着的 see()
   仍是 `https://beings.town/`，~0.4s 后才变 `/grove`。要可靠确认只能用 `expect=`。

F6. **see() 无子树参数 —— 已证实**：`hand/hand.py:447 def see(self, kind=None)`，只有一个参数；
   想取"footer 文字"只能整页取文本按行切（任务 4 的做法）。

F7. **两个 face 的能力差**：README 说 "The Python face adds no capability — it is the second face of
   the same body"。就 see 的返回形态而言，Python 面暴露 `see(kind=…)`，而 MCP 面是
   `cdp_see(kind=…)`，两者参数一致（都为枚举），这条成立；但 `see()` 的**返回字段表** README 只写了 a11y 一种形态，
   dom/network 的字段名（text/chars/total_chars、requests/total_requests/duration）无处可查，
   "固定字段序、byte-identical" 的契约实际只覆盖 a11y。

（以上 7 条中 F1/F2/F3 建议至少补进 README 的 see() 章节与 SPEC.md；F1 更像需要修的产品问题。）
