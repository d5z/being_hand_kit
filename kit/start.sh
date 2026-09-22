#!/bin/bash
# Hand — Portal Kit start script
# Launched by Portal. Sets up the CDP browser environment, then runs the
# MCP server over stdio.
#
# Cross-platform note: on Linux we need (a) a headless chromium binary and
# (b) bundled .so deps. On macOS a system Chrome/Safari usually suffices and
# CDP is optional.
#
# Requires python3 >= 3.10 (the mcp SDK and hand's own annotations).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Locate the kit home (where lib/ and hand/ live) ---
KIT_HOME="$SCRIPT_DIR"

# --- .env (optional) ---
# Load a kit-local .env before anything else, so it can set CHROME,
# HAND_PROFILE / HAND_PROFILE_DIR / HAND_HEADLESS, GROVE_TOKEN, ...
# `set -a` matters: plain KEY=value lines are not exported by sourcing alone,
# and the MCP process would never see them (F11).
if [ -f "$KIT_HOME/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$KIT_HOME/.env"
  set +a
fi

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

# --- Python interpreter ---
# Prefer the kit's own .venv (where `pip install -r requirements.txt` puts
# the mcp SDK on grove installs), fall back to system python3.
# Rationale (0.8.1, Judy 2026-09-22 #34 sample): a kit that depends on the
# mcp SDK but launches via bare system python3 is a dead end on any machine
# without a global mcp install — requirements go into .venv, but start.sh
# never looked there, so the venv was installed for nothing.
if [ -x "$KIT_HOME/.venv/bin/python3" ]; then
  PY="$KIT_HOME/.venv/bin/python3"
else
  PY="python3"
fi

cd "$KIT_HOME" || exit 1
exec "$PY" mcp_server.py
