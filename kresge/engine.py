"""The monitoring engine: a QObject that drives sampling on a timer and emits
signals the UI subscribes to. This is the single source of truth that both the
tray icon and the dashboard listen to, so they always show the same numbers.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .alerts import Alert, AlertLevel, AlertManager
from .config import Settings
from .database import Database
from .hotspot_monitor import HotspotDevice, HotspotMonitor
from .process_monitor import ProcessMonitor, ProcessUsage
from .sampler import NetworkSampler, Sample


class MonitorEngine(QObject):
    """Owns the sampling loop and broadcasts results.

    Signals
    -------
    sampleReady(Sample, list)   : a new throughput sample + per-process usages
    alertRaised(Alert)          : an alert rule tripped
    hotspotSample(list, str)    : connected hotspot devices + a status string
    """

    sampleReady = pyqtSignal(object, object)   # (Sample, list[ProcessUsage])
    alertRaised = pyqtSignal(object)           # (Alert,)
    hotspotSample = pyqtSignal(object, object)  # (list[HotspotDevice], status str)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.sampler = NetworkSampler()
        self.process_monitor = ProcessMonitor()
        self.db = Database()
        self.alerts = AlertManager(settings)
        self.hotspot = HotspotMonitor(self.db)

        self.latest_sample: Sample | None = None
        self.latest_processes: list[ProcessUsage] = []
        self.latest_devices: list[HotspotDevice] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # Prune old history roughly once an hour.
        self._prune_timer = QTimer(self)
        self._prune_timer.timeout.connect(self._prune)
        self._prune_timer.start(3600 * 1000)

    def start(self) -> None:
        self._timer.start(self.settings.sample_interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def apply_interval(self) -> None:
        """Restart the timer after a settings change to the sample interval."""
        if self._timer.isActive():
            self._timer.start(self.settings.sample_interval_ms)

    def _tick(self) -> None:
        sample = self.sampler.sample()
        if sample is None:
            return  # first reading just primes the baseline

        processes = self.process_monitor.sample(sample)
        self.latest_sample = sample
        self.latest_processes = processes

        self.db.record(sample)

        month_sent, month_recv = self.db.month_usage()
        for alert in self.alerts.check(sample, processes, month_sent, month_recv):
            self.alertRaised.emit(alert)

        self.sampleReady.emit(sample, processes)

        # Hotspot devices (no-op work when Mobile Hotspot is off).
        devices = self.hotspot.sample(sample.interval)
        self.latest_devices = devices
        for msg in self.hotspot.pop_events():
            self.alertRaised.emit(Alert(
                key="hotspot_cap", level=AlertLevel.WARNING,
                title="Hotspot data limit", message=msg, ts=sample.ts,
            ))
        self.hotspotSample.emit(devices, self.hotspot.status)

    def _prune(self) -> None:
        self.db.prune(self.settings.keep_minute_samples_days)

    def shutdown(self) -> None:
        self.stop()
        self.hotspot.shutdown()
        self.db.close()
