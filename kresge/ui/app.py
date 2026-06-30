"""Application bootstrap: build the QApplication, engine, and tray, then run."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from ..config import Settings
from ..engine import MonitorEngine
from .tray import TrayApp


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Kresge")
    # Keep running when the dashboard window is closed (we live in the tray).
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None, "Kresge",
            "No system tray is available on this system, so Kresge cannot run.",
        )
        return 1

    settings = Settings.load()
    engine = MonitorEngine(settings)
    tray = TrayApp(app, engine, settings)

    engine.start()
    if not settings.start_minimized:
        tray.show_window()

    return app.exec()
