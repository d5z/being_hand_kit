#!/usr/bin/env python3
"""阶段0核心验证：a11y 树 → 过滤 → 序列化 + backendNodeId→坐标解析。

验证三件事：
1. 过滤规则能压掉多少噪音
2. 序列化格式长什么样、多少 token
3. backendDOMNodeId → DOM.pushNodesByBackendIdsToFrontend → getBoxModel 能否拿到坐标
"""
import json
import sys
import urllib.request
import websocket

CDP_HTTP = "http://127.0.0.1:9222"

# 交互角色白名单——这些角色的节点需要坐标（可操作面）
INTERACTIVE_ROLES = {
    "link", "button", "textbox", "combobox", "checkbox", "radio",
    "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option",
    "switch", "searchbox", "slider", "spinbutton", "listbox",
}

# 有语义价值的状态属性
STATE_PROPS = {"disabled", "checked", "expanded", "selected", "pressed",
               "hasPopup", "required", "invalid", "level", "value"}


def get_page():
    with urllib.request.urlopen(f"{CDP_HTTP}/json") as r:
        pages = json.load(r)
    return next(p for p in pages if p.get("type") == "page")


class CDP:
    def __init__(self, page):
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
        self.mid = 0

    def call(self, method, params=None):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params or {}}))
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get("id") == self.mid:
                if "error" in resp:
                    raise RuntimeError(f"{method}: {resp['error']}")
                return resp.get("result", {})


def prop_value(node, name):
    for p in node.get("properties", []):
        if p["name"] == name:
            v = p.get("value", {})
            return v.get("value")
    return None


def build_snapshot(cdp):
    tree = cdp.call("Accessibility.getFullAXTree")["nodes"]

    # ---- 过滤 ----
    kept = []
    for n in tree:
        if n.get("ignored"):
            continue
        role = n.get("role", {}).get("value", "?")
        if role in ("InlineTextBox", "ListMarker"):
            continue
        kept.append(n)

    # ---- parentId → children 索引 ----
    by_id = {n["nodeId"]: n for n in kept}
    children = {}
    roots = []
    for n in kept:
        pid = n.get("parentId")
        if pid and pid in by_id:
            children.setdefault(pid, []).append(n)
        else:
            roots.append(n)

    # ---- 序列化（YAML 风格缩进树，v2：折叠无名 generic 链 + 去重复 StaticText）----
    lines = []
    meta = []  # (index, backendNodeId, role, name)
    counter = [0]

    def node_label(node):
        role = node.get("role", {}).get("value", "?")
        name = (node.get("name") or {}).get("value", "") or ""
        name = name.replace("\n", " ")[:60]
        states = []
        for p in STATE_PROPS:
            v = prop_value(node, p)
            if v in (None, False, "false", ""):
                continue
            if p == "level" and role != "heading":
                continue  # level 只对 heading 有语义（AX 树会误挂到 listitem）
            states.append(f"{p}={v}" if p != "level" else f"h{v}")
        focusable = prop_value(node, "focusable")
        if focusable and role not in INTERACTIVE_ROLES:
            states.append("focusable")
        state_s = f" ({', '.join(states)})" if states else ""
        return role, name, state_s

    def emit(node, depth):
        counter[0] += 1
        idx = counter[0]
        role, name, state_s = node_label(node)
        indent = "  " * depth
        lines.append(f"{indent}- {role} \"{name}\"{state_s} [{idx}]")
        bid = node.get("backendDOMNodeId")
        if bid:
            meta.append((idx, bid, role, name))
        for c in children.get(node["nodeId"], []):
            emit(c, depth + 1)

    def emit_compact(node, depth):
        """折叠：无名无状态无交互角色的单子链节点不占行，子节点上提。"""
        kids = children.get(node["nodeId"], [])
        role, name, state_s = node_label(node)
        is_structural = (role in ("generic", "none", "") and not name
                         and not state_s and len(kids) == 1)
        if is_structural:
            emit_compact(kids[0], depth)  # 透传，不占行
            return
        counter[0] += 1
        idx = counter[0]
        indent = "  " * depth
        lines.append(f"{indent}- {role} \"{name}\"{state_s} [{idx}]")
        bid = node.get("backendDOMNodeId")
        if bid:
            meta.append((idx, bid, role, name))
        parent_name = name
        for c in kids:
            c_role, c_name, _ = node_label(c)
            # StaticText 与父名重复 → 跳过（名字已在父行）
            if c_role == "StaticText" and c_name and c_name.strip() == parent_name.strip():
                counter[0] += 1  # 仍占索引，保持树完整可回溯
                continue
            emit_compact(c, depth + 1)

    for r in roots:
        emit_compact(r, 0)

    # ---- backendNodeId → 坐标（批量解析可操作面）----
    interactive_meta = [m for m in meta if m[2] in INTERACTIVE_ROLES]
    coords = {}
    if interactive_meta:
        cdp.call("DOM.getDocument", {"depth": 0})  # 初始化 DOM agent
        bids = [m[1] for m in interactive_meta if m[1]]
        res = cdp.call("DOM.pushNodesByBackendIdsToFrontend", {"backendNodeIds": bids})
        node_ids = res.get("nodeIds", [])
        for m, nid in zip(interactive_meta, node_ids):
            if not nid:
                continue
            try:
                box = cdp.call("DOM.getBoxModel", {"nodeId": nid})
                quad = box["model"]["content"]
                xs = [quad[i] for i in range(0, len(quad), 2)]
                ys = [quad[i] for i in range(1, len(quad), 2)]
                coords[m[0]] = {
                    "x": round((min(xs) + max(xs)) / 2),
                    "y": round((min(ys) + max(ys)) / 2),
                }
            except RuntimeError:
                coords[m[0]] = None  # 不在渲染树（display:none 等）

    return tree, kept, lines, coords, interactive_meta


def main():
    page = get_page()
    print(f"page: {page['url'][:80]}")
    cdp = CDP(page)
    tree, kept, lines, coords, interactive_meta = build_snapshot(cdp)

    print(f"原始节点: {len(tree)} → 过滤后: {len(kept)}")
    snapshot = "\n".join(lines)
    print(f"序列化: {len(lines)} 行, {len(snapshot)} chars, ~{len(snapshot)//4} tokens")

    ok = sum(1 for v in coords.values() if v)
    print(f"可操作面解析: {ok}/{len(coords)} 拿到坐标")

    print("\n===== 序列化样本（前 45 行）=====")
    print("\n".join(lines[:45]))

    print("\n===== 坐标样本（前 10 个交互元素）=====")
    for m in interactive_meta[:10]:
        c = coords.get(m[0])
        print(f"  [{m[0]}] {m[2]} \"{m[3][:30]}\" -> {c}")

    if "--save" in sys.argv:
        i = sys.argv.index("--save")
        with open(sys.argv[i + 1], "w") as f:
            f.write(snapshot)
        with open(sys.argv[i + 1] + ".coords.json", "w") as f:
            json.dump({str(k): v for k, v in coords.items()}, f, ensure_ascii=False, indent=1)
        print(f"\nsaved -> {sys.argv[i+1]}")


if __name__ == "__main__":
    main()
