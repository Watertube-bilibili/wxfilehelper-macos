#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
if [[ "$(uname -s)" != Darwin ]]; then
    echo "Build the .app and .dmg on macOS 14 or later."
    exit 1
fi
python="${WX_BUILD_PYTHON:-python3}"
if [[ -x .venv/bin/python && -z "${WX_BUILD_PYTHON:-}" ]]; then
    python=.venv/bin/python
fi
version="$("$python" -c 'from wxfilehelper import __version__; print(__version__)')"
architecture="$("$python" -c 'import platform; print(platform.machine())')"
"$python" scripts/collect_licenses.py
"$python" scripts/make_icon.py
"$python" -c 'from PIL import Image; Image.open("build/app.png").save("build/app.icns")'
"$python" -m PyInstaller --noconfirm packaging/WxFileHelperMac.spec
codesign --verify --deep --strict dist/WXFileHelper.app
spot="$(mktemp -d "$root/build/dmg-root.XXXXXX")"
report="$spot/launch-report.txt"
QT_QPA_PLATFORM=offscreen WXFILEHELPER_SMOKE_REPORT="$report" dist/WXFileHelper.app/Contents/MacOS/WXFileHelper --smoke-test
grep -qx OK "$report"
mkdir "$spot/volume"
ditto dist/WXFileHelper.app "$spot/volume/WXFileHelper.app"
ln -s /Applications "$spot/volume/Applications"
image="dist/WXFileHelper-$version-macOS-$architecture.dmg"
hdiutil create -ov -format UDZO -fs HFS+ -volname "WX FileHelper" -srcfolder "$spot/volume" "$image"
hdiutil verify "$image"
"$python" scripts/checksums.py "$image"
