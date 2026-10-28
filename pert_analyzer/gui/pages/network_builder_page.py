"""
Network Builder page: manual AON network construction workspace.

Layout:  LEFT (activity table)  |  CENTER (live graph)  |  RIGHT (inspector)
         BOTTOM (relationships + status bar + actions)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPolygonF,
    QTextOption,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.builder.model import ManualNetworkModel
from pert_analyzer.gui.results import layout as network_layout
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    DANGER,
    ELEVATED,
    SURFACE,
    SURFACE_LIGHT,
    SUCCESS,
    TEXT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    WARNING,
)
from pert_analyzer.gui.themes.typography import (
    BUTTON_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    TITLE_FONT,
)

logger = logging.getLogger(__name__)


class NetworkBuilderPage(QWidget):
    """
    Full manual network builder workspace.

    Provides:
    - Activity table (add/edit/delete activities with ID, duration, predecessors)
    - Live network graph (auto-layout, zoom, select nodes/edges)
    - Inspector panel (activity details or relationship details)
    - Relationship explorer (list of all edges)
    - Network status bar (validation status)
    - Action bar (Validate, Calculate CPM, Analyze)
    """

    analyze_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._model = ManualNetworkModel(self)
        self._setup_ui()
        self._connect_signals()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # fit_graph() may have computed its transform while this page was
        # still hidden and unsized (during construction), which bakes a
        # stale oversized zoom in.  Refit once the real viewport size is
        # known — but never override a manual zoom the user already chose.
        if not self._user_zoomed:
            QTimer.singleShot(0, self._on_fit)

    @property
    def model(self) -> ManualNetworkModel:
        return self._model

    # ── UI setup ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Header ───────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("Network Builder")
        title.setFont(QFont(*TITLE_FONT))
        title.setStyleSheet(f"color: {TEXT};")
        header.addWidget(title)
        header.addStretch()

        self._summary_label = QLabel("Activities: 0   Dependencies: 0")
        self._summary_label.setFont(QFont(*STATUS_FONT))
        self._summary_label.setStyleSheet(f"color: {ACCENT};")
        header.addWidget(self._summary_label)
        header.addSpacing(8)

        self._state_badge = QLabel("DRAFT")
        self._state_badge.setFont(QFont(*STATUS_FONT))
        self._state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_badge.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 10px;"
            f" padding: 2px 12px; font-weight: 600;"
        )
        header.addWidget(self._state_badge)
        self._results_snapshot: Optional[tuple] = None
        root.addLayout(header)

        subtitle = QLabel(
            "Build your AON project network manually. Add activities, "
            "define durations and predecessors, then validate and analyze."
        )
        subtitle.setFont(QFont(*MUTED_FONT))
        subtitle.setStyleSheet(f"color: {TEXT_MUTED};")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── Main splitter: LEFT | CENTER | RIGHT ────────────
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(4)
        main_splitter.setStyleSheet(
            f"QSplitter::handle {{ background-color: {BORDER}; "
            f"border-radius: 2px; }}"
        )

        # LEFT: Activity table
        left_panel = self._build_left_panel()
        main_splitter.addWidget(left_panel)

        # CENTER: Graph view
        center_panel = self._build_center_panel()
        main_splitter.addWidget(center_panel)

        # RIGHT: Inspector
        right_panel = self._build_right_panel()
        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([340, 500, 280])
        root.addWidget(main_splitter, stretch=1)

        # ── Bottom: Relationships + Status + Actions ─────────
        bottom = self._build_bottom_section()
        root.addWidget(bottom)

        # The model emits nothing at construction time, so the page would
        # otherwise come up with a blank canvas (no guidance), a Calculate
        # CPM button that still looks enabled, and stale counts.  Sync once.
        self._graph_nodes = {}
        self._graph_edges = []
        self._user_zoomed = False
        self._on_model_changed()

    def _build_left_panel(self) -> QWidget:
        """Activity table panel."""
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setStyleSheet(
            f"QFrame {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        lbl = QLabel("Activities")
        lbl.setFont(QFont(*LABEL_FONT))
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        header_row.addWidget(lbl)
        header_row.addStretch()

        self._add_btn = QPushButton("+ Add Activity")
        self._add_btn.setFont(QFont(*BUTTON_FONT))
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background-color: {ACCENT}; color: white;"
            f" border: none; border-radius: 6px; padding: 6px 14px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background-color: {ACCENT}DD; }}"
        )
        self._add_btn.clicked.connect(self._on_add_activity)
        header_row.addWidget(self._add_btn)
        layout.addLayout(header_row)

        # Activity rows container (scrollable)
        self._activity_container = QWidget()
        self._activity_layout = QVBoxLayout(self._activity_container)
        self._activity_layout.setContentsMargins(0, 0, 0, 0)
        self._activity_layout.setSpacing(4)
        self._activity_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._activity_container)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QScrollArea > QWidget {{ background: transparent; }}"
        )
        layout.addWidget(scroll, stretch=1)

        # Empty state
        self._empty_label = QLabel(
            "Add your first activity to begin.\n\n"
            "Each activity needs an ID, duration,\n"
            "and optional predecessors."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setFont(QFont(*MUTED_FONT))
        self._empty_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 20px;")
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        return panel

    def _build_center_panel(self) -> QWidget:
        """Live graph visualization panel."""
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setStyleSheet(
            f"QFrame {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_row = QHBoxLayout()
        lbl = QLabel("Live Network")
        lbl.setFont(QFont(*LABEL_FONT))
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        header_row.addWidget(lbl)
        header_row.addStretch()

        self._graph_zoom_in = QPushButton("+")
        self._graph_zoom_in.setFixedSize(30, 30)
        self._graph_zoom_in.setFont(QFont(*BUTTON_FONT))
        self._graph_zoom_in.setStyleSheet(
            f"QPushButton {{ background: {ELEVATED}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;"
            f" padding: 0px; min-height: 0px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {BORDER}; }}"
        )
        self._graph_zoom_in.clicked.connect(self._on_zoom_in)
        header_row.addWidget(self._graph_zoom_in)

        self._graph_zoom_out = QPushButton("\u2212")
        self._graph_zoom_out.setFixedSize(30, 30)
        self._graph_zoom_out.setFont(QFont(*BUTTON_FONT))
        self._graph_zoom_out.setStyleSheet(
            f"QPushButton {{ background: {ELEVATED}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;"
            f" padding: 0px; min-height: 0px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {BORDER}; }}"
        )
        self._graph_zoom_out.clicked.connect(self._on_zoom_out)
        header_row.addWidget(self._graph_zoom_out)

        self._graph_fit = QPushButton("Fit")
        self._graph_fit.setFont(QFont(*STATUS_FONT))
        self._graph_fit.setStyleSheet(
            f"QPushButton {{ background: {ELEVATED}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;"
            f" padding: 5px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {BORDER}; }}"
        )
        self._graph_fit.clicked.connect(self._on_fit)
        header_row.addWidget(self._graph_fit)

        layout.addLayout(header_row)

        self._graph_scene = QGraphicsScene(self)
        self._graph_view = QGraphicsView(self._graph_scene)
        self._graph_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._graph_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._graph_view.setStyleSheet(
            f"QGraphicsView {{ background: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        self._graph_view.setSceneRect(0, 0, 600, 300)
        layout.addWidget(self._graph_view, stretch=1)

        return panel

    def _build_right_panel(self) -> QWidget:
        """Inspector panel."""
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setStyleSheet(
            f"QFrame {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        lbl = QLabel("Inspector")
        lbl.setFont(QFont(*LABEL_FONT))
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(lbl)

        self._inspector_content = QLabel(
            "Select an activity or relationship\nfrom the network to inspect it."
        )
        self._inspector_content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inspector_content.setFont(QFont(*MUTED_FONT))
        self._inspector_content.setStyleSheet(f"color: {TEXT_MUTED}; padding: 20px;")
        self._inspector_content.setWordWrap(True)
        layout.addWidget(self._inspector_content, stretch=1)

        # Contextual actions for whatever the inspector is showing
        # (e.g. a Delete relationship button while an edge is selected).
        self._inspector_action_layout = QHBoxLayout()
        layout.addLayout(self._inspector_action_layout)

        return panel

    def _build_bottom_section(self) -> QWidget:
        """Relationships + status bar + action buttons."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        # Relationships section
        rel_frame = QFrame()
        rel_frame.setFrameShape(QFrame.Shape.NoFrame)
        rel_frame.setStyleSheet(
            f"QFrame {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        rel_layout = QVBoxLayout(rel_frame)
        rel_layout.setContentsMargins(12, 8, 12, 8)
        rel_layout.setSpacing(4)

        rel_header = QHBoxLayout()
        rel_lbl = QLabel("Relationships")
        rel_lbl.setFont(QFont(*LABEL_FONT))
        rel_lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        rel_header.addWidget(rel_lbl)
        rel_header.addStretch()

        # Add relationship controls (dropdowns filter to existing activities)
        from PySide6.QtWidgets import QComboBox

        self._rel_from = QComboBox()
        self._rel_from.addItem("\u2014")
        self._rel_from.setMaximumWidth(80)
        self._rel_from.setFont(QFont(*STATUS_FONT))
        self._rel_from.setStyleSheet(
            f"QComboBox {{ background: {SURFACE_LIGHT}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px;"
            f" padding: 3px 6px; }}"
        )
        rel_header.addWidget(self._rel_from)

        arrow = QLabel("\u2192")
        arrow.setFont(QFont(*STATUS_FONT))
        arrow.setStyleSheet(f"color: {TEXT_SECONDARY};")
        rel_header.addWidget(arrow)

        self._rel_to = QComboBox()
        self._rel_to.addItem("\u2014")
        self._rel_to.setMaximumWidth(80)
        self._rel_to.setFont(QFont(*STATUS_FONT))
        self._rel_to.setStyleSheet(
            f"QComboBox {{ background: {SURFACE_LIGHT}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px;"
            f" padding: 3px 6px; }}"
        )
        rel_header.addWidget(self._rel_to)

        self._add_rel_btn = QPushButton("Add")
        self._add_rel_btn.setFont(QFont(*MUTED_FONT))
        self._add_rel_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: white;"
            f" border: none; border-radius: 4px; padding: 4px 10px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT}DD; }}"
            f"QPushButton:disabled {{ background: {TEXT_MUTED};"
            f" color: {SURFACE}; }}"
        )
        self._add_rel_btn.clicked.connect(self._on_add_relationship)
        rel_header.addWidget(self._add_rel_btn)
        rel_layout.addLayout(rel_header)

        self._rel_list_label = QLabel("No relationships defined.")
        self._rel_list_label.setFont(QFont(*MUTED_FONT))
        self._rel_list_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self._rel_list_label.setWordWrap(True)
        rel_layout.addWidget(self._rel_list_label)

        # Interactive chips row: one chip per relationship, each with its
        # own remove action (the plain-text row above stays as the empty
        # hint and a fallback).
        self._rel_chips_area = QWidget()
        self._rel_chips_area.setStyleSheet("background: transparent;")
        self._rel_chips_layout = QHBoxLayout(self._rel_chips_area)
        self._rel_chips_layout.setContentsMargins(0, 2, 0, 0)
        self._rel_chips_layout.setSpacing(6)
        self._rel_chips_layout.addStretch()
        self._rel_chips_area.hide()
        rel_layout.addWidget(self._rel_chips_area)

        layout.addWidget(rel_frame)

        # Status bar
        status_bar = QFrame()
        status_bar.setFrameShape(QFrame.Shape.NoFrame)
        status_bar.setStyleSheet(
            f"QFrame {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(12, 6, 12, 6)

        self._status_icon = QLabel("\u25CB")
        self._status_icon.setFont(QFont(*STATUS_FONT))
        sb_layout.addWidget(self._status_icon)

        self._status_text = QLabel("No activities defined.")
        self._status_text.setFont(QFont(*STATUS_FONT))
        self._status_text.setStyleSheet(f"color: {TEXT_MUTED};")
        sb_layout.addWidget(self._status_text)
        sb_layout.addStretch()

        self._acts_count_label = QLabel("Activities: 0")
        self._acts_count_label.setFont(QFont(*MUTED_FONT))
        self._acts_count_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        sb_layout.addWidget(self._acts_count_label)

        self._deps_count_label = QLabel("Dependencies: 0")
        self._deps_count_label.setFont(QFont(*MUTED_FONT))
        self._deps_count_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        sb_layout.addWidget(self._deps_count_label)

        # The header already shows both counts; these stay updated for
        # programmatic access but out of the row, so the same two numbers
        # don't appear twice in one line.
        self._acts_count_label.hide()
        self._deps_count_label.hide()

        layout.addWidget(status_bar)

        # Action buttons
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()

        self._load_example_btn = QPushButton("Load Example")
        self._load_example_btn.setFont(QFont(*BUTTON_FONT))
        self._load_example_btn.setStyleSheet(
            f"QPushButton {{ background: {SURFACE_LIGHT}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;"
            f" padding: 8px 16px; }}"
            f"QPushButton:hover {{ background: {BORDER}; }}"
        )
        self._load_example_btn.clicked.connect(self._on_load_example)
        actions.addWidget(self._load_example_btn)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setFont(QFont(*BUTTON_FONT))
        self._clear_btn.setStyleSheet(
            f"QPushButton {{ background: {SURFACE_LIGHT}; color: {DANGER};"
            f" border: 1px solid {DANGER}44; border-radius: 6px;"
            f" padding: 8px 16px; }}"
            f"QPushButton:hover {{ background: {DANGER}22; }}"
        )
        self._clear_btn.clicked.connect(self._on_clear)
        actions.addWidget(self._clear_btn)

        self._calculate_btn = QPushButton("Calculate CPM")
        self._calculate_btn.setFont(QFont(*BUTTON_FONT))
        self._calculate_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: white;"
            f" border: none; border-radius: 6px; padding: 8px 20px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT}DD; }}"
            f"QPushButton:disabled {{ background: {TEXT_MUTED}; color: {SURFACE}; }}"
        )
        self._calculate_btn.clicked.connect(self._on_calculate_cpm)
        actions.addWidget(self._calculate_btn)

        self._analyze_btn = QPushButton("Analyze \u2192 Results")
        self._analyze_btn.setFont(QFont(*BUTTON_FONT))
        self._analyze_btn.setStyleSheet(
            f"QPushButton {{ background: {SUCCESS}; color: white;"
            f" border: none; border-radius: 6px; padding: 8px 20px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {SUCCESS}DD; }}"
            f"QPushButton:disabled {{ background: {TEXT_MUTED}; color: {SURFACE}; }}"
        )
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.clicked.connect(self._on_analyze)
        actions.addWidget(self._analyze_btn)

        layout.addWidget(QWidget())  # spacer
        layout.addLayout(actions)

        return container

    # ── Signal connections ───────────────────────────────────

    def _connect_signals(self) -> None:
        m = self._model
        m.model_changed.connect(self._on_model_changed)
        m.validation_changed.connect(self._on_validation_changed)
        m.cpm_calculated.connect(self._on_cpm_calculated)
        m.cpm_invalidated.connect(self._on_cpm_invalidated)
        m.selection_changed.connect(self._on_selection_changed)
        m.activity_added.connect(self._on_activity_added)
        m.activity_removed.connect(self._on_activity_removed)
        m.activity_changed.connect(self._on_activity_changed)
        m.relationship_added.connect(self._on_relationship_changed)
        m.relationship_removed.connect(self._on_relationship_changed)

    # ── Activity table operations ────────────────────────────

    def _on_add_activity(self) -> None:
        """Add a new activity row with inline editing."""
        aid = self._model.next_activity_id
        err = self._model.add_activity(aid, duration=1.0)
        if err:
            QMessageBox.warning(self, "Add Activity", err)
            return
        self._add_activity_row(aid)

    def _add_activity_row(self, activity_id: str) -> None:
        """Create an inline editing row for an activity."""
        from PySide6.QtWidgets import QLineEdit

        entry = self._model.get_activity(activity_id)
        if entry is None:
            return

        self._empty_label.hide()

        row = QFrame()
        row.setFrameShape(QFrame.Shape.NoFrame)
        row.setObjectName(f"activity_row_{activity_id}")
        row.setStyleSheet(
            f"QFrame {{ background: {SURFACE_LIGHT}; border: 1px solid {BORDER};"
            f" border-radius: 6px; padding: 4px; }}"
            f"QFrame:hover {{ border: 1px solid {ACCENT}; }}"
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(6)

        # Activity ID (read-only label)
        id_label = QLabel(activity_id)
        id_label.setFont(QFont(*STATUS_FONT))
        id_label.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        id_label.setFixedWidth(30)
        row_layout.addWidget(id_label)

        # Duration
        dur_input = QLineEdit(str(int(entry.duration)) if entry.duration == int(entry.duration) else str(entry.duration))
        dur_input.setMaximumWidth(50)
        dur_input.setFont(QFont(*STATUS_FONT))
        dur_input.setStyleSheet(
            f"QLineEdit {{ background: {SURFACE}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px;"
            f" padding: 3px 6px; }}"
        )
        dur_input.setPlaceholderText("dur")
        row_layout.addWidget(dur_input)

        # Predecessors
        pred_input = QLineEdit(entry.predecessors if entry.predecessors else "")
        pred_input.setFont(QFont(*STATUS_FONT))
        pred_input.setStyleSheet(
            f"QLineEdit {{ background: {SURFACE}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px;"
            f" padding: 3px 6px; }}"
        )
        pred_input.setPlaceholderText("predecessors (e.g. A, B)")
        row_layout.addWidget(pred_input, stretch=1)

        # Delete button
        del_btn = QPushButton("\u2715")
        del_btn.setFixedSize(24, 24)
        del_btn.setFont(QFont(*MUTED_FONT))
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED};"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {DANGER}33; color: {DANGER}; }}"
        )
        del_btn.clicked.connect(lambda checked, aid=activity_id: self._on_delete_activity(aid))
        row_layout.addWidget(del_btn)

        # Store input refs on the row widget for later access
        row._dur_input = dur_input
        row._pred_input = pred_input
        row._activity_id = activity_id

        # Connect editing finished signals
        dur_input.editingFinished.connect(
            lambda aid=activity_id, inp=dur_input: self._on_duration_changed(aid, inp)
        )
        pred_input.editingFinished.connect(
            lambda aid=activity_id, inp=pred_input: self._on_predecessors_changed(aid, inp)
        )

        # Insert before the stretch
        self._activity_layout.insertWidget(self._activity_layout.count() - 1, row)

    def _on_duration_changed(self, activity_id: str, inp: Any) -> None:
        try:
            val = float(inp.text())
        except ValueError:
            val = 0.0
        err = self._model.update_activity(activity_id, duration=val)
        if err:
            QMessageBox.warning(self, "Duration", err)

    def _on_predecessors_changed(self, activity_id: str, inp: Any) -> None:
        err = self._model.update_activity(activity_id, predecessors=inp.text())
        if err:
            QMessageBox.warning(self, "Predecessors", err)

    def _on_delete_activity(self, activity_id: str) -> None:
        entry = self._model.get_activity(activity_id)
        if entry is None:
            return

        deps = self._model.get_predecessors(activity_id)
        succs = self._model.get_successors(activity_id)
        affected = []
        for p in deps:
            affected.append(f"{p} \u2192 {activity_id}")
        for s in succs:
            affected.append(f"{activity_id} \u2192 {s}")

        msg = f"Delete Activity {activity_id}?"
        if affected:
            msg += "\n\nThis will also remove:\n" + "\n".join(affected)

        reply = QMessageBox.question(
            self, "Delete Activity", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._model.remove_activity(activity_id)
            self._remove_activity_row(activity_id)

    def _remove_activity_row(self, activity_id: str) -> None:
        for i in range(self._activity_layout.count()):
            w = self._activity_layout.itemAt(i).widget()
            if w is not None and getattr(w, "_activity_id", None) == activity_id:
                w.setParent(None)
                w.deleteLater()
                break
        if self._model.activity_count == 0:
            self._empty_label.show()

    # ── Relationship operations ──────────────────────────────

    def _on_add_relationship(self) -> None:
        src = self._rel_from.currentText().strip().upper()
        tgt = self._rel_to.currentText().strip().upper()
        if src == "\u2014" or tgt == "\u2014" or not src or not tgt:
            QMessageBox.warning(
                self, "Add Relationship",
                "Select both a source and a target activity."
            )
            return
        err = self._model.add_relationship(src, tgt)
        if err:
            QMessageBox.warning(self, "Add Relationship", err)
        else:
            self._rel_from.setCurrentIndex(0)
            self._rel_to.setCurrentIndex(0)

    # ── Event handlers ───────────────────────────────────────

    def _on_model_changed(self) -> None:
        self._summary_label.setText(
            f"Activities: {self._model.activity_count}   "
            f"Dependencies: {self._model.dependency_count}"
        )
        self._acts_count_label.setText(f"Activities: {self._model.activity_count}")
        self._deps_count_label.setText(f"Dependencies: {self._model.dependency_count}")
        self._calculate_btn.setEnabled(self._model.activity_count > 0)
        self._add_rel_btn.setEnabled(self._model.activity_count > 0)
        self._update_relationships_display()
        self._update_graph_display()
        self._update_state_badge()
        self._refresh_relationship_selectors()

    def _refresh_relationship_selectors(self) -> None:
        ids = self._model.get_activity_ids()
        for combo in (self._rel_from, self._rel_to):
            current_text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("\u2014")
            combo.addItems(sorted(ids))
            if current_text in ids:
                combo.setCurrentText(current_text)
            combo.blockSignals(False)

    def _update_state_badge(self) -> None:
        """Derive and render the builder state badge.

        States (spec): DRAFT, EDITING, VALIDATING, VALID, CPM READY,
        RESULTS READY, NETWORK MODIFIED, CPM OUTDATED, ERROR.
        """
        model = self._model
        if model.activity_count == 0:
            self._set_badge("DRAFT", TEXT_SECONDARY, SURFACE_LIGHT, BORDER)
            return
        if model.validation_result is None:
            self._set_badge("EDITING", ACCENT, SURFACE_LIGHT, ACCENT)
            return
        if not model.is_valid:
            self._set_badge("ERROR", DANGER, SURFACE_LIGHT, DANGER)
            return

        snapshot = self._network_snapshot()
        if self._results_snapshot is not None:
            if snapshot == self._results_snapshot:
                self._set_badge("RESULTS READY", ACCENT, SURFACE_LIGHT, ACCENT)
                return
            self._set_badge("NETWORK MODIFIED", DANGER, SURFACE_LIGHT, DANGER)
            return
        if model.cpm_result is not None and model.cpm_is_stale:
            self._set_badge("CPM OUTDATED", WARNING, SURFACE_LIGHT, WARNING)
            return
        if model.cpm_result is not None:
            self._set_badge("CPM READY", SUCCESS, SURFACE_LIGHT, SUCCESS)
            return
        self._set_badge("VALID", SUCCESS, SURFACE_LIGHT, SUCCESS)

    def mark_results_ready(self) -> None:
        """Record the exact network that was analyzed so the badge can
        distinguish RESULTS READY from NETWORK MODIFIED afterwards."""
        self._results_snapshot = self._network_snapshot()
        self._update_state_badge()

    def _network_snapshot(self) -> tuple:
        acts = sorted(
            (a.activity_id, a.duration, tuple(self._model.get_predecessors(a.activity_id)))
            for a in self._model.get_all_activities()
        )
        rels = sorted((r.source, r.target) for r in self._model.get_all_relationships())
        return (acts, rels)

    def _set_badge(self, text: str, fg: str, bg: str, border: str) -> None:
        self._state_badge.setText(text)
        self._state_badge.setStyleSheet(
            f"color: {fg}; background-color: {bg};"
            f" border: 1px solid {border}; border-radius: 10px;"
            f" padding: 2px 12px; font-weight: 600;"
        )

    def _on_validation_changed(self) -> None:
        v = self._model.validation_result
        if v is None:
            self._status_icon.setText("\u25CB")
            self._status_icon.setStyleSheet(f"color: {TEXT_MUTED};")
            self._status_text.setText("Not validated.")
            self._status_text.setStyleSheet(f"color: {TEXT_MUTED};")
            self._update_state_badge()
            return

        if v.status.value == "valid":
            self._status_icon.setText("\u2713")
            self._status_icon.setStyleSheet(f"color: {SUCCESS}; font-weight: bold;")
            self._status_text.setText("Network valid. CPM ready.")
            self._status_text.setStyleSheet(f"color: {SUCCESS};")
        else:
            errs = v.errors
            warns = v.warnings
            n = len(errs)
            self._status_icon.setText("\u2717")
            self._status_icon.setStyleSheet(f"color: {DANGER}; font-weight: bold;")
            if n == 0:
                self._status_text.setText("Network invalid. Resolve the issues above.")
            elif n == 1:
                self._status_text.setText(f"1 issue: {errs[0].message}")
                if warns:
                    self._status_text.setText(
                        f"1 issue: {errs[0].message}. {len(warns)} warning(s)."
                    )
            else:
                self._status_text.setText(f"{n} issues; first: {errs[0].message}")
            self._status_text.setStyleSheet(f"color: {DANGER};")

        self._analyze_btn.setEnabled(self._model.is_valid)
        self._update_state_badge()

    def _on_cpm_calculated(self) -> None:
        self._analyze_btn.setEnabled(True)
        self._status_icon.setText("\u2713")
        self._status_icon.setStyleSheet(f"color: {SUCCESS}; font-weight: bold;")
        self._status_text.setText("CPM calculated. Ready for Results.")
        self._status_text.setStyleSheet(f"color: {SUCCESS};")
        self._calculate_btn.setText("Recalculate CPM")
        self._update_state_badge()
        # A CPM result is new data the open inspector should show at once.
        if self._model.selected_activity is not None:
            self._update_inspector_activity(self._model.selected_activity)

    def _on_cpm_invalidated(self) -> None:
        self._analyze_btn.setEnabled(self._model.is_valid)
        self._status_icon.setText("\u26a0")
        self._status_icon.setStyleSheet(f"color: {WARNING}; font-weight: bold;")
        self._status_text.setText(
            "Network modified. CPM results outdated \u2014 recalculate."
        )
        self._status_text.setStyleSheet(f"color: {WARNING};")
        self._calculate_btn.setText("Recalculate CPM")
        self._update_state_badge()
        if self._model.selected_activity is not None:
            self._update_inspector_activity(self._model.selected_activity)

    def _on_selection_changed(self, item_type: str, item_id: str) -> None:
        if item_type == "activity":
            self._update_inspector_activity(item_id)
        elif item_type == "relationship":
            self._update_inspector_relationship(item_id)
        else:
            self._reset_inspector()
        self._refresh_graph_selection()

    def _refresh_graph_selection(self) -> None:
        """Re-apply the highlight to the existing scene items in place.

        Deliberately NOT a scene rebuild: clearing the scene from inside a
        click handler (mousePressEvent of a live item) is unsafe and would
        kill the rubber-band interplay at the same time."""
        selected = self._model.selected_activity
        selected_rel = self._model.selected_relationship
        for aid, node in self._graph_nodes.items():
            node.set_selected(selected == aid)
        for edge in self._graph_edges:
            edge.set_selected(selected_rel == (edge._source, edge._target))

    def _on_activity_added(self, activity_id: str) -> None:
        pass  # Row is added in _on_add_activity

    def _on_activity_removed(self, activity_id: str) -> None:
        self._remove_activity_row(activity_id)

    def _on_activity_changed(self, activity_id: str) -> None:
        self._update_inspector_activity(activity_id)

    def _on_relationship_changed(self, _a: str = "", _b: str = "") -> None:
        self._update_relationships_display()

    # ── Display updates ──────────────────────────────────────

    def _update_relationships_display(self) -> None:
        rels = self._model.get_all_relationships()
        # Clear the chips row (the trailing stretch stays in place).
        while self._rel_chips_layout.count() > 1:
            item = self._rel_chips_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not rels:
            self._rel_list_label.setText("No relationships defined.")
            self._rel_list_label.show()
            self._rel_chips_area.hide()
        else:
            for index, rel in enumerate(rels):
                self._rel_chips_layout.insertWidget(index, self._make_relationship_chip(rel))
            self._rel_list_label.hide()
            self._rel_chips_area.show()

    def _make_relationship_chip(self, rel) -> QWidget:
        """One removable "A → B ✕" chip for the relationships bar."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setStyleSheet(
            f"QFrame {{ background: {ELEVATED}; border: 1px solid {BORDER};"
            f" border-radius: 10px; }}"
            f"QFrame:hover {{ border: 1px solid {ACCENT}; }}"
        )
        chip_layout = QHBoxLayout(frame)
        chip_layout.setContentsMargins(10, 2, 4, 2)
        chip_layout.setSpacing(4)

        text = QLabel(f"{rel.source} \u2192 {rel.target}")
        text.setFont(QFont(*STATUS_FONT))
        text.setStyleSheet(
            f"color: {TEXT}; background: transparent; border: none;"
        )
        chip_layout.addWidget(text)

        remove_btn = QPushButton("\u2715")
        remove_btn.setFixedSize(18, 18)
        remove_btn.setFont(QFont(*MUTED_FONT))
        # padding/min-height: 0 counters the global button box model, which
        # would otherwise clip the glyph inside this tiny control.
        remove_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED};"
            f" border: none; border-radius: 9px; padding: 0px;"
            f" min-height: 0px; }}"
            f"QPushButton:hover {{ background: {DANGER}33; color: {DANGER}; }}"
        )
        remove_btn.clicked.connect(
            lambda checked=False, s=rel.source, t=rel.target:
                self._on_delete_relationship(s, t)
        )
        chip_layout.addWidget(remove_btn)

        return frame

    def _update_inspector_activity(self, activity_id: str) -> None:
        entry = self._model.get_activity(activity_id)
        if entry is None:
            self._reset_inspector()
            return
        self._clear_inspector_actions()

        preds = self._model.get_predecessors(activity_id)
        succs = self._model.get_successors(activity_id)
        pred_str = ", ".join(preds) if preds else "\u2014"
        succ_str = ", ".join(succs) if succs else "\u2014"
        dur_label = f"{entry.duration} day{'s' if entry.duration != 1 else ''}"

        lines = [
            f"<b style='color:{ACCENT}; font-size:14px;'>{activity_id}</b>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Duration:</span> "
            f"<span style='color:{TEXT};'>{dur_label}</span>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Predecessors:</span> "
            f"<span style='color:{TEXT};'>{pred_str}</span>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Successors:</span> "
            f"<span style='color:{TEXT};'>{succ_str}</span>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Status:</span> "
            f"<span style='color:{SUCCESS};'>Valid</span>",
        ]

        if self._model.cpm_result is not None and not self._model.cpm_is_stale:
            act_analysis = self._model.cpm_result.activity_analyses.get(activity_id)
            if act_analysis:
                critical_label = "YES" if act_analysis.is_critical else "NO"
                critical_color = WARNING if act_analysis.is_critical else TEXT
                lines.extend([
                    f"<br><br><b style='color:{TEXT_SECONDARY};'>CPM Analysis</b>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>ES:</span> "
                    f"<span style='color:{TEXT};'>{act_analysis.early_start}</span>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>EF:</span> "
                    f"<span style='color:{TEXT};'>{act_analysis.early_finish}</span>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>LS:</span> "
                    f"<span style='color:{TEXT};'>{act_analysis.late_start}</span>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>LF:</span> "
                    f"<span style='color:{TEXT};'>{act_analysis.late_finish}</span>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>Total Float:</span> "
                    f"<span style='color:{TEXT};'>{act_analysis.total_float}</span>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>Free Float:</span> "
                    f"<span style='color:{TEXT};'>{act_analysis.free_float}</span>",
                    f"<br><span style='color:{TEXT_SECONDARY};'>Critical:</span> "
                    f"<span style='color:{critical_color};'>{critical_label}</span>",
                ])
        elif self._model.cpm_result is not None and self._model.cpm_is_stale:
            lines.extend([
                f"<br><br><span style='color:{WARNING};'>"
                f"\u26a0 CPM results are outdated &mdash; the network has changed "
                f"since they were computed. Recalculate to restore ES/EF/LS/LF.</span>",
            ])

        self._inspector_content.setText("".join(lines))
        self._inspector_content.setTextFormat(Qt.TextFormat.RichText)

    def _add_inspector_delete_relationship(self, src: str, tgt: str) -> None:
        """Offer a direct way to remove the relationship being inspected."""
        delete_btn = QPushButton("Delete relationship")
        delete_btn.setFont(QFont(*STATUS_FONT))
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {DANGER};"
            f" border: 1px solid {DANGER}66; border-radius: 6px;"
            f" padding: 5px 10px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {DANGER}22;"
            f" border: 1px solid {DANGER}; }}"
        )
        delete_btn.clicked.connect(
            lambda checked=False, s=src, t=tgt: self._on_delete_relationship(s, t)
        )
        self._inspector_action_layout.addWidget(delete_btn)
        self._inspector_action_layout.addStretch()

    def _clear_inspector_actions(self) -> None:
        while self._inspector_action_layout.count():
            item = self._inspector_action_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _on_delete_relationship(self, source: str, target: str) -> None:
        err = self._model.remove_relationship(source, target)
        if err:
            QMessageBox.warning(self, "Remove Relationship", err)

    def _reset_inspector(self) -> None:
        self._inspector_content.setText(
            "Select an activity or relationship\nfrom the network to inspect it."
        )
        self._inspector_content.setTextFormat(Qt.TextFormat.PlainText)
        self._clear_inspector_actions()

    def _update_inspector_relationship(self, item_id: str) -> None:
        parts = item_id.split("\u2192")
        if len(parts) != 2:
            return
        src, tgt = parts[0].strip(), parts[1].strip()

        lines = [
            f"<b style='color:{ACCENT}; font-size:14px;'>Relationship</b>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Source:</span> "
            f"<span style='color:{TEXT};'>{src}</span>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Target:</span> "
            f"<span style='color:{TEXT};'>{tgt}</span>",
            f"<br><span style='color:{TEXT_SECONDARY};'>Status:</span> "
            f"<span style='color:{SUCCESS};'>Valid</span>",
        ]
        self._inspector_content.setText("".join(lines))
        self._inspector_content.setTextFormat(Qt.TextFormat.RichText)
        self._clear_inspector_actions()
        self._add_inspector_delete_relationship(src, tgt)

    def _update_graph_display(self) -> None:
        """Render the live AON network as real nodes and dependency arrows."""
        self._graph_scene.clear()
        acts = self._model.get_all_activities()
        rels = self._model.get_all_relationships()
        if not acts:
            # Dead maps would keep pointing at cleared scene items and
            # make every later count stale — wipe them with the canvas.
            self._graph_nodes = {}
            self._graph_edges = []
            self._build_empty_canvas_hint()
            self._graph_view.setSceneRect(self._graph_scene.itemsBoundingRect())
            # A cleared canvas is a fundamentally new content state: any
            # previous zoom makes no sense for the guidance composition.
            self._user_zoomed = False
            self.fit_graph()
            return

        ids = [a.activity_id for a in acts]
        positions = network_layout.build_layout(ids, rels)
        cpm = self._model.cpm_result
        analyses = getattr(cpm, "activity_analyses", {}) if cpm else {}

        self._graph_nodes = {}
        for aid, (x, y, w, h) in positions.items():
            node = _GraphNodeItem(aid, x, y, w, h)
            node.set_metrics(
                duration=self._model.get_activity(aid).duration,
                is_critical=bool(getattr(analyses.get(aid), "is_critical", False)),
                is_selected=(self._model.selected_activity == aid),
            )
            node.connect(lambda nid=aid: self._model.select_activity(nid))
            self._graph_scene.addItem(node)
            self._graph_nodes[aid] = node

        self._graph_edges = []
        for r in rels:
            start, end = network_layout.edge_points(positions, r.source, r.target)
            edge = _GraphEdgeItem(r.source, r.target, start, end)
            edge.set_selected(
                self._model.selected_relationship == (r.source, r.target)
            )
            edge.connect(
                lambda s=r.source, t=r.target: self._model.select_relationship(s, t)
            )
            self._graph_scene.addItem(edge)
            self._graph_edges.append(edge)

        self._graph_view.setSceneRect(
            self._graph_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        )
        if not self._user_zoomed:
            self.fit_graph()
        # fit_in_view leaves a round-off pixel or two inside the bars;
        # reset them so no scrollbar ghosts the canvas edge.
        self._graph_view.horizontalScrollBar().setValue(0)
        self._graph_view.verticalScrollBar().setValue(0)
        # First meaningful content: point the inspector at the first activity
        # instead of greeting a populated network with "select something".
        if (self._model.selected_activity is None
                and self._model.selected_relationship is None):
            self._model.select_activity(next(iter(self._graph_nodes)))

    def _build_empty_canvas_hint(self) -> None:
        """Compose the first-time guidance: a mini AON glyph plus copy.

        Drawn with the very same node/edge primitives the live network
        uses, so the canvas demonstrates the product instead of going
        quiet until the first click."""
        positions = {
            "A": (150, 26, 64, 34),
            "B": (356, 26, 64, 34),
            "C": (253, 106, 64, 34),
        }
        durations = {"A": 1, "B": 2, "C": 2}
        for aid, (x, y, w, h) in positions.items():
            node = _GraphNodeItem(aid, x, y, w, h)
            # Decorative props, not live widgets: ignore clicks.
            node.setFlag(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False
            )
            node.set_metrics(
                duration=durations[aid], is_critical=False, is_selected=False
            )
            self._graph_scene.addItem(node)
        for src, tgt in (("A", "B"), ("A", "C"), ("B", "C")):
            start, end = network_layout.edge_points(positions, src, tgt)
            edge = _GraphEdgeItem(src, tgt, start, end)
            edge.setFlag(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False
            )
            self._graph_scene.addItem(edge)

        cx = 285  # glyph horizontal center (150..420)
        title = QGraphicsTextItem("Your network takes shape here")
        title.setDefaultTextColor(QColor(TEXT))
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
        title.setTextWidth(340)
        title.document().setDefaultTextOption(
            QTextOption(Qt.AlignmentFlag.AlignHCenter)
        )
        title.setPos(cx - 170, 154)
        self._graph_scene.addItem(title)

        subtitle = QGraphicsTextItem(
            "Add an activity on the left, or press Load Example below "
            "to start from the reference network."
        )
        subtitle.setDefaultTextColor(QColor(TEXT_MUTED))
        f2 = subtitle.font()
        f2.setPointSize(10)
        subtitle.setFont(f2)
        subtitle.setTextWidth(360)
        subtitle.document().setDefaultTextOption(
            QTextOption(Qt.AlignmentFlag.AlignHCenter)
        )
        subtitle.setPos(cx - 180, 186)
        self._graph_scene.addItem(subtitle)

    def fit_graph(self) -> None:
        try:
            self._graph_view.fitInView(
                self._graph_scene.itemsBoundingRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        except Exception:  # noqa: BLE001 (empty/invalid rect is fine)
            pass

    def _on_zoom_in(self) -> None:
        self._user_zoomed = True
        self._graph_view.scale(1.2, 1.2)

    def _on_zoom_out(self) -> None:
        self._user_zoomed = True
        self._graph_view.scale(1.0 / 1.2, 1.0 / 1.2)

    def _on_fit(self) -> None:
        self._user_zoomed = False
        self.fit_graph()

    # ── Action handlers ──────────────────────────────────────

    def _on_calculate_cpm(self) -> None:
        err = self._model.calculate_cpm()
        if err:
            QMessageBox.warning(self, "CPM Analysis", err)

    def _on_analyze(self) -> None:
        """Build the candidate and signal the main window to show results."""
        logger.info("[BUILDER] Analyze button clicked")
        logger.info("[BUILDER] Activity count: %d", self._model.activity_count)
        logger.info("[BUILDER] Dependency count: %d", self._model.dependency_count)
        self.analyze_requested.emit()

    def _on_load_example(self) -> None:
        reply = QMessageBox.question(
            self, "Load Example",
            "Load the reference AON example (A\u2013V, 22 activities)?\n\n"
            "This will replace any current data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._reload_from_model()

    def _on_clear(self) -> None:
        if not self._model.has_activities:
            return
        reply = QMessageBox.question(
            self, "Clear All",
            "Remove all activities and relationships?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._model.clear()
            self._reload_from_model()

    def _reload_from_model(self) -> None:
        """Rebuild the UI from the model state."""
        # Clear existing rows
        while self._activity_layout.count():
            item = self._activity_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self._activity_layout.addStretch()

        if self._model.activity_count > 0:
            self._empty_label.hide()
            for entry in self._model.get_all_activities():
                self._add_activity_row(entry.activity_id)
        else:
            self._empty_label.show()

        self._on_model_changed()
        self._on_validation_changed()
        # _on_model_changed may have auto-selected the first activity and
        # already filled the inspector — only reset it when nothing is
        # selected (e.g. the model was cleared).
        if (self._model.selected_activity is None
                and self._model.selected_relationship is None):
            self._reset_inspector()

    # ── Public API ───────────────────────────────────────────

    def refresh(self, session: Any) -> None:
        """Called by MainWindow when navigating to this page."""
        pass

    def get_model(self) -> ManualNetworkModel:
        return self._model


class _GraphNodeItem(QGraphicsRectItem):
    """Clickable node box for the live network canvas."""

    def __init__(self, activity_id: str, x: float, y: float,
                 w: float, h: float) -> None:
        super().__init__(x, y, w, h)
        self._activity_id = activity_id
        self._click_handlers = []
        self._is_critical = False
        self._is_selected = False
        self.setBrush(QColor(SURFACE_LIGHT))
        self._apply_pen()
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        self._id_item = QGraphicsTextItem(activity_id, self)
        self._dur_item = QGraphicsTextItem("", self)
        for text_item in (self._id_item, self._dur_item):
            text_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            text_item.setAcceptHoverEvents(False)

    # QGraphicsItem is not a QObject, so expose a signal-like API.
    def connect(self, handler) -> None:
        self._click_handlers.append(handler)

    def _emit_clicked(self) -> None:
        for handler in self._click_handlers:
            handler(self._activity_id)

    def _apply_pen(self) -> None:
        if self._is_selected:
            self.setPen(QPen(QColor(ACCENT), 2.6))
        elif self._is_critical:
            self.setPen(QPen(QColor(WARNING), 2.2))
        else:
            self.setPen(QPen(QColor(BORDER), 1.2))

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self._apply_pen()
        self.update()

    def set_metrics(self, duration: float, is_critical: bool,
                    is_selected: bool) -> None:
        self._is_critical = is_critical
        self._is_selected = is_selected
        self._apply_pen()

        self._id_item.setPlainText(self._activity_id)
        self._id_item.setDefaultTextColor(QColor(TEXT))
        f = self._id_item.font()
        f.setBold(True)
        f.setPointSize(10)
        self._id_item.setFont(f)
        # Center computationally instead of hard-coded pixel offsets, so
        # any node size (and the empty-state glyph) stays optically true.
        cx = self.rect().center().x()
        ibr = self._id_item.boundingRect()
        self._id_item.setPos(
            cx - ibr.width() / 2,
            self.rect().top() + self.rect().height() * 0.12,
        )

        self._dur_item.setPlainText(f"{duration:g} d")
        self._dur_item.setDefaultTextColor(
            QColor(WARNING) if self._is_critical else QColor(TEXT_SECONDARY)
        )
        f2 = self._dur_item.font()
        f2.setPointSize(9)
        self._dur_item.setFont(f2)
        dbr = self._dur_item.boundingRect()
        self._dur_item.setPos(
            cx - dbr.width() / 2,
            self.rect().top() + self.rect().height() * 0.58,
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._emit_clicked()
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self.setBrush(QColor(ELEVATED))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.setBrush(QColor(SURFACE_LIGHT))
        super().hoverLeaveEvent(event)


class _GraphEdgeItem(QGraphicsRectItem):
    """Clickable dependency arrow between two activity nodes.

    A single item whose paint() draws the connecting line plus an
    arrowhead, with a fat invisible hit-rect for easier selection.
    """

    def __init__(self, source: str, target: str, start, end) -> None:
        super().__init__()
        self._source = source
        self._target = target
        self._click_handlers = []
        self._start = QPointF(start[0], start[1])
        self._end = QPointF(end[0], end[1])
        self._is_selected = False

        dx = self._end.x() - self._start.x()
        dy = self._end.y() - self._start.y()
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        dir_x, dir_y = dx / length, dy / length
        del dir_x, dir_y
        perp = 6.0
        self.setRect(
            min(self._start.x(), self._end.x()) - perp,
            min(self._start.y(), self._end.y()) - perp,
            abs(dx) + 2 * perp,
            abs(dy) + 2 * perp,
        )
        self.setPen(QPen(QColor(0, 0, 0, 0)))
        self.setBrush(QColor(0, 0, 0, 0))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)

    # QGraphicsItem is not a QObject, so expose a signal-like API.
    def connect(self, handler) -> None:
        self._click_handlers.append(handler)

    def _emit_clicked(self) -> None:
        for handler in self._click_handlers:
            handler(self._source, self._target)

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        del option, widget
        color = ACCENT if self._is_selected else TEXT
        width = 2.5 if self._is_selected else 2.0
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(self._start, self._end)

        angle = math.atan2(self._end.y() - self._start.y(),
                           self._end.x() - self._start.x())
        head = 11.0
        ax1 = self._end.x() - head * math.cos(angle - 0.42)
        ay1 = self._end.y() - head * math.sin(angle - 0.42)
        ax2 = self._end.x() - head * math.cos(angle + 0.42)
        ay2 = self._end.y() - head * math.sin(angle + 0.42)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([
            QPointF(self._end.x(), self._end.y()),
            QPointF(ax1, ay1),
            QPointF(ax2, ay2),
        ]))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._emit_clicked()
        super().mousePressEvent(event)
