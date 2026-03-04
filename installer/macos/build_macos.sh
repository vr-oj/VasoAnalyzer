#!/usr/bin/env bash
# macOS build script for VasoAnalyzer
#
# Produces: installer/macos/output/<AppName>.dmg
#
# No code signing or notarization — this is an unsigned open-source build.
# On first launch, users must right-click → Open to bypass Gatekeeper.
# This is standard for indie/open-source apps without an Apple Developer account.
#
# Requirements: Python + project dependencies + PyInstaller installed in the
# active environment. Run from anywhere; the script resolves paths automatically.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC="$ROOT/VasoAnalyzer.spec"
DIST_DIR="$ROOT/dist"
OUT_DIR="$ROOT/installer/macos/output"

echo "==> Building VasoAnalyzer .app with PyInstaller"
cd "$ROOT"
pyinstaller --noconfirm "$SPEC"

# Find the built .app bundle (name includes the version string)
APP_BUNDLE=$(find "$DIST_DIR" -maxdepth 2 -name "*.app" | head -1)
if [ -z "$APP_BUNDLE" ]; then
    echo "ERROR: No .app bundle found in $DIST_DIR" >&2
    exit 1
fi

APP_NAME=$(basename "$APP_BUNDLE" .app)
echo "==> Found bundle: $APP_BUNDLE"

# Architecture label: use ARCH_LABEL env var if set, otherwise detect from uname
ARCH_LABEL="${ARCH_LABEL:-$(uname -m)}"
echo "==> Architecture: $ARCH_LABEL"

# Derive a filesystem-safe DMG name (replace spaces with hyphens, append arch)
DMG_STEM="${APP_NAME// /-}-${ARCH_LABEL}"
DMG_PATH="$OUT_DIR/$DMG_STEM.dmg"
STAGING_DIR="$DIST_DIR/dmg_staging"

mkdir -p "$OUT_DIR"

echo "==> Staging DMG contents"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -R "$APP_BUNDLE" "$STAGING_DIR/"
# Applications symlink enables the standard drag-to-install experience
ln -s /Applications "$STAGING_DIR/Applications"

echo "==> Creating DMG: $DMG_STEM.dmg"
hdiutil create \
    -volname "VasoAnalyzer" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

rm -rf "$STAGING_DIR"

echo ""
echo "Build complete: $DMG_PATH"
echo ""
echo "NOTE: This app is unsigned. On first launch users must right-click → Open"
echo "      to bypass Gatekeeper. This is normal for unsigned open-source apps."
