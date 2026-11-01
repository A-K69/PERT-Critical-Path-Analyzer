"""
Results Dashboard (Phase 4): real CPM results page.

Replaces the placeholder with an executive Overview, a Qt-native Network
canvas, an Activities table with detail, and a Critical Paths view.

Readiness is gated on: analyzed workflow + applied candidate + valid graph +
open CPM gate + existing CPM result. When not ready the page explains why
and offers navigation. The backend CPM result is authoritative; this page
never recomputes ES/EF/LS/LF, floats, paths, or duration.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.locale import UiLanguage, widget_language
from pert_analyzer.gui.session import ValidationCenterStatus
from pert_analyzer.gui.results.activities import ActivitiesTab
from pert_analyzer.gui.results.critical_paths import CriticalPathsTab
from pert_analyzer.gui.results.data import (
    CPM_BLOCKED,
    GRAPH_INVALID,
    NO_ANALYSIS,
    RESULT_UNAVAILABLE,
    REVIEW_REQUIRED,
    describe_ready,
    extract,
    extract_pert,
)
from pert_analyzer.gui.results.formatting import format_duration
from pert_analyzer.gui.results.network import NetworkTab
from pert_analyzer.gui.results.overview import OverviewTab
from pert_analyzer.gui.results.pert import PertTab
from pert_analyzer.gui.results.preview import DetectedPreviewTab
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    DANGER,
    SUCCESS,
    SURFACE_LIGHT,
    TEXT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    WARNING,
    qrgba,
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

_PLACEHOLDER_TOOLTIP = "Coming in a later phase"
_EXPORT_TOOLTIP = "Export the current results (PDF, Excel, JSON, CSV)"
_REPORT_TOOLTIP = "Generate a detailed project report"


def _rgba(hex_color: str, alpha: int) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def _count_activities(graph: Any) -> int:
    if graph is None:
        return 0
    activities = getattr(graph, "activities", None)
    return len(activities) if activities else 0


def _count_dependencies(graph: Any) -> int:
    if graph is None:
        return 0
    dependencies = getattr(graph, "dependencies", None)
    return len(dependencies) if dependencies else 0


class ResultsPage(QWidget):
    """Full analytical Results dashboard."""

    go_review = Signal()
    go_validation = Signal()
    calculate_requested = Signal()
    pert_run_requested = Signal()
    export_requested = Signal()
    report_requested = Signal()

    _EMPTY = 0
    _DASHBOARD = 1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._session: Any = None
        self._busy: bool = False
        self._data: Any = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 12, 8)
        root.setSpacing(7)

        title = QLabel("Results")
        title.setFont(QFont(*TITLE_FONT))
        title.setStyleSheet(f"color: {TEXT};")
        root.addWidget(title)

        subtitle = QLabel("Verified schedule intelligence from the reviewed graph.")
        subtitle.setFont(QFont(*SUBTITLE_FONT))
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY};")
        root.addWidget(subtitle)

        root.addWidget(self._build_context_header())

        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_empty_state())   # 0
        self._stack.addWidget(self._build_dashboard())     # 1

        self._show_not_ready(NO_ANALYSIS)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_context_header(self) -> QWidget:
        """Build the shared context surface for every Results entry mode."""
        frame = QFrame()
        frame.setObjectName("resultsContextHeader")
        frame.setStyleSheet(
            f"QFrame#resultsContextHeader {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px; }}"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        self._context_mode_label = QLabel("ENTRY: —")
        self._context_mode_label.setFont(QFont(*STATUS_FONT))
        self._context_mode_label.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        layout.addWidget(self._context_mode_label)

        self._context_source_label = QLabel("Source: —")
        self._context_source_label.setFont(QFont(*MUTED_FONT))
        self._context_source_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._context_source_label, stretch=1)

        self._context_trust_label = QLabel("TRUST: NOT READY")
        self._context_trust_label.setFont(QFont(*STATUS_FONT))
        self._context_trust_label.setStyleSheet(f"color: {WARNING}; font-weight: 600;")
        layout.addWidget(self._context_trust_label)

        self._context_review_label = QLabel("Review: —")
        self._context_review_label.setFont(QFont(*MUTED_FONT))
        self._context_review_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._context_review_label)
        return frame

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addStretch()

        self._not_ready_heading = QLabel("RESULTS NOT READY")
        self._not_ready_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._not_ready_heading.setFont(QFont(*LABEL_FONT))
        self._not_ready_heading.setStyleSheet(f"color: {WARNING};")
        layout.addWidget(self._not_ready_heading)

        self._empty_status_banner = QFrame()
        status_layout = QHBoxLayout(self._empty_status_banner)
        status_layout.setContentsMargins(16, 10, 16, 10)
        status_layout.setSpacing(10)
        self._empty_status_icon = QLabel("!")
        self._empty_status_icon.setFont(QFont(*TITLE_FONT))
        status_layout.addWidget(self._empty_status_icon)
        status_text = QVBoxLayout()
        status_text.setSpacing(2)
        self._empty_status_label = QLabel("")
        self._empty_status_label.setFont(QFont(*STATUS_FONT))
        status_text.addWidget(self._empty_status_label)
        self._empty_status_hint = QLabel("")
        self._empty_status_hint.setWordWrap(True)
        self._empty_status_hint.setFont(QFont(*MUTED_FONT))
        status_text.addWidget(self._empty_status_hint)
        status_layout.addLayout(status_text, stretch=1)
        layout.addWidget(self._empty_status_banner)

        self._empty_label = QLabel("")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setFont(QFont(*BODY_FONT))
        self._empty_label.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(self._empty_label)

        self._preliminary_card = self._build_preliminary_card()
        layout.addWidget(self._preliminary_card)

        self._detected_preview = DetectedPreviewTab()
        layout.addWidget(self._detected_preview, stretch=1)

        self._readiness_label = QLabel("")
        self._readiness_label.setWordWrap(True)
        self._readiness_label.setTextFormat(Qt.TextFormat.RichText)
        self._readiness_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readiness_label.setFont(QFont(*MUTED_FONT))
        self._readiness_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._readiness_label, alignment=Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Resolve the issue below, then come back to Results.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(QFont(*MUTED_FONT))
        hint.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(hint)

        self._progress_label = QLabel("")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_label.setFont(QFont(*MUTED_FONT))
        self._progress_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self._progress_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        self._go_review_btn = QPushButton("Continue Review")
        self._go_review_btn.clicked.connect(self.go_review)
        self._go_validation_btn = QPushButton("Open Validation")
        self._go_validation_btn.clicked.connect(self.go_validation)
        self._calculate_btn = QPushButton("Calculate Results")
        self._calculate_btn.setToolTip(
            "Run the existing CPM service for this valid graph"
        )
        self._calculate_btn.clicked.connect(self._on_calculate_clicked)
        actions.addWidget(self._go_review_btn)
        actions.addWidget(self._go_validation_btn)
        actions.addWidget(self._calculate_btn)
        actions.addStretch()
        layout.addLayout(actions)

        layout.addStretch()
        self._empty_hint = hint
        return widget

    def _build_preliminary_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("preliminaryCard")
        card.setStyleSheet(
            f"QFrame#preliminaryCard {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 12, 18, 12)
        inner.setSpacing(4)

        title = QLabel("PRELIMINARY")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont(*MUTED_FONT))
        title.setStyleSheet(f"color: {WARNING}; font-weight: 600;")
        inner.addWidget(title)

        caption = QLabel("Detected from image \u2014 may change after review.")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setFont(QFont(*MUTED_FONT))
        caption.setStyleSheet(f"color: {TEXT_MUTED};")
        inner.addWidget(caption)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(18)
        self._preliminary_values: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in (
            ("activities", "Activities detected"),
            ("dependencies", "Dependencies detected"),
            ("review_items", "Review items"),
            ("graph_status", "Graph status"),
            ("cpm_readiness", "CPM readiness"),
        ):
            value = QLabel("\u2014")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setFont(QFont(*LABEL_FONT))
            value.setStyleSheet(f"color: {TEXT};")
            cap = QLabel(label)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setFont(QFont(*MUTED_FONT))
            cap.setStyleSheet(f"color: {TEXT_MUTED};")
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(value)
            col.addWidget(cap)
            cell = QWidget()
            cell.setLayout(col)
            kpi_row.addWidget(cell, stretch=1)
            self._preliminary_values[key] = (value, cap)

        inner.addLayout(kpi_row)

        self._priority_label = QLabel("")
        self._priority_label.setWordWrap(True)
        self._priority_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._priority_label.setFont(QFont(*MUTED_FONT))
        self._priority_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        inner.addWidget(self._priority_label)

        self._provenance_card_label = QLabel("")
        self._provenance_card_label.setWordWrap(True)
        self._provenance_card_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._provenance_card_label.setFont(QFont(*MUTED_FONT))
        self._provenance_card_label.setStyleSheet(f"color: {TEXT_MUTED};")
        inner.addWidget(self._provenance_card_label)

        self._review_trace_label = QLabel("")
        self._review_trace_label.setWordWrap(True)
        self._review_trace_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._review_trace_label.setFont(QFont(*MUTED_FONT))
        self._review_trace_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        inner.addWidget(self._review_trace_label)

        self._review_breakdown_label = QLabel("")
        self._review_breakdown_label.setWordWrap(True)
        self._review_breakdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._review_breakdown_label.setFont(QFont(*MUTED_FONT))
        self._review_breakdown_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        inner.addWidget(self._review_breakdown_label)
        return card

    def _build_dashboard(self) -> QWidget:
        content = QWidget()
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 8, 8, 18)
        layout.setSpacing(9)

        # Status banner
        self._status_banner = QFrame()
        banner_layout = QHBoxLayout(self._status_banner)
        banner_layout.setContentsMargins(16, 10, 16, 10)
        banner_layout.setSpacing(10)
        self._status_icon = QLabel("\u2713")
        self._status_icon.setFont(QFont(*TITLE_FONT))
        self._status_icon.setStyleSheet(f"color: {SUCCESS};")
        banner_layout.addWidget(self._status_icon)
        banner_text = QVBoxLayout()
        banner_text.setSpacing(2)
        self._status_label = QLabel("FINAL RESULTS")
        self._status_label.setFont(QFont(*STATUS_FONT))
        self._status_label.setStyleSheet(f"color: {SUCCESS}; font-weight: 600;")
        banner_text.addWidget(self._status_label)
        self._status_hint = QLabel("All review decisions applied. Graph validated. CPM computed.")
        self._status_hint.setFont(QFont(*MUTED_FONT))
        self._status_hint.setStyleSheet(f"color: {TEXT_SECONDARY};")
        banner_text.addWidget(self._status_hint)
        banner_layout.addLayout(banner_text, stretch=1)
        self._status_banner.setStyleSheet(
            f"QFrame {{ background-color: {_rgba(SUCCESS, 20)};"
            f" border: 1px solid {qrgba(SUCCESS, 68)}; border-radius: 8px; }}"
        )
        layout.addWidget(self._status_banner)

        self._provenance_label = QLabel("")
        self._provenance_label.setFont(QFont(*MUTED_FONT))
        self._provenance_label.setStyleSheet(
            f"color: {TEXT_MUTED}; padding: 2px 4px;"
        )
        layout.addWidget(self._provenance_label)

        top = QHBoxLayout()
        top.setSpacing(10)
        header_stack = QVBoxLayout()
        header_stack.setSpacing(2)
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setFont(QFont(*LABEL_FONT))
        self._summary_label.setStyleSheet(f"color: {ACCENT};")
        header_stack.addWidget(self._summary_label)
        top.addLayout(header_stack, stretch=1)

        self._export_btn = QPushButton("Export")
        self._export_btn.setToolTip(_EXPORT_TOOLTIP)
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._report_btn = QPushButton("Report")
        self._report_btn.setToolTip(_REPORT_TOOLTIP)
        self._report_btn.clicked.connect(self._on_report_clicked)
        top.addWidget(self._export_btn)
        top.addWidget(self._report_btn)
        layout.addLayout(top)

        self._tabs = QTabWidget()
        self._tabs.setMinimumWidth(0)
        self._tabs.setDocumentMode(True)
        self._tabs.setUsesScrollButtons(False)
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {BORDER};"
            f" border-radius: {RADIUS_SM}px; top: -1px; background: transparent; }}"
            f"QTabBar {{ background: transparent; }}"
            f"QTabBar::tab {{ padding: 9px 18px; margin-right: 4px;"
            f" min-height: 28px; color: {TEXT_MUTED}; border: 1px solid transparent;"
            f" border-radius: {RADIUS_SM}px; background: transparent; }}"
            f"QTabBar::tab:selected {{ color: {TEXT}; background: {SURFACE_LIGHT};"
            f" border-color: {ACCENT}; font-weight: 700; }}"
            f"QTabBar::tab:hover:!selected {{ color: {TEXT};"
            f" background: {SURFACE_LIGHT}; }}"
        )
        self._overview = OverviewTab()
        self._network = NetworkTab()
        self._activities = ActivitiesTab()
        self._critical_paths = CriticalPathsTab()
        self._pert = PertTab()
        self._tabs.addTab(self._overview, "Overview")
        self._tabs.addTab(self._network, "Network")
        self._tabs.addTab(self._activities, "Activities")
        self._tabs.addTab(self._critical_paths, "Critical Paths")
        self._tabs.addTab(self._pert, "PERT")
        layout.addWidget(self._tabs, stretch=1)

        self._critical_paths.path_selected.connect(self._on_path_selected)
        self._activities.activity_selected.connect(self._on_activity_selected)
        self._network.node_selected.connect(self._on_network_node_selected)
        self._overview.open_network_requested.connect(
            lambda: self._tabs.setCurrentWidget(self._network)
        )
        self._overview.open_activities_requested.connect(
            lambda: self._tabs.setCurrentWidget(self._activities)
        )
        self._overview.open_paths_requested.connect(
            lambda: self._tabs.setCurrentWidget(self._critical_paths)
        )
        self._overview.open_validation_requested.connect(self.go_validation)
        self._pert.pert_run_requested.connect(self._on_pert_run_clicked)
        scroll = QScrollArea()
        scroll.setObjectName("resultsDashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    # ------------------------------------------------------------------
    # Readiness gate
    # ------------------------------------------------------------------

    def _on_export_clicked(self) -> None:
        if not self._busy:
            self.export_requested.emit()

    def _on_report_clicked(self) -> None:
        if not self._busy:
            self.report_requested.emit()

    def refresh(self, session: Any) -> None:
        self._session = session
        ready, reason = describe_ready(session)
        self._update_context_header(session, ready, reason)
        self._pert.refresh(session)
        if not ready:
            self._show_not_ready(reason)
            return
        self._show_dashboard(session)

    @staticmethod
    def _entry_mode(session: Any) -> str:
        mode = getattr(session, "entry_mode", None)
        if mode in ("IMAGE_ANALYSIS", "NETWORK_BUILDER"):
            return mode
        if getattr(session, "current_image_path", None):
            return "IMAGE_ANALYSIS"
        if getattr(session, "workflow", None) is None and getattr(
            session, "current_candidate", None
        ) is not None:
            return "NETWORK_BUILDER"
        return "NONE"

    def _update_context_header(self, session: Any, ready: bool, reason: str) -> None:
        """Keep both Results modes inside one stable, explainable shell."""
        mode = self._entry_mode(session)
        mode_label = {
            "IMAGE_ANALYSIS": "ENTRY: IMAGE ANALYSIS",
            "NETWORK_BUILDER": "ENTRY: NETWORK BUILDER",
            "NONE": "ENTRY: NOT STARTED",
        }[mode]
        self._context_mode_label.setText(mode_label)

        source = self._provenance_text(session).split("  ·  ", 1)[0]
        if ": " in source:
            source = "Source: " + source.split(": ", 1)[1]
        if mode == "NETWORK_BUILDER":
            source = "Source: Manual Network Builder"
        self._context_source_label.setText(source)

        trust = "AUTHORITATIVE" if ready else {
            REVIEW_REQUIRED: "PRELIMINARY",
            GRAPH_INVALID: "NOT AUTHORITATIVE",
            CPM_BLOCKED: "NOT AUTHORITATIVE",
            RESULT_UNAVAILABLE: "REVIEWED / CPM PENDING",
            NO_ANALYSIS: "NOT READY",
        }.get(reason, "NOT READY")
        trust_color = SUCCESS if ready else (
            WARNING if reason in (REVIEW_REQUIRED, RESULT_UNAVAILABLE, NO_ANALYSIS)
            else DANGER
        )
        self._context_trust_label.setText(f"TRUST: {trust}")
        self._context_trust_label.setStyleSheet(
            f"color: {trust_color}; font-weight: 600;"
        )

        total = session.review_item_total() if session is not None else 0
        pending = session.pending_review_total() if session is not None else 0
        self._context_review_label.setText(
            f"Review: {max(0, total - pending)}/{total} resolved"
            if total
            else "Review: not required"
        )

    def _show_not_ready(self, reason: str) -> None:
        session = self._session
        message = {
            NO_ANALYSIS: (
                "Results not ready. No project analyzed. "
                "Run an analysis on the Analyze Diagram page."
            ),
            REVIEW_REQUIRED: (
                "Results not ready. Review required \u2014 finish the review "
                "and apply your decisions before CPM can run."
            ),
            GRAPH_INVALID: (
                "Results not ready. The reviewed graph is invalid \u2014 "
                "resolve the validation issues first."
            ),
            CPM_BLOCKED: (
                "Results not ready. CPM is blocked \u2014 the graph is not "
                "in a runnable state."
            ),
            RESULT_UNAVAILABLE: (
                "Results not ready. The graph is valid but no CPM result "
                "exists yet. Click Calculate Results to run the CPM service."
            ),
        }[reason]
        if widget_language(self) == UiLanguage.ARABIC:
            message = {
                NO_ANALYSIS: "النتائج غير جاهزة. لم يتم تحليل أي مشروع. شغّل التحليل من صفحة تحليل المخطط.",
                REVIEW_REQUIRED: "النتائج غير جاهزة. المراجعة مطلوبة — أكمل المراجعة وطبّق قراراتك قبل تشغيل CPM.",
                GRAPH_INVALID: "النتائج غير جاهزة. الرسم الذي تمت مراجعته غير صحيح — عالج مشكلات التحقق أولًا.",
                CPM_BLOCKED: "النتائج غير جاهزة. تم حظر CPM — الرسم ليس في حالة قابلة للتشغيل.",
                RESULT_UNAVAILABLE: "النتائج غير جاهزة. الرسم صحيح لكن لا توجد نتيجة CPM بعد. اضغط حساب النتائج لتشغيل الخدمة.",
            }[reason]
        self._empty_label.setText(message)
        self._empty_label.show()
        self._set_empty_status(reason)
        self._provenance_label.hide()
        self._set_calculate_visible(reason == RESULT_UNAVAILABLE)
        self._calculate_btn.setEnabled(reason == RESULT_UNAVAILABLE and not self._busy)
        self._set_readiness(reason)
        self._update_preliminary(session)
        self._update_progress(session)
        self._stack.setCurrentIndex(self._EMPTY)

    def _update_preliminary(self, session: Any) -> None:
        """Fill the PRELIMINARY detected-metrics card when an analysis exists."""
        if session is None:
            self._preliminary_card.hide()
            self._detected_preview.clear_preview()
            return
        candidate = session.current_candidate
        if session.workflow is None and candidate is None:
            self._preliminary_card.hide()
            self._detected_preview.clear_preview()
            return
        workflow = getattr(session, "workflow", None)
        if workflow is not None:
            summary = getattr(session, "review_summary", None) or {}
            values = {
                "activities": summary.get("total_activities", "\u2014"),
                "dependencies": summary.get("total_dependencies", "\u2014"),
                "review_items": session.review_item_total() or "\u2014",
                "graph_status": summary.get("graph_validation_status", "\u2014"),
                "cpm_readiness": summary.get("cpm_eligibility", "\u2014"),
            }
        else:
            graph = getattr(candidate, "graph", None)
            validation = getattr(candidate, "validation", None)
            gate = getattr(candidate, "cpm_gate", None)
            graph_status = getattr(validation, "status", None)
            values = {
                "activities": _count_activities(graph) or "\u2014",
                "dependencies": _count_dependencies(graph) or "\u2014",
                "review_items": "\u2014",
                "graph_status": getattr(graph_status, "value", graph_status) or "\u2014",
                "cpm_readiness": getattr(gate, "value", gate) or "\u2014",
            }
        for key, value in values.items():
            value_label, _ = self._preliminary_values[key]
            value_label.setText(str(value) if value not in (None, "") else "—")
        self._priority_label.setText(self._review_priority_text(session))
        self._provenance_card_label.setText(self._provenance_text(session))
        self._review_trace_label.setText(self._review_trace_text(session))
        self._review_breakdown_label.setText(self._review_breakdown_text(session))
        self._preliminary_card.show()
        if self._entry_mode(session) == "IMAGE_ANALYSIS":
            self._detected_preview.set_review_session(
                getattr(session, "review_session", None)
            )
        else:
            self._detected_preview.clear_preview()

    @staticmethod
    def _provenance_text(session: Any) -> str:
        """Describe the source and graph type without claiming authority."""
        review_session = getattr(session, "review_session", None)
        source = getattr(review_session, "source_image_id", None)
        if not source:
            image_path = getattr(session, "current_image_path", None)
            source = Path(image_path).name if image_path else ""
        source = source or "unknown image"

        summary = getattr(session, "review_summary", None) or {}
        diagram_type = summary.get("diagram_type")
        candidate = getattr(session, "current_candidate", None)
        graph = getattr(candidate, "graph", None) if candidate is not None else None
        if not diagram_type:
            diagram_type = getattr(graph, "diagram_type", None)
        diagram_type = getattr(diagram_type, "value", diagram_type) or "UNKNOWN"
        return f"Source image: {source}  ·  Diagram type: {diagram_type}"

    @staticmethod
    def _review_trace_text(session: Any) -> str:
        """Show review totals from the session, not reconstructed UI math."""
        total = session.review_item_total() if session is not None else 0
        pending = session.pending_review_total() if session is not None else 0
        corrected = 0
        review_session = getattr(session, "review_session", None)
        for collection_name in ("activities", "dependencies", "durations"):
            for item in getattr(review_session, collection_name, []) or []:
                status = getattr(getattr(item, "status", None), "value", "")
                if status == "CORRECTED":
                    corrected += 1
        resolved = max(0, total - pending)
        return (
            f"Review trace — {total} total · {pending} pending · "
            f"{resolved} resolved · {corrected} corrected"
        )

    @staticmethod
    def _review_breakdown_text(session: Any) -> str:
        """Show auditable totals by review category and final decision."""
        review_session = getattr(session, "review_session", None)
        if review_session is None:
            return "Review breakdown: unavailable"

        labels = (
            ("activities", "Activities"),
            ("dependencies", "Dependencies"),
            ("durations", "Durations"),
        )
        parts = []
        for collection_name, label in labels:
            items = list(getattr(review_session, collection_name, []) or [])
            counts = Counter(
                getattr(getattr(item, "status", None), "value", "PENDING")
                for item in items
            )
            total = len(items)
            parts.append(
                f"{label}: {total} total · {counts.get('PENDING', 0)} pending · "
                f"{counts.get('ACCEPTED', 0)} accepted · "
                f"{counts.get('CORRECTED', 0)} corrected"
            )
        return "Review breakdown — " + "  |  ".join(parts)

    def _set_empty_status(self, reason: str) -> None:
        """Set a concise trust state for every non-authoritative outcome."""
        states = {
            REVIEW_REQUIRED: (
                "REVIEW REQUIRED", WARNING,
                "CPM remains blocked until required review decisions are applied.",
            ),
            GRAPH_INVALID: (
                "GRAPH INVALID", DANGER,
                "The reviewed graph is not authoritative until validation issues are resolved.",
            ),
            CPM_BLOCKED: (
                "CPM BLOCKED", WARNING,
                "The graph cannot produce an authoritative CPM result in its current state.",
            ),
            RESULT_UNAVAILABLE: (
                "READY TO CALCULATE", SUCCESS,
                "The reviewed graph is valid; run CPM to create the authoritative result.",
            ),
            NO_ANALYSIS: (
                "NO ANALYSIS", TEXT_MUTED,
                "No detected or reviewed graph is available yet.",
            ),
        }
        title, color, hint = states[reason]
        if widget_language(self) == UiLanguage.ARABIC:
            title = {
                REVIEW_REQUIRED: "المراجعة مطلوبة",
                GRAPH_INVALID: "الرسم غير صحيح",
                CPM_BLOCKED: "تم حظر CPM",
                RESULT_UNAVAILABLE: "جاهز للحساب",
                NO_ANALYSIS: "لا يوجد تحليل",
            }[reason]
        self._empty_status_icon.setStyleSheet(f"color: {color};")
        self._empty_status_label.setStyleSheet(f"color: {color}; font-weight: 600;")
        self._empty_status_label.setText(title)
        self._empty_status_hint.setText(hint)
        self._empty_status_banner.setStyleSheet(
            f"QFrame {{ background-color: {_rgba(color, 20)};"
            f" border: 1px solid {color}44; border-radius: 8px; }}"
        )
        self._empty_status_banner.show()

    @staticmethod
    def _review_priority_text(session: Any) -> str:
        """Render pending review tiers from existing calibration evidence.

        This is presentation-only: it does not infer acceptance, alter
        confidence, or change the readiness gate. When calibration metadata
        is unavailable, the UI says so instead of inventing a tier.
        """
        review_session = getattr(session, "review_session", None)
        if review_session is None:
            return "Review priority: unavailable"

        counts: Counter[str] = Counter()
        metadata = getattr(review_session, "metadata", {}) or {}
        for collection_name in ("activities", "dependencies", "durations"):
            for item in getattr(review_session, collection_name, []) or []:
                status = getattr(getattr(item, "status", None), "value", "")
                if status and status != "PENDING":
                    continue
                tier = None
                for evidence in getattr(item, "evidence", []) or []:
                    calibration = (getattr(evidence, "metadata", {}) or {}).get(
                        "review_calibration", {}
                    )
                    tier = calibration.get("tier")
                    if tier:
                        break
                if tier:
                    counts[tier] += 1

        if not counts:
            configured = metadata.get("review_calibration", {}).get("tier_counts", {})
            if configured:
                counts.update(configured)
        if not counts:
            return "Review priority: calibration data unavailable"

        order = (
            "BLOCKING_REVIEW",
            "HIGH_PRIORITY_REVIEW",
            "HIGH_RISK_REVIEW",
            "STANDARD_REVIEW",
            "LOW_RISK_REVIEW",
            "STRONG_EVIDENCE_REVIEW",
        )
        labels = {
            "BLOCKING_REVIEW": "Blocking",
            "HIGH_PRIORITY_REVIEW": "High priority",
            "HIGH_RISK_REVIEW": "High risk",
            "STANDARD_REVIEW": "Standard",
            "LOW_RISK_REVIEW": "Low risk",
            "STRONG_EVIDENCE_REVIEW": "Strong evidence",
        }
        parts = [
            f"{labels[tier]}: {counts[tier]}"
            for tier in order
            if counts.get(tier, 0)
        ]
        return "Review priority — " + " · ".join(parts)

    def _update_progress(self, session: Any) -> None:
        total = session.review_item_total() if session is not None else 0
        pending = session.pending_review_total() if session is not None else 0
        done = max(0, total - pending)
        if session is not None and session.workflow is not None and total > 0:
            self._progress_label.setText(
                f"اكتملت مراجعة {done} من أصل {total}"
                if widget_language(self) == UiLanguage.ARABIC
                else f"{done} / {total} reviews complete"
            )
            self._progress_label.show()
        else:
            self._progress_label.setText("")
            self._progress_label.hide()

    def _set_readiness(self, reason: str) -> None:
        """At-a-glance readiness strip shown in the not-ready state."""
        session = self._session
        if session is None:
            self._readiness_label.setText("")
            return
        workflow = getattr(session, "workflow", None)
        candidate = session.current_candidate
        status = session.validation_status
        pending = session.pending_review_total()
        done = session.review_item_total()

        rows = []
        if workflow is not None or candidate is not None:
            rows.append(("\u2713", SUCCESS, "Analysis complete"))
        else:
            rows.append(("\u25CB", TEXT_MUTED, "Analysis complete"))
        if workflow is None:
            if candidate is not None:
                rows.append(("\u2713", SUCCESS, "Review resolved"))
            else:
                rows.append(("\u25CB", TEXT_MUTED, "Review"))
        elif pending == 0:
            rows.append(("\u2713", SUCCESS, f"Review resolved ({done} items)"))
        else:
            rows.append(("\u26a0", WARNING, f"Review in progress ({pending} pending)"))
        if status == ValidationCenterStatus.VALID:
            rows.append(("\u2713", SUCCESS, "Graph valid"))
        elif status == ValidationCenterStatus.INVALID:
            rows.append(("\u2717", DANGER, "Graph invalid"))
        elif status == ValidationCenterStatus.BLOCKED_REVIEW:
            rows.append(("\u26a0", WARNING, "Validation blocked"))
        else:
            rows.append(("\u25CB", TEXT_MUTED, "Graph not validated yet"))
        if reason == RESULT_UNAVAILABLE:
            rows.append(("\u2713", SUCCESS, "CPM-ready - run Calculate Results"))
        elif reason == CPM_BLOCKED:
            rows.append(("\u26a0", WARNING, "CPM unavailable"))
        elif reason == GRAPH_INVALID:
            rows.append(("\u2717", DANGER, "CPM unavailable"))
        else:
            rows.append(("\u25CB", TEXT_MUTED, "CPM result pending"))

        parts = [
            f'<font color="{color}">{glyph}</font> {label}'
            for glyph, color, label in rows
        ]
        self._readiness_label.setText("  \u00b7  ".join(parts))

    def _show_dashboard(self, session: Any) -> None:
        data = extract(session)
        self._data = data
        duration_text = format_duration(data.project_duration)
        self._summary_label.setText(
            (
                f"مدة المشروع: {duration_text}   ·   "
                f"المسارات الحرجة: {data.critical_path_count or 0}   ·   "
                f"الأنشطة الحرجة: {data.critical_activity_count}"
            )
            if widget_language(self) == UiLanguage.ARABIC
            else (
                f"Project duration: {duration_text}   ·   "
                f"Critical paths: {data.critical_path_count or 0}   ·   "
                f"Critical activities: {data.critical_activity_count}"
            )
        )
        self._overview.set_data(data, session)
        self._activities.set_data(data.activities)
        self._critical_paths.set_data(data)
        self._network.set_data(data)
        self._network.set_pert_data(extract_pert(session))
        self._set_calculate_visible(False)
        self._empty_label.hide()
        self._not_ready_heading.hide()
        self._preliminary_card.hide()
        self._detected_preview.clear_preview()
        self._progress_label.hide()
        self._export_btn.setEnabled(True)
        self._report_btn.setEnabled(True)

        # Update status banner
        self._status_banner.show()
        self._provenance_label.setText(
            "نتيجة معتمدة · رسم تمت مراجعته · لا يعاد حساب قيم CPM في الواجهة"
            if widget_language(self) == UiLanguage.ARABIC
            else "Authoritative result  ·  reviewed graph  ·  CPM values are not recomputed in the UI"
        )
        self._provenance_label.show()
        self._status_icon.setText("\u2713")
        self._status_icon.setStyleSheet(f"color: {SUCCESS};")
        self._status_label.setText(
            "النتائج النهائية" if widget_language(self) == UiLanguage.ARABIC else "FINAL RESULTS"
        )
        self._status_label.setStyleSheet(f"color: {SUCCESS}; font-weight: 600;")
        self._status_hint.setText(
            "تم تطبيق جميع قرارات المراجعة. تم التحقق من الرسم وحساب CPM."
            if widget_language(self) == UiLanguage.ARABIC
            else "All review decisions applied. Graph validated. CPM computed."
        )
        self._status_banner.setStyleSheet(
            f"QFrame {{ background-color: {_rgba(SUCCESS, 20)};"
            f" border: 1px solid {qrgba(SUCCESS, 68)}; border-radius: 8px; }}"
        )

        self._stack.setCurrentIndex(self._DASHBOARD)

    def _set_calculate_visible(self, visible: bool) -> None:
        self._calculate_btn.setVisible(visible)

    def _on_calculate_clicked(self) -> None:
        if self._busy:
            return
        self.calculate_requested.emit()

    def _on_pert_run_clicked(self) -> None:
        if self._busy:
            return
        self.pert_run_requested.emit()

    # ------------------------------------------------------------------
    # Cross-navigation (presentation-level only)
    # ------------------------------------------------------------------

    def _on_path_selected(self, path_ids: list[str]) -> None:
        self._network.highlight_path(list(path_ids))

    def _on_activity_selected(self, activity_id: str) -> None:
        self._network.set_selected_activity(activity_id)

    def _on_network_node_selected(self, activity_id: str) -> None:
        self._tabs.setCurrentWidget(self._activities)
        self._activities.select_activity(activity_id)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if self._stack.currentIndex() == self._EMPTY:
            self._calculate_btn.setEnabled(
                not busy and self._calculate_btn.isVisible()
            )
        self._pert.set_busy(busy)

    def stack_index(self) -> int:
        return self._stack.currentIndex()

    @property
    def data(self) -> Any:
        return self._data

    def overview(self) -> OverviewTab:
        return self._overview

    def network(self) -> NetworkTab:
        return self._network

    def activities(self) -> ActivitiesTab:
        return self._activities

    def critical_paths(self) -> CriticalPathsTab:
        return self._critical_paths

    def pert(self) -> PertTab:
        return self._pert

    def tabs(self) -> QTabWidget:
        return self._tabs
