#!/usr/bin/env bash
# run.sh — Launch VideoTimeStamp using the Homebrew Python installed by install.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure Homebrew is on PATH (needed on Apple Silicon)
if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# Use the Python path recorded by install.sh, fall back to Homebrew python3
if [[ -f "$SCRIPT_DIR/.python_path" ]]; then
    PYTHON=$(cat "$SCRIPT_DIR/.python_path")
else
    PYTHON="/opt/homebrew/bin/python3"
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python not found at: $PYTHON"
    echo "Please run install.sh first:  bash install.sh"
    exit 1
fi

# Silence the macOS system Tk deprecation warning (not applicable with Homebrew Python,
# but harmless to set)
export TK_SILENCE_DEPRECATION=1

exec "$PYTHON" app.py
