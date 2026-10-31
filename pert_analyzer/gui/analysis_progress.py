"""
Real-time analysis progress model and panel.

The model tracks the exact stages emitted by the pipeline through
``StageProgress`` events (see ``pert_analyzer.pipeline.progress``); it
never invents percentages. The panel renders the stages as a checklist,
an overall progress bar, the current stage message, and real
detected-object metrics (shapes, arrows, OCR labels, activities,
review items) only when the pipeline reports them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPolygonF,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

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
from pert_analyzer.gui.themes.spacing import RADIUS_MD, RADIUS_SM, LG, MD, SM, XS
from pert_analyzer.gui.themes.typography import (
    BODY_SMALL_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
)
from pert_analyzer.pipeline.progress import (
    COMPLETED,
    FAILED,
    PENDING,
    PIPELINE_STAGES,
    REVIEW_REQUIRED,
    RUNNING,
    SKIPPED,
    STAGE_LABELS,
)


@dataclass
class StageEntry:
    """One stage in the progress model with its current state."""

    stage_id: str
    name: str
    state: str = PENDING
    progress: float = 0.0
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)


class AnalysisProgressModel(QObject):
    """Tracks pipeline stage states and overall (real) progress."""

    updated = Signal(object)
    finished = Signal(str)  # "COMPLETED" | "FAILED"

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._entries: List[StageEntry] = [
            StageEntry(sid, STAGE_LABELS.get(sid, sid)) for sid in PIPELINE_STAGES
        ]
        self._by_id: Dict[str, StageEntry] = {e.stage_id: e for e in self._entries}
        self._overall = 0.0
        self._finished = False
        self._outcome = ""

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def entries(self) -> List[StageEntry]:
        return list(self._entries)

    @property
    def overall_progress(self) -> float:
        return self._overall

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def outcome(self) -> str:
        """\"COMPLETED\" | \"FAILED\" | \"\" (not finished yet)."""
        return self._outcome

    def stage_entry(self, stage_id: str) -> Optional[StageEntry]:
        return self._by_id.get(stage_id)

    def running_entry(self) -> Optional[StageEntry]:
        for entry in self._entries:
            if entry.state == RUNNING:
                return entry
        return None

    def collect_metrics(self) -> Dict[str, Any]:
        """Merge real metrics reported by the pipeline (later wins)."""
        merged: Dict[str, Any] = {}
        for entry in self._entries:
            for key, value in (entry.metrics or {}).items():
                merged[key] = value
        return merged

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Return every stage to PENDING for a new analysis run."""
        for entry in self._entries:
            entry.state = PENDING
            entry.progress = 0.0
            entry.message = ""
            entry.metrics = {}
        self._overall = 0.0
        self._finished = False
        self._outcome = ""
        self.updated.emit(self)

    def handle_stage(self, stage_progress: Any) -> None:
        """Apply one ``StageProgress`` event from the pipeline."""
        stage_id = getattr(stage_progress, "stage_id", "") or ""
        if not stage_id:
            return
        entry = self._by_id.get(stage_id)
        if entry is None:
            name = getattr(stage_progress, "name", "") or stage_id
            entry = StageEntry(stage_id, name)
            self._entries.append(entry)
            self._by_id[stage_id] = entry

        entry.state = getattr(stage_progress, "state", RUNNING) or RUNNING
        entry.progress = float(getattr(stage_progress, "progress", 0.0) or 0.0)
        message = getattr(stage_progress, "message", "") or ""
        if message:
            entry.message = message
        metrics = getattr(stage_progress, "metrics", None) or {}
        if metrics:
            entry.metrics = dict(metrics)

        if entry.state == RUNNING:
            # The stage just started; any stage that was still running
            # before it has really finished.
            seen = False
            for other in self._entries:
                if other is entry:
                    seen = True
                    continue
                if not seen and other.state == RUNNING:
                    other.state = COMPLETED
                if seen:
                    break

        self._overall = max(self._overall, entry.progress)
        self.updated.emit(self)

    def note_metric(self, key: str, value: Any) -> None:
        """Attach one real measured metric without fabricating a stage event."""
        if value is None or value == "":
            return
        for entry in self._entries:
            if entry.state == COMPLETED:
                entry.metrics = dict(entry.metrics)
                entry.metrics[key] = value
        self.updated.emit(self)

    def finish(self, ok: bool, message: str = "") -> None:
        """Classify the tail of the pipeline after the worker completes or fails."""
        self._finished = True
        running = [e for e in self._entries if e.state == RUNNING]
        if ok:
            self._outcome = "COMPLETED"
            for entry in self._entries:
                if entry.state in (PENDING, RUNNING):
                    entry.state = COMPLETED
                if message and entry.state == COMPLETED:
                    entry.message = message
            self._overall = 1.0
            self.finished.emit("COMPLETED")
        else:
            self._outcome = "FAILED"
            failed = running[-1] if running else None
            reached_failed = failed is None
            for entry in self._entries:
                if entry is failed:
                    entry.state = FAILED
                    if message:
                        entry.message = message
                    reached_failed = True
                elif entry.state in (PENDING, RUNNING):
                    entry.state = SKIPPED if reached_failed else entry.state
            self.finished.emit("FAILED")
        self.updated.emit(self)


def _rgba(hex_color: str, alpha: int) -> str:
    """QSS-valid rgba() tint from a #RRGGBB color (Qt rejects #AARRGGBB)."""
    h = hex_color.lstrip("#")
    return (
        f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, "
        f"{int(h[4:6], 16)}, {alpha})"
    )


