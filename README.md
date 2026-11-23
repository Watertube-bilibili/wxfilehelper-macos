# WX FileHelper for macOS · 微信文件传输助手 macOS 版

[中文](#中文) · [English](#english) · [发行 / Releases](https://github.com/Watertube-bilibili/wxfilehelper-macos/releases) · [免责声明 / Disclaimer](DISCLAIMER.md)

## 中文

使用 Qt Widgets 构建的原生 macOS 文件传输助手，普通窗口在左侧显示会话导航。与微信扫码授权后，可通过「文件传输助手」在手机和 Mac 之间发送文字、图片及文件。点击 `+` 打开第二个账号标签。切换标签时，账号各自的消息、草稿和文件列表都保留，传输继续。

把文件拖入窗口或使用「添加文件」，核对文件名和大小后点击发送。发送中途可以选择「完成此项后停止」。每批最多 100 个文件，每个文件最多 25 MiB。「另存为」会打开原生保存对话框。大屏模式放大文字、触控按钮和二维码，并隐藏昵称。自动更新检查指向此仓库的 GitHub Releases。

### 下载与构建

macOS 构建目标是 macOS 14 及以上，分别提供 Apple Silicon（`arm64`）和 Intel（`x86_64`）构建。可用安装文件以 Releases 页面为准。项目采用 AGPL-3.0-only，不隶属于腾讯。预览构建未经过 Apple 公证。真实双账号文件互传和教室触控设备仍待测试。

在对应架构的 Mac 上安装 Python 3.13，然后执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
bash scripts/build_macos.sh
```

脚本在 `dist/` 生成 `.app`、`.dmg` 和 SHA-256 校验文件，并检查打包应用能启动。也可执行 `.venv/bin/python run.py` 从源码运行。在共享电脑上用完后请退出应用，账号和消息仅在进程内存中保留。

Windows 下载见 [Windows 独立仓库](https://github.com/Watertube-bilibili/wxfilehelper-desktop/releases)。

## English

A native macOS file transfer utility built with Qt Widgets, with a sidebar in regular windows. Scan the QR code with WeChat to send text, photos and files between your phone and Mac using the File Transfer conversation. Click `+` for a second account. Tabs keep separate sessions, messages, drafts and file queues. Transfers continue when you switch.

Drop files into the window or click Add files. Review the queue and click Send. You can stop after the current item and keep the rest for later. Each batch supports up to 100 files, up to 25 MiB each. Save as opens a native file picker. Classroom mode enlarges text, controls and the QR code while hiding nicknames. The updater checks this repository's GitHub Releases.

### Downloads and builds

The build targets macOS 14 or later, with separate Apple Silicon (`arm64`) and Intel (`x86_64`) packages. Check Releases for available downloads. This independent AGPL-3.0-only project is unaffiliated with Tencent. Preview builds are not notarized by Apple. Live dual-account file transfers and physical classroom touchscreens remain unverified.

Install Python 3.13 on the Mac you want to build for. Create a virtual environment, install `requirements-dev.txt`, run `python -m pytest -q` and then `bash scripts/build_macos.sh`. The script checks bundled startup and produces an app, disk image and SHA-256 manifest in `dist/`. Run `.venv/bin/python run.py` to start the source version. Quit the app after using a shared computer. Sessions and messages stay in process memory.

Windows packages are available in the [separate Windows repository](https://github.com/Watertube-bilibili/wxfilehelper-desktop/releases).
