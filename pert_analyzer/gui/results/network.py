"""
Qt-native network canvas: QGraphicsView + QGraphicsScene visualization.

Renders the backend graph as reusable ActivityNodeItem / DependencyEdgeItem
objects. The GUI never re-derives graph relationships; it only lays out and
draws the snapshot produced by ``gui.results.data``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.results import layout as network_layout
from pert_analyzer.gui.themes.style import NETWORK_COLORS
from pert_analyzer.gui.themes.typography import FONT_FAMILY

MIN_ZOOM = 0.2
MAX_ZOOM = 5.0
ZOOM_STEP = 1.2


def _color(key: str) -> QColor:
    return QColor(NETWORK_COLORS[key])


class ActivityNodeItem(QGraphicsObject):
    """A rendered activity node (Activity ID, Duration, Float)."""

    clicked = Signal(str)

    def __init__(
        self,
        activity_id: str,
        duration: Optional[float],
        total_float: Optional[float],
        is_critical: bool,
        rect: Tuple[float, float, float, float],
        name: str = "",
        metric_label: str = "Duration",
        parent: Any = None,
    ):
        super().__init__(parent)
        self.activity_id = activity_id
        self.duration = duration
        self.total_float = total_float
        self.is_critical = bool(is_critical)
        self.name = name
        self.metric_label = metric_label
        self._rect = QRectF(*rect)
        self._path_highlight = False
        self._selected = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(10)
        self.setToolTip(
            f"{activity_id} - {name}\n"
            f"{metric_label}: {self._display(duration)}\n"
            f"Float: {self._display(total_float)}"
        )

    @staticmethod
    def _display(value: Optional[float]) -> str:
        if value is None:
            return "Unavailable"
        return f"{float(value):g}"

    def boundingRect(self) -> QRectF:
        return self._rect

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect, 8, 8)
        return path

    def set_path_highlight(self, on: bool) -> None:
        self._path_highlight = bool(on)
        self.update()

    def set_selected(self, on: bool) -> None:
        self._selected = bool(on)
        self.setSelected(on)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.activity_id)
        super().mousePressEvent(event)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        fill = _color("node_fill_critical" if self.is_critical else "node_fill")
        if self._selected or self._path_highlight:
            border = _color("node_selected")
        elif self.is_critical:
            border = _color("node_border_critical")
        else:
            border = _color("node_border")
        border_width = 2.5 if (self._selected or self._path_highlight) else 1.5

        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(border, border_width))
        painter.drawRoundedRect(self._rect, 8, 8)

        x = self._rect.x()
        width = self._rect.width()
        text_y = self._rect.y() + 14

        painter.setPen(QPen(_color("node_text")))
        title_font = QFont(FONT_FAMILY, 10, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(x + 6, text_y - 10, width - 12, 16),
            Qt.AlignmentFlag.AlignCenter,
            self.activity_id,
        )

        body_font = QFont(FONT_FAMILY, 8)
        painter.setFont(body_font)
        painter.setPen(QPen(_color("node_text_muted")))
        line_y = self._rect.y() + 26
        painter.drawText(
            QRectF(x + 6, line_y, width - 12, 14),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.metric_label}: {self._display(self.duration)}",
        )
        painter.drawText(
            QRectF(x + 6, line_y + 14, width - 12, 14),
            Qt.AlignmentFlag.AlignCenter,
            f"Float: {self._display(self.total_float)}",
        )
        if self.is_critical:
            painter.setPen(QPen(_color("node_border_critical")))
            painter.drawText(
                QRectF(x + 6, line_y + 28, width - 12, 13),
                Qt.AlignmentFlag.AlignCenter,
                "\u25cf Critical",
            )


class DependencyEdgeItem(QGraphicsObject):
    """A rendered source->target dependency arrow."""

    def __init__(
        self,
        source: str,
        target: str,
        start: Tuple[float, float],
        end: Tuple[float, float],
        is_critical: bool,
        parent: Any = None,
    ):
        super().__init__(parent)
        self.source = source
        self.target = target
        self._start = start
        self._end = end
        self.is_critical = bool(is_critical)
        self._path_highlight = False
        self.setZValue(0)
        self.setToolTip(f"Precedence: {source} \u2192 {target}")

    def boundingRect(self) -> QRectF:
        x1, y1 = self._start
        x2, y2 = self._end
        return QRectF(
            min(x1, x2) - 12,
            min(y1, y2) - 12,
            abs(x2 - x1) + 24,
            abs(y2 - y1) + 24,
        )

    def set_path_highlight(self, on: bool) -> None:
        self._path_highlight = bool(on)
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._path_highlight:
            color = _color("path_highlight")
            width = 3.0
        elif self.is_critical:
            color = _color("edge_critical")
            width = 2.0
        else:
            color = _color("edge")
            width = 1.5

        pen = QPen(color, width)
        painter.setPen(pen)
        x1, y1 = self._start
        x2, y2 = self._end
        painter.drawLine(x1, y1, x2, y2)
        _draw_arrowhead(painter, x1, y1, x2, y2, color)


def _draw_arrowhead(
    painter: QPainter, x1: float, y1: float, x2: float, y2: float, color: QColor
) -> None:
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    size = 10.0
    tip_x, tip_y = x2 + ux * 1.0, y2 + uy * 1.0
    base_x, base_y = x2 - ux * size, y2 - uy * size
    left = (base_x + px * size / 2, base_y + py * size / 2)
    right = (base_x - px * size / 2, base_y - py * size / 2)
    painter.setBrush(QBrush(color))
    painter.setPen(QPen(color, 1))
    tip = QPointF(tip_x, tip_y)
    painter.drawPolygon(QPolygonF([tip, QPointF(*left), QPointF(*right)]))


class _ZoomableGraphicsView(QGraphicsView):
    """QGraphicsView with mouse-wheel zoom anchored under the cursor."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # True once the user zoomed manually (wheel or +/- buttons); the tab
        # then stops re-fitting on show so it never fights the user.
        self.user_zoomed = False

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1.0 / ZOOM_STEP
        self._apply_zoom(factor)

    def _apply_zoom(self, factor: float) -> None:
        current = self.transform().m11()
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if abs(new_zoom - current) < 1e-9:
            return
        self.user_zoomed = True
        self.scale(new_zoom / current, new_zoom / current)


