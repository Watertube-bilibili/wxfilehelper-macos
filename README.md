# WX FileHelper for macOS · 微信文件传输助手

[中文](#中文) · [English](#english) · [下载 / Downloads](https://github.com/Watertube-bilibili/wxfilehelper-macos/releases) · [免责声明 / Disclaimer](DISCLAIMER.md)

## 中文

独立的微信文件传输助手。1.2 采用原生 AppKit 界面和 Go 传输核心，双账号分别在手机微信扫码授权。可在会话中收发文字和文件，单项上限 25 MiB。选择、拖入文件或使用原生「另存为」对话框。教室模式支持大字号、全屏和隐藏昵称。更新检查只链接到 GitHub 发布页。

需要 **macOS 14 或更新版本**。Apple 芯片选择 `arm64.dmg`，Intel 芯片选择 `x86_64.dmg`。打开磁盘映像，将 `WXFileHelper.app` 拖入「应用程序」。安装包使用临时签名，尚未经过 Apple 公证。

### 构建

安装 Go 1.26 和 Xcode 命令行工具，在对应架构的 Mac 运行 `bash native/packaging/macos/build.sh`。脚本执行测试、构建 `.app`、验证签名和 DMG 并检查两个位置的启动。生成文件在 `dist/`。

会话票据和消息仅保存在内存中。每个账号须自行扫码。服务条款、网络与账号条件可能影响可用性。项目依 AGPL-3.0-only 发布，与腾讯和微信无隶属关系。[免责声明](DISCLAIMER.md) · [许可证](LICENSE) · [Windows 版](https://github.com/Watertube-bilibili/wxfilehelper-desktop)

## English

Independent WeChat File Transfer app. Version 1.2 pairs a native AppKit interface with a Go transfer core. Each account has its own QR authorization and file queue. Send text and files up to 25 MiB, drag files into the window, and save transfers with the native Save panel. Classroom mode uses larger controls and hides account names. Update checks link to the GitHub release.

Requires **macOS 14 or later**. Download the `arm64.dmg` for Apple silicon or `x86_64.dmg` for Intel. Open the disk image and move `WXFileHelper.app` into Applications. The app uses an ad hoc signature and is pending Apple notarization.

### Build

Install Go 1.26 and the Xcode command line tools. On the target Mac architecture run `bash native/packaging/macos/build.sh`. The script runs tests, validates the signed app bundle and DMG, and starts the app from both locations. Outputs are in `dist/`.

Session credentials and messages stay in memory. Each account requires its own authorization. Service rules, connectivity and account eligibility may affect availability. Licensed under AGPL-3.0-only and unaffiliated with Tencent and WeChat. [Disclaimer](DISCLAIMER.md) · [License](LICENSE) · [Windows edition](https://github.com/Watertube-bilibili/wxfilehelper-desktop)
