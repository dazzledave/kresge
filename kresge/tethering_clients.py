"""Authoritative connected-client list via the Windows WinRT tethering API.

`NetworkOperatorTetheringManager.GetTetheringClients()` returns the devices
*currently* connected to the Mobile Hotspot — unlike the ARP/neighbor table,
which keeps stale entries for devices that have long since disconnected. Each
client carries its MAC, current IP, and the host name the device reported over
DHCP (when it provides one).

Requires the `winsdk` package. Returns ``None`` on any failure (winsdk missing,
hotspot not shareable, older Windows) so the caller can fall back to ARP.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass
class TetheringClient:
    mac: str            # normalized upper-case colon form
    ip: str | None      # current LAN IP, if reported
    name: str | None    # device-reported host name; None if absent/"unknown"


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def read_clients(subnet_prefix: str = "192.168.137.") -> list[TetheringClient] | None:
    """Return the currently-connected hotspot clients, or None if unavailable."""
    try:
        from winsdk.windows.networking.connectivity import NetworkInformation
        from winsdk.windows.networking.networkoperators import (
            NetworkOperatorTetheringManager,
        )
    except Exception:
        return None  # winsdk not installed / importable

    try:
        profile = NetworkInformation.get_internet_connection_profile()
        if profile is None:
            return None
        manager = NetworkOperatorTetheringManager.create_from_connection_profile(profile)

        clients: list[TetheringClient] = []
        for client in manager.get_tethering_clients():
            mac = (client.mac_address or "").replace("-", ":").upper().strip()
            if not mac:
                continue
            ip: str | None = None
            name: str | None = None
            for host in client.host_names:
                value = (host.canonical_name or host.display_name or "").strip()
                if not value:
                    continue
                if _is_ip(value):
                    if ip is None and value.startswith(subnet_prefix):
                        ip = value
                elif name is None and value.lower() != "unknown":
                    name = value
            clients.append(TetheringClient(mac=mac, ip=ip, name=name))
        return clients
    except Exception:
        return None
