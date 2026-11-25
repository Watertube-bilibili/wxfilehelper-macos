#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo "Build the AppKit application on macOS." >&2; exit 1; }
native="$(cd "$(dirname "$0")/../.." && pwd)"
repo="$(cd "$native/.." && pwd)"
out="$repo/dist"
mkdir -p "$out" "$native/build"
work="$(mktemp -d "$native/build/macos.XXXXXXXX")"
mounted=false
cleanup() {
    if [[ "$mounted" == true ]]; then hdiutil detach "$work/volume" -quiet || true; fi
    rm -rf "$work"
}
trap cleanup EXIT
app="$work/stage/WXFileHelper.app"
contents="$app/Contents"
exe="$contents/MacOS/WXFileHelper"
mkdir -p "$contents/MacOS" "$contents/Resources/licenses" "$work/volume" "$work/AppIcon.iconset"
cd "$native"
export CGO_ENABLED=1
export MACOSX_DEPLOYMENT_TARGET=14.0
arch="$(uname -m)"
case "$arch" in
    arm64) export GOARCH=arm64 ;;
    x86_64) export GOARCH=amd64 ;;
    *) echo "Unsupported build architecture: $arch" >&2; exit 1 ;;
esac
go test ./...
go build -trimpath -buildvcs=false -ldflags="-s -w -X github.com/Watertube-bilibili/wxfilehelper-desktop/native/internal/desktop.ReleaseRepo=Watertube-bilibili/wxfilehelper-macos" -o "$exe" ./cmd/wxfilehelper-mac
version="$("$exe" --version)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$(lipo -archs "$exe")" == "$arch" ]]
install -m 644 "$native/packaging/macos/Info.plist" "$contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" "$contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $version" "$contents/Info.plist"
plutil -lint "$contents/Info.plist"
for size in 16 32 128 256 512; do
    for scale in 1 2; do
        pixels=$((size * scale))
        suffix=""
        if ((scale == 2)); then suffix="@2x"; fi
        sips -z "$pixels" "$pixels" "$native/packaging/app.png" --out "$work/AppIcon.iconset/icon_${size}x${size}${suffix}.png" >/dev/null
    done
done
iconutil -c icns "$work/AppIcon.iconset" -o "$contents/Resources/AppIcon.icns"
for doc in LICENSE DISCLAIMER.md THIRD_PARTY_NOTICES.md; do
    install -m 644 "$repo/$doc" "$contents/Resources/$doc"
done
for notice in ItChat-MIT.txt WXFileHelper-MIT.txt; do
    install -m 644 "$repo/licenses/$notice" "$contents/Resources/licenses/$notice"
done
install -m 644 "$(go env GOROOT)/LICENSE" "$contents/Resources/licenses/Go-BSD.txt"
codesign --force --sign - --timestamp=none "$app"
codesign --verify --deep --strict "$app"
[[ "$("$exe" --smoke-test)" == OK ]]
ln -s /Applications "$work/stage/Applications"
name="WXFileHelper-$version-macOS-$arch.dmg"
image="$work/$name"
hdiutil create -format UDZO -fs HFS+ -volname "WX FileHelper" -srcfolder "$work/stage" "$image"
hdiutil verify "$image"
hdiutil attach -readonly -nobrowse -mountpoint "$work/volume" "$image"
mounted=true
mounted_app="$work/volume/WXFileHelper.app"
codesign --verify --deep --strict "$mounted_app"
[[ "$("$mounted_app/Contents/MacOS/WXFileHelper" --smoke-test)" == OK ]]
hdiutil detach "$work/volume" -quiet
mounted=false
ditto "$image" "$out/$name"
(cd "$out" && shasum -a 256 "$name" > SHA256SUMS.txt && shasum -a 256 -c SHA256SUMS.txt)
