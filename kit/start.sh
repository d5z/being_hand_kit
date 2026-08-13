#!/bin/bash
# Hand — Portal Kit start script
# Launched by Portal as: bash start.sh
# MCP protocol over stdio: stdin/stdout is JSON-RPC
#
# Locate this script's own directory and run the sibling mcp_server.py.
# Works both in dev layout (<root>/kit/) and bundle layout (<root>/).

HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/mcp_server.py"
