"""Hotspot monitor: device presence (Tier 1) + per-device usage (Tier 2).

Tier 1 enumerates devices connected to the Windows Mobile Hotspot by reading
the neighbor (ARP) table for the ICS subnet — no admin, no drivers. Each device
is identified by MAC, with a best-effort vendor name from its OUI prefix.

Tier 2 merges in live byte counts from :class:`HotspotCapture` (packet sniffing)
to compute per-device upload/download rates and cumulative totals, which are
persisted so usage survives restarts.

Everything is gated on the hotspot actually being active, so when Mobile
Hotspot is off this does no work beyond a cheap interface check.
"""
from __future__ import annotations

import csv
import subprocess
import time
from dataclasses import dataclass

import psutil

from .database import Database
from .hotspot_capture import DEFAULT_HOST_IP, HotspotCapture, is_admin

# A device is considered offline if it has neither sent traffic nor appeared in
# the neighbor table within this many seconds.
OFFLINE_AFTER_S = 60.0

_CREATE_NO_WINDOW = 0x08000000  # don't flash a console when calling PowerShell

# Small built-in OUI → vendor map for common consumer devices. Best-effort; a
# miss just yields a generic label. Keys are the first 3 MAC octets, upper-case.
_OUI: dict[str, str] = {
    "A4:38:CC": "Apple", "AC:92:32": "Apple", "F0:18:98": "Apple",
    "3C:5A:B4": "Google", "DA:A1:19": "Google",
    "AC:5F:3E": "Samsung", "B4:3A:28": "Samsung",
    "00:1A:11": "Google", "F8:E0:79": "Motorola",
    "00:15:5D": "Microsoft (Hyper-V)", "00:50:F2": "Microsoft",
    "EC:B5:FA": "Xiaomi", "28:6C:07": "Xiaomi",
    "00:E0:4C": "Realtek", "08:00:27": "VirtualBox",
}


@dataclass
class HotspotDevice:
    mac: str
    ip: str
    vendor: str
    name: str | None
    online: bool
    sent_rate: float = 0.0      # bytes/sec uploaded by the device (live)
    recv_rate: float = 0.0      # bytes/sec downloaded to the device (live)
    sent_total: int = 0         # cumulative bytes uploaded
    recv_total: int = 0         # cumulative bytes downloaded
    first_seen: float = 0.0
    last_seen: float = 0.0


def normalize_mac(mac: str) -> str:
    """Canonical upper-case colon form, e.g. 'a4-38-cc-...' -> 'A4:38:CC:...'."""
    return mac.replace("-", ":").upper().strip()


def lookup_vendor(mac: str) -> str:
    """Best-effort vendor name from a MAC address."""
    mac = normalize_mac(mac)
    parts = mac.split(":")
    if len(parts) < 3:
        return "Unknown"
    # Locally-administered bit (0x02 in the first octet) => randomized/private MAC.
    try:
        if int(parts[0], 16) & 0x02:
            return "Private (randomized MAC)"
    except ValueError:
        return "Unknown"
    oui = ":".join(parts[:3])
    if oui in _OUI:
        return _OUI[oui]
    # Fall back to scapy's bundled manufacturer DB if it's available.
    try:
        from scapy.all import conf
        manuf = getattr(conf, "manufdb", None)
        if manuf is not None:
            name = manuf._get_manuf(mac)
            # scapy echoes the MAC prefix back when it has no match; reject that.
            if name and ":" not in name and name.upper() not in mac:
                return name
    except Exception:
        pass
    return f"Unknown ({oui})"


