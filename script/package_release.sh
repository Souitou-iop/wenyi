#!/usr/bin/env bash
set -euo pipefail

: "${DEVELOPER_ID_APPLICATION:?Set DEVELOPER_ID_APPLICATION to the Developer ID Application identity}"
: "${NOTARY_PROFILE:?Set NOTARY_PROFILE to an xcrun notarytool keychain profile}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE_PATH="$ROOT_DIR/.build/WenyiMac.xcarchive"
EXPORT_DIR="$ROOT_DIR/dist/release"
DMG_PATH="$ROOT_DIR/dist/WenyiMac.dmg"

cd "$ROOT_DIR"
xcodegen generate
rm -rf "$ARCHIVE_PATH" "$EXPORT_DIR" "$DMG_PATH"
xcodebuild -project WenyiMac.xcodeproj -scheme WenyiMac -configuration Release -archivePath "$ARCHIVE_PATH" archive CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="$DEVELOPER_ID_APPLICATION" DEVELOPMENT_TEAM="${DEVELOPMENT_TEAM:-}"
mkdir -p "$EXPORT_DIR" "$(dirname "$DMG_PATH")"
cp -R "$ARCHIVE_PATH/Products/Applications/WenyiMac.app" "$EXPORT_DIR/"
/usr/bin/hdiutil create -volname "文译" -srcfolder "$EXPORT_DIR" -ov -format UDZO "$DMG_PATH"
xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
xcrun stapler staple "$DMG_PATH"
spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"
echo "$DMG_PATH"
