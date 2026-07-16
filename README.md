<div align="center">

<img src="kresge/ui/assets/logo.png" alt="Kresge" width="120">

# Kresge

### Real-time network monitoring for Windows

Live speed · per-process bandwidth · hotspot device control · usage history · network tools

<p>
  <a href="https://github.com/dazzledave/kresge/releases/latest">
    <img alt="Release" src="https://img.shields.io/github/v/release/dazzledave/kresge?style=flat-square&color=8CB000&label=release">
  </a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Built with" src="https://img.shields.io/badge/built%20with-PyQt6-41CD52?style=flat-square&logo=qt&logoColor=white">
  <a href="https://github.com/dazzledave/kresge/releases">
    <img alt="Downloads" src="https://img.shields.io/github/downloads/dazzledave/kresge/total?style=flat-square&color=8CB000">
  </a>
</p>

<a href="https://github.com/dazzledave/kresge/releases/tag/v0.2.0">
  <img alt="Download Kresge v0.2.0" src="https://img.shields.io/badge/Download%20Kresge-v0.2.0-8CB000?style=for-the-badge&logo=windows&logoColor=white&labelColor=24292e">
</a>

<sub>Single <code>.exe</code> · no Python required · Windows 10 / 11</sub>

</div>

---

## ✨ Features

