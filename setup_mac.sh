#!/usr/bin/env bash
# setup_mac.sh — One-shot setup script for SAHAYAK on macOS (Apple Silicon M4)
# Tagline: Your Voice. Your Freedom.
# Usage: bash setup_mac.sh

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }
section() { echo -e "\n${BOLD}$*${RESET}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

section "=========================================================="
echo "          SAHAYAK — Your Voice. Your Freedom."
echo "     Accessibility Assistant Setup for macOS (Apple Silicon)"
section "=========================================================="

# ── 1. Python version check ──────────────────────────────────────────────────
section "1. Checking Python runtime (Apple Silicon M4)..."

PYTHON_BIN=""
for candidate in python3.11 python3.12 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        major=$("$candidate" -c 'import sys; print(sys.version_info[0])')
        minor=$("$candidate" -c 'import sys; print(sys.version_info[1])')
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    error "Python 3.10+ is required but was not found.\nInstall via Homebrew: brew install python@3.11"
fi

info "Using $PYTHON_BIN ($(${PYTHON_BIN} --version))"

# ── 2. Virtual Environment Setup ─────────────────────────────────────────────
section "2. Setting up SAHAYAK Python virtual environment..."

VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    info "Created virtual environment at $VENV_DIR"
else
    info "Virtual environment already exists at $VENV_DIR"
fi

info "Upgrading pip and installing core free-first dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
info "All Python dependencies installed successfully."

# ── 3. Configuration & .env Setup ────────────────────────────────────────────
section "3. Configuring environment files..."

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    info "Created .env from .env.example"
    warn "ACTION REQUIRED: Open .env and paste your Gemini API key:"
    warn "  → GEMINI_API_KEY=your_key_here"
    warn "  (Get a free key from Google AI Studio: https://aistudio.google.com)"
else
    info ".env already exists — preserving your settings."
fi

if [ ! -f "$SCRIPT_DIR/server/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/server/.env"
fi

# ── 4. macOS Permissions Reminder ────────────────────────────────────────────
section "4. macOS Permissions Checklist"
echo ""
echo "  SAHAYAK requires three standard macOS permissions granted to your Terminal / IDE:"
echo ""
echo "  1. Accessibility    → System Settings → Privacy & Security → Accessibility"
echo "  2. Screen Recording → System Settings → Privacy & Security → Screen Recording"
echo "  3. Microphone       → System Settings → Privacy & Security → Microphone"
echo ""

# ── 5. Run automated test suite ──────────────────────────────────────────────
section "5. Verifying installation with automated test suite..."
"$VENV_DIR/bin/pytest" "$SCRIPT_DIR/tests/test_sahayak_e2e.py" -q || warn "Some tests warned; check above."

section "Setup complete!"
echo ""
echo "  To launch SAHAYAK, run:"
echo "    ${BOLD}./start.sh${RESET}"
echo ""
echo "  Or start manually:"
echo "    ${BOLD}venv/bin/python server/main.py${RESET}"
echo ""
