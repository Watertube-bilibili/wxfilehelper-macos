"""Shared Qt widgets, text and background workers. SPDX-License-Identifier: AGPL-3.0-only."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QThread, Signal, QObject, QRunnable
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QPlainTextEdit

from .protocol import ProtocolError, SessionExpired, Cancelled

TEXT = {
    "title": ("文件传输助手", "File Transfer"),
    "chat": ("文件传输", "File transfer"), "files": ("本次会话文件", "Session files"),
    "all_messages": ("全部消息", "All messages"), "files_only": ("仅看文件", "Files only"),
    "folder": ("下载文件夹", "Downloads folder"), "about": ("关于与开源代码", "About & source code"),
    "menu": ("更多选项", "More options"),
    "account": ("账号 {n}", "Account {n}"), "add_account": ("添加第二个账号", "Add a second account"),
    "close_account": ("关闭此账号标签", "Close this account tab"),
    "duplicate_account": ("这个微信账号正在另一个标签中使用。请用不同的账号扫码。", "This account is in the other tab. Scan with a different account."),
    "discard_title": ("结束此账号会话？", "End this account session?"),
    "discard_body": ("此标签的草稿和待发送文件列表会清空。", "The draft and pending file list in this tab will be cleared."),
    "unread": ("{n} 条新消息", "{n} new messages"),
    "archived": ("已断开连接。重新扫码可恢复发送。", "Disconnected. Scan again to resume sending."),
    "signed_out": ("已退出，请扫码登录", "Signed out · scan to sign in"),
    "sign_in": ("获取登录二维码", "Get sign-in code"),
    "relogin": ("重新扫码", "Scan again"),
    "scan": ("用手机微信扫码", "Scan with WeChat"),
    "scan_hint": ("打开微信「扫一扫」，然后在手机上确认登录。", "Open Scan in WeChat, then confirm on your phone."),
    "session_hint": ("登录信息仅在本次运行中保留，退出后需重新扫码。", "Sign-in lasts for this run. Scan again after restarting."),
    "refresh": ("刷新二维码", "Refresh QR code"), "signout": ("退出登录", "Sign out"),
    "waiting": ("等待扫码", "Waiting for scan"), "confirm": ("已扫码，请在手机上确认", "Scanned · confirm on your phone"),
    "starting": ("正在连接微信…", "Connecting to WeChat…"), "online": ("已连接", "Connected"),
    "reconnecting": ("连接中断，正在重试…", "Connection interrupted · retrying…"),
    "expired": ("二维码或会话已失效，请刷新", "Code or session expired · refresh to sign in"),
    "error": ("连接失败，请检查网络后重试", "Connection failed · check your network and retry"),
    "stopping": ("正在结束会话…", "Ending session…"),
    "placeholder": ("输入文字，或将文件拖到这里…", "Write a message, or drop files here…"),
    "attach": ("添加文件", "Add files"), "image": ("添加图片", "Add images"),
    "send": ("发送", "Send"), "remove": ("移除所选", "Remove selected"),
    "clear": ("清空列表", "Clear list"),
    "empty": ("与手机互传文件", "Transfer files with your phone"),
    "empty_hint": ("把文件拖到这里，或点击「添加文件」。", "Drop files here, or click Add files."),
    "files_empty": ("本次会话还没有文件", "No files in this session yet"),
    "download": ("另存为…", "Save as…"), "saved": ("已保存", "Saved"),
    "open_folder": ("所在文件夹", "Show folder"), "copy": ("复制", "Copy"),
    "you": ("你", "You"), "phone": ("手机微信", "WeChat on phone"),
    "sending": ("正在发送…", "Sending…"), "downloading": ("正在保存…", "Saving…"),
    "sending_item": ("正在发送 {index}/{total} · {name}", "Sending {index}/{total} · {name}"),
    "stop": ("完成此项后停止", "Stop after current"), "stopping_batch": ("将于当前项完成后停止", "Stopping after current"),
    "queue_stopped": ("已停止发送，剩余项目仍在列表中。", "Sending stopped. Remaining items are still in the list."),
    "queue_limit": ("每批最多添加 {n} 个文件。", "Add up to {n} files per batch."),
    "invalid_file": ("跳过 {n} 个无法读取、空白或超过 25 MiB 的文件。", "Skipped {n} unreadable, empty, or over-25 MiB files."),
    "pending": ("待发送 {n} 项 · {size}", "{n} ready · {size}"),
    "retry_send": ("发送剩余项", "Send remaining"),
    "send_failed": ("发送中断。若手机上已收到该项，请先移除对应草稿或附件。", "Sending stopped. If the item reached your phone, remove it from the draft or list before sending again."),
    "download_done": ("已保存 · {name}", "Saved · {name}"),
    "privacy": ("消息仅保留在本次会话；下载的文件由你选择保存位置。", "Messages stay in this session. You choose where downloads are saved."),
    "quit_title": ("传输仍在进行", "Transfer in progress"),
    "quit_body": ("退出会中断当前操作。确定退出吗？", "Quitting interrupts the current operation. Quit anyway?"),
    "updates": ("检查更新", "Check for updates"), "checking": ("正在检查更新…", "Checking for updates…"),
    "current": ("当前已是最新版本", "You are up to date"),
    "new_version": ("发现新版本 {version} · 查看更新", "Update {version} available · View release"),
    "update_failed": ("重试更新检查", "Retry update check"),
}

FILE_KINDS = frozenset(("file", "image", "video", "voice"))


def tr(language, key):
    return TEXT[key][0 if language == "zh" else 1]


def app_icon(size=64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0067c0"))
    painter.drawRoundedRect(0, 0, size, size, size * .24, size * .24)
    painter.setPen(QPen(QColor("white"), max(2, size * .055), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    for x1, y1, x2, y2 in ((.25, .37, .75, .37), (.62, .24, .75, .37), (.62, .50, .75, .37),
                           (.75, .65, .25, .65), (.38, .52, .25, .65), (.38, .78, .25, .65)):
        painter.drawLine(int(size*x1), int(size*y1), int(size*x2), int(size*y2))
    painter.end()
    return QIcon(pixmap)


def control_icon(name: str) -> QIcon:
    """Original 16 px line icons for the navigation and tab controls."""
    lines = {
        "add": (((8, 3), (8, 13)), ((3, 8), (13, 8))),
        "close": (((4, 4), (12, 12)), ((4, 12), (12, 4))),
        "chat": (((2.5, 3), (13.5, 3), (13.5, 11), (7, 11), (4, 14), (4, 11), (2.5, 11), (2.5, 3)),
                 ((5.5, 7), (10.5, 7))),
        "file": (((4, 2), (9, 2), (12.5, 5.5), (12.5, 14), (4, 14), (4, 2)),
                 ((9, 2), (9, 5.5), (12.5, 5.5)), ((6, 9), (10.5, 9)), ((6, 11.5), (10.5, 11.5))),
    }
    pixmap = QPixmap(32, 32)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#42536a"), 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if name == "menu":
        for x in (3.5, 8, 12.5):
            painter.drawPoint(QPointF(x, 8))
    else:
        for line in lines[name]:
            for first, second in zip(line, line[1:]):
                painter.drawLine(QPointF(*first), QPointF(*second))
    painter.end()
    return QIcon(pixmap)


def label(text="", name="", wrap=False):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    if name:
        result.setObjectName(name)
    return result


def size_text(size):
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MiB"
    if size >= 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size} B"


class LoginWorker(QThread):
    qr = Signal(bytes)
    state = Signal(str)
    ready = Signal(str)
    message = Signal(object)
    failure = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        try:
            self.qr.emit(self.client.create_qr())
            self.state.emit("waiting")
            deadline = time.monotonic() + 180
            scanned = False
            while not self.client.cancel.is_set():
                state = self.client.poll_login(scanned)
                if state == "online":
                    self.ready.emit(self.client.nickname)
                    self.state.emit("online")
                    break
                if state == "confirm":
                    scanned = True
                self.state.emit("confirm" if scanned and state == "waiting" else state)
                if state == "expired" or time.monotonic() > deadline:
                    self.state.emit("expired")
                    return
                self.client.cancel.wait(.5)
            failures = 0
            while not self.client.cancel.is_set() and self.client.logged_in:
                try:
                    for message in self.client.receive():
                        self.message.emit(message)
                    if failures:
                        self.state.emit("online")
                    failures = 0
                    self.client.cancel.wait(.3)
                except SessionExpired:
                    self.state.emit("expired")
                    return
                except Cancelled:
                    return
                except ProtocolError:
                    failures += 1
                    self.state.emit("reconnecting")
                    self.client.cancel.wait(min(30, 2 ** min(failures, 5)))
        except Cancelled:
            pass
        except ProtocolError as exc:
            self.failure.emit(str(exc))
            self.state.emit("error")
        except Exception:
            self.failure.emit("Unexpected response; please retry / 服务响应异常，请重试")
            self.state.emit("error")
        finally:
            self.client.logged_in = False


class TaskSignals(QObject):
    success = Signal(object)
    failure = Signal(str)
    progress = Signal(int)
    item = Signal(int, int, str)
    expired = Signal()
    finished = Signal()


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.success.emit(self.function(self.signals.progress.emit))
        except SessionExpired as exc:
            self.signals.failure.emit(str(exc))
            self.signals.expired.emit()
        except ProtocolError as exc:
            self.signals.failure.emit(str(exc))
        except OSError:
            self.signals.failure.emit("Cannot read or write this file / 无法读取或保存文件，请检查权限和磁盘空间")
        except Exception:
            self.signals.failure.emit("Unexpected response; operation not retried / 响应异常，未自动重试，请检查手机端结果")
        finally:
            self.signals.finished.emit()


class Composer(QPlainTextEdit):
    files_dropped = Signal(list)
    send_requested = Signal()

    def canInsertFromMimeData(self, source):
        return any(url.isLocalFile() for url in source.urls()) or source.hasText()

    def insertFromMimeData(self, source):
        paths = [Path(url.toLocalFile()) for url in source.urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        elif source.hasText():
            super().insertFromMimeData(source)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


