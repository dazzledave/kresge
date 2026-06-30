"""Programmatically drawn icons so the app ships with no binary assets.

A small upload/download arrow glyph is painted onto a QPixmap. Used for the
tray icon and the window icon.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap, QPolygonF


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
