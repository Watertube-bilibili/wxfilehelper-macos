import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QSettings, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wxfilehelper.protocol import FileHelperClient, Message, ProtocolError
from wxfilehelper.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(auto_connect=False, settings=settings)
    window.show()
    yield window
    window.close()
    wait_for(app, lambda: not window.accounts)
    window.deleteLater()


def wait_for(app, condition, timeout=3):
    expires = time.monotonic() + timeout
    while not condition() and time.monotonic() < expires:
        app.processEvents()
        QTest.qWait(5)
    app.processEvents()
    assert condition()


def test_initial_tab_requires_a_scan(window):
    tab = window.current_account
    assert tab.pages.currentIndex() == 0
    assert not tab.send_button.isEnabled()
    assert tab.scan_title.textFormat() == Qt.TextFormat.PlainText
    window._toggle_language()
    assert tab.send_button.text() == "Send"


def test_drop_stages_valid_files_once_without_sending(window, tmp_path):
    tab = window.current_account
    file = tmp_path / "test.txt"
    file.write_text("test")
    empty = tmp_path / "empty.txt"
    empty.touch()
    tab._set_state("online")
    tab._stage_files([file, empty, file, tmp_path])
    assert [item.path for item in tab.pending] == [file]
    assert tab.pending_list.count() == 1
    assert "2" in tab.feedback.text()
    assert not tab.messages and tab.active_task is None
    tab.pending_list.setCurrentRow(0)
    QTest.mouseClick(tab.remove_button, Qt.MouseButton.LeftButton)
    assert not tab.pending


def test_classroom_retains_tab_controls_and_hides_both_names(window):
    first = window.current_account
    second = window.add_account()
    first.nickname, second.nickname = "Private first name", "Private second name"
    first._set_state("online")
    second._set_state("online")
    window._toggle_classroom()
    assert window.classroom and window.isFullScreen()
    assert window.tabs.count() == 2
    assert not window.menu_button.isVisible()
    assert "Private" not in second.status.text()
    assert all("Private" not in window.tabs.tabText(i) for i in range(2))
    assert "Esc" in window.classroom_button.text()
    window._leave_classroom()
    assert "Private" in window.tabs.tabToolTip(1)

def test_sidebar_collapses_without_losing_current_account_filter(window, app):
    window.resize(1024, 680)
    first = window.current_account
    second = window.add_account()
    for n, pane in enumerate((first, second)):
        pane.account_id = str(n + 1)
        pane.pages.setCurrentIndex(1)
        pane._set_state("online")
    assert window.rail.isVisible() and not second.files_button.isVisible()
    QTest.mouseClick(window.rail_files, Qt.MouseButton.LeftButton)
    assert second.files_only and not first.files_only
    window.tabs.setCurrentIndex(0)
    assert window.rail_chat.isChecked()
    window.tabs.setCurrentIndex(1)
    window.resize(590, 430)
    app.processEvents()
    assert not window.rail.isVisible()
    assert second.files_button.isVisible() and second.files_button.isChecked()


@pytest.mark.parametrize("size", [(590, 430), (1024, 560), (1280, 720), (1920, 1080), (3840, 2160)])
def test_send_stays_on_screen_with_a_file_queue(window, app, tmp_path, size):
    window.resize(*size)
    window._toggle_language()
    tab = window.add_account()
    tab.pages.setCurrentIndex(1)
    tab._set_state("online")
    paths = []
    for n in range(8):
        file = tmp_path / f"file-{n}.txt"
        file.write_text("test")
        paths.append(file)
    tab._stage_files(paths)
    tab._add_message(Message("1", "file", "very-long-name-" * 16 + ".txt", size=4))
    wait_for(app, lambda: bool(tab.rows))
    send_rect = tab.send_button.geometry()
    assert tab.send_button.isVisible() and tab.send_button.isEnabled()
    assert send_rect.right() < tab.send_button.parentWidget().width()
    bottom = tab.send_button.mapTo(window, send_rect.bottomRight() - send_rect.topLeft())
    assert bottom.y() < window.height()
    assert tab.scroll.viewport().height() >= 40


def test_concurrent_tabs_keep_transfers_drafts_and_failures_isolated(window, app, tmp_path, monkeypatch):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image = QPixmap(32, 32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(buffer, "PNG")
    qr_bytes = bytes(buffer.data())

    a_started, allow_a = threading.Event(), threading.Event()
    clients = []

    class TestClient(FileHelperClient):
        def __init__(self):
            super().__init__()
            self.uin = str(len(clients) + 1)
            self.sent = []
            self.received_once = False
            clients.append(self)

        def create_qr(self):
            return qr_bytes

        def poll_login(self, scanned=False):
            self.logged_in = True
            self.nickname = f"Test tab {self.uin}"
            return "online"

        def receive(self):
            if self.received_once:
                return []
            self.received_once = True
            return [Message("same-sync-id", "text", f"received in tab {self.uin}")]

        def send_file(self, path, progress, *, image=False):
            if path.name == "fail.txt":
                raise ProtocolError("Test service refused this file")
            if self.uin == "1":
                a_started.set()
                if not allow_a.wait(2):
                    raise ProtocolError("Test upload stalled")
            self.sent.append(path.name)
            progress(100)
            return Message("same-upload-id", "file", path.name, True, local_path=str(path))

    monkeypatch.setattr("wxfilehelper.account.FileHelperClient", TestClient)
    first = window.current_account
    second = window.add_account()
    first.start_login()
    second.start_login()
    wait_for(app, lambda: "same-sync-id" in first.messages and "same-sync-id" in second.messages)
    assert first.client is not second.client
    assert first.messages["same-sync-id"].text != second.messages["same-sync-id"].text
    assert first.unread == 1
    window.tabs.setCurrentIndex(0)
    assert window.current_account is first and first.unread == 0
    for name in ("first.txt", "fail.txt", "later.txt", "second.txt"):
        (tmp_path / name).write_text(name)
    first._stage_files([tmp_path / "first.txt", tmp_path / "fail.txt", tmp_path / "later.txt"])
    first._send()
    try:
        wait_for(app, a_started.is_set)
        window.tabs.setCurrentIndex(1)
        second._stage_files([tmp_path / "second.txt"])
        second._send()
        wait_for(app, lambda: second.active_task is None)
        assert first.active_task is not None
        assert not second.pending
        assert second.messages["same-upload-id"].text == "second.txt"
    finally:
        allow_a.set()
    wait_for(app, lambda: first.active_task is None)
    assert clients[0].sent == ["first.txt"] and clients[1].sent == ["second.txt"]
    assert [item.path.name for item in first.pending] == ["fail.txt", "later.txt"]
    assert first.transfer_failed
    assert first.messages["same-upload-id"].text == "first.txt"
    second.composer.setPlainText("only in the second tab")
    first._clear_attachments()
    first.sign_out()
    wait_for(app, lambda: first.state == "signed_out")
    assert second.state == "online"
    assert second.composer.toPlainText() == "only in the second tab"


def test_local_ack_merges_sync_echo_in_same_tab(window):
    tab = window.current_account
    tab._add_message(Message("42", "file", "test.txt", False))
    tab._add_message(Message("42", "file", "test.txt", True, local_path="test.txt"))
    assert len(tab.messages) == 1
    assert tab.messages["42"].outgoing and tab.messages["42"].local_path == "test.txt"
