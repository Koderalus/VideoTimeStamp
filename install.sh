#!/usr/bin/env bash
# install.sh — One-time setup for VideoTimeStamp (macOS)

set -e

echo ""
echo "====================================="
echo "  VideoTimeStamp — Setup"
echo "====================================="
echo ""

# ── Homebrew ──────────────────────────────────────────────────────────────────
if command -v brew &>/dev/null; then
    echo "✓ Homebrew: $(brew --version | head -1)"
else
    echo "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Apple Silicon: add Homebrew to PATH for this session
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    echo "✓ Homebrew installed"
fi

# ── FFmpeg ────────────────────────────────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
    echo "✓ FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "Installing FFmpeg (this may take a few minutes)..."
    brew install ffmpeg
    echo "✓ FFmpeg installed"
fi

if ! command -v ffprobe &>/dev/null; then
    echo "ERROR: ffprobe not found after install. Try: brew reinstall ffmpeg"
    exit 1
fi

# ── Python 3 (Homebrew) ───────────────────────────────────────────────────────
# macOS ships with an old system Python + Tk 8.5 which breaks the GUI.
# We install Python and Tk via Homebrew to get a modern, supported version.
BREW_PYTHON=""
for ver in 3.13 3.12 3.11; do
    if [[ -f "/opt/homebrew/bin/python${ver}" ]]; then
        BREW_PYTHON="/opt/homebrew/bin/python${ver}"
        break
    fi
done

if [[ -n "$BREW_PYTHON" ]]; then
    echo "✓ Homebrew Python: $($BREW_PYTHON --version)"
else
    echo "Installing Python 3 via Homebrew..."
    brew install python@3.13
    BREW_PYTHON="/opt/homebrew/bin/python3.13"
    echo "✓ Python installed: $($BREW_PYTHON --version)"
fi

# Install matching Tk bindings
PYVER=$($BREW_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if brew list "python-tk@${PYVER}" &>/dev/null 2>&1; then
    echo "✓ Tk bindings already installed"
else
    echo "Installing Tk bindings for Python ${PYVER}..."
    brew install "python-tk@${PYVER}" || brew install python-tk
    echo "✓ Tk bindings installed"
fi

# Write the Python path so run.sh always uses the right interpreter
echo "$BREW_PYTHON" > .python_path

# ── Folders ───────────────────────────────────────────────────────────────────
mkdir -p input output logs
echo "✓ Folders ready: input/  output/  logs/"

# ── Default config ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/config.json"

if [[ ! -f "$CONFIG" ]]; then
    cat > "$CONFIG" << 'EOF'
{
  "timezone": "AEST (UTC+10:00) \u2014 QLD, NSW, VIC, TAS, ACT",
  "text_style": "White text only",
  "input_folder": "",
  "output_folder": ""
}
EOF
    echo "✓ Default config.json created"
else
    echo "✓ config.json already exists (not overwritten)"
fi

echo ""
echo "====================================="
echo "  Setup complete"
echo "====================================="
echo ""
echo "  To launch the app, double-click run.sh"
echo "  or run in Terminal:"
echo "    bash run.sh"
echo ""
