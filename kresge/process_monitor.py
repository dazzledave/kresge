"""Per-process bandwidth attribution.

Windows does not expose exact per-process byte counters through any
unprivileged, cross-platform API (psutil's per-process I/O counters are
*disk* I/O, not network). Getting byte-accurate numbers requires an ETW
(Event Tracing for Windows) kernel session, which needs Administrator rights.

This module provides a pragmatic estimator that works with no special
privileges: it inspects each process's active TCP/UDP connections and
distributes the measured global throughput across processes weighted by how
many active connections each one holds. The result is an *estimate* — good
for spotting which app is hogging bandwidth, not for billing.

The estimator is deliberately isolated behind :class:`ProcessMonitor` so an
exact ETW backend can be slotted in later without touching the rest of the app.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import psutil

from .sampler import Sample


@dataclass
class ProcessUsage:
    pid: int
    name: str
    sent_rate: float           # estimated bytes/sec up
    recv_rate: float           # estimated bytes/sec down
    connections: int           # active inet connections (the weighting basis)
    estimated: bool = True     # True until an exact backend is wired in


class ProcessMonitor:
    """Estimates per-process throughput from connection counts.

    Connection enumeration is moderately expensive, so we refresh the
    PID→connection-count map on its own cadence (``refresh_interval``) and
    reuse it between refreshes.
    """

    def __init__(self, refresh_interval: float = 2.0) -> None:
        self._refresh_interval = refresh_interval
        self._last_refresh = 0.0
        self._conn_by_pid: dict[int, int] = {}
        self._name_cache: dict[int, str] = {}

    def _process_name(self, pid: int) -> str:
        name = self._name_cache.get(pid)
        if name is None:
            try:
                name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                name = f"pid {pid}"
            self._name_cache[pid] = name
        return name

    def _refresh_connections(self) -> None:
        counts: dict[int, int] = {}
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError):
            # Without privileges some rows are hidden; we still use what we get.
            conns = []
        for c in conns:
            if not c.pid:
                continue
            # Established/active connections are the ones actually moving bytes.
            if c.status in (psutil.CONN_ESTABLISHED, psutil.CONN_NONE, "NONE"):
                counts[c.pid] = counts.get(c.pid, 0) + 1
        self._conn_by_pid = counts
        # Drop name-cache entries for processes that have gone away.
        live = set(counts)
        self._name_cache = {p: n for p, n in self._name_cache.items() if p in live}

    def sample(self, sample: Sample) -> list[ProcessUsage]:
        now = time.time()
        if now - self._last_refresh >= self._refresh_interval:
            self._refresh_connections()
            self._last_refresh = now

        total_weight = sum(self._conn_by_pid.values())
        if total_weight == 0:
            return []

        usages: list[ProcessUsage] = []
        for pid, weight in self._conn_by_pid.items():
            share = weight / total_weight
            usages.append(
                ProcessUsage(
                    pid=pid,
                    name=self._process_name(pid),
                    sent_rate=sample.sent_rate * share,
                    recv_rate=sample.recv_rate * share,
                    connections=weight,
                )
            )

        usages.sort(key=lambda u: u.sent_rate + u.recv_rate, reverse=True)
        return usages