class NetworkTab(QWidget):
    """Network visualization tab with fit/zoom/reset and selection."""

    node_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._data: Any = None
        self._node_items: Dict[str, ActivityNodeItem] = {}
        self._edge_items: Dict[Tuple[str, str], DependencyEdgeItem] = {}
        self._current_path: List[str] = []
        self._selected_id: Optional[str] = None
        self._metric_mode: str = "CPM"
        self._pert_rows: Dict[str, Any] = {}
        self._pert_paths: List[List[str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._metric_label = QLabel("Metrics:")
        self._metric_combo = QComboBox()
        self._metric_combo.addItems(["CPM", "PERT"])
        self._metric_combo.setToolTip(
            "CPM uses activity durations; PERT uses expected times "
            "when a PERT result is available."
        )
        self._metric_combo.currentTextChanged.connect(self._on_metric_changed)
        toolbar.addWidget(self._metric_label)
        toolbar.addWidget(self._metric_combo)
        self._fit_btn = QPushButton("Fit to view")
        self._fit_btn.setToolTip("Zoom to fit the whole network")
        self._fit_btn.clicked.connect(self.fit_to_view)
        self._reset_btn = QPushButton("Reset zoom")
        self._reset_btn.setToolTip("Return to the default zoom level")
        self._reset_btn.clicked.connect(self.reset_zoom)
        self._zoom_in_btn = QPushButton("+")
        self._zoom_in_btn.setToolTip("Zoom in")
        self._zoom_in_btn.clicked.connect(lambda: self.zoom_by(ZOOM_STEP))
        self._zoom_out_btn = QPushButton("\u2212")
        self._zoom_out_btn.setToolTip("Zoom out")
        self._zoom_out_btn.clicked.connect(lambda: self.zoom_by(1.0 / ZOOM_STEP))
        self._clear_path_btn = QPushButton("Clear highlight")
        self._clear_path_btn.setToolTip("Clear the highlighted critical path")
        self._clear_path_btn.clicked.connect(self.clear_highlight)
        self._focus_btn = QPushButton("Focus critical path")
        self._focus_btn.setToolTip("Highlight and zoom to the first critical path")
        self._focus_btn.clicked.connect(self.focus_critical_path)
        for btn in (self._fit_btn, self._reset_btn,
                    self._zoom_in_btn, self._zoom_out_btn,
                    self._clear_path_btn, self._focus_btn):
            toolbar.addWidget(btn)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self._scene = QGraphicsScene(self)
        self._view = _ZoomableGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self._view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # The results dashboard stacks tab pages in a QStackedLayout that sizes
        # every page to the tallest tab, so this canvas can be taller than the
        # visible area.  Alignment Left|Top keeps the fitted graph at the top
        # of the canvas — exactly the part the user sees first — instead of
        # centering it in whichever oversized viewport slice is visible.
        self._view.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._view.setBackgroundBrush(_color("canvas"))
        root.addWidget(self._view, stretch=1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # fit_to_view() may have computed its zoom while this tab was hidden
        # (data usually arrives before the tab is ever shown), which bakes a
        # stale half-size transform in.  Refit once the real viewport size is
        # known — but never override a manual zoom the user already chose.
        if not self._view.user_zoomed:
            QTimer.singleShot(0, self.fit_to_view)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_data(self, data: Any) -> None:
        """Populate the canvas from a results snapshot."""
        self._data = data
        self._render()

    def set_pert_data(self, pert_data: Any) -> None:
        """Provide PERT row metrics for PERT metric mode."""
        rows: Dict[str, Any] = {}
        paths: List[List[str]] = []
        if pert_data is not None:
            for row in getattr(pert_data, "rows", None) or []:
                rows[row.activity_id] = row
            paths = [
                list(p)
                for p in getattr(pert_data, "critical_paths", None) or []
            ]
        self._pert_rows = rows
        self._pert_paths = paths
        if self._metric_mode == "PERT":
            self._render()

    def set_metric_mode(self, mode: str) -> None:
        """Switch between CPM and PERT metric modes."""
        mode = "PERT" if mode == "PERT" else "CPM"
        if mode == self._metric_mode:
            return
        self._metric_mode = mode
        self._set_combo_silently(mode)
        if self._data is not None:
            self._render()

    def _on_metric_changed(self, mode: str) -> None:
        self.set_metric_mode(mode)

    def _set_combo_silently(self, mode: str) -> None:
        index = self._metric_combo.findText(mode)
        if index >= 0 and self._metric_combo.currentIndex() != index:
            self._metric_combo.blockSignals(True)
            self._metric_combo.setCurrentIndex(index)
            self._metric_combo.blockSignals(False)

    def metric_mode(self) -> str:
        return self._metric_mode

    def metric_combo(self) -> QComboBox:
        return self._metric_combo

    def _render(self) -> None:
        self.clear()
        data = self._data
        graphics = getattr(data, "graph", None)
        if graphics is None:
            self._show_no_data()
            return
        ids = list(getattr(graphics, "activities", None) or {}.keys())
        if not ids:
            self._show_no_data()
            return

        calls = getattr(graphics, "activities", None) or {}
        cpm_analyses = getattr(
            getattr(data, "cpm", None), "activity_analyses", None
        ) or {}
        positions = network_layout.build_layout(
            ids, getattr(graphics, "dependencies", None) or []
        )

        critical_edges = self._critical_edges_for()
        use_pert = (
            self._metric_mode == "PERT" and bool(self._pert_rows)
        )
        for aid, (x, y, w, h) in positions.items():
            if use_pert:
                row = self._pert_rows.get(aid)
                duration = _safe_num(getattr(row, "expected_time", None))
                total_float = _safe_num(getattr(row, "total_float", None))
                is_critical = bool(getattr(row, "is_critical", False))
                metric_label = "Expected"
            else:
                analysis = cpm_analyses.get(aid)
                duration = _safe_num(getattr(calls.get(aid), "duration", None))
                total_float = _safe_num(getattr(analysis, "total_float", None))
                is_critical = bool(getattr(analysis, "is_critical", False))
                metric_label = "Duration"
            item = ActivityNodeItem(
                activity_id=aid,
                duration=duration,
                total_float=total_float,
                is_critical=is_critical,
                rect=(x, y, w, h),
                name=getattr(calls.get(aid), "name", "") or "",
                metric_label=metric_label,
            )
            item.clicked.connect(self._on_node_clicked)
            self._scene.addItem(item)
            self._node_items[aid] = item

        for dep in getattr(graphics, "dependencies", None) or []:
            src = getattr(dep, "source", None)
            tgt = getattr(dep, "target", None)
            if src is None or tgt is None:
                continue
            if src not in self._node_items or tgt not in self._node_items:
                continue
            start, end = network_layout.edge_points(positions, src, tgt)
            item = DependencyEdgeItem(
                source=src,
                target=tgt,
                start=start,
                end=end,
                is_critical=(src, tgt) in critical_edges,
            )
            self._scene.addItem(item)
            self._edge_items[(src, tgt)] = item

        self._scene.setSceneRect(
            self._scene.itemsBoundingRect().adjusted(-40, -40, 60, 60)
        )
        self.fit_to_view()

    def _critical_edges_for(self) -> set:
        if self._metric_mode == "PERT" and self._pert_paths:
            edges = set()
            for path in self._pert_paths:
                for i in range(len(path) - 1):
                    edges.add((path[i], path[i + 1]))
            return edges
        return set(getattr(self._data, "critical_edges", set()) or set())

    def clear(self) -> None:
        self._node_items.clear()
        self._edge_items.clear()
        self._current_path = []
        self._selected_id = None
        self._scene.clear()
        self._view.resetTransform()

    def is_empty(self) -> bool:
        return not self._node_items

    def node_items(self) -> Dict[str, ActivityNodeItem]:
        return dict(self._node_items)

    def edge_items(self) -> Dict[Tuple[str, str], DependencyEdgeItem]:
        return dict(self._edge_items)

    def _show_no_data(self) -> None:
        from PySide6.QtWidgets import QGraphicsSimpleTextItem

        text = QGraphicsSimpleTextItem("No network data to display")
        text.setBrush(_color("node_text_muted"))
        font = QFont("Segoe UI", 12)
        text.setFont(font)
        self._scene.addItem(text)
        self._scene.setSceneRect(text.boundingRect().adjusted(-20, -20, 20, 20))

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_node_clicked(self, activity_id: str) -> None:
        self.set_selected_activity(activity_id)
        self.node_selected.emit(activity_id)

    def set_selected_activity(self, activity_id: Optional[str]) -> None:
        if self._selected_id is not None:
            item = self._node_items.get(self._selected_id)
            if item is not None and not self._in_current_path(self._selected_id):
                item.set_selected(False)
        self._selected_id = activity_id
        if activity_id is not None:
            item = self._node_items.get(activity_id)
            if item is not None:
                item.set_selected(True)

    def highlight_path(self, path: List[str]) -> None:
        """Highlight the activities and edges along a critical path."""
        path_ids = list(path)
        for aid, item in self._node_items.items():
            item.set_path_highlight(aid in set(path_ids))
        path_edge_set = {
            (path_ids[i], path_ids[i + 1])
            for i in range(len(path_ids) - 1)
        }
        for (src, tgt), item in self._edge_items.items():
            item.set_path_highlight((src, tgt) in path_edge_set)
        self._current_path = path_ids
        if self._selected_id is not None:
            item = self._node_items.get(self._selected_id)
            if item is not None:
                item.set_selected(True)

    def clear_highlight(self) -> None:
        self._current_path = []
        for item in self._node_items.values():
            item.set_path_highlight(False)
            item.set_selected(False)
        for item in self._edge_items.values():
            item.set_path_highlight(False)
        self._selected_id = None

    def focus_critical_path(self) -> None:
        """Highlight and zoom to the first backend-provided critical path."""
        paths = list(getattr(self._data, "critical_paths", None) or [])
        if self._metric_mode == "PERT" and self._pert_paths:
            paths = list(self._pert_paths)
        if not paths:
            return
        path = [activity_id for activity_id in paths[0] if activity_id in self._node_items]
        if not path:
            return
        self.highlight_path(path)
        bounds = QRectF()
        for activity_id in path:
            node = self._node_items[activity_id]
            bounds = node.sceneBoundingRect() if bounds.isNull() else bounds.united(
                node.sceneBoundingRect()
            )
        if not bounds.isNull():
            self._view.fitInView(
                bounds.adjusted(-50, -50, 50, 50),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

    def _in_current_path(self, activity_id: str) -> bool:
        return activity_id in set(self._current_path)

    def current_path(self) -> List[str]:
        return list(self._current_path)

    @property
    def selected_activity(self) -> Optional[str]:
        return self._selected_id

    # ------------------------------------------------------------------
    # Zoom / view
    # ------------------------------------------------------------------

    def zoom_by(self, factor: float) -> None:
        self._view._apply_zoom(factor)

    def fit_to_view(self) -> None:
        if self._scene.itemsBoundingRect().isNull():
            return
        self._view.fitInView(
            self._scene.itemsBoundingRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._view.user_zoomed = False

    def reset_zoom(self) -> None:
        self._view.resetTransform()
        center = self._scene.sceneRect().center()
        self._view.centerOn(center)

    @property
    def zoom(self) -> float:
        return self._view.transform().m11()


def _safe_num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
