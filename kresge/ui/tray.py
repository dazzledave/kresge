"""System tray icon. Shows live up/down speed in its tooltip, surfaces alerts
as balloon notifications, and provides a menu to open the dashboard or quit.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..alerts import Alert, AlertLevel
from ..config import Settings, format_rate
from ..engine import MonitorEngine
from ..sampler import Sample
from .dashboard import DashboardWindow
from .icons import make_icon

_LEVEL_ICON = {
    AlertLevel.INFO: QSystemTrayIcon.MessageIcon.Information,
    AlertLevel.WARNING: QSystemTrayIcon.MessageIcon.Warning,
    AlertLevel.CRITICAL: QSystemTrayIcon.MessageIcon.Critical,
}


class TrayApp:
    """Wires the engine, dashboard, and tray icon together."""

    def __init__(self, app: QApplication, engine: MonitorEngine, settings: Settings) -> None:
        self.app = app
        self.engine = engine
        self.settings = settings

        self.window = DashboardWindow(engine, settings)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip("Kresge — starting…")
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

        engine.sampleReady.connect(self._on_sample)
        engine.alertRaised.connect(self._on_alert)

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("Open dashboard", self.show_window)
        menu.addAction("Refresh history", self.window.refresh_history)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        return menu

    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.window.isVisible():
                self.window.hide()
            else:
                self.show_window()

    def _on_sample(self, sample: Sample, processes) -> None:
        bits = self.settings.units_bits
        self.tray.setToolTip(
            f"Kresge\n↓ {format_rate(sample.recv_rate, bits)}"
            f"\n↑ {format_rate(sample.sent_rate, bits)}"
        )

    def _on_alert(self, alert: Alert) -> None:
        if self.tray.supportsMessages():
            self.tray.showMessage(
                alert.title,
                alert.message,
                _LEVEL_ICON.get(alert.level, QSystemTrayIcon.MessageIcon.Information),
                8000,
            )

    def _quit(self) -> None:
        self.engine.shutdown()
        self.settings.save()
        self.tray.hide()
        self.app.quit()
