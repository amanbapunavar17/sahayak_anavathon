#!/usr/bin/env bash
# start.sh — Unified One-Command Startup for SAHAYAK
# Tagline: Your Voice. Your Freedom.
# Usage: ./start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "\n${BOLD}${CYAN}========================================================${RESET}"
echo -e "${BOLD}         SAHAYAK — Your Voice. Your Freedom.${RESET}"
echo -e "${CYAN}========================================================${RESET}\n"

# 1. Check virtual environment
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo -e "${YELLOW}[!] Virtual environment not found. Running setup_mac.sh...${RESET}"
    bash "$SCRIPT_DIR/setup_mac.sh"
fi

# 2. Check .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${YELLOW}[!] Creating .env from .env.example...${RESET}"
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
fi

# 3. Inform about Gemini API Key
if grep -q "^GEMINI_API_KEY=$" "$SCRIPT_DIR/.env" 2>/dev/null || grep -q "^GEMINI_API_KEY=\s*$" "$SCRIPT_DIR/.env" 2>/dev/null; then
    echo -e "${YELLOW}[NOTE] GEMINI_API_KEY is not configured yet in .env${RESET}"
    echo -e "       SAHAYAK will run in ${BOLD}Local Offline Assistive Mode${RESET} (using Apple Vision OCR & local rules)."
    echo -e "       To enable full Gemini 3.8 Flash intelligence, add your key to ${BOLD}.env${RESET}\n"
else
    echo -e "${GREEN}[✓] Gemini AI configuration detected.${RESET}\n"
fi

# 4. Check or Build native macOS Companion
if [ ! -d "$SCRIPT_DIR/macos_companion/SahayakCompanion.app" ]; then
    echo -e "${CYAN}[*] Building native macOS Companion (Option+Space global activation)...${RESET}"
    bash "$SCRIPT_DIR/macos_companion/build_companion.sh" || true
fi

# 5. Announce via macOS Speech
say -v Samantha "Starting SAHAYAK. Your Voice, Your Freedom." 2>/dev/null || true

# 6. Launch macOS Companion & Web Dashboard after brief startup delay
(
    sleep 2
    if [ -d "$SCRIPT_DIR/macos_companion/SahayakCompanion.app" ]; then
        open "$SCRIPT_DIR/macos_companion/SahayakCompanion.app" 2>/dev/null || true
    fi
    open "http://127.0.0.1:8080" 2>/dev/null || true
) &

# 7. Start the server
echo -e "${GREEN}[✓] Starting SAHAYAK Server on http://127.0.0.1:8080...${RESET}"
echo -e "    Press ${BOLD}Ctrl+C${RESET} to stop.\n"

export PYTHONPATH="$SCRIPT_DIR/server:${PYTHONPATH:-}"
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/server/main.py"

