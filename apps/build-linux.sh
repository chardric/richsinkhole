#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Build Linux AppImage and DEB package via electron-builder
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building web assets..."
npm run build

echo "==> Building Linux packages (AppImage + DEB)..."
npx electron-builder --linux AppImage deb

OUTPUT_DIR="$SCRIPT_DIR/../installer/linux"
mkdir -p "$OUTPUT_DIR"

echo "==> Copying packages to $OUTPUT_DIR..."
find "$SCRIPT_DIR/dist-electron" -maxdepth 1 \( -name "*.AppImage" -o -name "*.deb" \) -exec cp -v {} "$OUTPUT_DIR/" \;

echo ""
echo "Linux packages built successfully!"
ls -lh "$OUTPUT_DIR"
