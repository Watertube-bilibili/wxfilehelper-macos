"""Application entry point. SPDX-License-Identifier: AGPL-3.0-only."""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from .ui import MainWindow


def main():
    smoke_test = "--smoke-test" in sys.argv
    app = QApplication(sys.argv[:1] if smoke_test else sys.argv)
    app.setApplicationName("WX FileHelper Desktop")
    app.setOrganizationName("wxfilehelper-desktop")
    app.setQuitOnLastWindowClosed(False)
    font = QFont("Segoe UI" if sys.platform == "win32" else ".AppleSystemUIFont", 10)
    app.setFont(font)
    window = MainWindow(auto_connect=not smoke_test)
    if smoke_test:
        return _smoke_test(app, window)
    window.show()
    return app.exec()


def _smoke_test(app, window):
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    first = window.current_account
    second = window.add_account()
    window.tabs.setCurrentIndex(0)
    app.processEvents()
    if window.current_account is not first or window.tabs.count() != 2 or first is second:
        raise RuntimeError("Could not switch account tabs")
    if first.send_button.isEnabled() or second.send_button.isEnabled():
        raise RuntimeError("Send should require sign-in")
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
