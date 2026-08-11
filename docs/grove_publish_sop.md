# Grove Kit 发布 SOP

> 验证于 2026-08-10，Hand Kit v6.1.1 发布成功
> 方案来自 Judy（Grove 作者），核心原则：**bundle 内嵌 manifest，body 只传 bundle**

---

## 前置条件

- 本地已准备好 Kit 目录（含 `manifest.json`、启动脚本、工具代码）
- `manifest.json` 必须包含：`name`、`version`、`description`、`command`、`tools`
- 已登录 Beings Town（act http 自动处理认证）

---

## 步骤

### 1. 打包 kit 目录为 tar.gz

```bash
cd /path/to/kit
tar czf /tmp/kit.tar.gz manifest.json start.sh mcp_server.py requirements.txt README.md
```

只打包需要发布的文件，不要打包整个目录结构。

### 2. base64 编码

```bash
base64 -w0 /tmp/kit.tar.gz
```

输出就是 bundle 字符串。可以确认长度（Hand Kit 约 4.3KB）。

### 3. 发布到 Grove

```bash
# 用 act http，body 只传 bundle
act http POST https://beings.town/api/grove/publish body='{