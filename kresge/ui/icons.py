"""Icons for the app.

The window/tray icon is loaded from ``assets/logo.png`` when present, otherwise
a programmatically drawn glyph is used as a fallback. The sun/moon theme-toggle
icons are always drawn in code.
"""
from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)

_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"


def app_icon() -> QIcon:
    """The application/window/tray icon.

    Loads ``kresge/ui/assets/logo.png`` if it exists; falls back to the drawn
    up/down arrow glyph so the app always has an icon.
    """
    if _LOGO_PATH.exists():
        icon = QIcon(str(_LOGO_PATH))
        if not icon.isNull():
            return icon
    return make_icon()


def make_icon(size: int = 64, down_color: str = "#2ecc71", up_color: str = "#3498db") -> QIcon:
    """Two opposing arrows (download green, upload blue) on a dark rounded tile."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # background tile
    p.setBrush(QBrush(QColor("#1e1e2e")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.18, size * 0.18)

    def arrow(cx: float, color: str, pointing_down: bool) -> None:
        p.setBrush(QBrush(QColor(color)))
        h = size * 0.5
        top = size * 0.25
        shaft_w = size * 0.10
        head_w = size * 0.22
        if pointing_down:
            p.drawRect(int(cx - shaft_w / 2), int(top), int(shaft_w), int(h * 0.55))
            tip = QPolygonF([
                QPointF(cx - head_w / 2, top + h * 0.5),
                QPointF(cx + head_w / 2, top + h * 0.5),
                QPointF(cx, top + h),
            ])
        else:
            p.drawRect(int(cx - shaft_w / 2), int(top + h * 0.45), int(shaft_w), int(h * 0.55))
            tip = QPolygonF([
                QPointF(cx - head_w / 2, top + h * 0.5),
                QPointF(cx + head_w / 2, top + h * 0.5),
                QPointF(cx, top),
            ])
        p.drawPolygon(tip)

    arrow(size * 0.36, down_color, pointing_down=True)
    arrow(size * 0.64, up_color, pointing_down=False)
    p.end()

    return QIcon(pm)


def make_sun_icon(color: str = "#e8e8f0", size: int = 40) -> QIcon:
    """A simple sun: filled disc with radiating rays."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(color)
    cx = cy = size / 2
    r = size * 0.15

    p.setBrush(QBrush(col))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(cx, cy), r, r)

    pen = QPen(col)
    pen.setWidthF(max(1.6, size * 0.05))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    for k in range(8):
        a = k * math.pi / 4
        p.drawLine(
            QPointF(cx + math.cos(a) * r * 1.7, cy + math.sin(a) * r * 1.7),
            QPointF(cx + math.cos(a) * r * 2.4, cy + math.sin(a) * r * 2.4),
        )
    p.end()
    return QIcon(pm)


def make_moon_icon(color: str = "#e8e8f0", size: int = 40) -> QIcon:
    """A crescent moon (a disc with an offset disc subtracted out)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    r = size * 0.30
    cx = size * 0.52
    cy = size * 0.5
    outer = QPainterPath()
    outer.addEllipse(QPointF(cx, cy), r, r)
    inner = QPainterPath()
    inner.addEllipse(QPointF(cx + r * 0.55, cy - r * 0.25), r, r)

    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(outer.subtracted(inner))
    p.end()
    return QIcon(pm)
