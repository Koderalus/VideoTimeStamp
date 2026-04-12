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

# ── Python 3 ──────────────────────────────────────────────────────────────────
if command -v python3 &>/dev/null; then
    echo "✓ Python: $(python3 --version)"
else
    echo "ERROR: python3 not found. Install via: brew install python3"
    exit 1
fi

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
echo "  To launch the app:"
echo "    python3 app.py"
echo ""

# Remind Apple Silicon users to add Homebrew to their shell profile
if [[ -f /opt/homebrew/bin/brew ]] && ! grep -q 'homebrew' ~/.zprofile 2>/dev/null; then
    echo "  NOTE: Add Homebrew to your PATH permanently by running:"
    echo "    echo 'eval \"\$(/opt/homebrew/bin/brew shellenv)\"' >> ~/.zprofile"
    echo ""
fi
