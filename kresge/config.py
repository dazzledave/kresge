"""Configuration, paths, and shared formatting helpers.

Settings live in a JSON file under the user's local app data so they survive
restarts. Everything has a sensible default, so a missing or partial config
file is fine.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


APP_NAME = "Kresge"


def app_data_dir() -> Path:
    """Per-user writable directory for the database and settings."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_PATH = app_data_dir() / "config.json"
DB_PATH = app_data_dir() / "history.db"


@dataclass
class Settings:
    """User-tunable settings. Persisted as JSON."""

    # Sampling
    sample_interval_ms: int = 1000          # how often to poll counters
    chart_window_seconds: int = 120         # rolling window shown on the live chart

    # Alerts / data caps
    monthly_cap_gb: float = 0.0             # 0 disables the monthly data-cap alert
    cap_warn_percent: int = 90              # warn at this % of the cap
    process_hog_mbps: float = 0.0           # alert if a single process exceeds this (0 = off)
    high_usage_mbps: float = 0.0            # alert on sustained total usage above this (0 = off)
    high_usage_sustain_s: int = 10          # how long usage must stay high before alerting
    alert_cooldown_s: int = 300             # min seconds between repeats of the same alert

    # UI
    start_minimized: bool = False           # launch straight to the tray
    units_bits: bool = False                # show speeds in bits (Mbps) instead of bytes (MB/s)

    # History retention
    keep_minute_samples_days: int = 30      # prune per-minute history older than this

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Corrupt config shouldn't stop the app from starting.
                pass
        return cls()

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Formatting helpers (shared across UI + alerts)
# ---------------------------------------------------------------------------

_BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def format_bytes(num: float) -> str:
    """Human-readable byte size, e.g. 1536 -> '1.50 KB'."""
    value = float(num)
    for unit in _BYTE_UNITS:
        if abs(value) < 1024.0 or unit == _BYTE_UNITS[-1]:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def format_rate(bytes_per_sec: float, bits: bool = False) -> str:
    """Format a throughput value. Bytes/s by default, bits/s if requested."""
    if bits:
        value = bytes_per_sec * 8.0
        for unit in ["bps", "Kbps", "Mbps", "Gbps", "Tbps"]:
            if abs(value) < 1000.0 or unit == "Tbps":
                return f"{value:.1f} {unit}"
            value /= 1000.0
    return f"{format_bytes(bytes_per_sec)}/s"
