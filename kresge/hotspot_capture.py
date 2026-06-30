"""Tier 2: per-device usage via packet capture (npcap + scapy).

Your PC NATs all hotspot traffic, so Windows exposes no per-client byte
counters. The only way to measure each device's usage is to sniff the hotspot
interface and tally bytes per client IP.

This requires **Administrator rights** and the **npcap** driver. When either is
missing, :meth:`HotspotCapture.start` returns ``(False, reason)`` and the app
falls back to Tier 1 (presence only) — capture is never required for the rest
of the hotspot monitor to work.

Scapy is imported lazily (inside methods) so a normal launch that never touches
the hotspot feature doesn't pay its import cost or print its libpcap warning.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from collections import defaultdict

DEFAULT_HOST_IP = "192.168.137.1"   # standard Windows ICS host address


def is_admin() -> bool:
    """True if the current process is elevated (required to sniff)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class HotspotCapture:
    """Background sniffer that accumulates per-IP byte counts.

    Call :meth:`start` once, then :meth:`drain` each sampling tick to get (and
    reset) the bytes seen per client IP since the previous drain.
    """

    def __init__(self, host_ip: str = DEFAULT_HOST_IP) -> None:
        self.host_ip = host_ip
        self._prefix = host_ip.rsplit(".", 1)[0] + "."   # e.g. "192.168.137."
        self._broadcast = self._prefix + "255"
        self._acc: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # ip -> [sent, recv]
        self._lock = threading.Lock()
        self._sniffer = None
        self._ip_layer = None
        self.available = False
        self.status = "not started"

    # -- lifecycle ----------------------------------------------------------

    def _find_iface(self):
        """Locate the scapy interface that owns the hotspot host IP."""
        from scapy.all import conf
        for iface in conf.ifaces.values():
            ips = getattr(iface, "ips", {}) or {}
            v4 = ips.get(4, []) if isinstance(ips, dict) else []
            if self.host_ip in v4:
                return iface
        return None

    def start(self) -> tuple[bool, str]:
        """Begin capturing. Returns (ok, human-readable status/reason)."""
        if not is_admin():
            self.status = "Run Kresge as Administrator to measure per-device usage."
            return False, self.status
        try:
            logging.getLogger("scapy").setLevel(logging.ERROR)  # silence libpcap warning
            from scapy.all import AsyncSniffer, conf
            from scapy.layers.inet import IP

            if not getattr(conf, "use_pcap", False):
                self.status = "Npcap not installed — install it to measure per-device usage."
                return False, self.status

            iface = self._find_iface()
            if iface is None:
                self.status = "Hotspot interface not found (is Mobile Hotspot on?)."
                return False, self.status

            self._ip_layer = IP
            self._sniffer = AsyncSniffer(
                iface=iface, filter="ip", prn=self._on_packet, store=False
            )
            self._sniffer.start()
            self.available = True
            self.status = "Capturing per-device usage."
            return True, self.status
        except Exception as exc:  # npcap quirks, permission, etc.
            self.status = f"Usage capture unavailable: {exc}"
            return False, self.status

    def stop(self) -> None:
        if self._sniffer is not None:
            try:
                self._sniffer.stop()
            except Exception:
                pass
            self._sniffer = None
        self.available = False

    # -- data ---------------------------------------------------------------

    def _on_packet(self, pkt) -> None:
        ip_layer = self._ip_layer
        try:
            if ip_layer not in pkt:
                return
            ip = pkt[ip_layer]
            src, dst = ip.src, ip.dst
            size = len(pkt)
        except Exception:
            return
        with self._lock:
            # A client IP appearing as source = it uploaded; as destination =
            # it downloaded. The host (.1) and broadcast are not devices.
            if src.startswith(self._prefix) and src != self.host_ip and src != self._broadcast:
                self._acc[src][0] += size
            if dst.startswith(self._prefix) and dst != self.host_ip and dst != self._broadcast:
                self._acc[dst][1] += size

    def drain(self) -> dict[str, tuple[int, int]]:
        """Return {client_ip: (sent_bytes, recv_bytes)} since the last drain."""
        with self._lock:
            out = {ip: (v[0], v[1]) for ip, v in self._acc.items()}
            self._acc.clear()
        return out
