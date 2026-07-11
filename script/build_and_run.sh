#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DERIVED_DATA="$ROOT_DIR/.build/DerivedData"
APP="$DERIVED_DATA/Build/Products/Debug/WenyiMac.app"

cd "$ROOT_DIR"
pkill -x WenyiMac >/dev/null 2>&1 || true
xcodegen generate
xcodebuild -project WenyiMac.xcodeproj -scheme WenyiMac -configuration Debug -derivedDataPath "$DERIVED_DATA" build CODE_SIGNING_ALLOWED=NO

case "$MODE" in
  run)
    /usr/bin/open -n "$APP"
    ;;
  --debug|debug)
    lldb -- "$APP/Contents/MacOS/WenyiMac"
    ;;
  --logs|logs)
    /usr/bin/open -n "$APP"
    /usr/bin/log stream --info --style compact --predicate 'process == "WenyiMac"'
    ;;
  --telemetry|telemetry)
    /usr/bin/open -n "$APP"
    /usr/bin/log stream --info --style compact --predicate 'subsystem == "win.ebato.wenyi"'
    ;;
  --verify|verify)
    /usr/bin/open -n "$APP"
    sleep 2
    pgrep -x WenyiMac >/dev/null
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
