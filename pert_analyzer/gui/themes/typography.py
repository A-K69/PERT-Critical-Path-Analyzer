"""
Centralized typography system.

Font family, weights, and named (family, size, weight) tuples consumed by
QFont constructors throughout the GUI.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont

# ── Family ─────────────────────────────────────────────────────────
# Platform-native fonts so every OS renders with a first-choice family
# instead of relying on QSS fallback. Segoe UI ships with Windows and
# covers Latin + Arabic; Noto Sans Arabic covers Linux desktops.
_FONT_FAMILIES = {
    "win32": "Segoe UI",
    "darwin": "Helvetica Neue",
    "linux": "Noto Sans Arabic",
}
FONT_FAMILY = _FONT_FAMILIES.get(sys.platform, "Noto Sans Arabic")

# ── Named tuples: (family, size_px, weight) ────────────────────────
DISPLAY_FONT = (FONT_FAMILY, 28, QFont.Weight.Bold)
TITLE_FONT = (FONT_FAMILY, 16, QFont.Weight.DemiBold)
SUBTITLE_FONT = (FONT_FAMILY, 12, QFont.Weight.Normal)
LABEL_FONT = (FONT_FAMILY, 13, QFont.Weight.Normal)
BODY_FONT = (FONT_FAMILY, 13, QFont.Weight.Normal)
BODY_SMALL_FONT = (FONT_FAMILY, 11, QFont.Weight.Normal)
CAPTION_FONT = (FONT_FAMILY, 11, QFont.Weight.Normal)
MUTED_FONT = (FONT_FAMILY, 11, QFont.Weight.Normal)
STATUS_FONT = (FONT_FAMILY, 12, QFont.Weight.Normal)
TABLE_HEADER_FONT = (FONT_FAMILY, 11, QFont.Weight.DemiBold)
KPI_FONT = (FONT_FAMILY, 26, QFont.Weight.Bold)
BUTTON_FONT = (FONT_FAMILY, 12, QFont.Weight.Medium)
