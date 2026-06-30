"""The main dashboard window: live charts, per-process and per-interface
tables, a history view, and a settings panel. Subscribes to the engine's
signals and updates in place.
"""
from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import Settings, format_bytes, format_rate
from ..engine import MonitorEngine
from ..process_monitor import ProcessUsage
from ..sampler import Sample
from .icons import make_icon

DOWN_COLOR = "#2ecc71"
UP_COLOR = "#3498db"
ACCENT = "#5c7cff"

# Stylesheet for the History tab. Scoped via object names so it doesn't leak
# into the other tabs.
HISTORY_QSS = f"""
QFrame#histCard {{
    background: #252539;
    border: 1px solid #34344c;
    border-radius: 10px;
}}
QLabel#cardTitle {{ color: #8c8ca6; font-size: 11px; font-weight: 600; }}
QLabel#cardValue {{ color: #f0f0f8; font-size: 23px; font-weight: 700; }}
QLabel#cardSub   {{ font-size: 12px; }}
QLabel#histLegend {{ font-size: 12px; }}
QPushButton#segBtn {{
    background: #252539; color: #b0b0c8; border: 1px solid #34344c;
    padding: 6px 20px; font-weight: 600;
}}
QPushButton#segBtn:hover {{ background: #2e2e46; }}
QPushButton#segBtn:checked {{
    background: {ACCENT}; color: #ffffff; border-color: {ACCENT};
}}
QProgressBar#capBar {{
    border: 1px solid #34344c; border-radius: 8px; background: #252539;
    text-align: center; color: #e8e8f0; min-height: 22px;
}}
QPushButton#refreshBtn {{
    background: #252539; color: #b0b0c8; border: 1px solid #34344c;
    border-radius: 6px; padding: 6px 16px;
}}
QPushButton#refreshBtn:hover {{ background: #2e2e46; }}
"""


