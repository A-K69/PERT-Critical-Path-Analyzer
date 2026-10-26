"""
Activities tab: read-only activity table + detail panel.

Presents the backend ActivityAnalysis / GraphModel snapshot. CPM values are
displayed verbatim; a missing field renders as "Unavailable" instead of
being recomputed. Results are read-only (editing is deliberately disabled).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.results.formatting import format_days, format_number
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_MUTED,
    WARNING,
)
from pert_analyzer.gui.themes.typography import LABEL_FONT, MUTED_FONT, STATUS_FONT

TABLE_COLUMNS = [
    "ID",
    "Duration",
    "ES",
    "EF",
    "LS",
    "LF",
    "Total Float",
    "Free Float",
    "Critical",
    "Predecessors",
    "Successors",
]


class _NumericItem(QTableWidgetItem):
    """Table item that sorts numerically while displaying cleanly."""

    def __init__(self, value: Optional[float], text: str):
        super().__init__(text)
        self._value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight)

    def __lt__(self, other) -> bool:  # noqa: D105
        if isinstance(other, _NumericItem):
            left = self._value if self._value is not None else float("inf")
            right = other._value if other._value is not None else float("inf")
            return left < right
        return super().__lt__(other)


def _cell(text: str, value: Optional[float] = None) -> QTableWidgetItem:
    if value is None:
        return QTableWidgetItem(text)
    return _NumericItem(value, text)


class ActivitiesTab(QWidget):
    """Activity table with sorting, selection, and a read-only detail panel."""

    activity_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: List[Any] = []
        self._table = QTableWidget(0, len(TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col in (0, 1, 2, 3, 4, 5, 6, 7, 8):
            header.resizeSection(col, 54 if col in (2, 3, 4, 5) else 60)
        header.setStretchLastSection(True)
        # Default sort indicator: later clicks start ascending.  Populated rows
        # are re-sorted by this indicator in set_data, so the table opens on
        # the scan order (A -> V) instead of the header's descending default.
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px;}}"
            f"QHeaderView::section {{ background-color: {SURFACE_LIGHT};"
            f" color: {TEXT}; border: none;"
            f" border-right: 1px solid {BORDER}; padding: 4px;}}"
            f"QTableWidget::item:selected {{ background-color: {ACCENT};"
            f" color: white;}}"
        )
        self._table.currentCellChanged.connect(self._on_cell_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        heading = QLabel("Activities")
        heading.setFont(QFont(*LABEL_FONT))
        root.addWidget(heading)

        self._empty_label = QLabel("No activity data to display.")
        self._empty_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self._empty_label.setWordWrap(True)
        self._empty_label.hide()
        root.addWidget(self._empty_label)

        # Horizontal split: the table owns the full page height (scrolls
        # internally instead of being squeezed by the detail block below it),
        # and the read-only detail panel sits beside it, always visible.
        panel = self._build_detail_panel()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(340)
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(10)
        split.addWidget(self._table, stretch=1)
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(panel)
        side.addStretch(1)
        split.addLayout(side)
        root.addLayout(split, stretch=1)

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setStyleSheet(
            f"background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: 8px;"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Activity detail")
        title.setFont(QFont(*STATUS_FONT))
        header.addWidget(title)
        header.addStretch()
        self._critical_badge = QLabel("")
        self._critical_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._critical_badge.setStyleSheet(
            "border: none; background: transparent;"
        )
        header.addWidget(self._critical_badge)
        layout.addLayout(header)

        self._detail_fields: Dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        _NONE = object()
        fields = [
            ("Activity ID", "id"),
            ("Duration", "duration"),
            ("Early Start", "es"),
            ("Early Finish", "ef"),
            ("Late Start", "ls"),
            ("Late Finish", "lf"),
            ("Total Float", "tf"),
            ("Free Float", "ff"),
            ("Critical", "critical"),
            ("Predecessors", "pred"),
            ("Successors", "succ"),
        ]
        for col, (label, key) in enumerate(fields):
            row, column = divmod(col, 2)
            lab = QLabel(label)
            lab.setFont(QFont(*MUTED_FONT))
            lab.setStyleSheet(
                f"color: {TEXT_MUTED}; border: none; background: transparent;"
            )
            value = QLabel("")
            value.setFont(QFont(*STATUS_FONT))
            value.setStyleSheet("border: none; background: transparent;")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(lab, row * 2, column * 2)
            grid.addWidget(value, row * 2 + 1, column * 2)
            self._detail_fields[key] = value
        # value columns take the leftover panel width so long lists
        # ("S, R", "O, P") wrap inside the column instead of widening it
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        return panel

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_data(self, activities: List[Any]) -> None:
        self._rows = list(activities)
        sorting = self._table.isSortingEnabled()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._rows))
        for row, activity in enumerate(self._rows):
            self._populate_row(row, activity)
        self._table.setSortingEnabled(sorting)
        if not self._rows:
            self._empty_label.show()
            self._table.hide()
            self._clear_detail()
            return
        self._empty_label.hide()
        self._table.show()
        self._table.selectRow(0)

    def _populate_row(self, row: int, activity: Any) -> None:
        critical = bool(activity.is_critical)
        values = (
            (activity.activity_id, None),
            (format_number(activity.duration), activity.duration),
            (format_days(activity.early_start), activity.early_start),
            (format_days(activity.early_finish), activity.early_finish),
            (format_days(activity.late_start), activity.late_start),
            (format_days(activity.late_finish), activity.late_finish),
            (format_number(activity.total_float), activity.total_float),
            (format_number(activity.free_float), activity.free_float),
            ("Yes" if critical else "No", 1 if critical else 0),
            (_format_list(activity.predecessors), None),
            (_format_list(activity.successors), None),
        )
        for col, (text, value) in enumerate(values):
            item = _cell(text, value)
            if critical:
                item.setBackground(QBrush(QColor(0x2C, 0x32, 0x2E)))
            self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Selection / detail
    # ------------------------------------------------------------------

    def _on_cell_changed(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        del col, prev_row, prev_col
        if 0 <= row < len(self._rows):
            activity = self._rows[row]
            self._show_detail(activity)
            self.activity_selected.emit(activity.activity_id)

    def select_activity(self, activity_id: str) -> bool:
        """Select the row for an activity id. Returns True when found."""
        for row, activity in enumerate(self._rows):
            if activity.activity_id == activity_id:
                self._table.selectRow(row)
                self._table.setCurrentCell(row, 0)
                return True
        return False

    def selected_activity_id(self) -> Optional[str]:
        row = self._table.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row].activity_id
        return None

    def _show_detail(self, activity: Any) -> None:
        critical = bool(activity.is_critical)
        self._critical_badge.setText("\u25cf Critical Activity" if critical else "")
        if critical:
            self._critical_badge.setStyleSheet(
                f"color: {WARNING}; border: 1px solid {WARNING};"
                " border-radius: 8px; padding: 1px 8px; background: transparent;"
            )
        else:
            self._critical_badge.setStyleSheet(
                "border: none; background: transparent;"
            )
        self._set_field("id", activity.activity_id)
        self._set_field("duration", format_number(activity.duration))
        self._set_field("es", format_days(activity.early_start))
        self._set_field("ef", format_days(activity.early_finish))
        self._set_field("ls", format_days(activity.late_start))
        self._set_field("lf", format_days(activity.late_finish))
        self._set_field("tf", format_number(activity.total_float))
        self._set_field("ff", format_number(activity.free_float))
        self._set_field("critical", "Yes" if critical else "No")
        self._set_field("pred", _format_list(activity.predecessors))
        self._set_field("succ", _format_list(activity.successors))

    def _clear_detail(self) -> None:
        self._critical_badge.setText("")
        self._critical_badge.setStyleSheet("border: none; background: transparent;")
        for label in self._detail_fields.values():
            label.setText("")

    def _set_field(self, key: str, text: str) -> None:
        label = self._detail_fields.get(key)
        if label is not None:
            label.setText(text)

    def table(self) -> QTableWidget:
        return self._table

    def detail_fields(self) -> Dict[str, QLabel]:
        return dict(self._detail_fields)

    def rows(self) -> List[Any]:
        return list(self._rows)


def _format_list(items: Any) -> str:
    if not items:
        return ""
    if isinstance(items, (list, tuple)):
        return ", ".join(str(x) for x in items)
    return str(items)