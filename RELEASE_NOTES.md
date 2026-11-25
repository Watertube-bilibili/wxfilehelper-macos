# macOS 附件收发修复 / macOS attachment update

## 中文

- 修复手机发来的 PowerPoint 等附件在 Mac 上无法识别或保存的问题。文件名中的中文、空格和特殊字符可正确传给下载服务。选中可下载的附件后，可直接「另存为」。缺少下载信息的文件会说明原因，方便从手机重发。
- 同一文件发送成功后，服务回传的重复记录会与本次发送合并。手机另外发来的同名文件仍保留为独立条目。
- 应用在运行时定期检查此 macOS 仓库的更新。联网失败会稍后重试，先前找到的新版仍可从菜单打开发布页。
- 会话统一使用随窗口大小调整的布局，小窗口自动收起侧栏。此次更新移除了独立的教室大屏模式。

需要 macOS 14 或更新版本。Apple 芯片请选择 `arm64.dmg`，Intel 芯片请选择 `x86_64.dmg`。下载后可对照 `SHA256SUMS.txt` 校验。应用采用临时签名，尚未取得 Apple 公证。

附件回归测试使用合成的 PowerPoint 文件，经同步、识别和保存后逐字节比对。真实微信账号的端到端文件传输仍待验证。

## English

- Fixed detection and saving of PowerPoint presentations and other attachments sent from a phone. Download requests preserve Chinese characters, spaces and special characters in filenames. Select a downloadable attachment and choose Save As. If WeChat omits its download details, the app explains why the file needs to be resent.
- A server echo of a file you sent merges with that send. A separate file with the same name sent from your phone keeps its own entry.
- The running app checks the macOS repository periodically for new releases. A failed scheduled check is retried later, and a previously discovered update remains available from the menu.
- The conversation layout follows the window size, with the sidebar folding away in a small window. The separate classroom mode has been removed.

Requires macOS 14 or later. Choose `arm64.dmg` for Apple silicon or `x86_64.dmg` for Intel. Verify the download against `SHA256SUMS.txt`. The app is ad hoc signed and has not been notarized by Apple.

The attachment regression test syncs, identifies and saves a synthetic PowerPoint file, then compares the saved bytes with the original. End-to-end transfer with a live WeChat account is still unverified.

[免责声明 / Disclaimer](https://github.com/Watertube-bilibili/wxfilehelper-macos/blob/main/DISCLAIMER.md) · [Windows 版 / Windows edition](https://github.com/Watertube-bilibili/wxfilehelper-desktop)
