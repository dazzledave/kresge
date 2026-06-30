"""Global throughput sampling via psutil counters.

The OS exposes monotonically increasing byte counters per network interface.
We poll them on an interval and turn the deltas into rates (bytes/second).
This needs no special privileges and is accurate for total up/down speed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil


@dataclass
class NicRates:
    """Per-interface throughput for a single sample interval."""

    name: str
    sent_rate: float           # bytes/sec uploaded
    recv_rate: float           # bytes/sec downloaded
    sent_bytes: int            # bytes uploaded during this interval
    recv_bytes: int            # bytes downloaded during this interval


@dataclass
class Sample:
    """One throughput sample across all interfaces."""

    ts: float                                  # epoch seconds
    interval: float                            # seconds since previous sample
    sent_rate: float                           # total bytes/sec up
    recv_rate: float                           # total bytes/sec down
    sent_bytes: int                            # total bytes up this interval
    recv_bytes: int                            # total bytes down this interval
    per_nic: dict[str, NicRates] = field(default_factory=dict)


class NetworkSampler:
    """Turns cumulative interface counters into per-interval rates.

    The first call to :meth:`sample` only primes the baseline and returns
    ``None`` (there is no previous reading to diff against yet).
    """

    def __init__(self, ignore_loopback: bool = True) -> None:
        self._ignore_loopback = ignore_loopback
        self._prev: dict[str, psutil._common.snetio] | None = None
        self._prev_ts: float | None = None

    def _read_counters(self) -> dict[str, "psutil._common.snetio"]:
        counters = psutil.net_io_counters(pernic=True)
        if self._ignore_loopback:
            counters = {
                name: c
                for name, c in counters.items()
                if "loopback" not in name.lower() and not name.lower().startswith("lo")
            }
        return counters

    def sample(self) -> Sample | None:
        now = time.time()
        current = self._read_counters()

        if self._prev is None or self._prev_ts is None:
            self._prev, self._prev_ts = current, now
            return None

        interval = max(now - self._prev_ts, 1e-6)
        per_nic: dict[str, NicRates] = {}
        total_sent = total_recv = 0

        for name, cur in current.items():
            prev = self._prev.get(name)
            if prev is None:
                continue
            # Counters can reset (interface restart) — clamp negatives to 0.
            sent_b = max(cur.bytes_sent - prev.bytes_sent, 0)
            recv_b = max(cur.bytes_recv - prev.bytes_recv, 0)
            total_sent += sent_b
            total_recv += recv_b
            per_nic[name] = NicRates(
                name=name,
                sent_rate=sent_b / interval,
                recv_rate=recv_b / interval,
                sent_bytes=sent_b,
                recv_bytes=recv_b,
            )

        self._prev, self._prev_ts = current, now

        return Sample(
            ts=now,
            interval=interval,
            sent_rate=total_sent / interval,
            recv_rate=total_recv / interval,
            sent_bytes=total_sent,
            recv_bytes=total_recv,
            per_nic=per_nic,
        )
