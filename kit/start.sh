#!/bin/bash
# Hand V6.1 — Portal Kit start script
# Launched by Portal as: bash start.sh
# MCP protocol over stdio: stdin/stdout is JSON-RPC

cd "$(dirname "$0")/.."
exec python3 kit/mcp_server.py
