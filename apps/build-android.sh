#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Build Android APK via Capacitor
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building web assets..."
npm run build

echo "==> Syncing Capacitor Android project..."
npx cap sync android

echo "==> Building APK (debug)..."
cd android
./gradlew assembleDebug
cd ..

OUTPUT_DIR="$SCRIPT_DIR/../installer/mobile"
mkdir -p "$OUTPUT_DIR"

APK_SRC="$SCRIPT_DIR/android/app/build/outputs/apk/debug/app-debug.apk"
APK_DST="$OUTPUT_DIR/RichSinkhole.apk"

if [ -f "$APK_SRC" ]; then
    cp "$APK_SRC" "$APK_DST"
    echo ""
    echo "Android APK built successfully!"
    echo "  Output: $APK_DST"
else
    echo "ERROR: APK not found at $APK_SRC"
    exit 1
fi
