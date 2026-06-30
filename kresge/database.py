"""SQLite historical logging.

Two granularities are kept:

* ``minute_samples`` — one row per wall-clock minute with the bytes moved in
  that minute. Powers the history charts and is pruned after a retention window.
* ``daily_usage`` — one row per calendar day with cumulative bytes. Cheap to
  keep forever; powers totals, monthly cap tracking, and long-term trends.

Per-second samples are buffered in memory and flushed to the minute table when
the minute rolls over, so writes stay light regardless of sample rate.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from .config import DB_PATH
from .sampler import Sample


SCHEMA = """
CREATE TABLE IF NOT EXISTS minute_samples (
    minute_ts   INTEGER PRIMARY KEY,   -- epoch seconds truncated to the minute
    sent_bytes  INTEGER NOT NULL,
    recv_bytes  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_usage (
    day         TEXT PRIMARY KEY,      -- ISO date YYYY-MM-DD (local)
    sent_bytes  INTEGER NOT NULL,
    recv_bytes  INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        # timeout = how long to wait for a lock before raising "database is
        # locked". WAL mode lets readers and a writer coexist and shortens the
        # window a write holds the lock — both guard against transient
        # contention (e.g. a second instance briefly overlapping at shutdown).
        self._conn = sqlite3.connect(str(path), timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

        self._buf_minute: int | None = None
        self._buf_sent = 0
        self._buf_recv = 0

    # -- ingestion ----------------------------------------------------------

    def record(self, sample: Sample) -> None:
        """Accumulate one interval's bytes; flush when the minute changes."""
        minute = int(sample.ts // 60 * 60)

        if self._buf_minute is None:
            self._buf_minute = minute

        if minute != self._buf_minute:
            self._flush_minute()
            self._buf_minute = minute

        self._buf_sent += sample.sent_bytes
        self._buf_recv += sample.recv_bytes
        self._update_daily(sample.ts, sample.sent_bytes, sample.recv_bytes)

    def _flush_minute(self) -> None:
        if self._buf_minute is None or (self._buf_sent == 0 and self._buf_recv == 0):
            self._buf_sent = self._buf_recv = 0
            return
        self._conn.execute(
            """INSERT INTO minute_samples(minute_ts, sent_bytes, recv_bytes)
               VALUES (?, ?, ?)
               ON CONFLICT(minute_ts) DO UPDATE SET
                   sent_bytes = sent_bytes + excluded.sent_bytes,
                   recv_bytes = recv_bytes + excluded.recv_bytes""",
            (self._buf_minute, self._buf_sent, self._buf_recv),
        )
        self._conn.commit()
        self._buf_sent = self._buf_recv = 0

    def _update_daily(self, ts: float, sent: int, recv: int) -> None:
        if sent == 0 and recv == 0:
            return
        day = datetime.fromtimestamp(ts).date().isoformat()
        self._conn.execute(
            """INSERT INTO daily_usage(day, sent_bytes, recv_bytes)
               VALUES (?, ?, ?)
               ON CONFLICT(day) DO UPDATE SET
                   sent_bytes = sent_bytes + excluded.sent_bytes,
                   recv_bytes = recv_bytes + excluded.recv_bytes""",
            (day, sent, recv),
        )
        # daily commit happens alongside minute flush to limit fsyncs

    # -- queries ------------------------------------------------------------

    def daily_usage(self, days: int = 30) -> list[tuple[str, int, int]]:
        """Return (day, sent, recv) for the most recent `days`, oldest first."""
        cur = self._conn.execute(
            "SELECT day, sent_bytes, recv_bytes FROM daily_usage "
            "ORDER BY day DESC LIMIT ?",
            (days,),
        )
        return list(reversed(cur.fetchall()))

    def minute_history(self, since_ts: float) -> list[tuple[int, int, int]]:
        """Return (minute_ts, sent, recv) since the given epoch time."""
        self._flush_minute()  # make sure the current buffer is visible
        cur = self._conn.execute(
            "SELECT minute_ts, sent_bytes, recv_bytes FROM minute_samples "
            "WHERE minute_ts >= ? ORDER BY minute_ts",
            (int(since_ts),),
        )
        return cur.fetchall()

    def month_usage(self, year: int | None = None, month: int | None = None) -> tuple[int, int]:
        """Total (sent, recv) bytes for a calendar month (default: current)."""
        today = date.today()
        year = year or today.year
        month = month or today.month
        prefix = f"{year:04d}-{month:02d}-"
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(sent_bytes), 0), COALESCE(SUM(recv_bytes), 0) "
            "FROM daily_usage WHERE day LIKE ?",
            (prefix + "%",),
        )
        return cur.fetchone()

    def usage_buckets(self, granularity: str, limit: int) -> list[tuple[str, int, int]]:
        """Aggregate daily usage into day/week/month buckets for the history view.

        ``granularity`` is one of ``"day"``, ``"week"`` (Monday-started), or
        ``"month"``. Returns ``(label, sent_bytes, recv_bytes)`` oldest first,
        capped to the most recent ``limit`` buckets.
        """
        self._flush_minute()  # surface the latest in-progress data
        cur = self._conn.execute(
            "SELECT day, sent_bytes, recv_bytes FROM daily_usage ORDER BY day"
        )
        # dict preserves insertion order, and rows arrive chronologically.
        buckets: dict[str, list[int]] = {}
        labels: dict[str, str] = {}
        for day_str, sent, recv in cur.fetchall():
            d = date.fromisoformat(day_str)
            if granularity == "week":
                start = d - timedelta(days=d.weekday())   # Monday of that week
                key, label = start.isoformat(), start.strftime("%b %d")
            elif granularity == "month":
                key, label = f"{d.year:04d}-{d.month:02d}", d.strftime("%b %Y")
            else:  # day
                key, label = day_str, d.strftime("%b %d")
            acc = buckets.setdefault(key, [0, 0])
            acc[0] += sent
            acc[1] += recv
            labels[key] = label
        recent = list(buckets.items())[-limit:]
        return [(labels[k], v[0], v[1]) for k, v in recent]

    def total_usage(self) -> tuple[int, int]:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(sent_bytes), 0), COALESCE(SUM(recv_bytes), 0) "
            "FROM daily_usage"
        )
        return cur.fetchone()

    # -- maintenance --------------------------------------------------------

    def prune(self, keep_minute_days: int) -> None:
        cutoff = int(time.time() - keep_minute_days * 86400)
        self._conn.execute("DELETE FROM minute_samples WHERE minute_ts < ?", (cutoff,))
        self._conn.commit()

    def close(self) -> None:
        self._flush_minute()
        self._conn.commit()
        self._conn.close()
