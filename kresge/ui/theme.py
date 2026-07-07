"""Light/dark theming.

The app's base look is driven by a Qt palette (applied with the Fusion style so
it renders consistently regardless of the OS theme), plus a small scoped
stylesheet for the custom cards/buttons on the History and Hotspot tabs.

`DOWN_COLOR`, `UP_COLOR`, and `ACCENT` are theme-independent — they read well on
both backgrounds.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette

DOWN_COLOR = "#2ecc71"
UP_COLOR = "#3498db"
ACCENT = "#5c7cff"

DARK = {
    "window": "#1a1a26", "panel": "#252539", "border": "#34344c",
    "text": "#e8e8f0", "bright": "#f0f0f8", "subtext": "#8c8ca6",
    "plot_bg": "#1e1e2e", "axis": "#44445c", "axis_text": "#9090a8",
    "hover": "#2e2e46", "base": "#20202e", "alt_base": "#25253a",
    "legend": "#9090a8", "icon": "#e8e8f0",
}

LIGHT = {
    "window": "#f2f2f7", "panel": "#ffffff", "border": "#d3d3e0",
    "text": "#20202c", "bright": "#15151f", "subtext": "#66667e",
    "plot_bg": "#ffffff", "axis": "#c4c4d2", "axis_text": "#66667e",
    "hover": "#e8e8f2", "base": "#ffffff", "alt_base": "#f5f5fa",
    "legend": "#66667e", "icon": "#20202c",
}

THEMES = {"dark": DARK, "light": LIGHT}


def build_palette(c: dict) -> QPalette:
    """A full QPalette for the given theme colors (use with the Fusion style)."""
    p = QPalette()
    text = QColor(c["text"])
    p.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, QColor(c["base"]))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(c["alt_base"]))
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, QColor(c["panel"]))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["panel"]))
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["subtext"]))
    disabled = QColor(c["subtext"])
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def global_qss(c: dict) -> str:
    """App-wide rounding for tables, headers, group boxes, and input boxes so
    every framed element matches the rounded cards. Applied to the main window."""
    return f"""
    QTableView {{
        border: 1px solid {c['border']}; border-radius: 8px;
        background: {c['base']}; gridline-color: {c['border']};
    }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: {c['alt_base']}; color: {c['subtext']};
        padding: 5px 8px; border: none; border-bottom: 1px solid {c['border']};
    }}
    QHeaderView::section:first {{ border-top-left-radius: 8px; }}
    QHeaderView::section:last  {{ border-top-right-radius: 8px; }}
    QTableCornerButton::section {{
        background: {c['alt_base']}; border: none; border-top-left-radius: 8px;
    }}
    QGroupBox {{
        border: 1px solid {c['border']}; border-radius: 10px; margin-top: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {c['subtext']};
    }}
    QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox, QAbstractSpinBox {{
        border: 1px solid {c['border']}; border-radius: 6px;
        padding: 3px 6px; background: {c['base']};
    }}
    """


def scoped_qss(c: dict) -> str:
    """Stylesheet for the custom cards/segmented-buttons/cap-bar (by objectName)."""
    return f"""
    QFrame#histCard {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px;
    }}
    QLabel#cardTitle {{ color: {c['subtext']}; font-size: 11px; font-weight: 600; }}
    QLabel#cardValue {{ color: {c['bright']}; font-size: 23px; font-weight: 700; }}
    QLabel#cardSub   {{ font-size: 12px; }}
    QLabel#histLegend {{ font-size: 12px; }}
    QPushButton#segBtn {{
        background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
        padding: 6px 20px; font-weight: 600;
    }}
    QPushButton#segBtn:hover {{ background: {c['hover']}; }}
    QPushButton#segBtn:checked {{
        background: {ACCENT}; color: #ffffff; border-color: {ACCENT};
    }}
    QProgressBar#capBar {{
        border: 1px solid {c['border']}; border-radius: 8px; background: {c['panel']};
        text-align: center; color: {c['text']}; min-height: 22px;
    }}
    QPushButton#refreshBtn {{
        background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 6px; padding: 6px 16px;
    }}
    QPushButton#refreshBtn:hover {{ background: {c['hover']}; }}
    """
