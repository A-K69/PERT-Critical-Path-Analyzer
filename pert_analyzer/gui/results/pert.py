"""
PERT tab: three-point estimate entry + PERT results presentation.

The tab never computes TE / variance / std-dev itself. The backend
PertEngine derives the state (NO_PERT_DATA / PERT_REVIEW_REQUIRED /
PERT_INVALID / PERT_READY) and the backend PertResult is displayed verbatim.
Missing values render as "Unavailable" or as an empty cell; no fake zeros
are ever shown.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.analysis.pert_engine import PertEstimate, PertStatus
from pert_analyzer.gui.results.data import (
    PERT_NO_DATA_HINT,
    PERT_NO_DATA_TITLE,
    extract_pert,
)
from pert_analyzer.gui.results.formatting import format_duration, format_number
from pert_analyzer.gui.results.overview import KpiCard
from pert_analyzer.gui.results.paths import PathList
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    DANGER,
    SUCCESS,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_MUTED,
    WARNING,
)
from pert_analyzer.gui.themes.typography import (
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    TITLE_FONT,
)

ESTIMATE_COLUMNS = ["ID", "Optimistic (O)", "Most Likely (M)", "Pessimistic (P)"]
RESULT_COLUMNS = ["ID", "O", "M", "P", "Expected Time", "Variance", "Std Dev", "Critical"]

REVIEW_REQUIRED_TEXT = (
    "PERT analysis needs a complete three-point estimate (O, M, P) for every "
    "activity. Complete the missing values to continue."
)
INVALID_TEXT = (
    "PERT estimates are invalid. For each activity O, M and P must be numeric "
    "with 0 \u2264 O \u2264 M \u2264 P."
)
READY_TEXT = (
    "PERT estimates are ready. Click Run PERT to analyze the project using "
    "expected times."
)


class PertTab(QWidget):
    """PERT estimates editor and results presentation tab."""

    pert_run_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._session: Any = None
        self._graph: Any = None
        self._rows: List[str] = []
        self._draft: Dict[str, List[Optional[float]]] = {}
        self._populating = False
        self._data: Any = None
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        heading = QLabel("PERT analysis")
        heading.setFont(QFont(*TITLE_FONT))
        root.addWidget(heading)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setFont(QFont(*LABEL_FONT))
        self._status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        root.addWidget(self._status_label)

        root.addWidget(self._build_estimates_section())
        root.addLayout(self._build_actions())

        self._results_frame = self._build_results_section()
        root.addWidget(self._results_frame, stretch=1)

        self._sync_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_estimates_section(self) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setStyleSheet(
            f"background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px;"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        title = QLabel("PERT estimates")
        title.setFont(QFont(*STATUS_FONT))
        layout.addWidget(title)

        hint = QLabel(
            "Enter optimistic, most likely and pessimistic durations (days) "
            "for each activity. Values may be decimals."
        )
        hint.setWordWrap(True)
        hint.setFont(QFont(*MUTED_FONT))
        hint.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(hint)

        self._estimates_table = QTableWidget(0, len(ESTIMATE_COLUMNS))
        self._estimates_table.setHorizontalHeaderLabels(ESTIMATE_COLUMNS)
        self._estimates_table.setAlternatingRowColors(True)
        self._estimates_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectItems
        )
        self._estimates_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._estimates_table.verticalHeader().setVisible(False)
        header = self._estimates_table.horizontalHeader()
        # Balanced entry grid: compact auto-sized ID plus three equal O/M/P
        # columns sharing the width.  The previous Interactive +
        # stretched-last-section setup squeezed O/M to their defaults while
        # P swallowed the remaining ~1100px.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        self._estimates_table.setStyleSheet(
            f"QTableWidget {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;}}"
            f"QHeaderView::section {{ background-color: {SURFACE};"
            f" color: {TEXT}; border: none;"
            f" border-right: 1px solid {BORDER}; padding: 4px;}}"
        )
        self._estimates_table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self._estimates_table)
        return frame

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        self._run_btn = QPushButton("Run PERT")
        self._run_btn.setToolTip(
            "Analyze the project using PERT expected times. "
            "Requires valid O, M and P estimates for every activity."
        )
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run_clicked)
        actions.addWidget(self._run_btn)
        return actions

    def _build_results_section(self) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setStyleSheet(
            f"background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px;"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Project under expected times")
        title.setFont(QFont(*STATUS_FONT))
        layout.addWidget(title)

        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        self._kpi_cards: Dict[str, KpiCard] = {}
        for key, label in (
            ("expected_duration", "Expected Project Duration"),
            ("project_variance", "Project Variance"),
            ("project_std_dev", "Project Std Dev"),
            ("probability", "Completion Probability"),
        ):
            card = KpiCard(label)
            self._kpi_cards[key] = card
            self._cards_row.addWidget(card)
        self._probability = self._build_probability_control()
        self._cards_row.addWidget(self._probability)
        layout.addLayout(self._cards_row)

        self._results_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._results_table.setHorizontalHeaderLabels(RESULT_COLUMNS)
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._results_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._results_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setSortingEnabled(True)
        rheader = self._results_table.horizontalHeader()
        # Same balanced treatment as the estimates table: fixed ID, the
        # remaining result columns share the width equally.
        rheader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        rheader.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        rheader.resizeSection(0, 52)
        for col in range(1, len(RESULT_COLUMNS)):
            rheader.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        rheader.setStretchLastSection(False)
        self._results_table.setStyleSheet(
            f"QTableWidget {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;}}"
            f"QHeaderView::section {{ background-color: {SURFACE};"
            f" color: {TEXT}; border: none;"
            f" border-right: 1px solid {BORDER}; padding: 4px;}}"
        )
        layout.addWidget(self._results_table)

        paths_heading = QLabel("PERT Critical Paths")
        paths_heading.setFont(QFont(*LABEL_FONT))
        layout.addWidget(paths_heading)
        self._path_list = PathList()
        layout.addWidget(self._path_list)

        frame.setVisible(False)
        return frame

    def _build_probability_control(self) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.NoFrame)
        box.setStyleSheet(
            f"background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px;"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        label = QLabel("Probability target")
        label.setFont(QFont(*MUTED_FONT))
        label.setStyleSheet(
            f"color: {TEXT_MUTED}; border: none; background: transparent;"
        )
        layout.addWidget(label)
        self._target_spin = QDoubleSpinBox()
        self._target_spin.setRange(0.0, 1_000_000.0)
        self._target_spin.setDecimals(1)
        self._target_spin.setValue(0.0)
        self._target_spin.valueChanged.connect(self._on_target_changed)
        layout.addWidget(self._target_spin)
        return box

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def refresh(self, session: Any) -> None:
        """Repopulate from the given GuiSession (graph + estimates)."""
        self._session = session
        self._populate_estimates()
        self._sync_state()

    def _populate_estimates(self) -> None:
        self._populating = True
        session = self._session
        graph = getattr(session, "graph_model", None) if session else None
        self._graph = graph
        session_estimates = getattr(session, "pert_estimates", None) or {}
        ids = sorted(graph.activities) if graph is not None else []

        self._rows = ids
        self._draft = {}
        self._estimates_table.setRowCount(0)
        self._estimates_table.setRowCount(len(ids))
        for row, aid in enumerate(ids):
            o, m, p = self._values_for(aid, graph, session_estimates)
            self._draft[aid] = [o, m, p]
            id_item = QTableWidgetItem(aid)
            flags = id_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            id_item.setFlags(flags)
            self._estimates_table.setItem(row, 0, id_item)
            for col, value in ((1, o), (2, m), (3, p)):
                item = QTableWidgetItem("" if value is None else format_number(value))
                self._estimates_table.setItem(row, col, item)
        self._populating = False

    @staticmethod
    def _values_for(
        aid: str,
        graph: Any,
        session_estimates: Dict[str, PertEstimate],
    ) -> tuple:
        est = session_estimates.get(aid)
        if est is not None:
            return est.optimistic, est.most_likely, est.pessimistic
        if graph is None:
            return None, None, None
        act = graph.activities.get(aid)
        return (
            getattr(act, "optimistic_time", None),
            getattr(act, "most_likely_time", None),
            getattr(act, "pessimistic_time", None),
        )

    # ------------------------------------------------------------------
    # Estimate editing
    # ------------------------------------------------------------------

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._populating or col == 0:
            return
        if not (0 <= row < len(self._rows)):
            return
        aid = self._rows[row]
        item = self._estimates_table.item(row, col)
        value = self._parse_cell(item.text() if item else "")
        values = self._draft.setdefault(aid, [None, None, None])
        values[col - 1] = value
        self._write_back_estimates()
        self._sync_state()

    @staticmethod
    def _parse_cell(text: str) -> Optional[float]:
        stripped = text.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None

    def _write_back_estimates(self) -> None:
        session = self._session
        if session is None:
            return
        estimates: Dict[str, PertEstimate] = {}
        for aid, (o, m, p) in self._draft.items():
            if o is None and m is None and p is None:
                continue
            estimates[aid] = PertEstimate(
                optimistic=o, most_likely=m, pessimistic=p
            )
        session.pert_estimates = estimates
        # Estimates changed; any previous PERT result is now stale.
        session.pert_result = None

    # ------------------------------------------------------------------
    # State / results
    # ------------------------------------------------------------------

    def _sync_state(self) -> None:
        session = self._session
        if session is None:
            return
        data = extract_pert(session)
        self._data = data
        session.pert_status = data.status
        self._render_status(data.status)
        ready = data.status == PertStatus.PERT_READY
        self._run_btn.setEnabled(ready and not self._busy)
        self._render_results()

    def _render_status(self, status: PertStatus) -> None:
        text = {
            PertStatus.NO_PERT_DATA: PERT_NO_DATA_TITLE,
            PertStatus.PERT_REVIEW_REQUIRED: REVIEW_REQUIRED_TEXT,
            PertStatus.PERT_INVALID: INVALID_TEXT,
            PertStatus.PERT_READY: READY_TEXT,
        }[status]
        if status == PertStatus.NO_PERT_DATA:
            text = f"{text}\n{PERT_NO_DATA_HINT}"
        color = {
            PertStatus.NO_PERT_DATA: TEXT_MUTED,
            PertStatus.PERT_REVIEW_REQUIRED: WARNING,
            PertStatus.PERT_INVALID: DANGER,
            PertStatus.PERT_READY: SUCCESS,
        }[status]
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color};")

    def _render_results(self) -> None:
        data = self._data
        ready = (
            data is not None
            and data.status == PertStatus.PERT_READY
            and data.result is not None
        )
        self._results_frame.setVisible(ready)
        if not ready:
            self._clear_results()
            return
        self._kpi_cards["expected_duration"].set_value(
            format_duration(data.project_duration)
        )
        self._kpi_cards["project_variance"].set_value(
            format_number(data.project_variance)
        )
        self._kpi_cards["project_std_dev"].set_value(
            format_number(data.project_std_dev)
        )
        target = self._target_spin.value()
        probability = data.result.probability_for(target)
        self._kpi_cards["probability"].set_value(
            f"{probability.probability * 100:.1f}%"
        )
        self._target_spin.setEnabled(True)

        self._results_table.setSortingEnabled(False)
        self._results_table.setRowCount(0)
        self._results_table.setRowCount(len(data.rows))
        for row, entry in enumerate(data.rows):
            self._populate_result_row(row, entry)
        self._results_table.setSortingEnabled(True)

        self._path_list.set_paths(data.critical_paths, data.project_duration)

    def _populate_result_row(self, row: int, entry: Any) -> None:
        values = (
            (entry.activity_id, None),
            (format_number(entry.optimistic), entry.optimistic),
            (format_number(entry.most_likely), entry.most_likely),
            (format_number(entry.pessimistic), entry.pessimistic),
            (format_number(entry.expected_time), entry.expected_time),
            (format_number(entry.variance), entry.variance),
            (format_number(entry.std_dev), entry.std_dev),
            ("Yes" if entry.is_critical else "No", 1 if entry.is_critical else 0),
        )
        for col, (text, value) in enumerate(values):
            item = _numeric_item(text, value)
            self._results_table.setItem(row, col, item)

    def _clear_results(self) -> None:
        for card in self._kpi_cards.values():
            card.set_value("Unavailable")
        self._target_spin.setValue(0.0)
        self._target_spin.setEnabled(False)
        self._results_table.setRowCount(0)
        self._path_list.clear()

    def _on_target_changed(self, value: float) -> None:
        del value
        data = self._data
        if (
            data is None
            or data.status != PertStatus.PERT_READY
            or data.result is None
        ):
            return
        probability = data.result.probability_for(self._target_spin.value())
        self._kpi_cards["probability"].set_value(
            f"{probability.probability * 100:.1f}%"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        if self._busy:
            return
        self.pert_run_requested.emit()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if self._data is not None:
            self._run_btn.setEnabled(
                self._data.status == PertStatus.PERT_READY and not self._busy
            )

    # ------------------------------------------------------------------
    # Accessors (used by tests and the results page)
    # ------------------------------------------------------------------

    def status_label(self) -> QLabel:
        return self._status_label

    def run_button(self) -> QPushButton:
        return self._run_btn

    def estimates_table(self) -> QTableWidget:
        return self._estimates_table

    def results_table(self) -> QTableWidget:
        return self._results_table

    def summary_cards(self) -> Dict[str, KpiCard]:
        return dict(self._kpi_cards)

    def target_spin(self) -> QDoubleSpinBox:
        return self._target_spin

    def path_list(self) -> PathList:
        return self._path_list

    @property
    def data(self) -> Any:
        return self._data


def _numeric_item(text: str, value: Optional[float]) -> QTableWidgetItem:
    """Sortable numeric table item that tolerates missing values."""
    if value is None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        return item
    return _FloatItem(value, text)


class _FloatItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by float value while displaying cleanly."""

    def __init__(self, value: float, text: str):
        super().__init__(text)
        self._value = float(value)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight)

    def __lt__(self, other) -> bool:  # noqa: D105
        if isinstance(other, _FloatItem):
            return self._value < other._value
        return super().__lt__(other)