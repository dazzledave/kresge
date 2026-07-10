"""The Tools tab: common network diagnostics with a live streaming console.

Each tool runs in a background thread (subprocess for OS commands, plain Python
for socket-based ones) and streams output back to the UI via Qt signals, so the
window never blocks. A Stop button cancels the running tool.
"""
from __future__ import annotations

import re
import socket
import subprocess
import threading

import psutil
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .theme import scoped_qss

_CREATE_NO_WINDOW = 0x08000000

# Tool name -> (needs a target?, needs a port field?, input placeholder)
_TOOLS = {
    "Ping":        (True,  False, "example.com or 8.8.8.8"),
    "Traceroute":  (True,  False, "example.com or 8.8.8.8"),
    "DNS Lookup":  (True,  False, "example.com"),
    "Port Check":  (True,  True,  "host to scan"),
    "Public IP":   (False, False, ""),
    "IP Config":   (False, False, ""),
}
_DEFAULT_PORTS = [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 3389, 8080]


class ToolsTab(QWidget):
    _line = pyqtSignal(str)
    _done = pyqtSignal()

    def __init__(self, colors: dict) -> None:
        super().__init__()
        self.setStyleSheet(scoped_qss(colors))
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._cancel = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Tool selector (segmented buttons).
        toolbar = QHBoxLayout()
        toolbar.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, name in enumerate(_TOOLS):
            btn = QPushButton(name)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(btn)
            toolbar.addWidget(btn)
            if i == 0:
                btn.setChecked(True)
        self._group.buttonClicked.connect(self._on_tool_changed)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # Input row: target, optional port, continuous flag, action buttons.
        row = QHBoxLayout()
        row.addWidget(QLabel("Target:"))
        self.target = QLineEdit()
        self.target.returnPressed.connect(self._start)
        row.addWidget(self.target, stretch=1)

        self.port_label = QLabel("Port(s):")
        row.addWidget(self.port_label)
        self.port = QLineEdit()
        self.port.setPlaceholderText("blank = common")
        self.port.setFixedWidth(140)
        self.port.returnPressed.connect(self._start)
        row.addWidget(self.port)

        self.cont = QCheckBox("Continuous")
        row.addWidget(self.cont)

        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("segBtn")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.clicked.connect(self._start)
        row.addWidget(self.run_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("refreshBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.stop_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("refreshBtn")
        clear_btn.clicked.connect(lambda: self.console.clear())
        row.addWidget(clear_btn)
        layout.addLayout(row)

        # Output console.
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)   # cap growth for continuous ping
        self.console.setFont(QFont("Consolas", 10))
        self.console.setPlaceholderText("Output appears here…")
        layout.addWidget(self.console, stretch=1)

        self._line.connect(self.console.appendPlainText)
        self._done.connect(self._on_finished)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop)   # kill any running tool on exit
        self._on_tool_changed()

    def apply_theme(self, colors: dict) -> None:
        self.setStyleSheet(scoped_qss(colors))

    # -- UI state -----------------------------------------------------------

    def _current_tool(self) -> str:
        btn = self._group.checkedButton()
        return btn.text() if btn else "Ping"

    def _on_tool_changed(self, *_) -> None:
        tool = self._current_tool()
        needs_target, needs_port, placeholder = _TOOLS[tool]
        self.target.setEnabled(needs_target)
        self.target.setPlaceholderText(placeholder)
        self.port_label.setVisible(needs_port)
        self.port.setVisible(needs_port)
        self.cont.setVisible(tool == "Ping")

    # -- run / stop ---------------------------------------------------------

    @staticmethod
    def _clean_target(raw: str) -> str:
        """Turn a pasted URL into a bare host, e.g. https://x.com/p -> x.com."""
        t = raw.strip()
        for scheme in ("http://", "https://", "ftp://"):
            if t.lower().startswith(scheme):
                t = t[len(scheme):]
        t = t.split("/", 1)[0].split("?", 1)[0].strip()
        return t

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            self.console.appendPlainText("• A tool is still running — press Stop first.")
            return
        tool = self._current_tool()
        needs_target = _TOOLS[tool][0]
        target = self._clean_target(self.target.text())
        if needs_target and not target:
            self.console.appendPlainText("• Enter a target first.")
            return

        # Read widget state here on the GUI thread; the worker must not touch widgets.
        continuous = self.cont.isChecked()
        ports_text = self.port.text().strip()

        self._cancel = False
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.console.appendPlainText(
            f"\n$ {tool}{(' ' + target) if target else ''}\n" + "─" * 40)
        self._thread = threading.Thread(
            target=self._work, args=(tool, target, continuous, ports_text),
            daemon=True,
        )
        self._thread.start()

    def _stop(self) -> None:
        self._cancel = True
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _on_finished(self) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # -- workers (run on the background thread) -----------------------------

    def _work(self, tool: str, target: str, continuous: bool, ports_text: str) -> None:
        try:
            if tool == "Ping":
                args = ["ping", "-t", target] if continuous else ["ping", "-n", "4", target]
                self._run_proc(args)
            elif tool == "Traceroute":
                self._run_proc(["tracert", "-h", "30", target])
            elif tool == "DNS Lookup":
                self._dns_lookup(target)
            elif tool == "IP Config":
                self._run_proc(["ipconfig", "/all"])
            elif tool == "Port Check":
                self._port_check(target, ports_text)
            elif tool == "Public IP":
                self._public_ip()
        except Exception as exc:            # never let the worker die silently
            self._line.emit(f"Error: {exc}")
        finally:
            self._done.emit()

    def _run_proc(self, argv: list[str]) -> None:
        try:
            self._proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="oem", errors="replace", bufsize=1,
                creationflags=_CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            self._line.emit(f"Command not found: {argv[0]}")
            return
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._cancel:
                break
            line = line.rstrip("\r\n")
            if line:
                self._line.emit(line)
        try:
            self._proc.wait(timeout=1)
        except Exception:
            pass
        self._proc = None

    def _dns_lookup(self, host: str) -> None:
        self._line.emit(f"Resolving {host} …")
        try:
            infos = socket.getaddrinfo(host, None)
            seen = []
            for fam, _t, _p, _c, sockaddr in infos:
                ip = sockaddr[0]
                kind = "IPv6" if fam == socket.AF_INET6 else "IPv4"
                if (kind, ip) not in seen:
                    seen.append((kind, ip))
                    self._line.emit(f"  {kind}: {ip}")
            if not seen:
                self._line.emit("  No records found.")
        except socket.gaierror as e:
            self._line.emit(f"  Lookup failed: {e}")
            return
        # Also run nslookup for the authoritative/server detail.
        self._line.emit("")
        self._run_proc(["nslookup", host])

    def _port_check(self, host: str, ports_text: str) -> None:
        if ports_text:
            ports = [int(p) for p in re.split(r"[,\s]+", ports_text) if p.isdigit()]
        else:
            ports = _DEFAULT_PORTS
        self._line.emit(f"Scanning {len(ports)} port(s) on {host} …")
        for p in ports:
            if self._cancel:
                break
            try:
                with socket.create_connection((host, p), timeout=1.5):
                    self._line.emit(f"  {p:>5}  OPEN")
            except ConnectionRefusedError:
                self._line.emit(f"  {p:>5}  closed")
            except (socket.timeout, OSError):
                self._line.emit(f"  {p:>5}  filtered / no response")
        self._line.emit("Done.")

    def _public_ip(self) -> None:
        self._line.emit("Local addresses:")
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    self._line.emit(f"  {name}: {a.address}")
        self._line.emit("")
        self._line.emit("Fetching public IP …")
        import urllib.request
        for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
            try:
                ip = urllib.request.urlopen(url, timeout=5).read().decode().strip()
                self._line.emit(f"Public IP: {ip}")
                return
            except Exception:
                continue
        self._line.emit("Could not reach a public-IP service (no internet?).")
