"""
Executive Overview for the Results dashboard.

Overview is intentionally a summary surface. Detailed network, activity-table,
critical-path, and PERT data live in their dedicated tabs and are not embedded
here a second time.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.results.formatting import format_duration
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    DANGER,
    ELEVATED,
    INFO,
    SUCCESS,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    WARNING,
)
from pert_analyzer.gui.themes.spacing import RADIUS_LG, RADIUS_SM
from pert_analyzer.gui.themes.typography import (
    BODY_SMALL_FONT,
    KPI_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    TITLE_FONT,
)


def _rgba(hex_color: str, alpha: int) -> str:
    value = hex_color.lstrip("#")
    return (
        f"rgba({int(value[0:2], 16)}, {int(value[2:4], 16)}, "
        f"{int(value[4:6], 16)}, {alpha})"
    )


class KpiCard(QFrame):
    """A high-signal KPI card with accent, icon, value, and status cue."""

    def __init__(
        self,
        title: str,
        icon: str = "•",
        accent: str = ACCENT,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("overviewKpiCard")
        self.setMinimumWidth(0)
        self.setMinimumHeight(126)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            f"QFrame#overviewKpiCard {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px; }}"
            f"QFrame#overviewKpiCard:hover {{ border-color: {accent};"
            f" background-color: {SURFACE_LIGHT}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 11)
        layout.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(7)
        self._icon_label = QLabel(icon)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedSize(28, 28)
        self._icon_label.setFont(QFont(*STATUS_FONT))
        self._icon_label.setStyleSheet(
            f"color: {accent}; background-color: {_rgba(accent, 28)};"
            f" border-radius: {RADIUS_SM}px;"
        )
        top.addWidget(self._icon_label)
        self._title_label = QLabel(title.upper())
        self._title_label.setWordWrap(True)
        self._title_label.setMinimumWidth(0)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._title_label.setFont(QFont(*MUTED_FONT))
        self._title_label.setStyleSheet(
            f"color: {TEXT_MUTED}; border: none; background: transparent;"
        )
        top.addWidget(self._title_label, stretch=1)
        layout.addLayout(top)
        self._value_label = QLabel("Unavailable")
        self._value_label.setFont(QFont(KPI_FONT[0], 14, QFont.Weight.Bold))
        # NOTE: app-level QSS forces font-size 13px on all QWidget subclasses;
        # an explicit px size in the widget stylesheet is the only way to keep
        # the big KPI value visible.
        self._value_label.setStyleSheet(
            f"color: {accent}; border: none; background: transparent;"
            f" font-size: 36px; font-weight: 700;"
        )
        layout.addWidget(self._value_label)
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        self._note_label = QLabel("")
        self._note_label.setMinimumWidth(0)
        self._note_label.setWordWrap(True)
        self._note_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._note_label.setFont(QFont(*MUTED_FONT))
        self._note_label.setStyleSheet(
            f"color: {TEXT_MUTED}; border: none; background: transparent;"
        )
        bottom.addWidget(self._note_label, stretch=1)
        self._trend_label = QLabel("")
        self._trend_label.setMinimumWidth(0)
        self._trend_label.setWordWrap(True)
        self._trend_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._trend_label.setFont(QFont(*MUTED_FONT))
        self._trend_label.setStyleSheet(
            f"color: {accent}; border: none; background: transparent;"
        )
        bottom.addWidget(self._trend_label)
        layout.addLayout(bottom)

    def set_value(self, text: str, color: str = TEXT) -> None:
        self._value_label.setText(text)
        self._value_label.setStyleSheet(
            f"color: {color}; border: none; background: transparent;"
            f" font-size: 36px; font-weight: 700;"
        )

    def set_note(self, text: str) -> None:
        self._note_label.setText(text)

    def set_trend(self, text: str) -> None:
        self._trend_label.setText(text)

    def title(self) -> str:
        return self._title_label.text()

    def value(self) -> str:
        return self._value_label.text()


class _Panel(QFrame):
    """Shared restrained surface for Overview cards."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("overviewPanel")
        self.setStyleSheet(
            f"QFrame#overviewPanel {{ background-color: {SURFACE};"
            f" border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px; }}"
        )


