"""Main window and account tabs. SPDX-License-Identifier: AGPL-3.0-only."""
from __future__ import annotations

import re
import sys
from html import escape

from PySide6.QtCore import Qt, QSettings, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QMainWindow, QMenu, QMessageBox, QPushButton,
    QStackedWidget, QSystemTrayIcon, QTabBar, QVBoxLayout, QWidget,
)

from . import REPOSITORY, __version__
from .account import AccountPane, open_downloads
from .updates import check_for_update
from .widgets import Task, app_icon, label, tr

STYLE = """
QWidget { color: #1b1b1b; font-size: 14px; }
QMainWindow, QWidget#Main, QWidget#Login { background: #fafafa; }
QFrame#Chrome { background: #f0f0f0; border-bottom: 1px solid #d6d6d6; }
QLabel#Heading { font-size: 22px; font-weight: 600; }
QLabel#Brand { font-size: 17px; font-weight: 600; }
QLabel#Muted { color: #515151; font-size: 12px; }
QLabel#State { color: #005a9e; font-size: 13px; }
QLabel#Error { color: #9b3027; font-size: 13px; }
QLabel#QR { background: white; border: 1px solid #dedede; border-radius: 12px; }
QTabBar::tab { background: #e6e6e6; color: #333333; border: 1px solid #dddddd;
  border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 3px;
  padding: 7px 9px; min-height: 19px; min-width: 95px; }
QTabBar::tab:hover { background: #ededed; }
QTabBar::tab:selected { background: #fafafa; color: #005a9e; font-weight: 600;
  border-top: 2px solid #0067c0; border-bottom-color: #fafafa; padding-top: 6px; }
QPushButton { background: #ffffff; border: 1px solid #d0d0d0; border-radius: 6px; padding: 6px 10px; }
QPushButton:hover { background: #ededed; border-color: #a0a0a0; }
QPushButton:pressed { background: #e5e5e5; }
QPushButton:focus { border: 2px solid #0067c0; padding: 5px 9px; }
QPushButton:disabled { color: #737373; background: #eeeeee; border-color: #dedede; }
QPushButton#Primary { background: #0067c0; color: white; border-color: #0067c0; font-weight: 600; }
QPushButton#Primary:hover { background: #005a9e; }
QPushButton#Primary:disabled { color: #fafafa; background: #788898; border-color: #788898; }
QPushButton#Quiet, QPushButton#Filter { background: transparent; border-color: transparent; }
QPushButton#Quiet:hover, QPushButton#Filter:hover { background: #e9e9e9; }
QPushButton#Quiet:focus, QPushButton#Filter:focus { border-color: #0067c0; }
QPushButton#Quiet:disabled { color: #777777; }
QPushButton#Filter:checked { background: #e2effb; color: #005a9e; font-weight: 600; }
QPlainTextEdit, QListWidget#Pending { background: #ffffff; border: 1px solid #d0d0d0; border-radius: 6px;
  padding: 5px; selection-background-color: #cde7fa; selection-color: #1b1b1b; }
QPlainTextEdit:focus, QListWidget#Pending:focus { border-color: #0067c0; }
QListWidget#Pending::item { padding: 4px 5px; }
QScrollArea { border: none; background: transparent; }
QWidget#Stream { background: #fafafa; }
QFrame#Outgoing { background: #e1effa; border-radius: 9px; }
QFrame#Incoming { background: #eeeeee; border-radius: 9px; }
QFrame#Composer { background: #f4f4f4; border: 1px solid #dedede; border-radius: 9px; }
QProgressBar { border: none; background: #dfe4e8; border-radius: 2px; }
QProgressBar::chunk { background: #0067c0; border-radius: 2px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #aeaeae; min-height: 26px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
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
        self.classroom = False
        self.was_maximized = False
        self.display_scale = 1.0
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
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        chrome = QFrame(objectName="Chrome")
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(16, 7, 16, 0)
        chrome_layout.setSpacing(5)
        title = QHBoxLayout()
        logo = label()
        logo.setPixmap(self.icon.pixmap(24, 24))
        title.addWidget(logo)
        self.brand = label(name="Brand")
        title.addWidget(self.brand, 1)
        self.classroom_button = QPushButton(objectName="Quiet")
        self.classroom_button.clicked.connect(self._toggle_classroom)
        title.addWidget(self.classroom_button)
        self.menu_button = QPushButton("⋯", objectName="Quiet")
        self.menu_button.setMinimumWidth(35)
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
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self._tab_selected)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.add_button = QPushButton("+", objectName="Quiet")
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

    def _create_shortcuts(self):
        QShortcut(QKeySequence.StandardKey.Open, self, activated=self._choose_files)
        QShortcut(QKeySequence.StandardKey.AddTab, self, activated=self.add_account)
        QShortcut(QKeySequence("Meta+Tab" if sys.platform == "darwin" else "Ctrl+Tab"), self, activated=self._next_tab)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.tabs.setCurrentIndex(1))
        QShortcut(QKeySequence("F11"), self, activated=self._toggle_classroom)
        QShortcut(QKeySequence("Escape"), self, activated=self._leave_classroom)

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
        if self.closing or self.classroom or len(self.accounts) < 2:
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
        closable = len(self.accounts) > 1 and not self.classroom and not self.closing
        self.tabs.setTabsClosable(closable)
        self.add_button.setVisible(len(self.accounts) < 2 and not self.closing)
        font_metrics = self.tabs.fontMetrics()
        width = 112 if self.width() < 700 else 168
        for index, pane in enumerate(self.accounts):
            account = self.t("account").format(n=pane.number)
            name = pane.nickname if pane.nickname and not self.classroom else account
            number = (" · " + str(pane.number)) if name != account else ""
            badge = ("  • " + ("99+" if pane.unread > 99 else str(pane.unread))) if pane.unread else ""
            busy = "  ↕" if pane.active_task else ""
            caption = font_metrics.elidedText(name, Qt.TextElideMode.ElideRight, width)
            self.tabs.setTabText(index, caption.replace("&", "&&") + number + busy + badge)
            tooltip = escape(name + " · " + self.t(pane.state))
            if pane.unread:
                tooltip += " · " + escape(self.t("unread").format(n=pane.unread))
            self.tabs.setTabToolTip(index, "<qt>" + tooltip + "</qt>")
            close = self.tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if close:
                close.setToolTip(self.t("close_account"))
                close.setAccessibleName(self.t("close_account"))
        current = self.current_account
        self.signout_action.setEnabled(bool(current and not current.stop_action
                                            and (current.client or current.account_id)))

    def _translate(self):
        self.setWindowTitle(self.t("title") + " · WX FileHelper Desktop")
        self.brand.setText(self.t("title"))
        self.tabs.setAccessibleName(self.t("title"))
        self.add_button.setToolTip(self.t("add_account"))
        self.add_button.setAccessibleName(self.t("add_account"))
        self.classroom_button.setText(self.t("exit_classroom" if self.classroom else "classroom"))
        self.menu_button.setToolTip(self.t("menu"))
        self.menu_button.setAccessibleName(self.t("menu"))
        self.download_action.setText(self.t("folder"))
        self.update_action.setText(self.t(self.update_status))
        self.language_action.setText("English" if self.language == "zh" else "简体中文")
        self.about_action.setText(self.t("about"))
        self.signout_action.setText(self.t("signout"))
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
        scale = (1.6 if height >= 900 else 1.34 if height >= 700 else 1.15) if self.classroom else 1.0
        if scale != self.display_scale:
            self.display_scale = scale
            style = re.sub(r"font-size: (\d+)px", lambda m: f"font-size: {round(int(m[1]) * scale)}px", STYLE)
            if self.classroom:
                style += """
QPushButton, QPushButton#Quiet, QPushButton#Filter { min-height: 34px; padding: 7px 10px; }
QPushButton:focus, QPushButton#Quiet:focus, QPushButton#Filter:focus { padding: 6px 9px; }
QTabBar::tab { min-height: 34px; }
QScrollBar:vertical { width: 16px; }
"""
            self.setStyleSheet(style)
        for pane in self.accounts:
            pane.set_display(width, height, self.classroom)
        self._update_tabs()

    def _toggle_classroom(self):
        if self.classroom:
            self._leave_classroom()
            return
        self.was_maximized = self.isMaximized()
        self.classroom = True
        self.showFullScreen()
        self.menu_button.hide()
        self.classroom_button.setText(self.t("exit_classroom"))
        self._adapt_display()

    def _leave_classroom(self):
        if not self.classroom:
            return
        self.classroom = False
        if self.was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.menu_button.show()
        self.classroom_button.setText(self.t("classroom"))
        self._adapt_display()

    def _check_update(self):
        if self.update_task or self.closing:
            return
        self.update_status = "checking"
        self.update_action.setText(self.t(self.update_status))
        self.update_action.setEnabled(False)
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
            if self.classroom:
                self.showFullScreen()
            else:
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

