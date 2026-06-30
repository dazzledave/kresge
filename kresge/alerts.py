"""Alert rules: data caps, sustained high usage, and per-process hogs.

Each rule is checked once per sample. A cooldown prevents the same alert from
firing repeatedly. The manager is UI-agnostic — it returns :class:`Alert`
objects that the caller surfaces (e.g. as tray notifications).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from .config import Settings, format_bytes, format_rate
from .process_monitor import ProcessUsage
from .sampler import Sample


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    key: str                  # stable id for cooldown dedup (e.g. "cap", "hog:1234")
    level: AlertLevel
    title: str
    message: str
    ts: float


_GB = 1024 ** 3
_MB = 1024 ** 2


class AlertManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_fired: dict[str, float] = {}
        self._high_since: float | None = None

    def _ready(self, key: str, now: float) -> bool:
        last = self._last_fired.get(key, 0.0)
        return now - last >= self.settings.alert_cooldown_s

    def _fire(self, alert: Alert) -> Alert:
        self._last_fired[alert.key] = alert.ts
        return alert

    def check(
        self,
        sample: Sample,
        processes: list[ProcessUsage],
        month_sent: int,
        month_recv: int,
    ) -> list[Alert]:
        now = sample.ts
        out: list[Alert] = []
        s = self.settings

        # 1) Monthly data cap -------------------------------------------------
        if s.monthly_cap_gb > 0:
            used = month_sent + month_recv
            cap = s.monthly_cap_gb * _GB
            pct = used / cap * 100 if cap else 0
            if used >= cap and self._ready("cap", now):
                out.append(self._fire(Alert(
                    key="cap", level=AlertLevel.CRITICAL,
                    title="Data cap reached",
                    message=f"Monthly usage {format_bytes(used)} has reached the "
                            f"{s.monthly_cap_gb:g} GB cap.",
                    ts=now,
                )))
            elif pct >= s.cap_warn_percent and self._ready("cap_warn", now):
                out.append(self._fire(Alert(
                    key="cap_warn", level=AlertLevel.WARNING,
                    title="Approaching data cap",
                    message=f"Used {format_bytes(used)} ({pct:.0f}%) of the "
                            f"{s.monthly_cap_gb:g} GB monthly cap.",
                    ts=now,
                )))

        # 2) Sustained high total usage --------------------------------------
        if s.high_usage_mbps > 0:
            total_mbps = (sample.sent_rate + sample.recv_rate) * 8 / 1e6
            if total_mbps >= s.high_usage_mbps:
                if self._high_since is None:
                    self._high_since = now
                elif now - self._high_since >= s.high_usage_sustain_s and self._ready("high", now):
                    out.append(self._fire(Alert(
                        key="high", level=AlertLevel.WARNING,
                        title="High network usage",
                        message=f"Total throughput {format_rate(sample.sent_rate + sample.recv_rate, bits=True)} "
                                f"sustained for {s.high_usage_sustain_s}s.",
                        ts=now,
                    )))
            else:
                self._high_since = None

        # 3) Per-process bandwidth hog ---------------------------------------
        if s.process_hog_mbps > 0 and processes:
            top = processes[0]
            hog_mbps = (top.sent_rate + top.recv_rate) * 8 / 1e6
            if hog_mbps >= s.process_hog_mbps and self._ready(f"hog:{top.pid}", now):
                out.append(self._fire(Alert(
                    key=f"hog:{top.pid}", level=AlertLevel.WARNING,
                    title="Bandwidth hog detected",
                    message=f"{top.name} (pid {top.pid}) is using ~"
                            f"{format_rate(top.sent_rate + top.recv_rate, bits=True)} (estimated).",
                    ts=now,
                )))

        return out
