# Third-party notices / 第三方声明

Application code: AGPL-3.0-only, see [LICENSE](LICENSE).
The application license does not relicense Tencent services, trademarks, or
third-party libraries. / 应用许可不改变腾讯服务、商标或第三方库的许可。

## Protocol references / 协议参考

- [zzzzls/WXFileHelper](https://github.com/zzzzls/WXFileHelper), MIT,
  Copyright (c) 2021 江浩. License: [licenses/WXFileHelper-MIT.txt](licenses/WXFileHelper-MIT.txt).
- [littlecodersh/ItChat](https://github.com/littlecodersh/ItChat), MIT,
  Copyright (c) 2017 LittleCoder. License: [licenses/ItChat-MIT.txt](licenses/ItChat-MIT.txt).

These were references for interoperable HTTPS request fields. The desktop UI,
threading, security checks, packaging, and tests are maintained in this repository.
上述项目用于参考 HTTPS 通信字段；桌面 UI、线程管理、安全检查、打包与测试在本仓库维护。

## Native 1.2 / 原生 1.2

The application links the Go standard library and uses the operating system's Win32 or AppKit frameworks. See the [Go BSD 3-Clause license](https://go.dev/LICENSE). Its copy is included with the Windows installer and macOS app. Inno Setup builds the Windows installer under its own upstream license.

1.2 使用 Go 标准库和系统提供的 Win32 或 AppKit 框架。Windows 安装版和 macOS 应用附带 Go BSD 3-Clause 许可证。Windows 安装器由 Inno Setup 构建。

## Historical 0.2 builds / 历史 0.2 构建

| Component | License | Upstream source |
| --- | --- | --- |
| CPython | PSF-2.0 | https://github.com/python/cpython |
| Qt / PySide6 Essentials / Shiboken6 | LGPL-3.0, with Qt third-party notices | https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/qtbase.git/ |
| Qt 5.15.2 (Win10 1507 preview) | LGPL-3.0, with Qt third-party notices | [Matching Qt 5.15.2 source](https://download.qt.io/archive/qt/5.15/5.15.2/single/) |
| PyQt5 (Win10 1507 preview) | GPL-3.0 | [PyQt5 5.15.11 source distribution](https://pypi.org/project/PyQt5/5.15.11/#files) |
| PyQt5-sip (Win10 1507 preview) | BSD-2-Clause | [PyQt5-sip 12.20.1 source distribution](https://pypi.org/project/PyQt5-sip/12.20.1/#files) |
| Microsoft Visual C++ runtime (Windows) / 微软 Visual C++ 运行库 | Microsoft redistributable code, supplied with the PySide6 Windows wheel / 随 PySide6 Windows 包提供，适用微软可再发行代码条款 | [Microsoft redistribution list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution) |
| Requests | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | MIT | https://github.com/urllib3/urllib3 |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | MIT | https://github.com/jawah/charset_normalizer |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| defusedxml | PSF license | https://github.com/tiran/defusedxml |
| PyInstaller bootloader | GPL-2.0-or-later with bootloader exception | https://github.com/pyinstaller/pyinstaller |

Qt is dynamically linked. No restriction is imposed on modifying or replacing
LGPL-covered components or debugging those modifications. The installed directory
build exposes shared libraries in `_internal`; the one-file build can be rebuilt
from this repository using replacement libraries. Build scripts and requirements
are provided. LGPL and GPL texts are included in `licenses/`. For the exact Qt
version, see `requirements.txt` and the matching upstream release source archives.

Qt 采用动态链接。允许依 LGPL 修改或替换相关组件，并调试这些修改；安装版的
`_internal` 目录包含共享库，单文件版可使用本仓库源码、构建脚本和替换后的库重新构建。
完整 LGPL/GPL 文本随包提供。具体版本见 `requirements.txt` 及对应的上游源码归档。

Build tools (not part of the application API): Pillow (HPND), pytest (MIT),
PyInstaller (GPL with exception), Inno Setup (its upstream license).
This project does not bundle Qt WebEngine or Chromium.

Dependency license files extracted from installed distributions are included under
`licenses/dependencies/` in release builds. / 发行包在该目录附带依赖包的许可文件。