class HotspotMonitor:
    def __init__(
        self, db: Database, host_ip: str = DEFAULT_HOST_IP,
        refresh_interval: float = 6.0,
    ) -> None:
        self.db = db
        self.host_ip = host_ip
        self._prefix = host_ip.rsplit(".", 1)[0] + "."
        self._broadcast = self._prefix + "255"
        self._refresh_interval = refresh_interval

        self.capture = HotspotCapture(host_ip)
        self.capture_ok = False
        # Human-readable status surfaced in the UI (admin/npcap/off hints).
        self.status = "Administrator + Npcap required for usage." if not is_admin() \
            else "Usage capture will start when the hotspot is active."

        self._devices: dict[str, HotspotDevice] = {}   # keyed by MAC
        self._ip_to_mac: dict[str, str] = {}
        self._last_refresh = 0.0
        self._last_persist = 0.0

        self._load_persisted()

    # -- persistence --------------------------------------------------------

    def _load_persisted(self) -> None:
        for (mac, name, vendor, last_ip, first_seen, last_seen,
             sent_bytes, recv_bytes) in self.db.get_hotspot_devices():
            self._devices[mac] = HotspotDevice(
                mac=mac, ip=last_ip or "", vendor=vendor or "Unknown",
                name=name, online=False, sent_total=sent_bytes or 0,
                recv_total=recv_bytes or 0, first_seen=first_seen or 0.0,
                last_seen=last_seen or 0.0,
            )
            if last_ip:
                self._ip_to_mac[last_ip] = mac

    def _persist(self, dev: HotspotDevice) -> None:
        self.db.upsert_hotspot_device(
            mac=dev.mac, name=dev.name, vendor=dev.vendor, last_ip=dev.ip,
            first_seen=dev.first_seen, last_seen=dev.last_seen,
            sent_bytes=dev.sent_total, recv_bytes=dev.recv_total,
        )

    # -- presence -----------------------------------------------------------

    def is_active(self) -> bool:
        """True if the hotspot host IP is currently assigned to an interface."""
        try:
            for addrs in psutil.net_if_addrs().values():
                for a in addrs:
                    if a.family == 2 and a.address == self.host_ip:  # AF_INET
                        return True
        except Exception:
            pass
        return False

    def _read_neighbors(self) -> list[tuple[str, str]]:
        """Return [(ip, mac)] of valid devices in the hotspot subnet."""
        cmd = [
            "powershell", "-NoProfile", "-Command",
            # All segments are f-strings so brace escaping ({{ }}) is uniform.
            f"Get-NetNeighbor -AddressFamily IPv4 | "
            f"Where-Object {{ $_.IPAddress -like '{self._prefix}*' -and "
            f"$_.State -ne 'Unreachable' }} | "
            f"Select-Object IPAddress,LinkLayerAddress | ConvertTo-Csv -NoTypeInformation",
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW,
            ).stdout
        except Exception:
            return []

        devices: list[tuple[str, str]] = []
        for row in csv.DictReader(out.splitlines()):
            ip = (row.get("IPAddress") or "").strip()
            mac = normalize_mac(row.get("LinkLayerAddress") or "")
            if not ip or not mac or len(mac.split(":")) != 6:
                continue
            if mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
                continue
            if ip in (self.host_ip, self._broadcast):
                continue
            devices.append((ip, mac))
        return devices

    def _refresh_presence(self, now: float) -> None:
        self._last_refresh = now
        for ip, mac in self._read_neighbors():
            self._ip_to_mac[ip] = mac
            dev = self._devices.get(mac)
            if dev is None:
                dev = HotspotDevice(
                    mac=mac, ip=ip, vendor=lookup_vendor(mac), name=None,
                    online=True, first_seen=now, last_seen=now,
                )
                self._devices[mac] = dev
            else:
                dev.ip = ip
                if not dev.first_seen:
                    dev.first_seen = now

    # -- sampling -----------------------------------------------------------

    def sample(self, interval: float) -> list[HotspotDevice]:
        """One tick: fold capture bytes into devices and return them sorted.

        Returns an empty list when the hotspot is off.
        """
        now = time.time()

        if not self.is_active():
            self.capture.stop()
            self.capture_ok = False
            self.status = "Mobile Hotspot is off."
            for dev in self._devices.values():
                dev.online = False
                dev.sent_rate = dev.recv_rate = 0.0
            return []

        # Hotspot is on — make sure capture is running (best effort).
        if not self.capture_ok:
            self.capture_ok, self.status = self.capture.start()

        drained = self.capture.drain() if self.capture_ok else {}

        # Refresh presence on its cadence, or immediately if traffic appears for
        # an IP we don't yet have a MAC for.
        need_refresh = now - self._last_refresh >= self._refresh_interval
        if not need_refresh and any(ip not in self._ip_to_mac for ip in drained):
            need_refresh = True
        if need_refresh:
            self._refresh_presence(now)

        # Reset live rates; fold in this interval's captured bytes.
        for dev in self._devices.values():
            dev.sent_rate = dev.recv_rate = 0.0

        interval = max(interval, 1e-6)
        for ip, (sent, recv) in drained.items():
            mac = self._ip_to_mac.get(ip)
            if mac is None:
                continue  # unknown device this tick; picked up next refresh
            dev = self._devices[mac]
            dev.sent_rate = sent / interval
            dev.recv_rate = recv / interval
            dev.sent_total += sent
            dev.recv_total += recv
            dev.last_seen = now
            dev.online = True

        # Mark stale devices offline and persist active ones (throttled).
        persist_due = now - self._last_persist >= 5.0
        for dev in self._devices.values():
            if now - dev.last_seen > OFFLINE_AFTER_S:
                dev.online = False
            if persist_due and dev.last_seen:
                self._persist(dev)
        if persist_due:
            self._last_persist = now

        return sorted(
            self._devices.values(),
            key=lambda d: (d.online, d.sent_rate + d.recv_rate,
                           d.sent_total + d.recv_total),
            reverse=True,
        )

    def shutdown(self) -> None:
        self.capture.stop()
        for dev in self._devices.values():
            if dev.last_seen:
                self._persist(dev)
