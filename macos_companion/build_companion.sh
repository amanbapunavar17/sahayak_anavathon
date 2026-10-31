#!/usr/bin/env bash
# build_companion.sh — Compile & Package SAHAYAK Native macOS Companion
# Target Architecture: Apple Silicon (arm64) / macOS 12+
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/SahayakCompanion.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
RESOURCES_DIR="$APP_DIR/Contents/Resources"

echo "=========================================================="
echo "  Building SAHAYAK Native macOS Companion (Swift/SwiftUI) "
echo "=========================================================="

mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

echo "[1/4] Compiling Swift source files with on-device Neural Speech & Carbon Hotkeys..."
swiftc -O \
    -parse-as-library \
    -target arm64-apple-macos12.0 \
    -framework Cocoa \
    -framework SwiftUI \
    -framework Carbon \
    -framework Speech \
    -framework AVFoundation \
    "$SCRIPT_DIR/Sources/SafetyManager.swift" \
    "$SCRIPT_DIR/Sources/FloatingHUD.swift" \
    "$SCRIPT_DIR/Sources/VoiceManager.swift" \
    "$SCRIPT_DIR/Sources/WakeWordDetector.swift" \
    "$SCRIPT_DIR/Sources/ActivationManager.swift" \
    "$SCRIPT_DIR/Sources/CompanionView.swift" \
    "$SCRIPT_DIR/Sources/AppDelegate.swift" \
    "$SCRIPT_DIR/Sources/main.swift" \
    -o "$MACOS_DIR/SahayakCompanion"

echo "[2/4] Installing Info.plist with microphone and speech privacy permissions..."
cp "$SCRIPT_DIR/Info.plist" "$APP_DIR/Contents/Info.plist"

echo "[3/4] Applying ad-hoc codesign..."
codesign --force --deep -s - "$APP_DIR" 2>/dev/null || true

echo "[4/4] Build complete: $APP_DIR"
echo "To launch: open $APP_DIR"
