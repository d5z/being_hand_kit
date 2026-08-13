#!/bin/bash
# Hand — Portal Kit start script
# Launched by Portal. Sets up the CDP browser environment, then runs the
# MCP server over stdio.
#
# Cross-platform note: on Linux we need (a) a headless chromium binary and
# (b) bundled .so deps. On macOS a system Chrome/Safari usually suffices and
# CDP is optional.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Locate the kit home (where lib/ and hand/ live) ---
KIT_HOME="$SCRIPT_DIR"

# --- Chrome binary ---
# Prefer an explicit env override, then the playwright headless shell.
if [ -z "$CHROME" ]; then
  HS="$HOME/.cache/ms-playwright/chromium_headless_shell-"*"/chrome-headless-shell-linux64/chrome-headless-shell"
  CHROMIUM="$HOME/.cache/ms-playwright/chromium-"*"/chrome-linux64/chrome"
  # shellcheck disable=SC2086
  for cand in $HS $CHROMIUM; do
    if [ -f "$cand" ]; then
      CHROME="$cand"
      break
    fi
  done
fi
if [ -n "$CHROME" ]; then
  export CHROME
fi

# --- Bundled Linux .so deps ---
if [ -d "$KIT_HOME/lib" ]; then
  if [ -z "$LD_LIBRARY_PATH" ]; then
    export LD_LIBRARY_PATH="$KIT_HOME/lib"
  else
    export LD_LIBRARY_PATH="$KIT_HOME/lib:$LD_LIBRARY_PATH"
  fi
fi

cd "$KIT_HOME" || exit 1
exec python3 mcp_server.py
