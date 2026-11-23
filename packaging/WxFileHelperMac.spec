# SPDX-License-Identifier: AGPL-3.0-only
import platform
from pathlib import Path

root = Path(SPECPATH).parent
name = "WXFileHelper"
data = [
    (str(root / "LICENSE"), "."),
    (str(root / "DISCLAIMER.md"), "."),
    (str(root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(root / "licenses"), "licenses"),
]
a = Analysis(
    [str(root / "run.py")], pathex=[str(root)], datas=data,
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "tkinter", "pytest", "PIL",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=name, console=False,
    target_arch=platform.machine(), argv_emulation=False, strip=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
app = BUNDLE(
    coll, name="WXFileHelper.app", icon=str(root / "build" / "app.icns"),
    bundle_identifier="io.github.watertube-bilibili.wxfilehelper",
    info_plist={"CFBundleDisplayName": "WX FileHelper", "LSMinimumSystemVersion": "14.0",
                "NSHighResolutionCapable": True},
)
