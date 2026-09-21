#!/usr/bin/env python3
"""a11y_ab 阶段0：拉真实 a11y 树，看结构。

用法: python3 dump_ax.py [url_or_none] [--save out.json]
不传 url = 只 dump 当前已打开的页面。
"""
import json
import sys
import urllib.request
import websocket

CDP_HTTP = "http://127.0.0.1:9222"


def get_pages():
    with urllib.request.urlopen(f"{CDP_HTTP}/json") as r:
        return json.load(r)


def connect_page_ws(page):
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    return ws


def cdp_call(ws, method, params=None, msg_id=1):
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp


def main():
    save_path = None
    args = sys.argv[1:]
    if "--save" in args:
        i = args.index("--save")
        save_path = args[i + 1]
        args = args[:i] + args[i + 2:]

    pages = [p for p in get_pages() if p.get("type") == "page"]
    if not pages:
        print("no open page")
        sys.exit(1)
    page = pages[0]
    print(f"page: {page['url'][:80]}")

    ws = connect_page_ws(page)
    result = cdp_call(ws, "Accessibility.getFullAXTree")
    if "error" in result:
        print("ERROR:", result["error"])
        sys.exit(1)

    tree = result["result"]["nodes"]
    print(f"total nodes: {len(tree)}")

    # 角色分布
    from collections import Counter
    roles = Counter(n.get("role", {}).get("value", "?") for n in tree)
    print("\n===== role 分布 top 20 =====")
    for role, cnt in roles.most_common(20):
        print(f"  {role:24s} {cnt}")

    # backendNodeId 覆盖（能不能映射回可操作面）
    with_backend = sum(1 for n in tree if n.get("backendDOMNodeId"))
    print(f"\nbackendDOMNodeId 覆盖: {with_backend}/{len(tree)}")

    # 有名字的节点样本（看 name 来源）
    named = [n for n in tree if n.get("name", {}).get("value")]
    print(f"有 name 的节点: {len(named)}")
    name_sources = Counter(
        (n["name"].get("sources") or [{}])[0].get("type", "no-source")
        for n in named
    )
    print("\n===== name 来源分布 =====")
    for src, cnt in name_sources.most_common(10):
        print(f"  {src:24s} {cnt}")

    # 状态字段覆盖：checked/disabled/expanded/focused
    print("\n===== 状态字段覆盖 =====")
    for field in ("checked", "disabled", "expanded", "focused", "selected", "pressed"):
        cnt = sum(1 for n in tree if field in n and n[field] not in (None, "false"))
        cnt_any = sum(1 for n in tree if field in n)
        print(f"  {field:10s} 出现={cnt_any:5d}  非默认值={cnt}")

    # 样本：前 12 个有名字的节点完整结构
    print("\n===== 样本节点（前12个有name的）=====")
    for n in named[:12]:
        role = n.get("role", {}).get("value")
        name = n.get("name", {}).get("value", "")[:40]
        nid = n.get("backendDOMNodeId")
        extra = {k: n[k].get("value") if isinstance(n[k], dict) else n[k]
                 for k in ("checked", "disabled", "expanded", "focused")
                 if k in n and n[k] not in (None, "false")}
        print(f"  [{role}] {name!r} backend={nid} {extra if extra else ''}")

    if save_path:
        with open(save_path, "w") as f:
            json.dump(tree, f, ensure_ascii=False, indent=1)
        print(f"\nsaved -> {save_path}")

    ws.close()


if __name__ == "__main__":
    main()
