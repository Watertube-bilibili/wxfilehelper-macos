"""Main window and account tabs. SPDX-License-Identifier: AGPL-3.0-only."""
from __future__ import annotations

import sys
from html import escape

from PySide6.QtCore import Qt, QSettings, QSize, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QStackedWidget, QSystemTrayIcon, QTabBar, QToolButton, QVBoxLayout, QWidget,
)

from . import REPOSITORY, __version__
from .account import AccountPane, open_downloads
from .updates import check_for_update
from .widgets import Task, app_icon, control_icon, label, tr

STYLE = """
QWidget { color: #1d2939; font-size: 14px; }
QMainWindow, QWidget#Main, QWidget#Login, QWidget#Stream { background: #f9fbfd; }
QFrame#Rail { background: #eef2f7; border-right: 1px solid #dce4ed; }
QFrame#Chrome { background: #ffffff; border-bottom: 1px solid #dce4ed; }
QLabel#Heading { font-size: 22px; font-weight: 600; }
QLabel#Brand { font-size: 16px; font-weight: 600; }
QLabel#Muted { color: #53647a; font-size: 12px; }
QLabel#State { color: #005a9e; font-size: 13px; }
QLabel#Error { color: #922b24; font-size: 13px; }
QLabel#QR { background: #ffffff; border: 1px solid #dce4ed; border-radius: 13px; }
QTabBar::tab { background: #f1f4f8; color: #41536a; border: 1px solid #e2e8ef;
  border-top-left-radius: 7px; border-top-right-radius: 7px; margin-right: 4px;
  padding: 6px 10px; min-height: 19px; min-width: 80px; }
QTabBar::tab:hover { background: #e8eff7; }
QTabBar::tab:selected { background: #f9fbfd; color: #005a9e; font-weight: 600;
  border-top: 2px solid #0067c0; border-bottom-color: #f9fbfd; padding-top: 5px; }
QToolButton#TabClose { background: transparent; border: 1px solid transparent; border-radius: 4px; }
QToolButton#TabClose:hover { background: #dce8f3; }
QToolButton#TabClose:focus { border-color: #0067c0; }
QPushButton { background: #ffffff; border: 1px solid #cbd7e3; border-radius: 6px; padding: 6px 10px; }
QPushButton:hover { background: #edf4fb; border-color: #92aac4; }
QPushButton:pressed { background: #e4eef8; }
QPushButton:focus { border-color: #0067c0; background: #edf4fb; }
QPushButton:disabled { color: #68798b; background: #edf1f6; border-color: #dce4ed; }
QPushButton#Primary { background: #0067c0; color: #ffffff; border-color: #0067c0; font-weight: 600; }
QPushButton#Primary:hover, QPushButton#Primary:focus { background: #00589e; }
QPushButton#Primary:focus { border-color: #002f56; }
QPushButton#Primary:disabled { color: #53647a; background: #e4ebf3; border-color: #dce4ed; }
QPushButton#Quiet, QPushButton#Filter, QPushButton#RailLink, QPushButton#RailNav, QPushButton#Inline {
  background: transparent; border-color: transparent; }
QPushButton#Quiet:hover, QPushButton#Filter:hover, QPushButton#RailLink:hover, QPushButton#RailNav:hover,
QPushButton#Inline:hover { background: #e4edf7; }
QPushButton#Quiet:focus, QPushButton#Filter:focus, QPushButton#RailLink:focus, QPushButton#RailNav:focus,
QPushButton#Inline:focus { border-color: #0067c0; }
QPushButton#Quiet:disabled, QPushButton#RailLink:disabled { color: #647489; }
QPushButton#RailNav, QPushButton#RailLink { text-align: left; padding: 9px 10px; }
QPushButton#RailLink { color: #465970; }
QPushButton#Filter:checked, QPushButton#RailNav:checked { background: #dfedfa; color: #005a9e; font-weight: 600; }
QPushButton#Inline { padding: 1px 5px; font-size: 12px; color: #365772; }
QPlainTextEdit, QListWidget#Pending { background: #ffffff; border: 1px solid #cbd7e3; border-radius: 7px;
  padding: 6px; selection-background-color: #d9eaff; selection-color: #162b43; }
QPlainTextEdit { placeholder-text-color: #5c6c7e; }
QPlainTextEdit:focus, QListWidget#Pending:focus { border-color: #0067c0; }
QListWidget#Pending::item { padding: 3px 6px; }
QScrollArea { border: none; background: transparent; }
QFrame#Outgoing { background: #e0effe; border-radius: 10px; }
QFrame#Incoming { background: #edf2f7; border-radius: 10px; }
QFrame#Composer { background: transparent; border-top: 1px solid #dce4ed; }
QProgressBar { border: none; background: #dce7f1; border-radius: 2px; }
QProgressBar::chunk { background: #0067c0; border-radius: 2px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #a9b8c8; min-height: 26px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


class MainWindow(QMainWindow):
    def __init__(self, *, auto_connect=True, settings=None):
        super().__init__()
        self.settings = settings or QSettings("wxfilehelper-desktop", "FileTransfer")
        self.language = self.settings.value("language", "zh")
        self.auto_connect = auto_connect
        self.accounts: list[AccountPane] = []
        self.closing = False
        self.has_rail = False
        self.update_task = None
        self.update_result = None
        self.update_status = "updates"
        self.tray = None
        self.icon = app_icon()
        self.setWindowIcon(self.icon)
        self.setMinimumSize(590, 430)
        self._build()
        self._translate()
        screen = self.screen().availableGeometry()
        self.resize(min(1000, screen.width() - 30), min(725, screen.height() - 45))
        self.add_account()
        self._adapt_display()
        self._create_shortcuts()
        if auto_connect and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.icon, self)
            self.tray.setToolTip("WX FileHelper Desktop")
            tray_menu = QMenu(self)
            tray_menu.addAction("显示 / Show", self._show)
            tray_menu.addAction("退出 / Quit", self.close)
            self.tray.setContextMenu(tray_menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
        self.update_timer = QTimer(self, interval=6 * 60 * 60 * 1000)
        self.update_timer.timeout.connect(self._check_update)
        if auto_connect:
            QTimer.singleShot(5000, self, self._check_update)
            self.update_timer.start()

    @property
    def current_account(self):
        return self.stack.currentWidget()

    def t(self, key):
        return tr(self.language, key)

    def _build(self):
        root = QWidget(objectName="Main")
        self.setCentralWidget(root)
        frame = QHBoxLayout(root)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setSpacing(0)
        self.rail = self._build_rail()
        frame.addWidget(self.rail)
        content = QWidget()
        frame.addWidget(content, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        chrome = QFrame(objectName="Chrome")
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(22, 10, 20, 0)
        chrome_layout.setSpacing(8)
        title = QHBoxLayout()
        self.compact_icon = label()
        self.compact_icon.setPixmap(self.icon.pixmap(24, 24))
        title.addWidget(self.compact_icon)
        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        self.heading = label(name="Heading")
        self.account_status = label(name="State")
        self.account_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_block.addWidget(self.heading)
        title_block.addWidget(self.account_status)
        title.addLayout(title_block, 1)
        self.language_button = QPushButton(objectName="Quiet")
        self.language_button.clicked.connect(self._toggle_language)
        title.addWidget(self.language_button)
        self.signout_button = QPushButton(objectName="Quiet")
        self.signout_button.clicked.connect(self._signout)
        title.addWidget(self.signout_button)
        self.menu_button = QPushButton(icon=control_icon("menu"), objectName="Quiet")
        self.menu_button.setMinimumWidth(36)
        self.menu = QMenu(self)
        self.menu_button.setMenu(self.menu)
        self.download_action = self.menu.addAction("", lambda: open_downloads(self.settings))
        self.update_action = self.menu.addAction("", self._check_update)
        self.language_action = self.menu.addAction("", self._toggle_language)
        self.about_action = self.menu.addAction("", self._about)
        self.menu.addSeparator()
        self.signout_action = self.menu.addAction("", self._signout)
        title.addWidget(self.menu_button)
        chrome_layout.addLayout(title)
        tab_strip = QHBoxLayout()
        tab_strip.setContentsMargins(0, 0, 0, 0)
        tab_strip.setSpacing(5)
        self.tabs = QTabBar(documentMode=True, expanding=False)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.tabs.currentChanged.connect(self._tab_selected)
        self.add_button = QPushButton(icon=control_icon("add"), objectName="Quiet")
        self.add_button.setMinimumWidth(36)
        self.add_button.clicked.connect(self.add_account)
        tab_strip.addWidget(self.tabs)
        tab_strip.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        tab_strip.addStretch()
        chrome_layout.addLayout(tab_strip)
        layout.addWidget(chrome)

        self.update_banner = QPushButton(objectName="Filter")
        self.update_banner.clicked.connect(self._open_update)
        self.update_banner.hide()
        layout.addWidget(self.update_banner)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setStyleSheet(STYLE)

    def _build_rail(self):
        rail = QFrame(objectName="Rail")
        rail.setFixedWidth(196)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(16, 22, 16, 16)
        nav.setSpacing(5)
        logo = label()
        logo.setPixmap(self.icon.pixmap(44, 44))
        nav.addWidget(logo)
        nav.addSpacing(4)
        nav.addWidget(label("WX FileHelper", "Brand"))
        nav.addWidget(label("v" + __version__, "Muted"))
        nav.addSpacing(21)
        self.rail_chat = QPushButton(icon=control_icon("chat"), objectName="RailNav", checkable=True)
        self.rail_files = QPushButton(icon=control_icon("file"), objectName="RailNav", checkable=True)
        self.rail_chat.clicked.connect(lambda: self._set_filter(False))
        self.rail_files.clicked.connect(lambda: self._set_filter(True))
        nav.addWidget(self.rail_chat)
        nav.addWidget(self.rail_files)
        nav.addStretch()
        self.rail_downloads = QPushButton(objectName="RailLink")
        self.rail_update = QPushButton(objectName="RailLink")
        self.rail_about = QPushButton(objectName="RailLink")
        self.rail_downloads.clicked.connect(lambda: open_downloads(self.settings))
        self.rail_update.clicked.connect(self._check_update)
        self.rail_about.clicked.connect(self._about)
        for button in (self.rail_downloads, self.rail_update, self.rail_about):
            nav.addWidget(button)
        return rail

    def _set_filter(self, files_only):
        if self.current_account:
            self.current_account.filter_messages(files_only)

    def _create_shortcuts(self):
        QShortcut(QKeySequence.StandardKey.Open, self, activated=self._choose_files)
        QShortcut(QKeySequence.StandardKey.AddTab, self, activated=self.add_account)
        QShortcut(QKeySequence("Meta+Tab" if sys.platform == "darwin" else "Ctrl+Tab"), self, activated=self._next_tab)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.tabs.setCurrentIndex(1))

    def add_account(self):
        if self.closing or len(self.accounts) >= 2:
            return None
        number = next(n for n in (1, 2) if all(a.number != n for a in self.accounts))
        pane = AccountPane(number, self.settings, self._identity_available, self)
        pane.changed.connect(self._update_tabs)
        pane.disposed.connect(self._remove_disposed_tab)
        pane.translate(self.language)
        self.accounts.append(pane)
        self.stack.addWidget(pane)
        index = self.tabs.addTab(self.t("account").format(n=number))
        close = QToolButton(icon=control_icon("close"), objectName="TabClose")
        close.setIconSize(QSize(13, 13))
        close.setFixedSize(24, 24)
        close.clicked.connect(lambda _checked=False, account=pane: self._close_tab(self.accounts.index(account)))
        self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        self.tabs.setCurrentIndex(index)
        self._tab_selected(index)
        self._adapt_display()
        if self.auto_connect:
            QTimer.singleShot(0, pane, pane.start_login)
        return pane

    def _identity_available(self, pane, account_id):
        return not any(other is not pane and other.account_id == account_id
                       and other.state in ("online", "reconnecting") for other in self.accounts)

    def _next_tab(self):
        if self.accounts:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % len(self.accounts))

    def _tab_selected(self, index):
        if not 0 <= index < len(self.accounts):
            return
        active = self.accounts[index]
        self.stack.setCurrentWidget(active)
        for pane in self.accounts:
            pane.select(pane is active)
        self._update_tabs()

    def _close_tab(self, index):
        if self.closing or len(self.accounts) < 2 or not 0 <= index < len(self.accounts):
            return
        pane = self.accounts[index]
        if not pane.stop_action and pane.confirm_end():
            pane.dispose()

    def _remove_disposed_tab(self):
        pane = self.sender()
        index = self.accounts.index(pane)
        self.accounts.pop(index)
        self.stack.removeWidget(pane)
        self.tabs.removeTab(index)
        pane.deleteLater()
        self._tab_selected(self.tabs.currentIndex())
        self._update_tabs()
        self._quit_when_ready()

    def _update_tabs(self):
        closable = len(self.accounts) > 1 and not self.closing
        self.add_button.setVisible(len(self.accounts) < 2 and not self.closing)
        font = self.tabs.font()
        font.setBold(True)
        metrics = QFontMetrics(font)
        tab_space = self.width() - (self.rail.width() if self.has_rail else 0) - 48
        max_width = min(238, tab_space // max(len(self.accounts), 1))
        for index, pane in enumerate(self.accounts):
            account = self.t("account").format(n=pane.number)
            name = pane.nickname or account
            number = (" · " + str(pane.number)) if name != account else ""
            badge = ("  (" + ("99+" if pane.unread > 99 else str(pane.unread)) + ")") if pane.unread else ""
            suffix = number + badge
            room = max(55, max_width - (52 if closable else 24) - metrics.horizontalAdvance(suffix))
            caption = metrics.elidedText(name, Qt.TextElideMode.ElideRight, room)
            self.tabs.setTabText(index, caption.replace("&", "&&") + suffix)
            tooltip = escape(name + " · " + self.t(pane.state))
            if pane.task_kind:
                tooltip += " · " + escape(self.t(pane.task_kind))
            if pane.unread:
                tooltip += " · " + escape(self.t("unread").format(n=pane.unread))
            self.tabs.setTabToolTip(index, "<qt>" + tooltip + "</qt>")
            close = self.tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if close:
                close.setVisible(closable)
                close.setEnabled(not pane.stop_action)
                close.setToolTip(self.t("close_account"))
                close.setAccessibleName(self.t("close_account"))
        current = self.current_account
        can_signout = bool(current and not current.stop_action and (current.client or current.account_id))
        self.signout_action.setEnabled(can_signout)
        self.signout_button.setVisible(self.has_rail and can_signout)
        self.rail_chat.setChecked(bool(current and not current.files_only))
        self.rail_files.setChecked(bool(current and current.files_only))
        self.rail_chat.setEnabled(bool(current and current.account_id))
        self.rail_files.setEnabled(bool(current and current.account_id))
        self.account_status.setVisible(
            self.has_rail and bool(current and current.pages.currentIndex() == 1))
        if current:
            self.account_status.setText(current.status.text())

    def _translate(self):
        self.setWindowTitle(self.t("title") + " · WX FileHelper Desktop")
        self.heading.setText(self.t("title"))
        self.tabs.setAccessibleName(self.t("title"))
        self.add_button.setToolTip(self.t("add_account"))
        self.add_button.setAccessibleName(self.t("add_account"))
        self.menu_button.setToolTip(self.t("menu"))
        self.menu_button.setAccessibleName(self.t("menu"))
        self.rail_chat.setText(self.t("chat"))
        self.rail_files.setText(self.t("files"))
        self.rail_downloads.setText(self.t("folder"))
        self.rail_update.setText(self.t(self.update_status))
        self.rail_about.setText(self.t("about"))
        self.download_action.setText(self.t("folder"))
        self.update_action.setText(self.t(self.update_status))
        self.language_action.setText("English" if self.language == "zh" else "简体中文")
        self.language_button.setText(self.language_action.text())
        self.about_action.setText(self.t("about"))
        self.signout_action.setText(self.t("signout"))
        self.signout_button.setText(self.t("signout"))
        if self.update_result:
            self.update_banner.setText(self.t("new_version").format(version=self.update_result.version))
        for pane in self.accounts:
            pane.translate(self.language)
        self._update_tabs()

    def _toggle_language(self):
        self.language = "en" if self.language == "zh" else "zh"
        self.settings.setValue("language", self.language)
        self._translate()

    def _choose_files(self):
        if self.current_account:
            self.current_account.choose_files()

    def _signout(self):
        if self.current_account:
            self.current_account.sign_out()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "stack"):
            self._adapt_display()

    def _adapt_display(self):
        height, width = self.height(), self.width()
        self.has_rail = width >= 900 and height >= 510
        self.rail.setVisible(self.has_rail)
        self.compact_icon.setVisible(not self.has_rail)
        self.menu_button.setVisible(not self.has_rail)
        self.language_button.setVisible(self.has_rail)
        content_width = width - self.rail.width() if self.has_rail else width
        for pane in self.accounts:
            pane.set_display(content_width, height, inline_nav=not self.has_rail)
        self._update_tabs()

    def _check_update(self):
        if self.update_task or self.closing:
            return
        self.update_status = "checking"
        self.update_action.setText(self.t(self.update_status))
        self.update_action.setEnabled(False)
        self.rail_update.setText(self.t(self.update_status))
        self.rail_update.setEnabled(False)
        self.update_task = Task(lambda _progress: check_for_update())
        self.update_task.signals.success.connect(self._update_checked)
        self.update_task.signals.failure.connect(self._update_failed)
        self.update_task.signals.finished.connect(self._update_finished)
        QThreadPool.globalInstance().start(self.update_task)

    def _update_checked(self, result):
        self.update_result = result
        self.update_status = "updates" if result else "current"
        self.update_banner.setVisible(result is not None)
        if result:
            self.update_banner.setText(self.t("new_version").format(version=result.version))

    def _update_failed(self, _error):
        self.update_status = "update_failed"

    def _update_finished(self):
        self.update_task = None
        self.update_action.setText(self.t(self.update_status))
        self.update_action.setEnabled(True)
        self.rail_update.setText(self.t(self.update_status))
        self.rail_update.setEnabled(True)
        self._quit_when_ready()

    def _open_update(self):
        if self.update_result:
            QDesktopServices.openUrl(QUrl(self.update_result.url))

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle(self.t("about"))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(f"<b>WX FileHelper Desktop {__version__}</b>"
                    "<p>独立 Qt 开源项目，与腾讯无隶属关系。<br>Independent Qt project, unaffiliated with Tencent.</p>"
                    f'<p><a href="{REPOSITORY}">源码与许可证 / Source and license</a> · '
                    f'<a href="{REPOSITORY}/releases">发布 / Releases</a> · '
                    f'<a href="{REPOSITORY}/blob/main/DISCLAIMER.md">免责声明 / Disclaimer</a></p>')
        box.exec()

    def _show(self):
        if not self.closing:
            self.show()
            self.raise_()
            self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show()

    def closeEvent(self, event):
        if self.closing:
            event.accept()
            return
        if any(pane.active_task for pane in self.accounts):
            answer = QMessageBox.question(self, self.t("quit_title"), self.t("quit_body"),
                                          defaultButton=QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.closing = True
        self.update_timer.stop()
        if self.tray:
            self.tray.hide()
        event.accept()
        for pane in list(self.accounts):
            if pane.stop_action != "dispose":
                pane.dispose()
        self._quit_when_ready()

    def _quit_when_ready(self):
        if self.closing and not self.accounts and not self.update_task:
            QApplication.instance().quit()

