"""Enforcement for hotspot per-device limits and manual blocks.

Windows has no API to kick a client off the software hotspot, but because the
PC NATs all client traffic we can cut a device off by poisoning the host's
ARP/neighbor entry for it: point its IP at a bogus MAC so the device's return
traffic is dropped. This is validated to work on this setup. It's a *traffic*
block (device shows "connected, no internet"), fully reversible, and requires
Administrator (which usage capture already needs).

All operations shell out to PowerShell's Net-Neighbor cmdlets and are therefore
run off the UI thread by the caller.
"""
from __future__ import annotations

import subprocess
import threading

from .hotspot_capture import is_admin

_CREATE_NO_WINDOW = 0x08000000
_BOGUS_MAC = "02-00-00-00-00-99"   # locally-administered, nonexistent


class HotspotController:
    def __init__(self, host_ip: str) -> None:
        self.host_ip = host_ip
        self._if_index: int | None = None
        self._applied: dict[str, str] = {}   # mac -> IP currently blackholed
        self._lock = threading.Lock()

    def available(self) -> bool:
        """Blocking needs Administrator to modify the neighbor table."""
        return is_admin()

    # -- low-level ----------------------------------------------------------

    def _run(self, ps: str) -> bool:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _ifindex(self) -> int | None:
        if self._if_index is None:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-NetIPAddress -IPAddress {self.host_ip} "
                     f"-AddressFamily IPv4).InterfaceIndex"],
                    capture_output=True, text=True, timeout=15,
                    creationflags=_CREATE_NO_WINDOW,
                )
                self._if_index = int(r.stdout.strip().splitlines()[0])
            except Exception:
                self._if_index = None
        return self._if_index

    def _poison(self, ip: str) -> None:
        idx = self._ifindex()
        if idx is None:
            return
        self._run(
            f"Remove-NetNeighbor -InterfaceIndex {idx} -IPAddress {ip} "
            f"-Confirm:$false -ErrorAction SilentlyContinue; "
            f"New-NetNeighbor -InterfaceIndex {idx} -IPAddress {ip} "
            f"-LinkLayerAddress {_BOGUS_MAC} -State Permanent "
            f"-ErrorAction SilentlyContinue"
        )

    def _clear(self, ip: str) -> None:
        idx = self._ifindex()
        if idx is None:
            return
        # Removing our static entry lets Windows re-learn the real MAC.
        self._run(
            f"Remove-NetNeighbor -InterfaceIndex {idx} -IPAddress {ip} "
            f"-Confirm:$false -ErrorAction SilentlyContinue"
        )

    # -- high-level ---------------------------------------------------------

    def reconcile(self, desired: dict[str, str]) -> None:
        """Make the applied blocks exactly match `desired` (mac -> current IP).

        Idempotent: only devices whose block state or IP changed cause any
        neighbor-table writes, so the steady state is free.
        """
        with self._lock:
            for mac, ip in desired.items():
                if self._applied.get(mac) != ip:
                    old = self._applied.get(mac)
                    if old and old != ip:
                        self._clear(old)
                    self._poison(ip)
                    self._applied[mac] = ip
            for mac in list(self._applied):
                if mac not in desired:
                    self._clear(self._applied.pop(mac))

    def apply_one(self, mac: str, ip: str) -> None:
        """Immediately block one device (used for instant button feedback)."""
        with self._lock:
            old = self._applied.get(mac)
            if old == ip:
                return
            if old and old != ip:
                self._clear(old)
            self._poison(ip)
            self._applied[mac] = ip

    def clear_one(self, mac: str) -> None:
        with self._lock:
            ip = self._applied.pop(mac, None)
            if ip:
                self._clear(ip)

    def clear_all(self) -> None:
        """Remove every block — called on shutdown so nobody is left cut off."""
        with self._lock:
            for ip in self._applied.values():
                self._clear(ip)
            self._applied.clear()
