#!/usr/bin/env bash
# Build the macOS .app bundle with PyInstaller.
#
# Output:
#   dist/DesktopSmartOrganizer.app   – unsigned .app bundle
#   dist/DesktopSmartOrganizer-macos.zip – zipped bundle for distribution
#
# NOTE: the produced .app is NOT code-signed or notarized. Users must allow
# it via System Settings > Privacy & Security on first launch. Signing and
# notarization require an Apple Developer ID and are out of scope here.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name DesktopSmartOrganizer \
    --osx-bundle-identifier com.xiwei.desktopsmartorganizer \
    main.py

if [[ -d "dist/DesktopSmartOrganizer.app" ]]; then
    ditto -c -k --keepParent "dist/DesktopSmartOrganizer.app" "dist/DesktopSmartOrganizer-macos.zip"
    echo "Built dist/DesktopSmartOrganizer.app and dist/DesktopSmartOrganizer-macos.zip"
else
    echo "ERROR: dist/DesktopSmartOrganizer.app was not produced" >&2
    exit 1
fi
