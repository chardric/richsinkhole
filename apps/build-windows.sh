#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Build Windows NSIS installer via electron-builder (cross-compile from Linux)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# electron-builder requires wine for Windows cross-compilation on Linux
if ! command -v wine &>/dev/null; then
    echo "WARNING: wine is not installed. Windows cross-compilation may fail."
    echo "         Install with: sudo apt-get install wine64"
fi

echo "==> Building web assets..."
npm run build

echo "==> Building Windows NSIS installer..."
npx electron-builder --win

OUTPUT_DIR="$SCRIPT_DIR/../installer/windows"
mkdir -p "$OUTPUT_DIR"

echo "==> Copying installer to $OUTPUT_DIR..."
find "$SCRIPT_DIR/dist-electron" -maxdepth 1 -name "*.exe" -exec cp -v {} "$OUTPUT_DIR/" \;

echo ""
echo "Windows installer built successfully!"
ls -lh "$OUTPUT_DIR"