- 📊 **Live throughput** — real-time up/down speed per interface, with a rolling chart and headline speed cards.
- 🧩 **Per-process usage** — see which apps are moving data. <sub>(Estimated — [why?](#-how-per-process-attribution-works))</sub>
- 📡 **Hotspot monitor** — see every device on your Windows Mobile Hotspot (name, vendor, IP, MAC) **and how much data each one uses**.
- 🚦 **Per-device limits & blocking** — give a device a data cap, or cut it off the hotspot in one click.
- 🗓 **Usage history** — logged to SQLite; browse by **day, week, or month** with totals and trend charts.
- 🔔 **Alerts & data caps** — monthly cap with early warning, sustained high-usage and bandwidth-hog alerts, as native Windows notifications.
- 🛠 **Network tools** — ping, traceroute, DNS lookup, port scanner, public IP, and `ipconfig`, with live streaming output.
- 🌗 **Light & dark theme** — a sun/moon toggle in the tab bar; your choice is remembered.
- 🖥 **Tray + dashboard** — lives in the system tray showing live speed; double-click for the full dashboard.

---

## 🚀 Quick start

**[⬇ Download the latest release](https://github.com/dazzledave/kresge/releases/tag/v0.2.0)**, unzip if needed, and run **`Kresge.exe`**. That's it — no Python, no installer.

> [!TIP]
> For **per-device hotspot usage** and **blocking**, right-click `Kresge.exe` → **Run as administrator**. If the Npcap driver is missing, the Hotspot tab offers a one-click **Install Npcap** button.

Everything else — live speed, history, per-process, the device list, and the network tools — works out of the box.

---

## 🧑‍💻 Running from source

Requires **Python 3.10+**.

```powershell
git clone https://github.com/dazzledave/kresge.git
cd kresge
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Or double-click **`run.bat`** (no console window), or **`run-admin.bat`** to run elevated.

- The dashboard opens on launch (unless **Start minimized** is enabled in Settings).
- Closing the window hides it to the tray — it keeps monitoring.
- Right-click the tray icon → **Quit** to fully exit.

### Building the executable

```powershell
.venv\Scripts\python -m pip install pyinstaller pillow
.\build.bat
```

Produces **`dist\Kresge.exe`** — a single ~70 MB file that runs on any Windows PC. It bundles scapy, the WinRT bindings, and the logo, and embeds the logo as the exe icon.

---

## ⚙️ Configuration

Settings live in the **Settings** tab (each has an ⓘ explaining it) and persist to `%LOCALAPPDATA%\Kresge\config.json`.

| Setting | Meaning |
| --- | --- |
| Sample interval | How often counters are polled (default 1000 ms) |
| Chart window | Seconds of history shown on the live chart |
| Monthly data cap | GB cap for the current month (0 = off) |
| Warn at cap % | Early-warning threshold before the cap |
| High-usage alert | Alert when total speed stays above this many Mbps |
| Per-process hog alert | Alert when one process exceeds this many Mbps |
| Units | Show speeds in bytes (MB/s) or bits (Mbps) |

History lives in `%LOCALAPPDATA%\Kresge\history.db`. Per-minute samples are pruned after 30 days; daily totals are kept indefinitely.

---

## 📡 Hotspot monitoring

The **Hotspot** tab shows the devices *currently* connected to your Windows Mobile Hotspot, with per-device usage. It works in two tiers:

- **Tier 1 — devices (always available).** The connected-device list comes from the WinRT tethering API (`NetworkOperatorTetheringManager.GetTetheringClients`, via `winsdk`) — an exact, live list of who's connected, with each device's reported host name. Vendors are resolved from the MAC's OUI using scapy's bundled IEEE registry. If WinRT is unavailable, it falls back to the ICS neighbor (ARP) table on `192.168.137.0/24`.
- **Tier 2 — per-device usage (opt-in).** Because your PC NATs all hotspot traffic, Windows exposes **no per-client byte counters**. Kresge measures usage by sniffing the hotspot interface with [scapy](https://scapy.net) and attributing bytes to each client IP. This needs the **[Npcap](https://npcap.com)** driver and **Administrator**.

When Npcap is missing, the tab shows an **Install Npcap** button that downloads the official installer from npcap.com and installs it with safe flags (no raw-802.11, which breaks Mobile Hotspot). Kresge never bundles or redistributes Npcap.

**Connected / All devices** toggles between who's online now and a history of every device ever seen, with **lifetime totals** and last-connected times.

**Per-device limits & blocking** — right-click any device to:
- **Set a session data limit** — a per-connection cap. Cross it and you get a notification, and the device is automatically cut off until it reconnects or you clear the limit.
- **Block / unblock** — cut a device off instantly, or restore it.

Double-click a device to give it a **custom name** (handy for a Nintendo Switch or anything reporting "Unknown device"). Phones using **randomized MACs** are labelled as such.

<details>
<summary><b>How blocking works (and its limits)</b></summary>

<br>

Windows has no API to kick a client off the software hotspot. Kresge instead poisons the host's ARP/neighbor entry for the device, so its return traffic is dropped — the device shows *"connected, no internet"*.

It's a **traffic block, not a Wi-Fi deauth**, is fully reversible, and requires Administrator. Blocks are cleared automatically when Kresge exits, so no device is left stuck offline. A device's blocked/limit state is remembered and re-applied when it reconnects while Kresge is running.

</details>

---

## 🧩 How per-process attribution works

Windows doesn't expose exact per-process network byte counters through any unprivileged, cross-platform API. Kresge estimates per-process usage by distributing measured total throughput across each process's active TCP/UDP connections. Great for spotting *which* app is hogging bandwidth; the byte figures are approximate.

Byte-accurate per-process numbers would need an Administrator [ETW](https://learn.microsoft.com/windows/win32/etw/about-event-tracing) kernel session. The estimator is isolated behind `ProcessMonitor` in `kresge/process_monitor.py`, so an exact ETW backend can be slotted in later.

---

## 🗂 Project layout

<details>
<summary><b>Show the file map</b></summary>

<br>

```
main.py                  Entry point
kresge/
  config.py              Settings + byte/rate formatting
  sampler.py             Global throughput from psutil counters
  process_monitor.py     Per-process bandwidth estimation
  hotspot_monitor.py     Hotspot device list + usage orchestration
  hotspot_capture.py     Per-device packet capture (scapy/Npcap, opt-in)
  hotspot_control.py     Per-device blocking / limit enforcement (ARP)
  tethering_clients.py   WinRT connected-client list + device names
  npcap.py               Npcap detection + in-app installer
  database.py            SQLite history (minute + daily) + hotspot devices
  alerts.py              Cap / high-usage / hog alert rules
  engine.py              Timer-driven engine; emits Qt signals
  ui/
    dashboard.py         Live charts, tables, history, hotspot, about, settings
    tools.py             Network tools tab (ping/traceroute/DNS/ports/…)
    theme.py             Light/dark palettes + rounded-widget stylesheets
    tray.py              System-tray icon + notifications
    app.py               Application bootstrap
    icons.py             Loads assets/logo.png (drawn fallback) + sun/moon icons
    assets/logo.png      App / window / tray / taskbar icon
```

</details>

---

<div align="center">

**Built with** Python · PyQt6 · pyqtgraph · psutil · scapy · WinRT · SQLite

Developed by **[dazzledave](https://github.com/dazzledave)**

<a href="https://github.com/dazzledave/kresge/releases/tag/v0.2.0">
  <img alt="Download Kresge" src="https://img.shields.io/badge/Download%20Kresge-v0.2.0-8CB000?style=for-the-badge&logo=windows&logoColor=white&labelColor=24292e">
</a>

</div>
