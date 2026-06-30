"""Application bootstrap: build the QApplication, engine, and tray, then run.

Enforces a single running instance. Kresge is a tray app backed by one SQLite
database with a single writer — running several copies at once just makes them
fight over the database lock ("database is locked"). If an instance is already
running, a new launch asks it to show its dashboard and then exits.
"""
from __future__ import annotations

import sys

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from ..config import Settings
from ..engine import MonitorEngine
from .tray import TrayApp

# Per-user unique name so the guard works across separate logins on one machine.
_INSTANCE_KEY = "Kresge-SingleInstance"


def _activate_running_instance() -> bool:
    """If another instance owns the lock, poke it to show and return True."""
    socket = QLocalSocket()
    socket.connectToServer(_INSTANCE_KEY)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True
    return False


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Kresge")
    # Keep running when the dashboard window is closed (we live in the tray).
    app.setQuitOnLastWindowClosed(False)

    # Single-instance guard. Fast path: an existing instance answers, so hand
    # off the "show" request and exit. Otherwise claim the name ourselves.
    if _activate_running_instance():
        return 0
    server = QLocalServer()
    if not server.listen(_INSTANCE_KEY):
        # listen() failed — either another copy won a startup race, or a stale
        # socket from a previous crash is squatting the name.
        if _activate_running_instance():
            return 0  # the other copy is live; let it handle the request
        QLocalServer.removeServer(_INSTANCE_KEY)  # clear the stale socket
        server.listen(_INSTANCE_KEY)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None, "Kresge",
            "No system tray is available on this system, so Kresge cannot run.",
        )
        return 1

    settings = Settings.load()
    engine = MonitorEngine(settings)
    tray = TrayApp(app, engine, settings)

    # A second launch connects to our server; dequeue it and bring the
    # dashboard forward.
    def _on_second_launch() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        tray.show_window()

    server.newConnection.connect(_on_second_launch)

    engine.start()
    if not settings.start_minimized:
        tray.show_window()

    return app.exec()
