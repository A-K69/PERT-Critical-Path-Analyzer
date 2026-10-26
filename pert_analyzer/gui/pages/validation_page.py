"""
Validation Center: graph validation status, issues, and CPM readiness.

The page is a pure presentation/orchestration layer. It reads the
candidate produced by the backend review pipeline (``ReviewedGraphCandidate``)
and its ``GraphValidationResult``; it never re-implements validation, CPM,
or graph-model logic. Issue severity and review-target mapping live in
``gui.reviews.validation_presentation``.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.reviews.categories import ReviewCategory
from pert_analyzer.gui.reviews.validation_presentation import (
    ValidationSeverity,
    present_issues,
    review_target,
)
from pert_analyzer.gui.reviews.widgets import BadgeLabel, SectionCard
from pert_analyzer.gui.session import ValidationCenterStatus
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    DANGER,
    SUCCESS,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    WARNING,
)
from pert_analyzer.gui.themes.spacing import RADIUS_SM
from pert_analyzer.gui.themes.typography import (
    BODY_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    SUBTITLE_FONT,
    TITLE_FONT,
)

_STATUS_META = {
    ValidationCenterStatus.VALID: (
        "\u2713",
        SUCCESS,
        "VALIDATED",
        "The reviewed graph is valid and ready for CPM analysis.",
    ),
    ValidationCenterStatus.INVALID: (
        "\u2717",
        DANGER,
        "INVALID",
        "The reviewed graph contains blocking issues. Resolve them, then revalidate.",
    ),
    ValidationCenterStatus.BLOCKED_REVIEW: (
        "\u26a0",
        WARNING,
        "REVIEW REQUIRED",
        "The review is incomplete or has pending changes. Finish the review and apply decisions.",
    ),
    ValidationCenterStatus.NOT_AVAILABLE: (
        "\u2014",
        TEXT_MUTED,
        "NOT AVAILABLE",
        "No reviewed graph available yet. Complete analysis and review first.",
    ),
}

_BANNER_PADDING = 4  # alpha 0x14 for banner background tint


def _rgba(hex_color: str, alpha: int) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def _blocked_review_details(session: Any) -> str:
    """Synthesize a concrete list of pending items blocking validation."""
    review_session = getattr(session, "review_session", None)
    if review_session is None:
        return ""
    parts = []
    for dur in getattr(review_session, "durations", []) or []:
        status = getattr(dur, "status", None)
        status_value = getattr(status, "value", status)
        if str(status_value).lower() != "pending":
            continue
        aid = getattr(dur, "activity_id", None) or ""
        current = getattr(dur, "current_duration", None)
        if current is not None and current <= 0:
            parts.append(f"Activity '{aid or '?'}' has an invalid duration.")
    for act in getattr(review_session, "activities", []) or []:
        status = getattr(act, "status", None)
        status_value = getattr(status, "value", status)
        if str(status_value).lower() != "pending":
            continue
        if not (getattr(act, "corrected_activity_id", None) or
                getattr(act, "proposed_activity_id", None)):
            parts.append(
                f"Activity at node "
                f"'{getattr(act, 'geometric_node_id', '?')}' is missing an ID."
            )
    return " ".join(parts[:2])


class ValidationPage(QWidget):
    """Interactive Validation Center for the current reviewed graph."""

    revalidate_requested = Signal()
    continue_requested = Signal()
    back_to_review = Signal()
    go_analyze = Signal()
    review_issue_requested = Signal(object, str)  # (ReviewCategory, item key)

    _EMPTY = 0
    _WORKSPACE = 1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._session: Any = None
        self._busy: bool = False
        self._issues: list[Any] = []
        self._current_issue: Any = None
        self._current_target: Optional[Tuple[ReviewCategory, str]] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(8)

        title = QLabel("Validation Center")
        title.setFont(QFont(*TITLE_FONT))
        title.setStyleSheet(f"color: {TEXT};")
        root.addWidget(title)

        subtitle = QLabel("Validate the reviewed graph before running CPM.")
        subtitle.setFont(QFont(*SUBTITLE_FONT))
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY};")
        root.addWidget(subtitle)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_empty_state())       # 0
        self._stack.addWidget(self._build_workspace())         # 1

        self._show_empty(
            "No project analyzed. Run an analysis on the Analyze Diagram page.",
            show_analyze=True,
            show_review=False,
            show_revalidate=False,
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addStretch()

        self._empty_label = QLabel("")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setFont(QFont(*BODY_FONT))
        self._empty_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self._empty_label)

        self._readiness_label = QLabel("")
        self._readiness_label.setWordWrap(True)
        self._readiness_label.setTextFormat(Qt.TextFormat.RichText)
        self._readiness_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readiness_label.setFont(QFont(*MUTED_FONT))
        self._readiness_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._readiness_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._go_analyze_btn = QPushButton("Go to Analyze Diagram")
        self._go_analyze_btn.setObjectName("primary")
        self._go_analyze_btn.clicked.connect(self.go_analyze.emit)
        layout.addWidget(self._go_analyze_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._go_review_btn = QPushButton("Go to Review")
        self._go_review_btn.clicked.connect(self.back_to_review.emit)
        layout.addWidget(self._go_review_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._empty_revalidate_btn = QPushButton("Revalidate")
        self._empty_revalidate_btn.clicked.connect(self.revalidate_requested.emit)
        layout.addWidget(self._empty_revalidate_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        return widget

    def _build_workspace(self) -> QWidget:
        """Workspace wrapped in a scroll area.

        The workspace content (banner + summary cards + issues + details +
        action bar) is taller than the central area at common window sizes.
        Without a scroll area the outer layout squeezed flexible rows until
        checklist and detail labels collapsed to zero height and their text
        vanished.  Scrolling keeps every row at its natural height.
        """
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host_layout.addWidget(scroll)

        workspace = QWidget()
        scroll.setWidget(workspace)
        outer = QVBoxLayout(workspace)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # --- status banner -------------------------------------------------
        self._status_banner = QFrame()
        banner_layout = QHBoxLayout(self._status_banner)
        banner_layout.setContentsMargins(16, 14, 16, 14)
        banner_layout.setSpacing(12)

        self._status_icon = QLabel("")
        self._status_icon.setFont(QFont(*TITLE_FONT))
        banner_layout.addWidget(self._status_icon)

        banner_text = QVBoxLayout()
        banner_text.setSpacing(2)
        self._status_label = QLabel("")
        self._status_label.setFont(QFont(*STATUS_FONT))
        banner_text.addWidget(self._status_label)
        self._status_hint = QLabel("")
        self._status_hint.setWordWrap(True)
        self._status_hint.setFont(QFont(*LABEL_FONT))
        banner_text.addWidget(self._status_hint)
        banner_layout.addLayout(banner_text, stretch=1)
        outer.addWidget(self._status_banner)

        # --- second row: graph summary + cpm readiness ----------------------
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(12)

        self._summary_card = SectionCard("Graph Summary")
        self._stat_cells: dict[str, QLabel] = {}
        stat_host = QWidget()
        stat_host.setStyleSheet("background: transparent; border: none;")
        stat_grid = QGridLayout(stat_host)
        stat_grid.setContentsMargins(0, 0, 0, 0)
        stat_grid.setHorizontalSpacing(12)
        stat_grid.setVerticalSpacing(12)
        stats_meta = [
            ("activities", "Activities"),
            ("dependencies", "Dependencies"),
            ("nodes", "Nodes"),
            ("components", "Connected components"),
            ("cycles", "Cycles"),
            ("pending_reviews", "Pending reviews"),
        ]
        for index, (key, caption) in enumerate(stats_meta):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            value = QLabel("\u2014")
            value.setFont(QFont(*STATUS_FONT))
            value.setStyleSheet(f"color: {TEXT};")
            cell.addWidget(value)
            label = QLabel(caption)
            label.setFont(QFont(*MUTED_FONT))
            label.setStyleSheet(f"color: {TEXT_MUTED};")
            cell.addWidget(label)
            wrapper = QWidget()
            wrapper.setStyleSheet("background: transparent; border: none;")
            wrapper.setLayout(cell)
            stat_grid.addWidget(wrapper, index // 3, index % 3)
            self._stat_cells[key] = value

        self._tech_btn = QPushButton("Technical details")
        self._tech_btn.setObjectName("ghost")
        self._tech_btn.setCheckable(True)
        self._tech_btn.setChecked(False)
        self._tech_btn.toggled.connect(self._toggle_technical)

        self._technical = QWidget()
        self._technical.setStyleSheet("background: transparent; border: none;")
        technical_layout = QVBoxLayout(self._technical)
        technical_layout.setContentsMargins(0, 0, 0, 0)
        technical_layout.setSpacing(4)
        self._tech_rows: dict[str, QLabel] = {}
        for key in ("graph_status", "blocking_issues", "warnings"):
            label = QLabel("")
            label.setWordWrap(True)
            label.setFont(QFont(*MUTED_FONT))
            technical_layout.addWidget(label)
            self._tech_rows[key] = label
        self._technical.setVisible(False)

        self._summary_card.add_widget(stat_host)

        # Validation checklist
        self._checklist_card = SectionCard("Validation Checklist")
        self._checklist_items: dict[str, QLabel] = {}
        checklist_host = QWidget()
        checklist_host.setStyleSheet("background: transparent; border: none;")
        checklist_layout = QVBoxLayout(checklist_host)
        checklist_layout.setContentsMargins(0, 0, 0, 0)
        checklist_layout.setSpacing(4)
        for key, caption in (
            ("activities_valid", "Activities valid"),
            ("durations_valid", "Durations valid"),
            ("dependencies_resolved", "Dependencies resolved"),
            ("no_duplicates", "No duplicate dependencies"),
            ("no_self_loops", "No self-loops"),
            ("connected", "Graph connected"),
            ("acyclic", "Graph acyclic"),
            ("cpm_ready", "CPM ready"),
        ):
            row = QHBoxLayout()
            row.setSpacing(6)
            glyph = QLabel("\u25CB")
            glyph.setFont(QFont(*BODY_FONT))
            glyph.setFixedWidth(18)
            lbl = QLabel(caption)
            lbl.setFont(QFont(*BODY_FONT))
            lbl.setStyleSheet(f"color: {TEXT_MUTED};")
            row.addWidget(glyph)
            row.addWidget(lbl)
            row.addStretch()
            wrapper = QWidget()
            wrapper.setStyleSheet("background: transparent; border: none;")
            wrapper.setLayout(row)
            checklist_layout.addWidget(wrapper)
            self._checklist_items[key] = (glyph, lbl)
        self._checklist_card.add_widget(checklist_host)
        middle.addWidget(self._checklist_card, stretch=1)
        self._summary_card.add_widget(self._tech_btn)
        self._summary_card.add_widget(self._technical)
        middle.addWidget(self._summary_card, stretch=2)

        self._cpm_card = SectionCard("CPM Readiness")
        self._cpm_rows: dict[str, QLabel] = {}
        for key in ("cpm_gate", "project_duration", "critical_paths"):
            label = QLabel("")
            label.setWordWrap(True)
            label.setFont(QFont(*MUTED_FONT))
            self._cpm_card.add_widget(label)
            self._cpm_rows[key] = label
        middle.addWidget(self._cpm_card, stretch=1)
        outer.addLayout(middle)

        # --- third row: validation issues (large) ---------------------------
        self._issues_card = SectionCard("Validation Issues")
        self._issue_list = QListWidget()
        self._issue_list.setAlternatingRowColors(False)
        self._issue_list.setStyleSheet(
            f"QListWidget {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px;}}"
            f"QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {BORDER};}}"
            f"QListWidget::item:selected {{ background-color: {ACCENT}; color: white;}}"
            f"QListWidget::item:hover:!selected {{ background-color: {SURFACE_LIGHT};}}"
        )
        self._issue_list.currentRowChanged.connect(self._on_issue_selected)
        self._issues_card.add_widget(self._issue_list)
        outer.addWidget(self._issues_card, stretch=3)

        # --- bottom row: scrollable issue details ---------------------------
        self._detail_card = SectionCard("Issue Details")
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        detail_scroll.setMinimumHeight(120)
        detail_body = QWidget()
        detail_body.setStyleSheet("background: transparent; border: none;")
        detail_layout = QVBoxLayout(detail_body)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)

        self._detail_title = QLabel("")
        self._detail_title.setWordWrap(True)
        self._detail_title.setFont(QFont(*LABEL_FONT))
        detail_layout.addWidget(self._detail_title)

        self._badge_row = QWidget()
        self._badge_row.setStyleSheet("background: transparent; border: none;")
        badge_layout = QHBoxLayout(self._badge_row)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setSpacing(8)
        self._severity_badge = BadgeLabel("", "INFO")
        badge_layout.addWidget(self._severity_badge)
        self._blocking_label = QLabel("")
        self._blocking_label.setFont(QFont(*MUTED_FONT))
        badge_layout.addWidget(self._blocking_label)
        badge_layout.addStretch()
        self._source_label = QLabel("")
        self._source_label.setFont(QFont(*MUTED_FONT))
        self._source_label.setStyleSheet(f"color: {TEXT_MUTED};")
        badge_layout.addWidget(self._source_label)
        detail_layout.addWidget(self._badge_row)

        self._detail_message = QLabel("")
        self._detail_message.setWordWrap(True)
        self._detail_message.setFont(QFont(*LABEL_FONT))
        detail_layout.addWidget(self._detail_message)

        self._detail_elements = QLabel("")
        self._detail_elements.setWordWrap(True)
        self._detail_elements.setFont(QFont(*MUTED_FONT))
        self._detail_elements.setStyleSheet(f"color: {TEXT_MUTED};")
        detail_layout.addWidget(self._detail_elements)

        self._detail_explanation = QLabel("")
        self._detail_explanation.setWordWrap(True)
        self._detail_explanation.setFont(QFont(*MUTED_FONT))
        detail_layout.addWidget(self._detail_explanation)

        self._detail_action = QLabel("")
        self._detail_action.setWordWrap(True)
        self._detail_action.setFont(QFont(*LABEL_FONT))
        detail_layout.addWidget(self._detail_action)

        self._target_hint = QLabel("")
        self._target_hint.setWordWrap(True)
        self._target_hint.setFont(QFont(*MUTED_FONT))
        self._target_hint.setStyleSheet(f"color: {TEXT_MUTED};")
        detail_layout.addWidget(self._target_hint)

        self._review_issue_btn = QPushButton("Open in Review")
        self._review_issue_btn.clicked.connect(self._on_review_issue)
        detail_layout.addWidget(self._review_issue_btn)

        detail_scroll.setWidget(detail_body)
        self._detail_card.add_widget(detail_scroll)
        outer.addWidget(self._detail_card)

        # --- bottom action bar ---------------------------------------------
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 4, 0, 0)
        bar.setSpacing(10)

        self._back_btn = QPushButton("Back to Review")
        self._back_btn.clicked.connect(self.back_to_review.emit)
        bar.addWidget(self._back_btn)

        self._feedback = QLabel("")
        self._feedback.setWordWrap(True)
        self._feedback.setFont(QFont(*MUTED_FONT))
        bar.addWidget(self._feedback, stretch=1)

        self._revalidate_btn = QPushButton("Revalidate")
        self._revalidate_btn.clicked.connect(self.revalidate_requested.emit)
        bar.addWidget(self._revalidate_btn)

        self._continue_btn = QPushButton("Continue to Results")
        self._continue_btn.setObjectName("primary")
        self._continue_btn.clicked.connect(self.continue_requested.emit)
        bar.addWidget(self._continue_btn)

        outer.addLayout(bar)
        return host

    # ------------------------------------------------------------------
    # Refresh API
    # ------------------------------------------------------------------

    def refresh(self, session: Any) -> None:
        """Rebuild the page from the current session state."""
        self._session = session
        if self._busy:
            return
        self._render()

    def _render(self) -> None:
        session = self._session
        if session is None or session.workflow is None:
            self._set_readiness(session)
            self._show_empty(
                "No project analyzed. Run an analysis on the Analyze Diagram page.",
                show_analyze=True,
                show_review=False,
                show_revalidate=False,
            )
            return

        if session.validation_status == ValidationCenterStatus.NOT_AVAILABLE:
            pending = session.pending_review_total()
            if pending > 0:
                message = (
                    f"{pending} review item(s) still need attention before "
                    "the reviewed graph can be validated."
                )
            else:
                message = (
                    "No reviewed graph is available yet. "
                    "Complete the review and apply decisions to validate."
                )
            self._set_readiness(session)
            self._show_empty(
                message,
                show_analyze=False,
                show_review=True,
                show_revalidate=(pending == 0),
            )
            return

        self._stack.setCurrentIndex(self._WORKSPACE)
        self._render_status(session)
        self._render_summary(session)
        self._render_stats(session)
        self._render_cpm(session)
        self._populate_issues(session)
        self._sync_buttons()
        self._feedback.setText("")
        self._feedback.setStyleSheet(f"color: {TEXT_MUTED};")

    def _show_empty(
        self,
        message: str,
        show_analyze: bool,
        show_review: bool,
        show_revalidate: bool,
    ) -> None:
        self._empty_label.setText(message)
        self._go_analyze_btn.setVisible(show_analyze)
        self._go_review_btn.setVisible(show_review)
        self._empty_revalidate_btn.setVisible(show_revalidate)
        self._go_analyze_btn.setEnabled(not self._busy)
        self._go_review_btn.setEnabled(not self._busy)
        self._empty_revalidate_btn.setEnabled(not self._busy and show_revalidate)
        self._stack.setCurrentIndex(self._EMPTY)

    def _set_readiness(self, session: Any) -> None:
        """At-a-glance readiness strip shown in the empty state."""
        if session is None:
            self._readiness_label.setText("")
            return
        workflow = getattr(session, "workflow", None)
        status = session.validation_status
        pending = session.pending_review_total()
        done = session.review_item_total()

        rows = []
        if workflow is None:
            rows.append(("\u25CB", TEXT_MUTED, "Analysis complete"))
        else:
            rows.append(("\u2713", SUCCESS, "Analysis complete"))
        if workflow is None:
            rows.append(("\u25CB", TEXT_MUTED, "Review"))
        elif pending == 0:
            rows.append(("\u2713", SUCCESS, f"Review resolved ({done} items)"))
        else:
            rows.append(("\u26a0", WARNING, f"Review in progress ({pending} pending)"))
        if status == ValidationCenterStatus.VALID:
            rows.append(("\u2713", SUCCESS, "Graph valid and CPM-ready"))
        elif status == ValidationCenterStatus.INVALID:
            rows.append(("\u2717", DANGER, "Graph invalid - fix blocking issues"))
        elif status == ValidationCenterStatus.BLOCKED_REVIEW:
            rows.append(("\u26a0", WARNING, "Validation blocked by review"))
        else:
            rows.append(("\u25CB", TEXT_MUTED, "Graph not validated yet"))

        parts = [
            f'<font color="{color}">{glyph}</font> {label}'
            for glyph, color, label in rows
        ]
        self._readiness_label.setText("  \u00b7  ".join(parts))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_status(self, session: Any) -> None:
        status = session.validation_status
        icon, color, label, hint = _STATUS_META[status]
        self._status_icon.setText(icon)
        self._status_icon.setStyleSheet(f"color: {color};")
        self._status_label.setText(label)
        self._status_label.setStyleSheet(f"color: {color};")
        self._status_hint.setText(hint)

        if status == ValidationCenterStatus.BLOCKED_REVIEW:
            pending = session.pending_review_total()
            if pending > 0:
                self._status_hint.setText(
                    f"{pending} review item(s) are still pending. "
                    "Finish the review and apply decisions to continue."
                )
            details = _blocked_review_details(session)
            if details:
                self._status_hint.setText(
                    self._status_hint.text() + " " + details
                )
        elif status == ValidationCenterStatus.INVALID:
            blocking = len(getattr(session.validation_result, "errors", []) or [])
            self._status_hint.setText(
                f"{blocking} blocking validation issue(s) found. "
                "Resolve them in the Review Center, then revalidate."
            )

        banner_style = (
            f"QFrame {{ background-color: {_rgba(color, 22)};"
            f" border: 1px solid {color}; border-radius: 8px; }}"
        )
        self._status_banner.setStyleSheet(banner_style)

    def _toggle_technical(self, checked: bool) -> None:
        self._technical.setVisible(checked)

    def _render_summary(self, session: Any) -> None:
        result = session.validation_result
        errors = len(getattr(result, "errors", []) or [])
        warnings = len(getattr(result, "warnings", []) or [])
        status_text = getattr(result, "status", None)
        rows = {
            "graph_status": f"<b>Graph status:</b> {_value(status_text)}",
            "blocking_issues": f"<b>Blocking issues:</b> {errors}",
            "warnings": f"<b>Warnings:</b> {warnings}",
        }
        for key, text in rows.items():
            self._tech_rows[key].setText(text)

    def _render_stats(self, session: Any) -> None:
        candidate = session.current_candidate
        result = session.validation_result
        graph = getattr(candidate, "graph", None)
        activities = dependencies = nodes = None
        if graph is not None:
            activities = getattr(graph, "activity_count", None)
            dependencies = getattr(graph, "dependency_count", None)
            nodes = getattr(graph, "node_count", None)
        acyclic = bool(getattr(result, "is_acyclic", True))
        components = getattr(result, "component_count", 1)
        pending = session.pending_review_total()

        values = {
            "activities": (_as_text(activities), TEXT),
            "dependencies": (_as_text(dependencies), TEXT),
            "nodes": (_as_text(nodes), TEXT),
            "components": (_as_text(components), TEXT),
            "cycles": ("No" if acyclic else "Yes", SUCCESS if acyclic else DANGER),
            "pending_reviews": (_as_text(pending), WARNING if pending else TEXT_MUTED),
        }
        for key, (text, color) in values.items():
            label = self._stat_cells[key]
            label.setText(text)
            label.setStyleSheet(f"color: {color};")

        # Update validation checklist
        self._render_checklist(session)

    def _render_checklist(self, session: Any) -> None:
        """Update the validation checklist based on actual graph state."""
        candidate = session.current_candidate
        result = session.validation_result
        graph = getattr(candidate, "graph", None)
        is_valid = bool(getattr(result, "is_valid", False))
        acyclic = bool(getattr(result, "is_acyclic", True))
        components = getattr(result, "component_count", 0)
        errors = getattr(result, "errors", []) or []
        pending = session.pending_review_total()
        gate = getattr(candidate, "cpm_gate", None)
        gate_value = getattr(gate, "value", gate) if gate is not None else None

        # Determine checklist state
        checks = {
            "activities_valid": bool(graph and getattr(graph, "activity_count", 0) > 0),
            "durations_valid": not any(
                getattr(e, "code", "") == "invalid_duration" for e in errors
            ),
            "dependencies_resolved": pending == 0,
            "no_duplicates": not any(
                getattr(e, "code", "") == "duplicate_edge" for e in errors
            ),
            "no_self_loops": not any(
                getattr(e, "code", "") == "self_loop" for e in errors
            ),
            "connected": components <= 1,
            "acyclic": acyclic,
            "cpm_ready": gate_value == "RUNNABLE",
        }

        for key, passed in checks.items():
            glyph, lbl = self._checklist_items[key]
            if passed:
                glyph.setText("\u2713")
                glyph.setStyleSheet(f"color: {SUCCESS};")
                lbl.setStyleSheet(f"color: {TEXT};")
            else:
                glyph.setText("\u2717")
                glyph.setStyleSheet(f"color: {DANGER};")
                lbl.setStyleSheet(f"color: {TEXT_MUTED};")

    def _render_cpm(self, session: Any) -> None:
        candidate = session.current_candidate
        gate = getattr(candidate, "cpm_gate", None)
        gate_value = getattr(gate, "value", gate) if gate is not None else None
        duration = getattr(candidate, "cpm_project_duration", None)
        paths = getattr(candidate, "critical_path_count", None)
        rows = {
            "cpm_gate": f"<b>CPM gate:</b> {gate_value if gate_value else 'UNKNOWN'}",
            "project_duration": (
                f"<b>Project duration:</b> {duration if duration is not None else 'Not computed'}"
            ),
            "critical_paths": (
                f"<b>Critical paths:</b> {paths if paths is not None else 'Not computed'}"
            ),
        }
        for key, text in rows.items():
            self._cpm_rows[key].setText(text)

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def _populate_issues(self, session: Any) -> None:
        self._issues = present_issues(session.validation_result)
        self._issue_list.blockSignals(True)
        self._issue_list.clear()
        for index, presented in enumerate(self._issues):
            marker = "\u25cf" if presented.severity == ValidationSeverity.WARNING else "\u2717"
            text = (
                f"{marker}  [{presented.code}]  {presented.title}\n"
                f"     {presented.message}"
            )
            item = QListWidgetItem(text)
            color = (
                WARNING
                if presented.severity == ValidationSeverity.WARNING
                else DANGER
            )
            item.setForeground(QBrush(QColor(color)))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._issue_list.addItem(item)
        self._issue_list.blockSignals(False)
        if self._issues:
            self._issue_list.setCurrentRow(0)
        else:
            self._clear_issue_detail()

    def _on_issue_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._issues):
            self._clear_issue_detail()
            return
        self._render_issue_detail(self._issues[row])

    def _clear_issue_detail(self) -> None:
        self._current_issue = None
        self._current_target = None
        self._detail_title.setText("No issues detected")
        self._severity_badge.set_status("INFO", "OK")
        self._blocking_label.setText("")
        self._blocking_label.setStyleSheet("")
        self._source_label.setText("")
        self._detail_message.setText("The reviewed graph passed validation.")
        self._detail_elements.setText("")
        self._detail_explanation.setText("")
        self._detail_action.setText("")
        self._target_hint.setText("")
        self._review_issue_btn.setEnabled(False)

    def _render_issue_detail(self, presented: Any) -> None:
        self._current_issue = presented
        is_error = presented.severity == ValidationSeverity.ERROR

        self._detail_title.setText(presented.title)
        self._severity_badge.set_status(
            "WARNING" if not is_error else "ERROR",
            "Blocking" if is_error else "Warning",
        )
        blocking_color = DANGER if is_error else WARNING
        self._blocking_label.setText(
            "Must be resolved before CPM can run" if is_error else "Non-blocking warning"
        )
        self._blocking_label.setStyleSheet(f"color: {blocking_color};")
        self._source_label.setText(f"Code: {presented.code}  \u00b7  Source: {presented.source}")

        elements = ", ".join(str(e) for e in presented.elements) or "(none)"
        self._detail_message.setText(presented.message or presented.title)
        self._detail_elements.setText(f"Affected: {elements}")
        self._detail_explanation.setText(presented.explanation)
        self._detail_action.setText(presented.action)

        target = None
        if self._session is not None:
            review_session = getattr(self._session, "review_session", None)
            target = review_target(presented.issue, review_session)
        self._current_target = target
        if target is not None:
            category, key = target
            self._target_hint.setText(
                f"Review item: {_category_label(category)}"
            )
            self._review_issue_btn.setEnabled(True)
        else:
            self._target_hint.setText(
                "No matching review item was found for this issue."
            )
            self._review_issue_btn.setEnabled(False)

    def _on_review_issue(self) -> None:
        target = self._current_target
        if target is None or self._busy:
            return
        category, key = target
        self.review_issue_requested.emit(category, key)

    # ------------------------------------------------------------------
    # Feedback / busy / buttons
    # ------------------------------------------------------------------

    def _sync_buttons(self) -> None:
        session = self._session
        status = (
            session.validation_status
            if session is not None
            else ValidationCenterStatus.NOT_AVAILABLE
        )
        revalidate_allowed = (
            not self._busy
            and session is not None
            and session.workflow is not None
            and session.current_candidate is not None
            and session.pending_review_total() == 0
        )
        self._revalidate_btn.setEnabled(revalidate_allowed)
        self._back_btn.setEnabled(not self._busy)
        self._continue_btn.setEnabled(
            not self._busy and status == ValidationCenterStatus.VALID
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (
            self._go_analyze_btn,
            self._go_review_btn,
            self._empty_revalidate_btn,
            self._back_btn,
            self._revalidate_btn,
            self._continue_btn,
            self._review_issue_btn,
            self._issue_list,
        ):
            button.setEnabled(not busy)
        self._sync_buttons()
        self._review_issue_btn.setEnabled(not busy and self._current_target is not None)

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def stack_index(self) -> int:
        return self._stack.currentIndex()

    @property
    def current_issues(self) -> list[Any]:
        return list(self._issues)

    def set_feedback(self, text: str, error: bool = False) -> None:
        color = DANGER if error else SUCCESS
        self._feedback.setText(text)
        self._feedback.setStyleSheet(f"color: {color};")


def _category_label(category: ReviewCategory) -> str:
    return {
        ReviewCategory.ACTIVITIES: "Activities",
        ReviewCategory.DEPENDENCIES: "Dependencies",
        ReviewCategory.DURATIONS: "Durations",
    }.get(category, category.value)


def _value(status: Any) -> str:
    return getattr(status, "value", status) if status is not None else "n/a"


def _as_text(value: Any) -> str:
    return str(value) if value is not None else "n/a"