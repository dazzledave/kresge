"""The main dashboard window: live charts, per-process and per-interface
tables, a history view, and a settings panel. Subscribes to the engine's
signals and updates in place.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..config import Settings, format_bytes, format_rate
from ..engine import MonitorEngine
from ..process_monitor import ProcessUsage
from ..sampler import Sample
from .icons import make_icon

DOWN_COLOR = "#2ecc71"
UP_COLOR = "#3498db"


class _StatCard(QGroupBox):
    """A big headline number (e.g. current download speed)."""

    def __init__(self, title: str, color: str) -> None:
        super().__init__(title)
        layout = QVBoxLayout(self)
        self.value = QLabel("0 B/s")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value.setStyleSheet(f"font-size: 26px; font-weight: 600; color: {color};")
        self.sub = QLabel("session: 0 B")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setStyleSheet("color: #888;")
        layout.addWidget(self.value)
        layout.addWidget(self.sub)


class DashboardWindow(QMainWindow):
    def __init__(self, engine: MonitorEngine, settings: Settings) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.setWindowTitle("Kresge — Network Monitor")
        self.setWindowIcon(make_icon())
        self.resize(940, 680)

        # rolling buffers for the live chart
        self._t0 = time.time()
        maxlen = max(self.settings.chart_window_seconds * 2, 60)
        self._times: deque[float] = deque(maxlen=maxlen)
        self._down: deque[float] = deque(maxlen=maxlen)
        self._up: deque[float] = deque(maxlen=maxlen)
        self._session_sent = 0
        self._session_recv = 0

        tabs = QTabWidget()
        tabs.addTab(self._build_live_tab(), "Live")
        tabs.addTab(self._build_history_tab(), "History")
        tabs.addTab(self._build_settings_tab(), "Settings")
        self.setCentralWidget(tabs)

        engine.sampleReady.connect(self._on_sample)

    # -- Live tab -----------------------------------------------------------

    def _build_live_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        cards = QHBoxLayout()
        self.card_down = _StatCard("Download", DOWN_COLOR)
        self.card_up = _StatCard("Upload", UP_COLOR)
        cards.addWidget(self.card_down)
        cards.addWidget(self.card_up)
        layout.addLayout(cards)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#1e1e2e")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setLabel("left", "Throughput", units="B/s")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.addLegend()
        self._curve_down = self.plot.plot(pen=pg.mkPen(DOWN_COLOR, width=2), name="Download")
        self._curve_up = self.plot.plot(pen=pg.mkPen(UP_COLOR, width=2), name="Upload")
        layout.addWidget(self.plot, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.proc_table = QTableWidget(0, 5)
        self.proc_table.setHorizontalHeaderLabels(
            ["Process", "PID", "Download", "Upload", "Conns"]
        )
        self.proc_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        proc_box = QGroupBox("Top processes (estimated)")
        pl = QVBoxLayout(proc_box)
        pl.addWidget(self.proc_table)
        splitter.addWidget(proc_box)

        self.nic_table = QTableWidget(0, 3)
        self.nic_table.setHorizontalHeaderLabels(["Interface", "Download", "Upload"])
        self.nic_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.nic_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        nic_box = QGroupBox("Interfaces")
        nl = QVBoxLayout(nic_box)
        nl.addWidget(self.nic_table)
        splitter.addWidget(nic_box)
        splitter.setSizes([560, 360])

        layout.addWidget(splitter, stretch=1)
        return w

    # -- History tab --------------------------------------------------------

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.month_label = QLabel("This month: —")
        self.month_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self.month_label)

        self.cap_bar = QProgressBar()
        self.cap_bar.setFormat("%p% of monthly cap")
        self.cap_bar.setVisible(False)
        layout.addWidget(self.cap_bar)

        self.total_label = QLabel("All-time: —")
        self.total_label.setStyleSheet("color: #888;")
        layout.addWidget(self.total_label)

        self.hist_plot = pg.PlotWidget()
        self.hist_plot.setBackground("#1e1e2e")
        self.hist_plot.showGrid(x=False, y=True, alpha=0.2)
        self.hist_plot.setLabel("left", "Daily usage", units="B")
        self.hist_plot.setTitle("Last 30 days")
        layout.addWidget(self.hist_plot, stretch=1)

        refresh = QPushButton("Refresh history")
        refresh.clicked.connect(self.refresh_history)
        layout.addWidget(refresh, alignment=Qt.AlignmentFlag.AlignLeft)
        return w

    def refresh_history(self) -> None:
        # Monthly total + cap progress
        m_sent, m_recv = self.engine.db.month_usage()
        m_total = m_sent + m_recv
        self.month_label.setText(
            f"This month: {format_bytes(m_total)}  "
            f"(↓ {format_bytes(m_recv)} / ↑ {format_bytes(m_sent)})"
        )
        if self.settings.monthly_cap_gb > 0:
            cap = self.settings.monthly_cap_gb * 1024 ** 3
            pct = min(int(m_total / cap * 100), 100) if cap else 0
            self.cap_bar.setVisible(True)
            self.cap_bar.setValue(pct)
        else:
            self.cap_bar.setVisible(False)

        t_sent, t_recv = self.engine.db.total_usage()
        self.total_label.setText(
            f"All-time: {format_bytes(t_sent + t_recv)}  "
            f"(↓ {format_bytes(t_recv)} / ↑ {format_bytes(t_sent)})"
        )

        # Daily bar chart (download + upload grouped)
        rows = self.engine.db.daily_usage(30)
        self.hist_plot.clear()
        if rows:
            xs = list(range(len(rows)))
            recv = [r[2] for r in rows]
            sent = [r[1] for r in rows]
            self.hist_plot.addItem(pg.BarGraphItem(
                x=[x - 0.2 for x in xs], height=recv, width=0.4, brush=DOWN_COLOR
            ))
            self.hist_plot.addItem(pg.BarGraphItem(
                x=[x + 0.2 for x in xs], height=sent, width=0.4, brush=UP_COLOR
            ))
            ax = self.hist_plot.getAxis("bottom")
            ax.setTicks([[(i, datetime.fromisoformat(r[0]).strftime("%m-%d"))
                          for i, r in enumerate(rows)]])

    # -- Settings tab -------------------------------------------------------

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        form = QFormLayout()
        s = self.settings

        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(250, 10000)
        self.sp_interval.setSingleStep(250)
        self.sp_interval.setSuffix(" ms")
        self.sp_interval.setValue(s.sample_interval_ms)
        form.addRow("Sample interval", self.sp_interval)

        self.sp_window = QSpinBox()
        self.sp_window.setRange(30, 1800)
        self.sp_window.setSuffix(" s")
        self.sp_window.setValue(s.chart_window_seconds)
        form.addRow("Chart window", self.sp_window)

        self.sp_cap = QDoubleSpinBox()
        self.sp_cap.setRange(0, 100000)
        self.sp_cap.setSuffix(" GB")
        self.sp_cap.setValue(s.monthly_cap_gb)
        form.addRow("Monthly data cap (0 = off)", self.sp_cap)

        self.sp_capwarn = QSpinBox()
        self.sp_capwarn.setRange(1, 100)
        self.sp_capwarn.setSuffix(" %")
        self.sp_capwarn.setValue(s.cap_warn_percent)
        form.addRow("Warn at cap %", self.sp_capwarn)

        self.sp_high = QDoubleSpinBox()
        self.sp_high.setRange(0, 100000)
        self.sp_high.setSuffix(" Mbps")
        self.sp_high.setValue(s.high_usage_mbps)
        form.addRow("High-usage alert (0 = off)", self.sp_high)

        self.sp_high_sustain = QSpinBox()
        self.sp_high_sustain.setRange(1, 600)
        self.sp_high_sustain.setSuffix(" s")
        self.sp_high_sustain.setValue(s.high_usage_sustain_s)
        form.addRow("…sustained for", self.sp_high_sustain)

        self.sp_hog = QDoubleSpinBox()
        self.sp_hog.setRange(0, 100000)
        self.sp_hog.setSuffix(" Mbps")
        self.sp_hog.setValue(s.process_hog_mbps)
        form.addRow("Per-process hog alert (0 = off)", self.sp_hog)

        self.cb_bits = QCheckBox("Show speeds in bits (Mbps) instead of bytes")
        self.cb_bits.setChecked(s.units_bits)
        form.addRow("", self.cb_bits)

        self.cb_min = QCheckBox("Start minimized to tray")
        self.cb_min.setChecked(s.start_minimized)
        form.addRow("", self.cb_min)

        outer.addLayout(form)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save_settings)
        outer.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addStretch(1)

        note = QLabel(
            "Note: per-process figures are estimated by distributing total "
            "throughput across active connections. Exact per-app byte counts "
            "on Windows require an Administrator ETW session."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        outer.addWidget(note)
        return w

    def _save_settings(self) -> None:
        s = self.settings
        s.sample_interval_ms = self.sp_interval.value()
        s.chart_window_seconds = self.sp_window.value()
        s.monthly_cap_gb = self.sp_cap.value()
        s.cap_warn_percent = self.sp_capwarn.value()
        s.high_usage_mbps = self.sp_high.value()
        s.high_usage_sustain_s = self.sp_high_sustain.value()
        s.process_hog_mbps = self.sp_hog.value()
        s.units_bits = self.cb_bits.isChecked()
        s.start_minimized = self.cb_min.isChecked()
        s.save()
        self.engine.apply_interval()
        # resize rolling buffers if the window changed
        maxlen = max(s.chart_window_seconds * 2, 60)
        self._times = deque(self._times, maxlen=maxlen)
        self._down = deque(self._down, maxlen=maxlen)
        self._up = deque(self._up, maxlen=maxlen)
        self.refresh_history()

    # -- live updates -------------------------------------------------------

    def _on_sample(self, sample: Sample, processes: list[ProcessUsage]) -> None:
        bits = self.settings.units_bits
        self._session_sent += sample.sent_bytes
        self._session_recv += sample.recv_bytes

        self.card_down.value.setText(format_rate(sample.recv_rate, bits))
        self.card_down.sub.setText(f"session: {format_bytes(self._session_recv)}")
        self.card_up.value.setText(format_rate(sample.sent_rate, bits))
        self.card_up.sub.setText(f"session: {format_bytes(self._session_sent)}")

        t = sample.ts - self._t0
        self._times.append(t)
        self._down.append(sample.recv_rate)
        self._up.append(sample.sent_rate)
        self._curve_down.setData(list(self._times), list(self._down))
        self._curve_up.setData(list(self._times), list(self._up))
        window = self.settings.chart_window_seconds
        self.plot.setXRange(max(0, t - window), t, padding=0)

        self._fill_proc_table(processes, bits)
        self._fill_nic_table(sample, bits)

    def _fill_proc_table(self, processes: list[ProcessUsage], bits: bool) -> None:
        top = processes[:15]
        self.proc_table.setRowCount(len(top))
        for row, u in enumerate(top):
            self.proc_table.setItem(row, 0, QTableWidgetItem(u.name))
            self.proc_table.setItem(row, 1, QTableWidgetItem(str(u.pid)))
            d = QTableWidgetItem(format_rate(u.recv_rate, bits))
            d.setForeground(QColor(DOWN_COLOR))
            self.proc_table.setItem(row, 2, d)
            up = QTableWidgetItem(format_rate(u.sent_rate, bits))
            up.setForeground(QColor(UP_COLOR))
            self.proc_table.setItem(row, 3, up)
            self.proc_table.setItem(row, 4, QTableWidgetItem(str(u.connections)))

    def _fill_nic_table(self, sample: Sample, bits: bool) -> None:
        nics = sorted(
            sample.per_nic.values(),
            key=lambda n: n.recv_rate + n.sent_rate,
            reverse=True,
        )
        self.nic_table.setRowCount(len(nics))
        for row, n in enumerate(nics):
            self.nic_table.setItem(row, 0, QTableWidgetItem(n.name))
            d = QTableWidgetItem(format_rate(n.recv_rate, bits))
            d.setForeground(QColor(DOWN_COLOR))
            self.nic_table.setItem(row, 1, d)
            up = QTableWidgetItem(format_rate(n.sent_rate, bits))
            up.setForeground(QColor(UP_COLOR))
            self.nic_table.setItem(row, 2, up)

    # -- window behaviour ---------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self.refresh_history()

    def closeEvent(self, event) -> None:  # noqa: N802
        # Hide to tray instead of quitting; the tray menu handles real exit.
        event.ignore()
        self.hide()