def format_metric(key: str, value: Any) -> str:
    """Human label for a real detected-object metric."""
    return {
        "shapes": f"{value} shapes detected",
        "arrows": f"{value} arrow candidates",
        "ocr": f"{value} OCR labels",
        "activities": f"{value} activities",
        "review_items": f"{value} review items",
        "nodes": f"{value} nodes",
        "edges": f"{value} edges",
    }.get(key, f"{key}: {value}")


_STATE_GLYPHS = {
    COMPLETED: "\u2713",
    RUNNING: "\u25CF",
    PENDING: "\u25CB",
    REVIEW_REQUIRED: "\u26a0",
    FAILED: "\u2717",
    SKIPPED: "\u2013",
}

_STATE_COLORS = {
    COMPLETED: SUCCESS,
    RUNNING: ACCENT,
    PENDING: TEXT_MUTED,
    REVIEW_REQUIRED: WARNING,
    FAILED: DANGER,
    SKIPPED: TEXT_MUTED,
}

# Quarter-circle wheel glyphs in order; the running stage chip cycles
# through them so the waiting user can see the current stage turn.
_SPINNER_FRAMES = ("\u25D0", "\u25D3", "\u25D1", "\u25D2")


class _SheenProgressBar(QProgressBar):
    """Slim progress bar with a travelling highlight.

    The plain blue chunk looks dead while a stage runs for several
    seconds without emitting events; the sheen keeps the bar visibly
    alive without inventing progress values.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._sheen_t = 0.0
        self._sheen_active = False

    def set_sheen_active(self, active: bool) -> None:
        self._sheen_active = bool(active)
        self.update()

    def sheen_tick(self, dt: float) -> None:
        if not self._sheen_active:
            return
        self._sheen_t = (self._sheen_t + dt) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = painter.viewport().adjusted(0, 1, -1, -2)
        radius = track.height() / 2
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(QColor(SURFACE))
        painter.drawRoundedRect(track, radius, radius)

        span = int(self.maximum() - self.minimum()) or 1
        frac = max(0.0, min(1.0, (self.value() - self.minimum()) / span))
        if frac <= 0.0:
            painter.end()
            return
        w = max(radius * 2, int(track.width() * frac))
        chunk = track.adjusted(0, 0, -(track.width() - w), 0)
        grad = QLinearGradient(0, chunk.top(), 0, chunk.bottom())
        grad.setColorAt(0.0, QColor(ACCENT))
        grad.setColorAt(1.0, QColor(ACCENT).lighter(130))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(chunk, radius, radius)

        if self._sheen_active and chunk.width() > radius * 4:
            # A narrow bright band slides forward through the filled part.
            band_w = max(8, int(chunk.width() * 0.16))
            cx = chunk.left() - band_w + self._sheen_t * (chunk.width() + band_w)
            sheen = QLinearGradient(cx, 0, cx + band_w, 0)
            sheen.setColorAt(0.0, QColor(255, 255, 255, 0))
            sheen.setColorAt(0.5, QColor(255, 255, 255, 70))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(sheen)
            sheen_rect = chunk.adjusted(max(0, int(cx) - chunk.left()), 0,
                                        0, 0)
            sheen_rect = sheen_rect.adjusted(0, 1, -1, -1)
            if sheen_rect.width() > 0:
                painter.drawRect(sheen_rect)
        painter.end()

    def visible_width(self) -> int:
        return self.width()


class _GearWidget(QWidget):
    """Small rotating gear for the panel headline.

    Pure decoration that answers 'is it running?' at a glance; stops
    spinning the moment the pipeline finishes.
    """

    TEETH = 10

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self._angle = 0.0
        self._spinning = False

    def set_spinning(self, spinning: bool) -> None:
        self._spinning = bool(spinning)
        self.update()

    def tick(self, dt_degrees: float) -> None:
        if not self._spinning:
            return
        self._angle = (self._angle + dt_degrees) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        color = QColor(ACCENT) if self._spinning else QColor(TEXT_MUTED)
        center = rect.center()
        outer = min(rect.width(), rect.height()) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)

        # NOTE: built from QPointF-center ellipse overloads + polygon
        # fills on purpose.  The connected-QPainterPath composition and
        # the (x, y, w, h) overloads crash the PySide6 6.9.x binding
        # during real raster paints on Windows (C0000005 inside
        # shiboken6.abi3.dll); the QPointF/polygon primitives do not.
        painter.drawEllipse(center, outer * 0.86, outer * 0.86)
        tooth_len = outer * 0.30
        pitch = outer * 0.86
        half = tooth_len * 0.5
        for i in range(self.TEETH):
            ang = math.radians(
                self._angle + i * (360.0 / self.TEETH)
            )
            dx, dy = math.cos(ang), math.sin(ang)
            nx, ny = -dy, dx
            tooth = QPolygonF([
                QPointF(center.x() + pitch * dx - nx * half,
                        center.y() + pitch * dy - ny * half),
                QPointF(center.x() + pitch * dx + nx * half,
                        center.y() + pitch * dy + ny * half),
                QPointF(center.x() + (pitch + tooth_len) * dx + nx * half,
                        center.y() + (pitch + tooth_len) * dy + ny * half),
                QPointF(center.x() + (pitch + tooth_len) * dx - nx * half,
                        center.y() + (pitch + tooth_len) * dy - ny * half),
            ])
            painter.drawPolygon(tooth)

        # Spokes: cut a smaller hole + the hub.
        painter.setBrush(QColor(SURFACE_LIGHT))
        painter.drawEllipse(center, outer * 0.42, outer * 0.42)
        painter.setBrush(color)
        painter.drawEllipse(center, outer * 0.20, outer * 0.20)
        painter.end()


class _LiveWireframe(QWidget):
    """Mini AON wireframe that visibly "builds" while the pipeline runs.

    Decorative, but driven only by real pipeline counters: ``shapes``
    grows the nodes, ``arrows`` (or ``activities`` while the graph is
    assembled) grows the edges.  Nothing is invented: the wireframe
    simply mirrors what the stages already report.

    Painted exclusively with the primitive set that survived the
    PySide6 6.9.1 forensics: ``fillRect``, pen + ``drawRoundedRect``
    over a ``QRectF``, ``drawEllipse(QPointF, r, r)`` and int
    ``drawLine``.  No ``QPainterPath``, no four-float ellipse, no
    two-argument ``QColor``.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(150)
        self.setMinimumHeight(96)
        # Real counter targets + eased visible counters.
        self._target_nodes = 0
        self._target_edges = 0
        self._shown_nodes = 0.0
        self._shown_edges = 0.0
        self._running = False
        self._done = False
        self._failed = False
        self._phase = 0

    # ------------------------------------------------------------------
    # Data plumbing
    # ------------------------------------------------------------------

    def set_metrics(
        self,
        metrics: Dict[str, Any],
        running: bool,
        done: bool,
        failed: bool,
    ) -> None:
        native = dict(metrics or {})
        self._target_nodes = int(native.get("shapes") or 0)
        edges = native.get("arrows")
        if not edges:
            edges = native.get("activities")
        self._target_edges = int(edges or 0)
        self._running = bool(running)
        self._done = bool(done)
        self._failed = bool(failed)
        if not self._running:
            # Idle/finished: no beat to ease with — snap into place so
            # resets drain instantly and the final frame is static.
            self._shown_nodes = float(self._target_nodes)
            self._shown_edges = float(self._target_edges)
        self.update()

    def tick(self, phase: int) -> None:
        """One 33ms machine beat: ease the build counters toward targets."""
        self._phase = phase
        rate = 0.16
        self._shown_nodes += (self._target_nodes - self._shown_nodes) * rate
        self._shown_edges += (self._target_edges - self._shown_edges) * rate
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _node_layout(self, count: int):
        """Deterministic grid positions for ``count`` nodes."""
        w = float(self.width())
        h = float(self.height())
        cols = max(3, min(8, int((w - 24.0) // 26.0)))
        cols = max(cols, 1)
        rows = max(1, (count + cols - 1) // cols)
        gap_x = (w - 24.0) / cols
        # Vertically the grid must FIT the widget: squeeze the row gap
        # down before letting rows clip (22 nodes on a narrow well must
        # stay fully visible in ~110px).
        gap_y = max(11.0, min(26.0, (h - 20.0) / rows))
        top = (h - (rows - 1) * gap_y) / 2.0
        top = max(8.0, top)
        positions = []
        for idx in range(count):
            r, c = divmod(idx, cols)
            positions.append(QPointF(12.0 + gap_x * (c + 0.5),
                                     top + gap_y * r))
        return positions

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())

        painter.fillRect(QRectF(0, 0, w, h), QColor(SURFACE))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1),
                                RADIUS_MD, RADIUS_MD)

        n_shown = int(self._shown_nodes)
        if n_shown <= 0:
            # Idle well: a couple of ghost rings waiting for data.
            ghost = QColor(BORDER)
            ghost.setAlpha(70)
            painter.setPen(QPen(ghost, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(w * 0.30, h * 0.50), 6.0, 6.0)
            painter.drawEllipse(QPointF(w * 0.50, h * 0.42), 6.0, 6.0)
            painter.drawEllipse(QPointF(w * 0.70, h * 0.54), 6.0, 6.0)
            painter.end()
            return

        positions = self._node_layout(n_shown)
        if self._done and not self._failed:
            edge_color = QColor(SUCCESS)
            node_color = QColor(SUCCESS)
        elif self._failed:
            edge_color = QColor(DANGER)
            node_color = QColor(DANGER)
        else:
            edge_color = QColor(ACCENT)
            node_color = QColor(ACCENT)

        # --- edges first so nodes sit on top.
        e_shown = int(self._shown_edges)
        frac_e = self._shown_edges - e_shown
        chain = max(n_shown - 1, 0)
        links = []
        for k in range(min(e_shown, chain)):
            links.append((k, k + 1, 1.0))
        extras = max(0, e_shown - chain)
        for k in range(extras):
            base = k % max(chain, 1)
            b = min(n_shown - 1, base + 2)
            if b > base:
                links.append((base, b, 1.0))
        if self._running and frac_e > 0.05 and links:
            last = links[-1]
            links[-1] = (last[0], last[1], min(1.0, frac_e))
        painter.setPen(QPen(edge_color, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for a, b, t in links:
            pa, pb = positions[a], positions[b]
            if t < 1.0:
                mx = pa.x() + (pb.x() - pa.x()) * t
                my = pa.y() + (pb.y() - pa.y()) * t
                painter.drawLine(int(pa.x()), int(pa.y()), int(mx), int(my))
            else:
                painter.drawLine(int(pa.x()), int(pa.y()),
                                 int(pb.x()), int(pb.y()))

        # --- nodes.
        pop = self._shown_nodes - n_shown
        for i, p in enumerate(positions):
            base_f = 1.0
            r = 5.0
            fill = QColor(node_color)
            is_popping = (i == n_shown - 1) and (self._running or pop > 0.02)
            if is_popping and pop > 0.02:
                r = 3.0 + 2.5 * pop
                base_f = 0.55 + 0.45 * pop
                fill.setAlpha(max(40, int(230 * pop)))
            if self._running and is_popping:
                breath = 1.0 + 0.18 * math.sin(self._phase * 0.6)
                r *= breath
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawEllipse(p, r * base_f, r * base_f)
            if self._running and is_popping:
                halo = QColor(node_color)
                halo.setAlpha(70)
                painter.setPen(QPen(halo, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(p, r + 3.0, r + 3.0)

        if self._failed:
            # A clear "this is where it died" mark on the last node.
            p = positions[-1]
            painter.setPen(QPen(QColor(DANGER), 2))
            for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                painter.drawLine(int(p.x() + dx * 4), int(p.y() + dy * 4),
                                 int(p.x() - 0), int(p.y() - 0))
        painter.end()


class StageProgressPanel(QWidget):
    """Animated pipeline monitor: chips checklist, machine gear, timers.

    The model remains the single source of truth (real pipeline stages,
    never invented percentages); the panel only renders it with life -
    stage chips that light up, a spinning gear while a stage runs, a
    sheen travelling through the progress bar, a typewriter for the
    current message and an elapsed-time counter.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._model: Optional[AnalysisProgressModel] = None
        self._chips: List[QLabel] = []
        self._spin_phase = 0
        self._type_pos = 0
        self._type_target = ""
        self._run_seconds = 0

        card = QFrame(self)
        card.setObjectName("progressCard")
        card.setStyleSheet(
            f"QFrame#progressCard {{ background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(LG, MD, LG, MD)
        card_layout.setSpacing(SM)

        header = QHBoxLayout()
        header.setSpacing(MD)
        self._gear = _GearWidget()
        header.addWidget(self._gear)
        self._title = QLabel("ANALYZING DIAGRAM")
        self._title.setFont(QFont(*STATUS_FONT))
        self._title.setStyleSheet(f"color: {TEXT}; border: none; background: transparent;")
        header.addWidget(self._title)
        header.addStretch()
        self._elapsed_label = QLabel("\u23f1 00:00")
        self._elapsed_label.setFont(QFont(*STATUS_FONT))
        self._elapsed_label.setStyleSheet(f"color: {TEXT_MUTED}; border: none; background: transparent;")
        header.addWidget(self._elapsed_label)
        self._percent_label = QLabel("0%")
        self._percent_label.setFont(QFont(*STATUS_FONT))
        self._percent_label.setStyleSheet(
            f"color: {ACCENT}; border: none; background: transparent;"
        )
        header.addWidget(self._percent_label)
        card_layout.addLayout(header)

        # Stage chips: one pill per pipeline stage. The plain-text
        # checklist below stays as the model-to-screen mirror the tests
        # read, but is kept invisible so the two renderers never fight.
        chip_row = QWidget()
        chip_row.setStyleSheet("background: transparent; border: none;")
        self._chips_layout = QHBoxLayout(chip_row)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()
        card_layout.addWidget(chip_row)
        self._chip_row = chip_row  # A-5b elide budgets measure this row

        # A-4 live wireframe: the mini AON graph the user asked for.
        # It sits LEFT of the textual rows (stage/bar/message/metrics)
        # so the chips keep the full card width and the diagram image
        # keeps its full preview size.
        body_row = QHBoxLayout()
        body_row.setSpacing(LG)
        self._wireframe = _LiveWireframe()
        body_row.addWidget(self._wireframe)

        text_col = QVBoxLayout()
        text_col.setSpacing(SM)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(LG)
        self._stage_row = QLabel("<b>Current stage:</b> \u2014")
        self._stage_row.setTextFormat(Qt.TextFormat.RichText)
        self._stage_row.setFont(QFont(*BODY_SMALL_FONT))
        self._stage_row.setStyleSheet(
            "color: %s; border: none; background: transparent;" % TEXT
        )
        summary_row.addWidget(self._stage_row)
        summary_row.addStretch()
        self._detected_row = QLabel("<b>Detected:</b> \u2014")
        self._detected_row.setTextFormat(Qt.TextFormat.RichText)
        self._detected_row.setFont(QFont(*BODY_SMALL_FONT))
        self._detected_row.setStyleSheet(
            "color: %s; border: none; background: transparent;" % TEXT
        )
        summary_row.addWidget(self._detected_row)
        text_col.addLayout(summary_row)

        self._progress = _SheenProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        text_col.addWidget(self._progress)

        self._message = QLabel("Preparing analysis\u2026")
        self._message.setWordWrap(True)
        self._message.setFont(QFont(*LABEL_FONT))
        self._message.setStyleSheet(f"color: {TEXT_MUTED}; border: none; background: transparent;")
        text_col.addWidget(self._message)

        self._checklist = QLabel("")
        self._checklist.setTextFormat(Qt.TextFormat.RichText)
        self._checklist.setWordWrap(True)
        self._checklist.setFont(QFont(*BODY_SMALL_FONT))
        self._checklist.setStyleSheet("color: %s; border: none; background: transparent;" % TEXT)
        self._checklist.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        # Hidden mirror: the chips row is the visible renderer.
        self._checklist.hide()
        text_col.addWidget(self._checklist)

        self._metrics = QLabel("")
        self._metrics.setWordWrap(True)
        self._metrics.setFont(QFont(*MUTED_FONT))
        text_col.addWidget(self._metrics)

        body_row.addLayout(text_col)
        card_layout.addLayout(body_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, SM, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(card)

        # Machine clock: one fast timer paints every animation (gear
        # angle, spinner frame, chip pulse, typewriter, sheen) and a
        # 1 Hz timer walks the elapsed counter.
        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._on_anim_tick)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._on_elapsed_tick)

    # ------------------------------------------------------------------
    # Model wiring
    # ------------------------------------------------------------------

    def set_model(self, model: AnalysisProgressModel) -> None:
        """Bind the panel to a progress model and render its current state."""
        if self._model is model and self._model is not None:
            return
        if self._model is not None:
            try:
                self._model.updated.disconnect(self._on_updated)
            except (TypeError, RuntimeError):
                pass
        self._model = model
        if model is not None:
            model.updated.connect(self._on_updated)
            self._on_updated(model)

    @property
    def model(self) -> Optional[AnalysisProgressModel]:
        return self._model

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _on_updated(self, model: Any) -> None:
        if model is None:
            return
        percent = int(round(model.overall_progress * 100))
        self._progress.setValue(min(100, max(0, percent)))
        self._percent_label.setText(f"{percent}%")

        running = model.running_entry()

        # Machine state: gears, sheen, spinner and elapsed counter run
        # only while the pipeline still has a live stage.
        self._apply_running(
            running is not None and not getattr(model, "is_finished", False)
        )

        self._sync_chips(model)
        self._sync_title(model)
        self._sync_wireframe(model)
        lines: List[str] = []
        for entry in model.entries:
            glyph = _STATE_GLYPHS.get(entry.state, PENDING)
            color = _STATE_COLORS.get(entry.state, TEXT_MUTED)
            name = entry.name or entry.stage_id
            if entry.state == RUNNING and entry.message:
                name = f"{name} \u2014 {entry.message}"
            lines.append(
                f'<font color="{color}">{glyph}</font> {name}'
            )
        self._checklist.setText("<br/>".join(lines))

        if running is not None:
            stage_name = running.name or running.stage_id
        elif getattr(model, "is_finished", False):
            stage_name = "Complete"
        else:
            stage_name = "\u2014"
        self._stage_row.setText(f"<b>Current stage:</b> {stage_name}")
        self._detected_row.setText(f"<b>Detected:</b> {self._detected_text(model)}")

        if running is not None and running.message:
            self._set_message(running.message)
        elif running is not None:
            self._set_message(f"Running: {running.name}")
        else:
            self._set_message(self._status_line(model))

        self._render_metrics(model.collect_metrics())

    # ------------------------------------------------------------------
    # Animation plumbing
    # ------------------------------------------------------------------

    def _apply_running(self, running: bool) -> None:
        """Start/stop the machine: gear, sheen, spinner, elapsed clock."""
        self._gear.set_spinning(running)
        self._progress.set_sheen_active(running)
        self._elapsed_label.setVisible(running)
        if running:
            if not self._anim.isActive():
                self._spin_phase = 0
                self._run_seconds = 0
                self._elapsed_label.setText("\u23f1 00:00")
                self._anim.start()
                self._elapsed_timer.start()
            return
        if self._anim.isActive():
            self._anim.stop()
            # Flush any half-typed message so the final text is complete.
            self._type_pos = len(self._type_target)
            self._message.setText(self._type_target)
        if self._elapsed_timer.isActive():
            self._elapsed_timer.stop()

    def _on_anim_tick(self) -> None:
        self._spin_phase = (self._spin_phase + 1) % 64
        self._gear.tick(8.0)  # 8 deg per 33ms ~ one turn per 1.5s
        self._progress.sheen_tick(1.0 / 45.0)
        self._wireframe.tick(self._spin_phase)
        # Typewriter reveals ~5 chars per tick.
        if self._type_pos < len(self._type_target):
            self._type_pos = min(
                len(self._type_target), self._type_pos + 5
            )
            self._message.setText(self._type_target[: self._type_pos])
        self._refresh_running_chips()

    def _on_elapsed_tick(self) -> None:
        self._run_seconds += 1
        mm, ss = divmod(self._run_seconds, 60)
        self._elapsed_label.setText(f"\u23f1 {mm:02d}:{ss:02d}")

    def _set_message(self, text: str) -> None:
        """Retype the current message only when it actually changed.

        The typewriter only runs while the machine is animating; when
        the pipeline is idle (finished/failed) the full text appears
        instantly, otherwise the completion message would stay blank.
        """
        if text == self._type_target:
            if self._type_pos >= len(self._type_target) or (
                not self._anim.isActive()
            ):
                self._message.setText(text)
            return
        self._type_target = text
        if not self._anim.isActive():
            self._type_pos = len(text)
            self._message.setText(text)
            return
        self._type_pos = 0
        self._message.setText("")

    def _sync_chips(self, model: Any) -> None:
        """One chip per stage; created lazily, restyled on every update."""
        entries = model.entries
        while len(self._chips) < len(entries):
            chip = QLabel("", self)
            chip.setObjectName("stageChip")
            chip.setFont(QFont(*BODY_SMALL_FONT))
            chip._full_text = ""
            chip._px_budget = 0.0
            chip._is_elided = False
            chip._chip_name = ""
            chip._default_tip = ""
            insert_at = self._chips_layout.count() - 1  # before the stretch
            self._chips_layout.insertWidget(insert_at, chip)
            self._chips.append(chip)
        # Scheme: chip index mirrors entries order; when stages are
        # removed (never expected) drop extras defensively.
        while len(self._chips) > len(entries):
            chip = self._chips.pop()
            self._chips_layout.removeWidget(chip)
            chip.deleteLater()
        for chip, entry in zip(self._chips, entries):
            chip._chip_name = entry.name or entry.stage_id
            chip._default_tip = entry.message or chip._chip_name
            # Tooltip default is the stage message; an elided chip
            # overrides it with the full name inside _set_chip_text.
            if not getattr(chip, "_is_elided", False):
                chip.setToolTip(chip._default_tip)
        self._refresh_running_chips()
        self._apply_chip_budgets()

    def _refresh_running_chips(self) -> None:
        """Animate chips cheaply: restyle on state change only.

        The running chip's spinner glyph rotates via setText (~4 Hz);
        its stylesheet is touched ONLY on state transitions so we never
        repolish QSS 30 times per second.
        """
        model = self._model
        if model is None:
            return
        frames = len(_SPINNER_FRAMES)
        frame_idx = (self._spin_phase // 8) % frames
        for chip, entry in zip(self._chips, model.entries):
            state = entry.state
            last = getattr(chip, "_styled_state", None)
            if last != state:
                self._restyle_chip(chip, state)
                chip._styled_state = state
            if state == RUNNING and getattr(chip, "_frame_idx", -1) != (
                frame_idx
            ):
                chip._frame_idx = frame_idx
                name = getattr(chip, "_chip_name", "") or ""
                self._set_chip_text(
                    chip, f"{_SPINNER_FRAMES[frame_idx]} {name}"
                )

    def _restyle_chip(self, chip: QLabel, state: str) -> None:
        color = _STATE_COLORS.get(state, TEXT_MUTED)
        idx = self._chips.index(chip) if chip in self._chips else -1
        name = ""
        if idx >= 0 and self._model is not None:
            entries = self._model.entries
            if idx < len(entries):
                name = entries[idx].name or entries[idx].stage_id
        if state == RUNNING:
            glyph = _SPINNER_FRAMES[
                (self._spin_phase // 8) % len(_SPINNER_FRAMES)
            ]
            chip._frame_idx = (self._spin_phase // 8) % len(_SPINNER_FRAMES)
            self._set_chip_text(chip, f"{glyph} {name}")
            chip.setStyleSheet(
                f"QLabel {{ background-color: {_rgba(ACCENT, 60)};"
                f" color: {ACCENT}; border: 1px solid {ACCENT};"
                f" border-radius: 10px; padding: 3px 10px;"
                f" font-weight: 600; }}"
            )
            return
        glyph = _STATE_GLYPHS.get(state, "\u25CB")
        self._set_chip_text(chip, f"{glyph} {name}")
        if state == COMPLETED:
            bg = _rgba(SUCCESS, 26)
        elif state == FAILED:
            bg = _rgba(DANGER, 26)
        elif state == REVIEW_REQUIRED:
            bg = _rgba(WARNING, 26)
        else:
            bg = _rgba(TEXT_MUTED, 16)
        chip.setStyleSheet(
            f"QLabel {{ background-color: {bg}; color: {color};"
            f" border: 1px solid {bg}; border-radius: 10px;"
            f" padding: 3px 10px; }}"
        )

    # ------------------------------------------------------------------
    # A-5b: smart chip elide — one tidy row, full name on hover
    # ------------------------------------------------------------------

    _CHIP_TEXT_PAD = 20.0  # QSS padding: 3px 10px  → 20px horizontal

    def _set_chip_text(self, chip: QLabel, text: str) -> None:
        """Route EVERY chip text assignment through here.

        Keeps ``chip._full_text`` authoritative, honours the chip's
        width budget (set by ``_apply_chip_budgets``) by eliding to
        '…', and swaps the tooltip to the full stage name while the
        text is trimmed.  Chips are never dropped: membership in
        ``_chips`` (what the tests read) is untouched.
        """
        chip._full_text = text
        budget = float(getattr(chip, "_px_budget", 0.0) or 0.0)
        fm = QFontMetrics(chip.font())
        if budget >= 8.0 and fm.horizontalAdvance(text) > budget:
            budget_px = max(8.0, budget - self._CHIP_TEXT_PAD)
            elided = fm.elidedText(
                text, Qt.TextElideMode.ElideRight, int(budget_px)
            )
            chip.setText(elided)
            chip._is_elided = True
            chip.setToolTip(
                getattr(chip, "_chip_name", "") or text
            )
        else:
            chip.setText(text)
            chip._is_elided = False
            chip.setToolTip(
                getattr(chip, "_default_tip", "") or text
            )

    def _apply_chip_budgets(self) -> None:
        """Water-filling budgets so 12 pills share one row gracefully.

        Every chip first asks for its natural width; when the row
        cannot hold them all the surplus is spread evenly (smallest
        labels keep theirs, roomy labels donate).  Result: minimum
        damage per pill, right-side '…', full name on hover.
        """
        row = getattr(self, "_chip_row", None)
        chips = self._chips
        n = len(chips)
        if n == 0 or row is None:
            return
        avail = row.width()
        if avail <= 0:
            return  # layout not resolved yet; resizeEvent will call us
        gap = self._chips_layout.spacing() or 6
        usable = avail - gap * (n - 1)
        if usable <= 0:
            return
        natural = []
        for chip in chips:
            text = getattr(chip, "_full_text", "") or chip.text()
            fm = QFontMetrics(chip.font())
            natural.append(
                fm.horizontalAdvance(text) + self._CHIP_TEXT_PAD
            )
        if sum(natural) <= usable:
            for chip in chips:
                if getattr(chip, "_px_budget", 0.0) or getattr(
                    chip, "_is_elided", False
                ):
                    chip._px_budget = 0.0
                    self._set_chip_text(
                        chip, getattr(chip, "_full_text", "")
                    )
            return
        budgets = [usable / n] * n
        for _pass in range(4):
            freed = 0.0
            donors = []
            for i, (budget, nat) in enumerate(zip(budgets, natural)):
                if nat <= budget:
                    freed += budget - nat
                    budgets[i] = float(nat)
                    donors.append(i)
            if not donors or freed <= 0.5:
                break
            share = freed / len(donors)
            for i in donors:
                budgets[i] += share
        for chip, budget in zip(chips, budgets):
            chip._px_budget = float(budget)
            self._set_chip_text(chip, getattr(chip, "_full_text", ""))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_chip_budgets()

    def _sync_title(self, model: Any) -> None:
        """Header reflects the machine state: running vs. outcome."""
        if not getattr(model, "is_finished", False):
            self._title.setText("ANALYZING DIAGRAM")
            self._title.setStyleSheet(
                f"color: {TEXT}; border: none; background: transparent;"
            )
            return
        if (getattr(model, "outcome", "") or "COMPLETED") == "FAILED":
            color, label = DANGER, "ANALYSIS FAILED"
        else:
            color, label = SUCCESS, "ANALYSIS COMPLETE"
        self._title.setText(label)
        self._title.setStyleSheet(
            f"color: {color}; border: none; background: transparent;"
        )

    def _sync_wireframe(self, model: Any) -> None:
        """Feed the mini AON wireframe the REAL counters reported so far."""
        finished = getattr(model, "is_finished", False)
        outcome = getattr(model, "outcome", "") or "COMPLETED"
        self._wireframe.set_metrics(
            model.collect_metrics(),
            running=not finished and model.running_entry() is not None,
            done=finished and outcome != "FAILED",
            failed=finished and outcome == "FAILED",
        )

    def _status_line(self, model: Any) -> str:
        if getattr(model, "is_finished", False):
            return "Analysis complete."
        done = sum(1 for e in model.entries if e.state == COMPLETED)
        if done == 0:
            return "Preparing analysis\u2026"
        return f"{done} of {len(model.entries)} stages complete."

    def _detected_text(self, model: Any) -> str:
        """Compact human summary of the detection metrics gathered so far."""
        metrics = model.collect_metrics()
        parts: List[str] = []
        for key in ("shapes", "arrows", "ocr", "activities", "review_items"):
            value = metrics.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)) and value == 0:
                continue
            parts.append(format_metric(key, value))
        return "  \u00b7  ".join(parts) if parts else "\u2014"

    def _render_metrics(self, metrics: Dict[str, Any]) -> None:
        parts: List[str] = []
        for key in ("shapes", "arrows", "ocr", "activities", "review_items"):
            value = metrics.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)) and value == 0:
                continue
            parts.append(
                f'<span style="color:{ACCENT};">{format_metric(key, value)}</span>'
            )
        self._metrics.setText("  \u00b7  ".join(parts) if parts else "")