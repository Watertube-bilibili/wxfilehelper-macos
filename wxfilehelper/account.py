"""One isolated File Transfer tab. SPDX-License-Identifier: AGPL-3.0-only."""
from __future__ import annotations

import stat
import threading
import time
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QScroller, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .protocol import FileHelperClient, MAX_FILE_SIZE, Message, safe_filename
from .widgets import FILE_KINDS, Composer, LoginWorker, Task, label, size_text, tr

MAX_BATCH_FILES = 100


@dataclass(frozen=True)
class Attachment:
    path: Path
    size: int
    image: bool


def open_downloads(settings):
    folder = settings.value("downloads", QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation))
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


class AccountPane(QWidget):
    changed = Signal()
    disposed = Signal()

    def __init__(self, number, settings, identity_available, parent=None):
        super().__init__(parent)
        self.number = number
        self.settings = settings
        self.identity_available = identity_available
        self.language = "zh"
        self.client = None
        self.worker = None
        self.account_id = ""
        self.nickname = ""
        self.state = "signed_out"
        self.stop_action = None
        self.active_task = None
        self.task_kind = None
        self.stop_batch = threading.Event()
        self.progress_item = None
        self.transfer_failed = False
        self.pending: list[Attachment] = []
        self.messages: dict[str, Message] = {}
        self.rows: dict[str, tuple[Message, QWidget]] = {}
        self.unread = 0
        self.selected = False
        self.classroom = False
        self.files_only = False
        self.qr_pixmap = None
        self.feedback_key = ""
        self.feedback_values = {}
        self.feedback_detail = ""
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.cleanup_timer = QTimer(self, singleShot=True, interval=50)
        self.cleanup_timer.timeout.connect(self._release_if_idle)
        self.render_timer = QTimer(self, singleShot=True, interval=35)
        self.render_timer.timeout.connect(self._render_messages)
        self.setAcceptDrops(True)
        self._build()
        self.translate("zh")

    def t(self, key):
        return tr(self.language, key)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)

        login = QScrollArea(widgetResizable=True, objectName="LoginScroll")
        login_body = QWidget(objectName="Login")
        self.login_layout = QVBoxLayout(login_body)
        self.login_layout.setContentsMargins(16, 12, 16, 12)
        self.login_layout.setSpacing(8)
        self.login_layout.addStretch(1)
        self.scan_title = label(name="Heading", wrap=True)
        self.scan_hint = label(name="Muted", wrap=True)
        self.qr_label = label(name="QR", wrap=True)
        self.qr_label.setFixedSize(208, 208)
        self.login_status = label(name="State", wrap=True)
        self.login_error = label(name="Error", wrap=True)
        for widget in (self.scan_title, self.scan_hint, self.qr_label, self.login_status, self.login_error):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.login_layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.login_error.setMaximumWidth(680)
        self.login_error.hide()
        self.refresh_button = QPushButton(objectName="Primary")
        self.refresh_button.clicked.connect(self.start_login)
        self.login_layout.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.session_hint = label(name="Muted", wrap=True)
        self.session_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.login_layout.addWidget(self.session_hint)
        self.login_layout.addStretch(1)
        login.setWidget(login_body)
        self.pages.addWidget(login)

        chat = QWidget()
        self.chat_layout = QVBoxLayout(chat)
        self.chat_layout.setContentsMargins(20, 8, 20, 10)
        self.chat_layout.setSpacing(8)
        nav = QHBoxLayout()
        self.status = label(name="State")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        nav.addWidget(self.status, 1)
        self.chat_button = QPushButton(objectName="Filter", checkable=True)
        self.files_button = QPushButton(objectName="Filter", checkable=True)
        self.chat_button.clicked.connect(lambda: self._filter(False))
        self.files_button.clicked.connect(lambda: self._filter(True))
        self.relogin_button = QPushButton(objectName="Primary")
        self.relogin_button.clicked.connect(self.start_login)
        for button in (self.chat_button, self.files_button, self.relogin_button):
            nav.addWidget(button)
        self.chat_layout.addLayout(nav)

        self.scroll = QScrollArea(widgetResizable=True, objectName="History")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        stream = QWidget(objectName="Stream")
        self.stream_layout = QVBoxLayout(stream)
        self.stream_layout.setContentsMargins(10, 10, 10, 10)
        self.stream_layout.setSpacing(9)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        self.empty_title = label(name="Heading", wrap=True)
        self.empty_hint = label(name="Muted", wrap=True)
        for widget in (self.empty_title, self.empty_hint):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(widget)
        empty_layout.addStretch()
        self.stream_layout.addWidget(self.empty, 1)
        self.stream_layout.addStretch()
        self.scroll.setWidget(stream)
        self.scroll.setMinimumHeight(40)
        QScroller.grabGesture(self.scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.chat_layout.addWidget(self.scroll, 1)

        frame = QFrame(objectName="Composer")
        controls = QVBoxLayout(frame)
        controls.setContentsMargins(12, 9, 12, 9)
        controls.setSpacing(6)
        self.queue = QWidget()
        queue_layout = QVBoxLayout(self.queue)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(3)
        queue_bar = QHBoxLayout()
        self.pending_label = label(name="Muted")
        self.remove_button = QPushButton(objectName="Quiet")
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = QPushButton(objectName="Quiet")
        self.clear_button.clicked.connect(self._clear_attachments)
        queue_bar.addWidget(self.pending_label, 1)
        queue_bar.addWidget(self.remove_button)
        queue_bar.addWidget(self.clear_button)
        queue_layout.addLayout(queue_bar)
        self.pending_list = QListWidget(objectName="Pending")
        self.pending_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.pending_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pending_list.itemSelectionChanged.connect(self._controls)
        QScroller.grabGesture(self.pending_list.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        queue_layout.addWidget(self.pending_list)
        controls.addWidget(self.queue)
        self.composer = Composer()
        self.composer.files_dropped.connect(self._stage_files)
        self.composer.send_requested.connect(self._send)
        self.composer.textChanged.connect(self._controls)
        controls.addWidget(self.composer)

        self.progress = QProgressBar(textVisible=False)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        controls.addWidget(self.progress)
        self.feedback = label(name="Muted", wrap=True)
        self.feedback.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.feedback.hide()
        controls.addWidget(self.feedback)
        toolbar = QHBoxLayout()
        self.attach_button = QPushButton(objectName="Quiet")
        self.attach_button.clicked.connect(self.choose_files)
        self.image_button = QPushButton(objectName="Quiet")
        self.image_button.clicked.connect(lambda: self.choose_files(image=True))
        self.stop_button = QPushButton(objectName="Quiet")
        self.stop_button.clicked.connect(self._stop_after_current)
        self.send_button = QPushButton(objectName="Primary")
        self.send_button.clicked.connect(self._send)
        self.send_button.setMinimumWidth(85)
        toolbar.addWidget(self.attach_button)
        toolbar.addWidget(self.image_button)
        toolbar.addStretch()
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.send_button)
        controls.addLayout(toolbar)
        self.chat_layout.addWidget(frame)
        self.pages.addWidget(chat)

    def translate(self, language, *, redraw=True):
        self.language = language
        for widget, key in (
            (self.scan_title, "scan"), (self.scan_hint, "scan_hint"), (self.chat_button, "chat"),
            (self.files_button, "files"), (self.relogin_button, "relogin"), (self.session_hint, "session_hint"),
            (self.attach_button, "attach"), (self.image_button, "image"), (self.remove_button, "remove"),
            (self.clear_button, "clear"), (self.stop_button, "stop"),
        ):
            widget.setText(self.t(key))
        self.composer.setPlaceholderText(self.t("placeholder"))
        self.composer.setAccessibleName(self.t("placeholder"))
        self._state_ui()
        self._pending_ui()
        self._feedback_ui()
        if redraw:
            self._invalidate_rows()

    def set_display(self, width, height, classroom):
        redraw = classroom != self.classroom
        self.classroom = classroom
        padding = max(12 if width < 750 else 22, (width - (1240 if classroom else 1120)) // 2)
        self.chat_layout.setContentsMargins(padding, 6, padding, 8)
        self.composer.setFixedHeight(88 if classroom and height >= 750 else 56 if height < 655 else 76)
        self.pending_list.setFixedHeight(56 if height < 655 else 94 if classroom else 76)
        qr_size = min(372 if classroom else 224, max(150, int(height * (.36 if classroom else .34))))
        if qr_size != self.qr_label.width():
            self.qr_label.setFixedSize(qr_size, qr_size)
            self._fit_qr()
        if redraw:
            self._state_ui()
            self._invalidate_rows()

    def select(self, selected):
        self.selected = selected
        if selected:
            self.unread = 0
            self._render_messages()

    def _set_state(self, state):
        self.state = state
        self._state_ui()
        self.changed.emit()

    def _state_ui(self):
        current = self.state
        status = self.t(current)
        if current in ("online", "reconnecting") and self.nickname and not self.classroom:
            status += " · " + self.nickname
        self.status.setText(self.t("archived") if current == "expired" and self.account_id else status)
        self.login_status.setText(self.t(current))
        self.relogin_button.setVisible(current == "expired" and bool(self.account_id))
        self.refresh_button.setText(self.t("sign_in" if current == "signed_out" else "refresh"))
        self.refresh_button.setEnabled(current in ("signed_out", "waiting", "confirm", "expired", "error") and not self.active_task)
        if current in ("expired", "error", "signed_out", "stopping"):
            self.qr_pixmap = None
            self.qr_label.clear()
        self.qr_label.setVisible(current in ("starting", "waiting", "confirm") and self.pages.currentIndex() == 0)
        self._controls()

    def _controls(self):
        can_edit = self.state == "online" and self.active_task is None
        self.composer.setReadOnly(not can_edit)
        self.attach_button.setEnabled(can_edit)
        self.image_button.setEnabled(can_edit)
        self.remove_button.setEnabled(can_edit and bool(self.pending_list.selectedItems()))
        self.clear_button.setEnabled(can_edit and bool(self.pending))
        self.send_button.setText(self.t("retry_send" if self.transfer_failed else "send"))
        self.send_button.setEnabled(can_edit and (bool(self.pending) or bool(self.composer.toPlainText().strip())))
        self.stop_button.setVisible(self.task_kind == "sending" and bool(
            self.progress_item and self.progress_item[0] < self.progress_item[1]))
        self.stop_button.setEnabled(not self.stop_batch.is_set())

    def start_login(self):
        if self.stop_action or self.active_task or self.state in ("online", "reconnecting"):
            return
        if self.worker:
            self._stop("refresh")
            return
        self._launch_login()

    def _launch_login(self):
        self.pages.setCurrentIndex(0)
        self.login_error.hide()
        self._set_state("starting")
        self.client = FileHelperClient()
        self.worker = LoginWorker(self.client, self)
        self.worker.qr.connect(self._show_qr)
        self.worker.state.connect(self._worker_state)
        self.worker.ready.connect(self._ready)
        self.worker.message.connect(self._add_message)
        self.worker.failure.connect(self._login_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _show_qr(self, data):
        if self.stop_action:
            return
        self.qr_pixmap = QPixmap()
        if not self.qr_pixmap.loadFromData(data):
            self._login_failed("二维码图片无效 / Invalid QR image")
            self._stop("error")
            return
        self._fit_qr()

    def _fit_qr(self):
        if self.qr_pixmap:
            size = self.qr_label.width() - 18
            self.qr_label.setPixmap(self.qr_pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio))

    def _worker_state(self, state):
        if not self.stop_action and self.client and not self.client.cancel.is_set():
            self._set_state(state)

    def _login_failed(self, error):
        if not self.stop_action:
            self.login_error.setText(error)
            self.login_error.show()

    def _ready(self, nickname):
        if self.stop_action:
            return
        account_id = self.client.uin
        if not self.identity_available(self, account_id):
            self._login_failed(self.t("duplicate_account"))
            self._stop("error")
            return
        if self.account_id and self.account_id != account_id:
            self._forget_session()
        self.account_id = account_id
        self.nickname = nickname
        self.pages.setCurrentIndex(1)
        self._set_state("online")
        self._render_messages()
        if self.selected:
            self.composer.setFocus()

    def _worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self._release_if_idle()

    def confirm_end(self):
        if not (self.active_task or self.pending or self.composer.toPlainText().strip()):
            return True
        body = self.t("quit_body" if self.active_task else "discard_body")
        return QMessageBox.question(self, self.t("discard_title"), body,
                                    defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def sign_out(self):
        if not self.stop_action and self.confirm_end():
            self._stop("sign_out")

    def dispose(self):
        self._stop("dispose")

    def _stop(self, action):
        self.stop_action = action
        if self.client:
            self.client.cancel.set()
        self._set_state("stopping")
        self._release_if_idle()

    def _release_if_idle(self):
        if self.worker or self.active_task:
            return
        if self.pool.activeThreadCount():
            self.cleanup_timer.start()
            return
        if self.client:
            self.client.close()
            self.client = None
        action, self.stop_action = self.stop_action, None
        if action == "refresh":
            self._launch_login()
        elif action == "error":
            self._set_state("error")
        elif action in ("sign_out", "dispose"):
            self._forget_session()
            self.pages.setCurrentIndex(0)
            self.login_error.hide()
            self._set_state("signed_out")
            if action == "dispose":
                self.disposed.emit()

    def _forget_session(self):
        self.account_id = self.nickname = ""
        self.unread = 0
        self.messages.clear()
        self.composer.clear()
        self.transfer_failed = False
        self._clear_attachments()
        self._set_feedback()
        self._invalidate_rows()

    def _filter(self, files_only):
        self.files_only = files_only
        self._render_messages()

    def _invalidate_rows(self):
        for _, row in self.rows.values():
            self.stream_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows.clear()
        self._render_messages()

    def _render_messages(self):
        if not self.selected:
            return
        self.chat_button.setChecked(not self.files_only)
        self.files_button.setChecked(self.files_only)
        messages = [m for m in self.messages.values() if not self.files_only or m.kind in FILE_KINDS][-300:]
        wanted = {message.id: message for message in messages}
        bar = self.scroll.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 36
        for message_id, (old, row) in list(self.rows.items()):
            if wanted.get(message_id) is not old:
                self.stream_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
                del self.rows[message_id]
        for index, message in enumerate(messages, 1):
            if message.id not in self.rows:
                row = self._message_row(message)
                self.rows[message.id] = (message, row)
                self.stream_layout.insertWidget(index, row)
        self.empty.setVisible(not messages)
        self.empty_title.setText(self.t("files_empty" if self.files_only else "empty"))
        self.empty_hint.setText(self.t("privacy" if self.files_only else "empty_hint"))
        if follow:
            QTimer.singleShot(0, bar, lambda: bar.setValue(bar.maximum()))

    def _message_row(self, message):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame(objectName="Outgoing" if message.outgoing else "Incoming")
        bubble.setMaximumWidth(745 if self.classroom else 530)
        box = QVBoxLayout(bubble)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(4)
        who = self.t("you" if message.outgoing else "phone")
        box.addWidget(label(who + " · " + time.strftime("%H:%M", time.localtime(message.timestamp)), "Muted"))
        content = label(message.text, wrap=True)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        box.addWidget(content)
        if message.kind in FILE_KINDS:
            line = QHBoxLayout()
            line.addWidget(label(size_text(message.size) if message.size else message.kind.upper(), "Muted"))
            line.addStretch()
            action = QPushButton(self.t("open_folder" if message.local_path else "download"), objectName="Quiet")
            action.clicked.connect(lambda: self._file_action(message))
            line.addWidget(action)
            box.addLayout(line)
        elif message.kind == "text":
            copy = QPushButton(self.t("copy"), objectName="Quiet")
            copy.clicked.connect(lambda: QApplication.clipboard().setText(message.text))
            box.addWidget(copy, alignment=Qt.AlignmentFlag.AlignLeft)
        if message.outgoing:
            layout.addStretch(1)
        layout.addWidget(bubble, 4)
        if not message.outgoing:
            layout.addStretch(1)
        return row

    def _add_message(self, message, *, replace_existing=False):
        if self.stop_action:
            return
        existing = self.messages.get(message.id)
        if existing is not None and not (message.outgoing or replace_existing):
            return
        self.messages[message.id] = message
        if len(self.messages) > 1000:
            del self.messages[next(iter(self.messages))]
        if self.selected:
            if not self.render_timer.isActive():
                self.render_timer.start()
        elif existing is None and not message.outgoing:
            self.unread += 1
            self.changed.emit()

    def choose_files(self, *, image=False):
        if self.state != "online" or self.active_task:
            return
        pattern = "Images (*.png *.jpg *.jpeg *.bmp)" if image else ""
        names, _ = QFileDialog.getOpenFileNames(self, self.t("image" if image else "attach"), "", pattern)
        self._stage_files([Path(name) for name in names], image)

    def dragEnterEvent(self, event):
        if self.state == "online" and not self.active_task and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def dropEvent(self, event):
        self._stage_files([Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()])
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _stage_files(self, paths, image=False):
        if self.state != "online" or self.active_task or not paths:
            return
        existing = {item.path for item in self.pending}
        invalid = 0
        full = False
        for path in paths:
            path = path.absolute()
            if path in existing:
                continue
            if len(self.pending) >= MAX_BATCH_FILES:
                full = True
                break
            try:
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_SIZE:
                    invalid += 1
                    continue
            except OSError:
                invalid += 1
                continue
            self.pending.append(Attachment(path, info.st_size, image))
            existing.add(path)
        self._pending_ui()
        if full:
            self._set_feedback("queue_limit", n=MAX_BATCH_FILES)
        elif invalid:
            self._set_feedback("invalid_file", n=invalid)
        elif not self.transfer_failed:
            self._set_feedback()

    def _remove_selected(self):
        index = self.pending_list.currentRow()
        if not self.active_task and 0 <= index < len(self.pending):
            del self.pending[index]
            self._pending_ui()

    def _clear_attachments(self):
        self.pending.clear()
        self._pending_ui()

    def _pending_ui(self):
        self.pending_list.clear()
        for attachment in self.pending:
            item = QListWidgetItem(f"{attachment.path.name}  ·  {size_text(attachment.size)}")
            item.setToolTip("<qt>" + escape(attachment.path.name) + "</qt>")
            self.pending_list.addItem(item)
        summary = self.t("pending").format(n=len(self.pending), size=size_text(sum(x.size for x in self.pending)))
        self.pending_label.setText(summary)
        self.pending_list.setAccessibleName(summary)
        self.queue.setVisible(bool(self.pending))
        self._controls()

    def _set_feedback(self, key="", detail="", **values):
        self.feedback_key, self.feedback_detail, self.feedback_values = key, detail, values
        self._feedback_ui()

    def _feedback_ui(self):
        message = self.t(self.feedback_key).format(**self.feedback_values) if self.feedback_key else ""
        self.feedback.setText("\n".join(filter(None, (message, self.feedback_detail))))
        self.feedback.setVisible(bool(self.feedback.text()))

    def _start_task(self, task, kind):
        self.active_task = task
        self.task_kind = kind
        self.progress_item = None
        self.stop_batch.clear()
        task.signals.success.connect(self._acknowledge)
        task.signals.failure.connect(self._task_failed)
        task.signals.progress.connect(self.progress.setValue)
        task.signals.item.connect(self._show_item)
        task.signals.expired.connect(self._expire_session)
        task.signals.finished.connect(self._task_finished)
        self.progress.setValue(0)
        self.progress.show()
        self._set_feedback(kind)
        self._controls()
        self.changed.emit()
        self.pool.start(task)

    def _send(self):
        client = self.client
        if not client or self.state != "online" or self.active_task:
            return
        draft = self.composer.toPlainText()
        uploads = list(self.pending)
        count = len(uploads) + bool(draft.strip())
        if not count:
            return
        self.transfer_failed = False
        task = Task(None)
        signals = task.signals
        stop_batch = self.stop_batch

        def send(progress):
            index = 0
            if draft.strip():
                index += 1
                signals.item.emit(index, count, "")
                signals.success.emit(("text", client.send_text(draft), None))
            for attachment in uploads:
                if stop_batch.is_set():
                    return
                index += 1
                signals.item.emit(index, count, attachment.path.name)
                message = client.send_file(attachment.path, progress, image=attachment.image)
                signals.success.emit(("file", message, attachment))

        task.function = send
        self._start_task(task, "sending")

    def _show_item(self, index, total, name):
        self.progress_item = (index, total, name)
        self.progress.setValue(0)
        if not self.stop_batch.is_set():
            self._set_feedback("sending_item", index=index, total=total, name=name or self.t("send"))
        self._controls()

    def _stop_after_current(self):
        self.stop_batch.set()
        self._set_feedback("stopping_batch")
        self._controls()

    def _acknowledge(self, result):
        if self.stop_action or result is None:
            return
        kind, message, attachment = result
        if kind == "saved":
            self._add_message(message, replace_existing=True)
            self._set_feedback("download_done", name=Path(message.local_path).name)
            return
        self._add_message(message)
        if kind == "text":
            self.composer.clear()
        else:
            self.pending.remove(attachment)
            self._pending_ui()

    def _task_failed(self, error):
        if not self.stop_action:
            self.transfer_failed = self.task_kind == "sending"
            self._set_feedback("send_failed" if self.transfer_failed else "", detail=error)

    def _expire_session(self):
        if not self.stop_action and self.client:
            self.client.cancel.set()
            self._set_state("expired")

    def _task_finished(self):
        self.active_task = None
        self.progress.hide()
        self.progress_item = None
        self.task_kind = None
        if self.stop_batch.is_set() and self.pending and not self.transfer_failed:
            self._set_feedback("queue_stopped")
        elif self.feedback_key in ("sending", "sending_item", "stopping_batch"):
            self._set_feedback()
        self._state_ui()
        self.changed.emit()
        if not self.worker:
            self._release_if_idle()

    def _file_action(self, message):
        if message.local_path and Path(message.local_path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(message.local_path).parent)))
            return
        client = self.client
        if not client or self.state != "online" or self.active_task:
            return
        base = self.settings.value("downloads", QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation))
        target, _ = QFileDialog.getSaveFileName(self, self.t("download"), str(Path(base) / safe_filename(message.text)))
        if not target or self.client is not client or self.state != "online" or self.active_task:
            return
        self.settings.setValue("downloads", str(Path(target).parent))

        def download(progress):
            path = client.download(message, Path(target), progress)
            return "saved", replace(message, local_path=str(path)), None

        self._start_task(Task(download), "downloading")
