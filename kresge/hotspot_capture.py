"""Tier 2: per-device usage via packet capture (npcap + scapy).

Your PC NATs all hotspot traffic, so Windows exposes no per-client byte
counters. The only way to measure each device's usage is to sniff the hotspot
interface and tally bytes per client IP.

This requires **Administrator rights** and the **npcap** driver. When either is
missing, :meth:`HotspotCapture.start` returns ``(False, reason)`` and the app
falls back to Tier 1 (presence only) — capture is never required for the rest
of the hotspot monitor to work.

To keep up at high throughput we read **raw frames** (``recv_raw``) and parse
just the source/destination IP out of the header bytes ourselves, instead of
letting scapy dissect every packet into a full object (and re-serialize it via
``len(pkt)``). That per-packet Python work is what caused npcap to drop packets
and under-count fast devices.

Scapy is imported lazily (inside methods) so a normal launch that never touches
the hotspot feature doesn't pay its import cost or print its libpcap warning.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
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
        self._sock = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
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
            from scapy.all import conf

            if not getattr(conf, "use_pcap", False):
                self.status = "Npcap not installed — install it to measure per-device usage."
                return False, self.status

            iface = self._find_iface()
            if iface is None:
                self.status = "Hotspot interface not found (is Mobile Hotspot on?)."
                return False, self.status

            # Raw L2 listen socket (BPF filter to IPv4 only), read without
            # dissection in a background thread.
            self._sock = conf.L2listen(iface=iface, filter="ip")
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._capture_loop, name="hotspot-capture", daemon=True
            )
            self._thread.start()
            self.available = True
            self.status = "Capturing per-device usage."
            return True, self.status
        except Exception as exc:  # npcap quirks, permission, etc.
            self.status = f"Usage capture unavailable: {exc}"
            return False, self.status

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()   # unblocks recv_raw() in the loop
            except Exception:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.available = False

    # -- data ---------------------------------------------------------------

    def _capture_loop(self) -> None:
        sock = self._sock
        while not self._stop.is_set():
            try:
                data = sock.recv_raw()   # (LinkLayer, raw_bytes, timestamp)
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.02)   # avoid a busy-spin on transient errors
                continue
            raw = data[1] if isinstance(data, tuple) and len(data) >= 2 else None
            if raw:
                self._count(raw)

    def _count(self, raw: bytes) -> None:
        """Parse the src/dst IPv4 addresses out of a raw Ethernet frame and add
        its size to the right client's counters. Frames are IPv4 (BPF filtered)."""
        if len(raw) < 34:
            return
        off = 14   # Ethernet II header
        if raw[12] == 0x81 and raw[13] == 0x00:   # 802.1Q VLAN tag
            off = 18
            if len(raw) < off + 20:
                return
        si, di = off + 12, off + 16   # IPv4 header: src at +12, dst at +16
        src = f"{raw[si]}.{raw[si + 1]}.{raw[si + 2]}.{raw[si + 3]}"
        dst = f"{raw[di]}.{raw[di + 1]}.{raw[di + 2]}.{raw[di + 3]}"
        size = len(raw)
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