class _ByteAxisItem(pg.AxisItem):
    """Y-axis that prints human-readable byte sizes instead of raw counts."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 (pyqtgraph API)
        return [format_bytes(max(v, 0)) for v in values]


class _HistoryCard(QFrame):
    """A summary tile: small title, big value, and a colored up/down sub-line."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("histCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        self.sub = QLabel("")
        self.sub.setObjectName("cardSub")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.sub)

    def update_values(self, sent: int, recv: int) -> None:
        self.value.setText(format_bytes(sent + recv))
        self.sub.setText(
            f"<span style='color:{DOWN_COLOR}'>&#8595; {format_bytes(recv)}</span>"
            f"&nbsp;&nbsp;&nbsp;"
            f"<span style='color:{UP_COLOR}'>&#8593; {format_bytes(sent)}</span>"
        )


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
        tabs.addTab(self._build_hotspot_tab(), "Hotspot")
        tabs.addTab(self._build_settings_tab(), "Settings")
        self.setCentralWidget(tabs)

        engine.sampleReady.connect(self._on_sample)
        engine.hotspotSample.connect(self._on_hotspot_sample)

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
        w.setStyleSheet(HISTORY_QSS)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Summary cards: this month, all-time, and the selected-period total.
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_month = _HistoryCard("THIS MONTH")
        self.card_total = _HistoryCard("ALL-TIME")
        self.card_period = _HistoryCard("SELECTED PERIOD")
        cards.addWidget(self.card_month)
        cards.addWidget(self.card_period)
        cards.addWidget(self.card_total)
        layout.addLayout(cards)

        # Monthly data-cap progress (only shown when a cap is configured).
        self.cap_bar = QProgressBar()
        self.cap_bar.setObjectName("capBar")
        self.cap_bar.setVisible(False)
        layout.addWidget(self.cap_bar)

        # Toolbar: segmented Day/Week/Month toggle + chart legend.
        toolbar = QHBoxLayout()
        self._gran_group = QButtonGroup(w)
        self._gran_group.setExclusive(True)
        for label in ("Day", "Week", "Month"):
            btn = QPushButton(label)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._gran_group.addButton(btn)
            toolbar.addWidget(btn)
            if label == "Day":
                btn.setChecked(True)
        self._gran_group.buttonClicked.connect(lambda _: self.refresh_history())
        toolbar.addStretch(1)
        legend = QLabel(
            f"<span style='color:{DOWN_COLOR}'>&#9632; Download</span>"
            f"&nbsp;&nbsp;&nbsp;"
            f"<span style='color:{UP_COLOR}'>&#9632; Upload</span>"
        )
        legend.setObjectName("histLegend")
        toolbar.addWidget(legend)
        layout.addLayout(toolbar)

        # Usage chart with a human-readable byte axis.
        self.hist_plot = pg.PlotWidget(
            axisItems={"left": _ByteAxisItem(orientation="left")}
        )
        self.hist_plot.setBackground("#1e1e2e")
        self.hist_plot.showGrid(x=False, y=True, alpha=0.15)
        self.hist_plot.setMouseEnabled(x=False, y=False)
        self.hist_plot.setMenuEnabled(False)
        self.hist_plot.hideButtons()
        for name in ("left", "bottom"):
            ax = self.hist_plot.getAxis(name)
            ax.setPen("#44445c")
            ax.setTextPen("#9090a8")
        layout.addWidget(self.hist_plot, stretch=1)

        # Empty-state placeholder, shown when there's no data yet.
        self.hist_placeholder = QLabel(
            "No history yet.\nUsage will appear here as you use the network."
        )
        self.hist_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hist_placeholder.setStyleSheet("color: #6c6c84; font-size: 14px;")
        self.hist_placeholder.setVisible(False)
        layout.addWidget(self.hist_placeholder, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("refreshBtn")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.refresh_history)
        bottom.addWidget(refresh)
        layout.addLayout(bottom)
        return w

    def _current_granularity(self) -> str:
        btn = self._gran_group.checkedButton()
        return btn.text() if btn else "Day"

    # How each filter maps to a DB granularity, bucket count, and chart title.
    _HIST_VIEWS = {
        "Day": ("day", 30, "Last 30 days"),
        "Week": ("week", 12, "Last 12 weeks"),
        "Month": ("month", 12, "Last 12 months"),
    }

    def refresh_history(self) -> None:
        # Summary cards: month + all-time.
        m_sent, m_recv = self.engine.db.month_usage()
        self.card_month.update_values(m_sent, m_recv)
        t_sent, t_recv = self.engine.db.total_usage()
        self.card_total.update_values(t_sent, t_recv)

        # Monthly data-cap progress, colored by how close to the cap we are.
        if self.settings.monthly_cap_gb > 0:
            cap = self.settings.monthly_cap_gb * 1024 ** 3
            m_total = m_sent + m_recv
            pct = min(int(m_total / cap * 100), 100) if cap else 0
            color = "#2ecc71" if pct < 75 else "#f1c40f" if pct < 90 else "#e74c3c"
            self.cap_bar.setStyleSheet(
                f"QProgressBar#capBar::chunk {{ border-radius: 7px; background: {color}; }}"
            )
            self.cap_bar.setFormat(
                f"  {format_bytes(m_total)} of {self.settings.monthly_cap_gb:g} GB "
                f"monthly cap  ({pct}%)"
            )
            self.cap_bar.setValue(pct)
            self.cap_bar.setVisible(True)
        else:
            self.cap_bar.setVisible(False)

        # Usage bar chart (download + upload grouped), bucketed by the filter.
        granularity, limit, title = self._HIST_VIEWS[self._current_granularity()]
        rows = self.engine.db.usage_buckets(granularity, limit)

        # Selected-period card + section title.
        p_sent = sum(r[1] for r in rows)
        p_recv = sum(r[2] for r in rows)
        self.card_period.title.setText(title.upper())
        self.card_period.update_values(p_sent, p_recv)

        self.hist_plot.clear()
        has_data = bool(rows)
        self.hist_plot.setVisible(has_data)
        self.hist_placeholder.setVisible(not has_data)
        if has_data:
            xs = list(range(len(rows)))
            sent = [r[1] for r in rows]
            recv = [r[2] for r in rows]
            self.hist_plot.addItem(pg.BarGraphItem(
                x=[x - 0.2 for x in xs], height=recv, width=0.38,
                brush=DOWN_COLOR, pen=None,
            ))
            self.hist_plot.addItem(pg.BarGraphItem(
                x=[x + 0.2 for x in xs], height=sent, width=0.38,
                brush=UP_COLOR, pen=None,
            ))
            # Thin out x labels when crowded so they stay legible.
            step = max(1, len(rows) // 12)
            ticks = [(i, rows[i][0]) for i in xs if i % step == 0]
            self.hist_plot.getAxis("bottom").setTicks([ticks])
            self.hist_plot.setXRange(-0.6, len(rows) - 0.4, padding=0)

    # -- Hotspot tab --------------------------------------------------------

    _HOTSPOT_COLS = ["", "Device", "Vendor", "MAC", "IP", "Download", "Upload",
                     "Total ↓", "Total ↑"]

    def _build_hotspot_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(HISTORY_QSS)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.hs_banner = QLabel("Mobile Hotspot is off.")
        self.hs_banner.setWordWrap(True)
        self.hs_banner.setStyleSheet(
            "background:#252539; border:1px solid #34344c; border-radius:8px;"
            "padding:10px 14px; color:#c8c8dc; font-size:13px;"
        )
        layout.addWidget(self.hs_banner)

        summary = QHBoxLayout()
        summary.setSpacing(12)
        self.hs_card_count = _HistoryCard("CONNECTED DEVICES")
        self.hs_card_down = _HistoryCard("TOTAL DOWNLOAD RATE")
        self.hs_card_up = _HistoryCard("TOTAL UPLOAD RATE")
        # These cards show single values, so hide the up/down sub-line.
        for c in (self.hs_card_count, self.hs_card_down, self.hs_card_up):
            c.sub.setVisible(False)
            summary.addWidget(c)
        layout.addLayout(summary)

        self._hs_devices: list = []   # row index -> device, for rename
        self.hs_table = QTableWidget(0, len(self._HOTSPOT_COLS))
        self.hs_table.setHorizontalHeaderLabels(self._HOTSPOT_COLS)
        self.hs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.hs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.hs_table.verticalHeader().setVisible(False)
        self.hs_table.cellDoubleClicked.connect(self._rename_hotspot_device)
        hh = self.hs_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in range(2, len(self._HOTSPOT_COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.hs_table, stretch=1)

        hint = QLabel("Tip: double-click a device to rename it.")
        hint.setStyleSheet("color:#6c6c84; font-size:11px;")
        layout.addWidget(hint)

        self.hs_empty = QLabel(
            "No devices are connected to your hotspot right now.\n"
            "Connect a device to your Windows Mobile Hotspot to see it here."
        )
        self.hs_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hs_empty.setStyleSheet("color:#6c6c84; font-size:14px;")
        self.hs_empty.setVisible(False)
        layout.addWidget(self.hs_empty, stretch=1)
        return w

    def _rename_hotspot_device(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._hs_devices):
            return
        dev = self._hs_devices[row]
        text, ok = QInputDialog.getText(
            self, "Rename device",
            f"Name for {dev.vendor}  ({dev.mac}):",
            text=(dev.name or dev.auto_name or ""),
        )
        if ok:
            self.engine.hotspot.rename_device(dev.mac, text)
            # Re-render immediately so the new name shows without waiting a tick.
            self._on_hotspot_sample(self.engine.latest_devices, self.engine.hotspot.status)

    def _on_hotspot_sample(self, devices, status: str) -> None:
        bits = self.settings.units_bits
        self._hs_devices = list(devices)   # devices are the currently-connected set

        # Banner reflects capture/status; color hints at whether usage is live.
        if "Capturing" in status:
            banner_color, text = "#2ecc71", f"● {status}"
        elif "off" in status.lower():
            banner_color, text = "#6c6c84", "○ Mobile Hotspot is off."
        else:
            banner_color, text = "#f1c40f", f"▲ {status}  (showing device presence only)"
        self.hs_banner.setText(text)
        self.hs_banner.setStyleSheet(
            f"background:#252539; border:1px solid #34344c; border-radius:8px;"
            f"padding:10px 14px; color:{banner_color}; font-size:13px;"
        )

        total_down = sum(d.recv_rate for d in devices)
        total_up = sum(d.sent_rate for d in devices)
        self.hs_card_count.value.setText(f"{len(devices)}")
        self.hs_card_down.value.setText(format_rate(total_down, bits))
        self.hs_card_up.value.setText(format_rate(total_up, bits))

        has_rows = bool(devices)
        self.hs_table.setVisible(has_rows)
        self.hs_empty.setVisible(not has_rows)

        self.hs_table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            dot = QTableWidgetItem("●")
            dot.setForeground(QColor("#2ecc71"))   # only connected devices shown
            dot.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hs_table.setItem(row, 0, dot)

            name = QTableWidgetItem(d.label())
            if not d.name and not d.auto_name:
                name.setForeground(QColor("#8c8ca6"))   # grey for "Unknown device"
            self.hs_table.setItem(row, 1, name)
            self.hs_table.setItem(row, 2, QTableWidgetItem(d.vendor))
            self.hs_table.setItem(row, 3, QTableWidgetItem(d.mac))
            self.hs_table.setItem(row, 4, QTableWidgetItem(d.ip or "—"))

            down = QTableWidgetItem(format_rate(d.recv_rate, bits))
            down.setForeground(QColor(DOWN_COLOR))
            self.hs_table.setItem(row, 5, down)
            up = QTableWidgetItem(format_rate(d.sent_rate, bits))
            up.setForeground(QColor(UP_COLOR))
            self.hs_table.setItem(row, 6, up)

            self.hs_table.setItem(row, 7, QTableWidgetItem(format_bytes(d.recv_total)))
            self.hs_table.setItem(row, 8, QTableWidgetItem(format_bytes(d.sent_total)))

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
