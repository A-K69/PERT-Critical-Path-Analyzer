"""
Understanding page: preliminary reconstruction of the analyzed diagram.

The page shows the original image alongside an auto-laid-out preview of the
detected nodes and edges (driven by the review session) before the user moves
into the detailed Human Review Center. It only renders state; all logic lives
in the backend pipeline and the review session.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.pages.analysis_page import ImageView
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
    qrgba,
)
from pert_analyzer.gui.themes.spacing import LG, MD, RADIUS_LG, RADIUS_MD, SM, XS
from pert_analyzer.gui.themes.typography import (
    BODY_FONT,
    BODY_SMALL_FONT,
    KPI_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    SUBTITLE_FONT,
    TITLE_FONT,
)

_NODE_RADIUS = 20


def _is_resolved(item: Any) -> bool:
    """A review item has been resolved when its status leaves PENDING."""
    status = getattr(item, "status", None)
    value = getattr(status, "value", status)
    return str(value).lower() != "pending"


class ReconstructionCanvas(QWidget):
    """Radial layout preview of the detected reconstruction.

    Confirmed items are drawn solid/in accent, unresolved items stay amber
    with a dashed outline so the user can see exactly what still needs review.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[tuple[int, int, bool]] = []
        self._durations: dict[int, str] = {}
        self._positions: list[tuple[float, float]] = []
        self._id_to_index: dict[str, int] = {}
        self.setMinimumHeight(230)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_reconstruction(
        self,
        activities: list[Any],
        dependencies: list[Any],
        durations: list[Any],
    ) -> int:
        """Rebuild the preview from review items. Returns node count."""
        self._nodes = []
        self._edges = []
        self._durations = {}
        self._id_to_index = {}

        for act in activities or []:
            geometric = getattr(act, "geometric_node_id", None)
            activity_id = getattr(act, "activity_id", None)
            node_id = geometric or activity_id or "?"
            index = len(self._nodes)
            self._nodes.append(
                {
                    "id": str(node_id),
                    "label": str(node_id),
                    "resolved": _is_resolved(act),
                }
            )
            for key in (geometric, activity_id):
                if key is not None:
                    self._id_to_index.setdefault(str(key), index)

        for dep in dependencies or []:
            source = getattr(dep, "current_source_id", None) or getattr(
                dep, "source_node_id", None
            )
            target = getattr(dep, "current_target_id", None) or getattr(
                dep, "target_node_id", None
            )
            if source is None or target is None:
                continue
            si = self._id_to_index.get(str(source))
            ti = self._id_to_index.get(str(target))
            if si is not None and ti is not None:
                self._edges.append((si, ti, _is_resolved(dep)))  # type: ignore[arg-type]

        for dur in durations or []:
            geometric = getattr(dur, "geometric_node_id", None)
            activity_id = getattr(dur, "activity_id", None)
            index = None
            for key in (geometric, activity_id):
                if key is not None:
                    index = self._id_to_index.get(str(key))
                    if index is not None:
                        break
            if index is None:
                continue
            current = getattr(dur, "current_duration", None)
            if _is_resolved(dur) and current is not None:
                self._durations[index] = f"d={current:g}"
            else:
                self._durations[index] = "d=?"

        self._layout()
        self.update()
        return len(self._nodes)

    def clear(self) -> None:
        self._nodes = []
        self._edges = []
        self._durations = {}
        self._positions = []
        self._id_to_index = {}
        self.update()

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def pending_count(self) -> int:
        return sum(1 for node in self._nodes if not node["resolved"])

    # ------------------------------------------------------------------
    # Layout + painting
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        self._positions = []
        count = len(self._nodes)
        if count == 0:
            return
        cx, cy = self.width() / 2.0, self.height() / 2.0
        radius = min(cx, cy) - _NODE_RADIUS - 18
        if radius < 40:
            radius = 40
        for i in range(count):
            angle = -90.0 + 360.0 * i / count
            rad = math.radians(angle)
            self._positions.append(
                (cx + radius * math.cos(rad), cy + radius * math.sin(rad))
            )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event  # unused
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(SURFACE))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        edge = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(edge, RADIUS_LG, RADIUS_LG)

        if not self._nodes:
            painter.setFont(QFont(*BODY_FONT))
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No reconstruction available yet",
            )
            painter.end()
            return

        # edges first (under the nodes)
        for si, ti, resolved in self._edges:
            if si >= len(self._positions) or ti >= len(self._positions):
                continue
            pen = QPen(QColor(ACCENT if resolved else WARNING), 1.5)
            if not resolved:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(
                self._positions[si][0],
                self._positions[si][1],
                self._positions[ti][0],
                self._positions[ti][1],
            )

        painter.setFont(QFont(*BODY_FONT))
        for index, node in enumerate(self._nodes):
            x, y = self._positions[index]
            rect = QRectF(
                x - _NODE_RADIUS, y - _NODE_RADIUS, 2 * _NODE_RADIUS, 2 * _NODE_RADIUS
            )
            fill = QColor(SURFACE_LIGHT if node["resolved"] else SURFACE_LIGHT)
            color = QColor(ACCENT if node["resolved"] else WARNING)
            pen = QPen(color, 2)
            if not node["resolved"]:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawEllipse(rect)

            painter.setPen(QColor(TEXT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, node["label"])

            duration = self._durations.get(index)
            if duration is not None:
                painter.setFont(QFont(*MUTED_FONT))
                painter.setPen(QColor(TEXT_MUTED if node["resolved"] else WARNING))
                painter.drawText(
                    QRectF(x - 40, y + _NODE_RADIUS + 4, 80, 18),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    duration,
                )
                painter.setFont(QFont(*BODY_FONT))

        painter.end()


def _status_color(status: Any) -> str:
    value = getattr(status, "value", status)
    return {
        "VALIDATED": SUCCESS,
        "VALID": SUCCESS,
        "INVALID": DANGER,
        "REVIEW REQUIRED": WARNING,
        "BLOCKED_REVIEW": WARNING,
    }.get(str(value), TEXT_MUTED)


class UnderstandingPage(QWidget):
    """Diagram understanding / preliminary reconstruction workspace."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._session: Any = None
        self._loaded_image_path: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SM)

        self._empty_label = QLabel("")
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setFont(QFont(*LABEL_FONT))
        self._empty_label.setStyleSheet(f"color: {TEXT_MUTED};")
        root.addWidget(self._empty_label, stretch=1)
        self._empty_label.hide()

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent; border: none;")
        content = QVBoxLayout(self._content)
        content.setContentsMargins(24, 24, 24, 24)
        content.setSpacing(MD)
        root.addWidget(self._content, stretch=1)

        # header row: title + subtitle + reconstruction banner
        header = QHBoxLayout()
        header.setSpacing(MD)
        header.setContentsMargins(0, 0, 0, 0)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        self._title_label = QLabel("Diagram Understanding")
        self._title_label.setFont(QFont(*TITLE_FONT))
        self._title_label.setStyleSheet(f"color: {TEXT}; border: none; background: transparent;")
        title_col.addWidget(self._title_label)

        subtitle = QLabel(
            "Review the preliminary reconstruction of the detected diagram before final review."
        )
        subtitle.setFont(QFont(*SUBTITLE_FONT))
        subtitle.setStyleSheet(
            f"color: {TEXT_MUTED}; border: none; background: transparent;"
        )
        title_col.addWidget(subtitle)
        header.addLayout(title_col, stretch=1)

        self._banner = QLabel("  \u25C8  PRELIMINARY RECONSTRUCTION  ")
        self._banner.setFont(QFont(*BODY_SMALL_FONT))
        self._banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner.setStyleSheet(
            f"color: {ACCENT}; background-color: {qrgba(ACCENT, 24)};"
            f" border: 1px solid {qrgba(ACCENT, 68)}; border-radius: 6px;"
            f" padding: 4px 10px; font-weight: 600;"
        )
        header.addWidget(self._banner, alignment=Qt.AlignmentFlag.AlignTop)
        content.addLayout(header)
        content.addSpacing(SM)

        # body: original image left, metrics card right
        body = QWidget()
        body.setStyleSheet("background: transparent; border: none;")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(MD)

        left = QVBoxLayout()
        left.setSpacing(MD)
        self._image_view = ImageView()
        self._image_view.setMinimumHeight(200)
        left.addWidget(self._image_view, stretch=1)
        body_layout.addLayout(left, stretch=3)

        self._metrics_card = QFrame()
        self._metrics_card.setObjectName("understandingMetrics")
        self._metrics_card.setStyleSheet(
            f"QFrame#understandingMetrics {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; }}"
        )
        metrics_layout = QVBoxLayout(self._metrics_card)
        metrics_layout.setContentsMargins(LG, MD, LG, MD)
        metrics_layout.setSpacing(MD)

        grid = QGridLayout()
        grid.setHorizontalSpacing(MD)
        grid.setVerticalSpacing(LG)
        self._metric_cells: dict[str, tuple[QLabel, QLabel]] = {}
        for col, (key, caption) in enumerate(
            (("activities", "Activities detected"), ("candidate_deps", "Candidate connections"))
        ):
            grid.addLayout(self._metric_cell(key, caption), 0, col)
        for col, (key, caption) in enumerate(
            (("confirmed_deps", "Confirmed dependencies"), ("review_required", "Review required"))
        ):
            grid.addLayout(self._metric_cell(key, caption), 1, col)
        for col, (key, caption) in enumerate(
            (("review_items", "Total review items"), ("pending", "Pending resolution"))
        ):
            grid.addLayout(self._metric_cell(key, caption), 2, col)
        metrics_layout.addLayout(grid)

        metrics_layout.addSpacing(XS)
        metrics_layout.addWidget(self._separator())

        self._validation_row = QLabel("")
        self._validation_row.setWordWrap(True)
        self._validation_row.setTextFormat(Qt.TextFormat.RichText)
        metrics_layout.addWidget(self._validation_row)

        self._cpm_row = QLabel("")
        self._cpm_row.setWordWrap(True)
        self._cpm_row.setTextFormat(Qt.TextFormat.RichText)
        metrics_layout.addWidget(self._cpm_row)

        metrics_layout.addStretch()
        self._metrics_card.setFixedWidth(300)
        body_layout.addWidget(self._metrics_card, alignment=Qt.AlignmentFlag.AlignTop)
        content.addWidget(body, stretch=5)

        # bottom: reconstruction canvas with legend
        canvas_section = QWidget()
        canvas_section.setStyleSheet("background: transparent; border: none;")
        canvas_layout = QVBoxLayout(canvas_section)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(SM)

        canvas_header = QHBoxLayout()
        canvas_header.setSpacing(SM)
        canvas_title = QLabel("Detected structure")
        canvas_title.setFont(QFont(*LABEL_FONT))
        canvas_title.setStyleSheet(f"color: {TEXT}; border: none; background: transparent;")
        canvas_header.addWidget(canvas_title)
        canvas_header.addStretch()
        self._legend_label = QLabel(
            f'<font color="{ACCENT}">\u25CF</font> Confirmed'
            f'<font color="{TEXT_MUTED}">   </font>'
            f'<font color="{WARNING}">\u25CB</font> Pending review'
        )
        self._legend_label.setFont(QFont(*MUTED_FONT))
        self._legend_label.setTextFormat(Qt.TextFormat.RichText)
        self._legend_label.setStyleSheet(
            "border: none; background: transparent;"
        )
        canvas_header.addWidget(self._legend_label)
        canvas_layout.addLayout(canvas_header)

        self._canvas = ReconstructionCanvas()
        self._canvas.setMinimumHeight(200)
        canvas_layout.addWidget(self._canvas, stretch=1)
        content.addWidget(canvas_section, stretch=4)

        self._content.hide()
        self._show_empty(
            "No analysis yet. Run an analysis on the Analyze Diagram page."
        )

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _metric_cell(self, key: str, caption: str) -> QVBoxLayout:
        cell = QVBoxLayout()
        cell.setSpacing(2)
        value = QLabel("\u2014")
        value.setFont(QFont(*KPI_FONT))
        value.setStyleSheet("border: none; background: transparent;")
        cell.addWidget(value)
        label = QLabel(caption)
        label.setFont(QFont(*BODY_SMALL_FONT))
        label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; border: none; background: transparent;"
        )
        cell.addWidget(label)
        self._metric_cells[key] = (value, label)
        return cell

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {BORDER}; background-color: {BORDER};")
        line.setFixedHeight(1)
        return line

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def title(self) -> str:
        return self._title_label.text()

    @property
    def banner_text(self) -> str:
        return self._banner.text()

    def canvas(self) -> ReconstructionCanvas:
        return self._canvas

    def set_reconstruction(self, session: Any) -> None:
        """Render content for a session with a workflow + review session."""
        review_session = session.review_session
        activities = getattr(review_session, "activities", None) or []
        dependencies = getattr(review_session, "dependencies", None) or []
        durations = getattr(review_session, "durations", None) or []
        self._canvas.set_reconstruction(activities, dependencies, durations)

        image_path = getattr(session, "current_image_path", None)
        if image_path and image_path != self._loaded_image_path:
            self._image_view.set_image(image_path)
            self._loaded_image_path = image_path

        summary = getattr(session, "review_summary", None) or {}
        total_activities = summary.get("total_activities")
        if total_activities is None:
            total_activities = len(activities)
        total_dependencies = summary.get("total_dependencies")
        if total_dependencies is None:
            total_dependencies = len(dependencies)

        # Count confirmed (accepted/corrected) vs pending dependencies
        confirmed_deps = 0
        review_required_deps = 0
        for dep in dependencies:
            status_val = getattr(dep, "status", None)
            val = getattr(status_val, "value", status_val) if status_val is not None else "pending"
            if str(val).lower() in ("accepted", "corrected"):
                confirmed_deps += 1
            else:
                review_required_deps += 1

        # Count confirmed vs pending activities
        confirmed_activities = 0
        review_required_activities = 0
        for act in activities:
            status_val = getattr(act, "status", None)
            val = getattr(status_val, "value", status_val) if status_val is not None else "pending"
            if str(val).lower() in ("accepted", "corrected"):
                confirmed_activities += 1
            else:
                review_required_activities += 1

        self._metric_cells["activities"][0].setText(str(total_activities))
        self._metric_cells["candidate_deps"][0].setText(str(total_dependencies))
        self._metric_cells["confirmed_deps"][0].setText(str(confirmed_deps))
        self._metric_cells["review_required"][0].setText(str(review_required_deps))
        self._metric_cells["review_items"][0].setText(str(session.review_item_total()))
        self._metric_cells["pending"][0].setText(str(session.pending_review_total()))

        status = session.validation_status
        status_value = getattr(status, "value", status)
        self._validation_row.setText(
            f"<b>Graph validation:</b> "
            f'<font color="{_status_color(status)}">{status_value}</font>'
        )
        eligible = bool(getattr(session, "cpm_eligible", False))
        self._cpm_row.setText(
            f"<b>CPM ready:</b> "
            f'<font color="{SUCCESS if eligible else TEXT_MUTED}">'
            f'{"Yes" if eligible else "Not yet"}</font>'
        )

    # ------------------------------------------------------------------
    # Refresh API
    # ------------------------------------------------------------------

    def refresh(self, session: Any) -> None:
        self._session = session
        if session is None or getattr(session, "workflow", None) is None:
            self._content.hide()
            self._empty_label.show()
            self._empty_label.setText(
                "No analysis yet. Run an analysis on the Analyze Diagram page."
            )
            return
        review_session = getattr(session, "review_session", None)
        if review_session is None:
            self._content.hide()
            self._empty_label.show()
            self._empty_label.setText(
                "No reconstruction data is available for this analysis."
            )
            return
        self._empty_label.hide()
        self._content.show()
        self.set_reconstruction(session)

    def _show_empty(self, message: str) -> None:
        self._content.hide()
        self._empty_label.show()
        self._empty_label.setText(message)