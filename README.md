# Kresge — Advanced Network Monitor for Windows

A lightweight system-tray network monitor that tracks live upload/download
speed, estimates per-process bandwidth, keeps a searchable history, and raises
alerts for data caps and bandwidth hogs.

Built with Python + PyQt6 + pyqtgraph + psutil.

## Features

- **Live throughput** — real-time up/down speed per network interface, with a
  rolling chart and headline speed cards.
- **Per-process usage** — see which apps are moving data. (Estimated — see
  [How per-process works](#how-per-process-attribution-works).)
- **History** — per-minute and per-day usage logged to SQLite; monthly totals,
  all-time totals, and a usage chart you can group by **day, week, or month**.
- **Alerts & data caps** — monthly cap with early-warning threshold, sustained
  high-usage alerts, and per-process bandwidth-hog alerts, delivered as native
  Windows tray notifications.
- **Tray + dashboard** — lives in the system tray showing live speed in its
  tooltip; double-click (or use the menu) to open the full dashboard.

## Setup

Requires Python 3.10+.

```powershell
cd C:\Users\theon\Documents\kresge
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Running

```powershell
.venv\Scripts\python main.py
```

Or just double-click **`run.bat`**, which launches it without a console window
(suitable for adding to your Startup folder so it runs at login).

- The dashboard opens on first launch (unless **Start minimized** is enabled
  in Settings).
- Closing the window hides it to the tray — it keeps monitoring.
- Right-click the tray icon → **Quit** to fully exit.

## Configuration

All settings are editable in the **Settings** tab and persisted to
`%LOCALAPPDATA%\Kresge\config.json`:

| Setting | Meaning |
| --- | --- |
| Sample interval | How often counters are polled (default 1000 ms) |
| Chart window | Seconds of history shown on the live chart |
| Monthly data cap | GB cap for the current month (0 = off) |
| Warn at cap % | Early-warning threshold before the cap |
| High-usage alert | Alert when total speed stays above this many Mbps |
| Per-process hog alert | Alert when one process exceeds this many Mbps |
| Units | Show speeds in bytes (MB/s) or bits (Mbps) |

History lives in `%LOCALAPPDATA%\Kresge\history.db`. Per-minute samples are
pruned after 30 days by default; daily totals are kept indefinitely.

## How per-process attribution works

Windows does not expose exact per-process network byte counters through any
unprivileged, cross-platform API. Kresge estimates per-process usage by
distributing the measured total throughput across each process's active TCP/UDP
connections. This is great for spotting *which* app is hogging bandwidth, but
the byte figures are approximate.

For byte-accurate per-process numbers, an Administrator
[ETW](https://learn.microsoft.com/windows/win32/etw/about-event-tracing)
(Event Tracing for Windows) kernel session is required. The estimator is
isolated behind `ProcessMonitor` in `kresge/process_monitor.py`, so an exact
ETW backend can be added later without changing the rest of the app.

## Project layout

```
main.py                  Entry point
kresge/
  config.py              Settings + byte/rate formatting
  sampler.py             Global throughput from psutil counters
  process_monitor.py     Per-process bandwidth estimation
  database.py            SQLite history (minute + daily granularity)
  alerts.py              Cap / high-usage / hog alert rules
  engine.py              Timer-driven engine; emits Qt signals
  ui/
    dashboard.py         Live charts, tables, history, settings
    tray.py              System-tray icon + notifications
    app.py               Application bootstrap
    icons.py             Programmatically drawn app icon
```

## Notes

- Loopback interfaces are excluded from totals.
- Counters that reset (e.g. an interface restart) are clamped so speeds never
  go negative.
