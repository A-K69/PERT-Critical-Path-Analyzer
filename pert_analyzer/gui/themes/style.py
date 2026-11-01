"""
GUI stylesheet builder.

Imports the design-system token modules (palette, typography, spacing) and
builds a single application-wide QSS.  All legacy names (COLORS, TITLE_FONT
…) are re-exported from the canonical modules so existing widget imports
continue to work without changes.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

# ── canonical re-exports (backward compatible) ─────────────────────
from pert_analyzer.gui.themes.palette import COLORS, NETWORK_COLORS
from pert_analyzer.gui.themes.typography import (
    DISPLAY_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    SUBTITLE_FONT,
    TITLE_FONT,
    FONT_FAMILY,
    KPI_FONT,
    BUTTON_FONT,
)
from pert_analyzer.gui.themes.spacing import (
    RADIUS_SM,
    RADIUS_MD,
    RADIUS_LG,
    SIDEBAR_WIDTH,
    HEADER_HEIGHT,
    LG,
    XL,
    XXL,
    XXXL,
    SM,
    XS,
)
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    ACCENT_HOVER,
    BG,
    BORDER,
    DANGER,
    ELEVATED,
    INFO,
    SUCCESS,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_SECONDARY,
    TEXT_MUTED,
    WARNING,
    qrgba,
)


def _build_stylesheet() -> str:
    """Return the full application QSS built from design-system tokens."""
    return f"""
        /* ── Global defaults ────────────────────────────────── */
        /* NOTE: no global font-size here — a 13px rule silently overrode
           every constructor font (titles, display sizes, KPIs) and flattened
           the whole typography system to a single size. */
        QWidget {{
            background-color: {BG};
            color: {TEXT};
            font-family: '{FONT_FAMILY}', 'Segoe UI', sans-serif;
        }}

        /* Display-leaf widgets never paint their own background.  Without
           this, every QLabel inherited the app background color and painted
           a dark box behind each text line (banners, panels, cards).  Labels
           that intentionally carry a background set it in their own
           stylesheet, which always wins over the app-level rule. */
        QLabel, QCheckBox, QRadioButton {{
            background: transparent;
        }}

        /* Content widgets placed inside a scroll area also stay transparent
           so the surrounding page/card background shows through instead of
           a dark viewport-coloured rectangle. */
        QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}

        /* ── Push buttons ───────────────────────────────────── */
        QPushButton {{
            background-color: {SURFACE_LIGHT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 7px 18px;
            min-height: 26px;
        }}
        QPushButton:hover {{
            background-color: {ELEVATED};
            border-color: {ACCENT};
        }}
        QPushButton:pressed {{
            background-color: {ACCENT};
            color: #ffffff;
        }}
        QPushButton:disabled {{
            color: {TEXT_MUTED};
            border-color: {SURFACE};
            background-color: {SURFACE};
        }}
        QPushButton#primary {{
            background-color: {ACCENT};
            color: #ffffff;
            border: none;
            font-weight: 600;
        }}
        QPushButton#primary:hover {{
            background-color: {ACCENT_HOVER};
        }}
        QPushButton#primary:pressed {{
            background-color: #3A7AEE;
        }}
        QPushButton#primary:disabled {{
            background-color: {SURFACE};
            color: {TEXT_MUTED};
        }}
        QPushButton#danger {{
            background-color: {DANGER};
            color: #ffffff;
            border: none;
            font-weight: 600;
        }}
        QPushButton#danger:hover {{
            background-color: #E04A56;
        }}
        QPushButton#danger:disabled {{
            background-color: {SURFACE};
            color: {TEXT_MUTED};
        }}
        QPushButton#ghost {{
            background-color: transparent;
            color: {TEXT};
            border: 1px solid {BORDER};
        }}
        QPushButton#ghost:hover {{
            background-color: {SURFACE_LIGHT};
        }}
        QPushButton#ghost:pressed {{
            background-color: {SURFACE_LIGHT};
            border-color: {ACCENT};
        }}
        QPushButton#ghost:disabled {{
            color: {TEXT_MUTED};
            border-color: {SURFACE};
            background-color: transparent;
        }}
        QPushButton#secondary {{
            background-color: transparent;
            color: {ACCENT};
            border: 1px solid {qrgba(ACCENT, 102)};
            font-weight: 600;
        }}
        QPushButton#secondary:hover {{
            background-color: {qrgba(ACCENT, 20)};
            border-color: {ACCENT};
        }}
        QPushButton#secondary:pressed {{
            background-color: {qrgba(ACCENT, 34)};
        }}
        QPushButton#secondary:disabled {{
            color: {TEXT_MUTED};
            border-color: {SURFACE};
            background-color: transparent;
        }}
        QPushButton#success {{
            background-color: {SUCCESS};
            color: #ffffff;
            border: none;
            font-weight: 600;
        }}
        QPushButton#success:hover {{
            background-color: #2BB37E;
        }}
        QPushButton#success:pressed {{
            background-color: #27A672;
        }}
        QPushButton#success:disabled {{
            background-color: {SURFACE};
            color: {TEXT_MUTED};
        }}

        /* ── Stacked widget ─────────────────────────────────── */
        QStackedWidget {{
            border: none;
            background: transparent;
        }}

        /* ── Status bar ─────────────────────────────────────── */
        QStatusBar {{
            background-color: {SURFACE};
            color: {TEXT_SECONDARY};
            border-top: 1px solid {BORDER};
            font-size: 11px;
        }}

        /* ── Menu bar ───────────────────────────────────────── */
        QMenuBar {{
            background-color: {SURFACE};
            color: {TEXT};
            border-bottom: 1px solid {BORDER};
        }}
        QMenuBar::item:selected {{
            background-color: {SURFACE_LIGHT};
        }}
        QMenu {{
            background-color: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px;
        }}
        QMenu::item:selected {{
            background-color: {ACCENT};
            color: #ffffff;
        }}

        /* ── Scroll areas ───────────────────────────────────── */
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: {SURFACE};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {BORDER};
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {TEXT_MUTED};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background: {SURFACE};
            height: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {BORDER};
            border-radius: 4px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {TEXT_MUTED};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        /* ── Lists / tables ─────────────────────────────────── */
        QListWidget {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD}px;
            padding: 4px;
        }}
        QListWidget::item {{
            padding: 6px 8px;
            border-radius: {RADIUS_SM}px;
        }}
        QListWidget::item:selected {{
            background-color: {ACCENT};
            color: #ffffff;
        }}
        QListWidget::item:hover:!selected {{
            background-color: {SURFACE_LIGHT};
        }}

        QTableWidget {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD}px;
            gridline-color: {BORDER};
            alternate-background-color: {SURFACE_LIGHT};
        }}
        QTableWidget::item {{
            padding: 5px 8px;
        }}
        QTableWidget::item:selected {{
            background-color: {qrgba(ACCENT, 51)};
        }}
        QHeaderView::section {{
            background-color: {ELEVATED};
            color: {TEXT_SECONDARY};
            border: none;
            border-bottom: 1px solid {BORDER};
            padding: 6px 8px;
            font-size: 11px;
            font-weight: 600;
        }}

        /* ── Tab widget ─────────────────────────────────────── */
        QTabWidget::pane {{
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD}px;
            background: transparent;
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {SURFACE};
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER};
            border-bottom: none;
            border-top-left-radius: {RADIUS_SM}px;
            border-top-right-radius: {RADIUS_SM}px;
            padding: 7px 18px;
            margin-right: 2px;
            font-size: 12px;
        }}
        QTabBar::tab:selected {{
            background-color: {SURFACE_LIGHT};
            color: {TEXT};
            font-weight: 600;
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {ELEVATED};
        }}

        /* ── Line edits / text edits ────────────────────────── */
        QLineEdit, QPlainTextEdit, QTextEdit {{
            background-color: {SURFACE_LIGHT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 6px 8px;
            selection-background-color: {qrgba(ACCENT, 102)};
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
            border-color: {ACCENT};
        }}

        /* ── Combo box ──────────────────────────────────────── */
        QComboBox {{
            background-color: {SURFACE_LIGHT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 5px 10px;
            min-height: 22px;
        }}
        QComboBox:hover {{
            border-color: {ACCENT};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            color: {TEXT};
            selection-background-color: {ACCENT};
        }}

        /* ── Splitter ───────────────────────────────────────── */
        QSplitter::handle {{
            background-color: {BORDER};
        }}
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        QSplitter::handle:vertical {{
            height: 2px;
        }}

        /* ── Tool tips ──────────────────────────────────────── */
        QToolTip {{
            background-color: {ELEVATED};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 4px 8px;
            font-size: 11px;
        }}

        /* ── Progress bar ───────────────────────────────────── */
        QProgressBar {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px;
            text-align: center;
            color: {TEXT};
            height: 8px;
        }}
        QProgressBar::chunk {{
            background-color: {ACCENT};
            border-radius: {RADIUS_SM}px;
        }}
    """


def apply_theme(app: QApplication) -> None:
    """Apply the dark professional engineering stylesheet."""
    app.setStyleSheet(_build_stylesheet())
