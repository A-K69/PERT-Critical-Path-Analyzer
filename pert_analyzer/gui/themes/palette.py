"""
Centralized color palette for the dark professional engineering dashboard.

All color values are defined here. No widget should import raw hex literals.
Change a color once → every consumer updates automatically.
"""

from __future__ import annotations

# ── Background & surfaces ──────────────────────────────────────────
BG = "#0F1117"
SURFACE = "#171A21"
SURFACE_LIGHT = "#1E222B"
ELEVATED = "#242934"
BORDER = "#303642"

# ── Text hierarchy ─────────────────────────────────────────────────
TEXT = "#F1F3F5"
TEXT_SECONDARY = "#9BA3AF"
TEXT_MUTED = "#8A93A0"

# ── Accent / interactive ───────────────────────────────────────────
ACCENT = "#4F8CFF"
ACCENT_HOVER = "#6B9EFF"

# ── Semantic states ────────────────────────────────────────────────
SUCCESS = "#31C48D"
WARNING = "#F2B84B"
DANGER = "#EF5B67"
INFO = "#56B4D8"

# ── Legacy aliases (consumed by existing widgets) ──────────────────
COLORS: dict[str, str] = {
    "bg": BG,
    "surface": SURFACE,
    "surface_light": SURFACE_LIGHT,
    "elevated": ELEVATED,
    "text": TEXT,
    "text_secondary": TEXT_SECONDARY,
    "muted": TEXT_MUTED,
    "accent": ACCENT,
    "accent_hover": ACCENT_HOVER,
    "success": SUCCESS,
    "danger": DANGER,
    "warning": WARNING,
    "info": INFO,
    "border": BORDER,
}

# ── Status language (standardized labels) ─────────────────────────
STATUS_ANALYZING = "ANALYZING"
STATUS_PRELIMINARY = "PRELIMINARY"
STATUS_REVIEW_REQUIRED = "REVIEW REQUIRED"
STATUS_REVIEW_IN_PROGRESS = "REVIEW IN PROGRESS"
STATUS_VALIDATING = "VALIDATING"
STATUS_VALIDATED = "VALIDATED"
STATUS_CPM_READY = "CPM READY"
STATUS_FINAL_RESULTS = "FINAL RESULTS"
STATUS_BLOCKED = "BLOCKED"
STATUS_ERROR = "ERROR"

# Status label → (glyph, color) for consistent rendering
STATUS_STYLE: dict[str, tuple[str, str]] = {
    STATUS_ANALYZING: ("\u25CF", ACCENT),
    STATUS_PRELIMINARY: ("\u25C8", ACCENT),
    STATUS_REVIEW_REQUIRED: ("\u26A0", WARNING),
    STATUS_REVIEW_IN_PROGRESS: ("\u26A0", WARNING),
    STATUS_VALIDATING: ("\u25CF", ACCENT),
    STATUS_VALIDATED: ("\u2713", SUCCESS),
    STATUS_CPM_READY: ("\u2713", SUCCESS),
    STATUS_FINAL_RESULTS: ("\u2713", SUCCESS),
    STATUS_BLOCKED: ("\u2717", DANGER),
    STATUS_ERROR: ("\u2717", DANGER),
}

# ── Network canvas (Results dashboard) ─────────────────────────────
NETWORK_COLORS: dict[str, str] = {
    "canvas": "#0D0F14",
    "node_fill": SURFACE_LIGHT,
    "node_fill_critical": "#1C2A1C",
    "node_border": BORDER,
    "node_border_critical": WARNING,
    "node_text": TEXT,
    "node_text_muted": TEXT_MUTED,
    "node_selected": ACCENT,
    "edge": "#4A5568",
    "edge_critical": WARNING,
    "path_highlight": ACCENT,
}
