# WX FileHelper for macOS · 微信文件传输助手

[中文](#中文) · [English](#english) · [下载 / Downloads](https://github.com/Watertube-bilibili/wxfilehelper-macos/releases) · [免责声明 / Disclaimer](DISCLAIMER.md)

## 中文

在手机微信和 Mac 之间收发文字、文件和课件。这个独立客户端使用原生 AppKit 窗口和 Go 传输核心，支持两个分别扫码授权的账号。每个标签都有自己的会话、草稿和待发文件。

**安装**　需要 macOS 14 或更新版本。Apple 芯片下载文件名以 `-macOS-arm64.dmg` 结尾的磁盘映像，Intel 芯片选择 `-macOS-x86_64.dmg`。打开映像，将 `WXFileHelper.app` 拖入「应用程序」。发布页附有 SHA-256 校验清单。应用采用临时签名，尚未取得 Apple 公证。[下载](https://github.com/Watertube-bilibili/wxfilehelper-macos/releases)

**收发文件**

1. 打开应用，用手机微信扫码并确认登录。要添加第二个账号，点标签旁的 `+`，用另一个账号扫码。
2. 从 Mac 发送时，点「添加文件」或将文件拖入窗口，核对当前标签和待发列表后点「发送」。每个待发文件支持 1 字节至 25 MiB。
3. 从手机发送时，在微信里把文件发到「文件传输助手」。在 Mac 的对应标签中选中附件，点「另存为」，或双击附件后选择保存位置。若微信未提供下载信息，可在手机上重新发送原文件。

窄窗口会收起侧栏，仍可在会话中筛选文件。应用运行期间会自动检查此 macOS 仓库的新版，也可在菜单中手动检查，然后前往发布页下载。会话票据和消息仅保存在内存中，已保存到磁盘的文件由你管理。

**从源码构建**　安装 Go 1.26 和 Xcode 命令行工具，在目标架构的 Mac 上运行 `bash native/packaging/macos/build.sh`。脚本会运行 Go 测试，启动构建出的应用及 DMG 内的副本，验证签名和映像，最后将 DMG 和校验清单写入 `dist/`。

项目按 AGPL-3.0-only 开源，与腾讯和微信无隶属关系。[许可证](LICENSE) · [免责声明](DISCLAIMER.md) · [Windows 版](https://github.com/Watertube-bilibili/wxfilehelper-desktop)

## English

Transfer text, files and presentations between WeChat on your phone and your Mac. This independent client uses native AppKit windows and a Go transfer core. Two accounts can be authorized separately, each with its own tab, history, draft and upload queue.

**Install.** Requires macOS 14 or later. For Apple silicon, choose the disk image ending in `-macOS-arm64.dmg`. For Intel, choose `-macOS-x86_64.dmg`. Open the image and drag `WXFileHelper.app` into Applications. The release includes SHA-256 checksums. The app is ad hoc signed and has not been notarized by Apple. [Downloads](https://github.com/Watertube-bilibili/wxfilehelper-macos/releases)

**Send and receive files**

1. Open the app, scan the QR code with WeChat on your phone, and confirm sign-in. To add a second account, click `+` beside the tab and scan with the other account.
2. To send from your Mac, choose Add Files or drag files into the window. Check the active tab and queue, then click Send. Each outgoing file may be from 1 byte to 25 MiB.
3. To receive from your phone, send the original file to WeChat’s File Transfer conversation. In the matching Mac tab, select the attachment and choose Save As, or double-click it and choose a destination. If WeChat supplies no download details, send the original file again from the phone.

The sidebar folds away in a small window. The file filter remains available in the conversation. While running, the app checks this macOS repository for updates. You can also check manually from the menu, then open the release page to download an update. Session credentials and messages stay in memory. Files you save to disk stay at the destination you choose.

**Build from source.** Install Go 1.26 and the Xcode command line tools. On a Mac of the target architecture, run `bash native/packaging/macos/build.sh`. The script runs the Go tests, starts both the built app and the copy mounted from the DMG, verifies the signature and disk image, and writes the DMG and checksums to `dist/`.

Licensed under AGPL-3.0-only. This is an independent project unaffiliated with Tencent or WeChat. [License](LICENSE) · [Disclaimer](DISCLAIMER.md) · [Windows edition](https://github.com/Watertube-bilibili/wxfilehelper-desktop)
