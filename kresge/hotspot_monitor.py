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
import threading
import time
from dataclasses import dataclass

import psutil

from .database import Database
from .hotspot_capture import DEFAULT_HOST_IP, HotspotCapture, is_admin
from .tethering_clients import TetheringClient, read_clients

# In ARP-fallback mode (no WinRT), a device is considered offline if it hasn't
# appeared in the neighbor table within this many seconds. In WinRT mode the
# connected set is authoritative, so this isn't used.
OFFLINE_AFTER_S = 60.0

_CREATE_NO_WINDOW = 0x08000000  # don't flash a console when calling PowerShell


@dataclass
class HotspotDevice:
    mac: str
    ip: str
    vendor: str
    name: str | None            # user-assigned custom name (persisted)
    online: bool
    auto_name: str | None = None  # device-reported host name (live, not persisted)
    sent_rate: float = 0.0      # bytes/sec uploaded by the device (live)
    recv_rate: float = 0.0      # bytes/sec downloaded to the device (live)
    sent_total: int = 0         # cumulative bytes uploaded
    recv_total: int = 0         # cumulative bytes downloaded
    first_seen: float = 0.0
    last_seen: float = 0.0

    def label(self) -> str:
        """What to show in the UI: custom name > reported name > fallback."""
        return self.name or self.auto_name or "Unknown device"


def normalize_mac(mac: str) -> str:
    """Canonical upper-case colon form, e.g. 'a4-38-cc-...' -> 'A4:38:CC:...'."""
    return mac.replace("-", ":").upper().strip()


def lookup_vendor(mac: str) -> str:
    """Vendor name from a MAC via the IEEE OUI registry (scapy's bundled DB)."""
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
        self._last_persist = 0.0

        # Client discovery (WinRT call or PowerShell ARP read) is too slow for
        # the UI thread, so a daemon thread refreshes this snapshot in the
        # background and sample() (UI thread) just reads it — never blocking.
        # `authoritative` is True when the snapshot came from the WinRT tethering
        # API (an exact connected-device list) vs the ARP fallback.
        self._lock = threading.Lock()
        self._snapshot: list[TetheringClient] = []
        self._authoritative = False
        self._poll_stop = threading.Event()

        self._load_persisted()

        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="hotspot-neighbors", daemon=True
        )
        self._poll_thread.start()

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

    def _poll_loop(self) -> None:
        """Background: refresh the client snapshot off the UI thread.

        Prefers the WinRT tethering API (exact connected list + names); falls
        back to the ARP neighbor table if WinRT is unavailable.
        """
        while not self._poll_stop.is_set():
            snapshot: list[TetheringClient] = []
            authoritative = True
            try:
                if self.is_active():
                    clients = read_clients(self._prefix)
                    if clients is not None:
                        snapshot = clients
                    else:
                        # Fallback: ARP gives MAC + IP but no names.
                        authoritative = False
                        snapshot = [
                            TetheringClient(mac=mac, ip=ip, name=None)
                            for ip, mac in self._read_neighbors()
                        ]
            except Exception:
                snapshot, authoritative = [], True
            with self._lock:
                self._snapshot = snapshot
                self._authoritative = authoritative
            # Sleep, but wake immediately on shutdown.
            self._poll_stop.wait(self._refresh_interval)

    def _consume_snapshot(self, now: float) -> tuple[set[str], bool]:
        """Fold the latest background snapshot into the device map (UI thread).

        Returns (currently-present MACs, authoritative?) for sample() to decide
        which devices count as connected.
        """
        with self._lock:
            snapshot = list(self._snapshot)
            authoritative = self._authoritative

        present: set[str] = set()
        for client in snapshot:
            mac = client.mac
            present.add(mac)
            if client.ip:
                self._ip_to_mac[client.ip] = mac
            dev = self._devices.get(mac)
            if dev is None:
                dev = HotspotDevice(
                    mac=mac, ip=client.ip or "", vendor=lookup_vendor(mac),
                    name=None, auto_name=client.name, online=True,
                    first_seen=now, last_seen=now,
                )
                self._devices[mac] = dev
            else:
                if client.ip:
                    dev.ip = client.ip
                if client.name:
                    dev.auto_name = client.name
                dev.last_seen = now
                dev.online = True
                if not dev.first_seen:
                    dev.first_seen = now
        return present, authoritative

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

        # Fold in the latest client snapshot (refreshed off-thread).
        present, authoritative = self._consume_snapshot(now)

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

        # Decide who is connected. With WinRT the present set is exact; with the
        # ARP fallback, fall back to a last-seen timeout.
        for dev in self._devices.values():
            if authoritative:
                dev.online = dev.mac in present
            elif now - dev.last_seen > OFFLINE_AFTER_S:
                dev.online = False

        # Persist active devices (throttled).
        persist_due = now - self._last_persist >= 5.0
        if persist_due:
            for dev in self._devices.values():
                if dev.last_seen:
                    self._persist(dev)
            self._last_persist = now

        # Only currently-connected devices are shown; history stays in the DB.
        return sorted(
            (d for d in self._devices.values() if d.online),
            key=lambda d: (d.sent_rate + d.recv_rate, d.sent_total + d.recv_total),
            reverse=True,
        )

    def rename_device(self, mac: str, name: str) -> None:
        """Assign (or clear) a user-defined name for a device, and persist it."""
        dev = self._devices.get(normalize_mac(mac))
        if dev is not None:
            dev.name = name.strip() or None
            self._persist(dev)

    def shutdown(self) -> None:
        self._poll_stop.set()
        self._poll_thread.join(timeout=2.0)
        self.capture.stop()
        for dev in self._devices.values():
            if dev.last_seen:
                self._persist(dev)