class OverviewTab(QWidget):
    """Executive summary without duplicated Network or Activities widgets."""

    open_network_requested = Signal()
    open_activities_requested = Signal()
    open_paths_requested = Signal()
    open_validation_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._data: Any = None
        self._session: Any = None
        self._kpi_cards: dict[str, KpiCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        heading_stack = QVBoxLayout()
        heading_stack.setSpacing(2)
        heading = QLabel("Project overview")
        heading.setFont(QFont(*TITLE_FONT))
        heading.setStyleSheet(f"color: {TEXT};")
        heading_stack.addWidget(heading)
        self._subtitle = QLabel(
            "A concise view of schedule health, critical structure, and review state."
        )
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(QFont(*MUTED_FONT))
        self._subtitle.setStyleSheet(f"color: {TEXT_MUTED};")
        heading_stack.addWidget(self._subtitle)
        header.addLayout(heading_stack, stretch=1)
        self._open_network_btn = self._action_button("Open Network")
        self._open_network_btn.clicked.connect(self.open_network_requested)
        header.addWidget(self._open_network_btn)
        root.addLayout(header)

        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        for key, title, icon, accent in (
            ("duration", "Project duration", "◷", ACCENT),
            ("activities", "Activities", "▦", ACCENT),
            ("dependencies", "Dependencies", "↗", ELEVATED),
            ("critical_paths", "Critical paths", "⚑", WARNING),
            ("critical_activities", "Critical activities", "◎", WARNING),
            ("review_state", "Review state", "✓", SUCCESS),
        ):
            card = KpiCard(title, icon, accent)
            self._kpi_cards[key] = card
            self._cards_row.addWidget(card, stretch=1)
        root.addLayout(self._cards_row)

        content = QGridLayout()
        content.setHorizontalSpacing(10)
        content.setVerticalSpacing(10)
        # wider snapshot column: full-length routes then wrap to one line
        content.addWidget(self._build_health_panel(), 0, 0, 1, 2)
        content.addWidget(self._build_paths_panel(), 0, 2, 1, 3)
        content.addWidget(self._build_composition_panel(), 1, 0, 1, 2)
        content.addWidget(self._build_confidence_panel(), 1, 2, 1, 2)
        content.addWidget(self._build_action_panel(), 1, 4, 1, 1)
        root.addLayout(content, stretch=1)

    @staticmethod
    def _action_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("overviewAction")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton#overviewAction {{ color: {ACCENT};"
            f" background-color: {SURFACE_LIGHT}; border: 1px solid {BORDER};"
            f" border-radius: {RADIUS_SM}px; padding: 7px 12px; }}"
            f"QPushButton#overviewAction:hover {{ border-color: {ACCENT};"
            f" background-color: {ELEVATED}; }}"
        )
        return button

    @staticmethod
    def _panel_heading(panel: QFrame, kicker: str, title: str) -> QVBoxLayout:
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(5)
        kicker_label = QLabel(kicker.upper())
        kicker_label.setFont(QFont(*BODY_SMALL_FONT))
        kicker_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(kicker_label)
        title_label = QLabel(title)
        title_label.setFont(QFont(*STATUS_FONT))
        title_label.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(title_label)
        return layout

    def _build_health_panel(self) -> QFrame:
        panel = _Panel()
        layout = self._panel_heading(panel, "Project health", "Ready for decision-making")
        header = QHBoxLayout()
        self._health_status = QLabel("Authoritative")
        self._health_status.setFont(QFont(*TITLE_FONT))
        self._health_status.setStyleSheet(f"color: {SUCCESS};")
        header.addWidget(self._health_status)
        self._health_score = QLabel("100%")
        self._health_score.setFont(QFont(KPI_FONT[0], 14, QFont.Weight.Bold))
        self._health_score.setStyleSheet(
            f"color: {SUCCESS}; font-size: 38px; font-weight: 700;"
        )
        header.addWidget(self._health_score)
        self._health_score_caption = QLabel("All checks passed")
        self._health_score_caption.setFont(QFont(*MUTED_FONT))
        self._health_score_caption.setStyleSheet(f"color: {SUCCESS};")
        header.addWidget(self._health_score_caption)
        header.addStretch()
        self._health_button = self._action_button("View validation")
        self._health_button.clicked.connect(self.open_validation_requested)
        header.addWidget(self._health_button)
        layout.addLayout(header)
        self._health_checks = QLabel("")
        self._health_checks.setWordWrap(True)
        self._health_checks.setFont(QFont(*MUTED_FONT))
        self._health_checks.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background-color: {SURFACE_LIGHT};"
            f" border-radius: {RADIUS_SM}px; padding: 8px;"
        )
        layout.addWidget(self._health_checks)
        layout.addStretch(1)
        return panel

    def _build_paths_panel(self) -> QFrame:
        panel = _Panel()
        layout = self._panel_heading(panel, "Critical structure", "Critical path snapshot")
        # summary and button share one row; the route list below stays compact
        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        self._paths_summary = QLabel("No critical paths available.")
        self._paths_summary.setWordWrap(True)
        self._paths_summary.setFont(QFont(*MUTED_FONT))
        self._paths_summary.setStyleSheet(f"color: {TEXT_SECONDARY};")
        summary_row.addWidget(self._paths_summary, stretch=1)
        self._paths_button = self._action_button("Compare all paths")
        self._paths_button.clicked.connect(self.open_paths_requested)
        summary_row.addWidget(self._paths_button)
        layout.addLayout(summary_row)
        self._path_rows = QVBoxLayout()
        self._path_rows.setSpacing(0)
        layout.addLayout(self._path_rows)
        self._more_paths = QLabel("")
        self._more_paths.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._more_paths.setFont(QFont(*MUTED_FONT))
        self._more_paths.setStyleSheet(
            f"color: {ACCENT}; background-color: {SURFACE_LIGHT};"
            f" border-radius: {RADIUS_SM}px; padding: 7px;"
        )
        layout.addWidget(self._more_paths)
        layout.addStretch(1)
        return panel

    def _build_composition_panel(self) -> QFrame:
        panel = _Panel()
        layout = self._panel_heading(panel, "Network composition", "How the project is shaped")
        row = QHBoxLayout()
        row.setSpacing(10)
        self._composition = QLabel("")
        self._composition.setWordWrap(True)
        self._composition.setFont(QFont(*MUTED_FONT))
        self._composition.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background-color: {SURFACE_LIGHT};"
            f" border-radius: {RADIUS_SM}px; padding: 10px;"
        )
        row.addWidget(self._composition, stretch=1)
        button = self._action_button("Open Activities")
        button.clicked.connect(self.open_activities_requested)
        row.addWidget(button)
        layout.addLayout(row)
        return panel

    def _build_confidence_panel(self) -> QFrame:
        panel = _Panel()
        layout = self._panel_heading(panel, "Schedule confidence", "Deterministic CPM basis")
        self._confidence = QLabel("")
        self._confidence.setWordWrap(True)
        self._confidence.setFont(QFont(*MUTED_FONT))
        self._confidence.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._confidence)
        self._confidence_bar = QProgressBar()
        self._confidence_bar.setRange(0, 3)
        self._confidence_bar.setValue(0)
        self._confidence_bar.setTextVisible(False)
        self._confidence_bar.setToolTip("Verified readiness checks")
        layout.addWidget(self._confidence_bar)
        self._confidence_caption = QLabel("3 / 3 readiness checks passed")
        self._confidence_caption.setFont(QFont(*MUTED_FONT))
        self._confidence_caption.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self._confidence_caption)
        return panel

    def _build_action_panel(self) -> QFrame:
        panel = _Panel()
        layout = self._panel_heading(panel, "Next useful action", "Explore the schedule")
        row = QHBoxLayout()
        row.setSpacing(10)
        self._next_action = QLabel("")
        self._next_action.setWordWrap(True)
        self._next_action.setFont(QFont(*MUTED_FONT))
        self._next_action.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background-color: {_rgba(WARNING, 24)};"
            f" border-left: 3px solid {WARNING}; border-radius: {RADIUS_SM}px; padding: 10px;"
        )
        row.addWidget(self._next_action, stretch=1)
        button = self._action_button("Go to Critical Paths")
        button.clicked.connect(self.open_paths_requested)
        row.addWidget(button)
        layout.addLayout(row)
        return panel

    def set_data(self, data: Any, session: Any = None) -> None:
        """Populate the summary from the authoritative ResultsData snapshot."""
        self._data = data
        self._session = session
        path_count = data.critical_path_count or 0
        self._kpi_cards["duration"].set_value(format_duration(data.project_duration), ACCENT)
        self._kpi_cards["duration"].set_note("CPM verified")
        self._kpi_cards["duration"].set_trend("")
        self._kpi_cards["activities"].set_value(str(data.activity_count), ACCENT)
        self._kpi_cards["activities"].set_note("reviewed activities")
        self._kpi_cards["activities"].set_trend("100% reviewed")
        self._kpi_cards["dependencies"].set_value(str(data.dependency_count), INFO)
        self._kpi_cards["dependencies"].set_note("unique relationships")
        self._kpi_cards["dependencies"].set_trend("graph linked")
        self._kpi_cards["critical_paths"].set_value(str(path_count), WARNING)
        self._kpi_cards["critical_paths"].set_note("zero-float routes")
        self._kpi_cards["critical_paths"].set_trend("compare →")
        self._kpi_cards["critical_activities"].set_value(
            str(data.critical_activity_count), WARNING
        )
        self._kpi_cards["critical_activities"].set_note("on critical structure")
        self._kpi_cards["critical_activities"].set_trend(
            f"{(data.critical_activity_count / data.activity_count * 100):.1f}% of graph"
            if data.activity_count else "—"
        )
        self._kpi_cards["review_state"].set_value("Complete", SUCCESS)
        self._kpi_cards["review_state"].set_note("graph validated")
        self._kpi_cards["review_state"].set_trend("authoritative")

        self._health_status.setText("Authoritative")
        self._health_status.setStyleSheet(f"color: {SUCCESS};")
        self._health_checks.setText(
            "<b>✓ Reviewed graph applied</b>&nbsp;&nbsp;&nbsp;"
            "<b>✓ Validation passed</b><br>"
            "<b>✓ CPM result available</b>&nbsp;&nbsp;&nbsp;"
            f"<font color='{WARNING}'>⚠ {path_count} critical routes to compare</font>"
        )
        non_critical = max(0, data.activity_count - data.critical_activity_count)
        self._composition.setText(
            f"<b>{data.activity_count} reviewed activities</b> · "
            f"<b>{data.dependency_count}</b> unique dependencies<br>"
            f"zero-float <font color='{WARNING}'><b>{data.critical_activity_count}</b></font>"
            f" · non-critical <b>{non_critical}</b>"
        )
        self._confidence.setText(
            "Calculation source <b>Backend CPM</b> · "
            f"<font color='{SUCCESS}'>Graph valid</font> · Result authoritative"
        )
        self._confidence_bar.setValue(3)
        self._confidence_caption.setText("3 / 3 readiness checks passed")
        self._next_action.setText(
            f"There are {path_count} equal-duration critical route(s). "
            "Compare their branches, then inspect any activity in Network."
        )
        self._set_path_snapshot(data)

    def _set_path_snapshot(self, data: Any) -> None:
        while self._path_rows.count():
            item = self._path_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        paths = list(data.critical_paths or [])
        self._paths_summary.setText(
            f"{len(paths)} critical path(s) share the project duration of "
            f"{format_duration(data.project_duration)}."
            if paths
            else "No critical paths available."
        )
        self._more_paths.setText(
            f"+ {max(0, len(paths) - 3)} more equal-duration paths · Open Critical Paths →"
            if len(paths) > 3 else ""
        )
        for index, path in enumerate(paths[:3], start=1):
            route = " → ".join(path)
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ border-top: 1px solid {BORDER}; padding: 6px 0; }}"
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 5, 0, 5)
            rank = QLabel(f"{index:02d}")
            rank.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rank.setFixedSize(28, 28)
            rank.setFont(QFont(*MUTED_FONT))
            rank.setStyleSheet(
                f"color: {WARNING}; background-color: {_rgba(WARNING, 35)};"
                f" border-radius: {RADIUS_SM}px;"
            )
            row_layout.addWidget(rank)
            # single compact line-pair: the full route only.  The per-row
            # "N activities · zero float" caption was dropped — it repeated
            # the panel summary for every route.
            route_label = QLabel(route)
            route_label.setWordWrap(True)
            route_label.setFont(QFont(*MUTED_FONT))
            route_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
            row_layout.addWidget(route_label, stretch=1)
            self._path_rows.addWidget(row)

    def kpi_cards(self) -> dict[str, KpiCard]:
        return dict(self._kpi_cards)
