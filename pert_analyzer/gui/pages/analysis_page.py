"""
Analysis page: image upload, preview, Analyze button, status panel.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from typing import Any, Optional

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.analysis_progress import (
    AnalysisProgressModel,
    StageProgressPanel,
)
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BORDER,
    DANGER,
    SURFACE,
    SURFACE_LIGHT,
    SUCCESS,
    TEXT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    WARNING,
)
from pert_analyzer.gui.themes.typography import (
    BODY_SMALL_FONT,
    BODY_FONT,
    LABEL_FONT,
    MUTED_FONT,
    SUBTITLE_FONT,
    TITLE_FONT,
    KPI_FONT,
)
from pert_analyzer.gui.themes.spacing import (
    LG,
    MD,
    RADIUS_LG,
    RADIUS_MD,
    SM,
    XL,
    XS,
)

logger = logging.getLogger(__name__)


def _pixmap_from_pil(path: str) -> Optional[QPixmap]:
    """Load an image via PIL as a fallback for formats Qt cannot decode (e.g. TIFF)."""
    try:
        from PIL import Image as _PILImage

        from PySide6.QtGui import QImage as _QImage

        img = _PILImage.open(path).convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = _QImage(data, img.width, img.height, _QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())
    except Exception:
        return None


_IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".webp",
}

_MAX_ZOOM = 8.0
_ZOOM_STEP = 1.25


def _accent_color(alpha: int) -> QColor:
    """ACCENT with an explicit alpha.

    Deliberately avoids the two-argument QColor(name, alpha)
    constructor: build from the plain hex name, then setAlpha.
    """
    color = QColor(ACCENT)
    color.setAlpha(int(alpha))
    return color


class ImageView(QLabel):
    """
    Image preview with fit / zoom / pan / reset and drag-and-drop support.

    Behaves like the previous QLabel preview (same ``set_image`` / ``clear_image``
    / ``text()`` API) but paints the image itself so zoom and pan work while the
    diagram always stays fitted on load.
    """

    image_dropped = Signal(str)
    zoom_changed = Signal(float)
    activate_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._press_pos: Optional[QPoint] = None
        self._pan_origin = QPoint(0, 0)
        self._drag_hover = False
        # Live scanning sweep while the pipeline runs on this diagram.
        self._scanning = False
        self._scan_t = 0.0
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(33)
        self._scan_timer.timeout.connect(self._advance_scan)
        self.setMinimumHeight(240)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._set_placeholder()

    def set_scanning(self, on: bool) -> None:
        """Animate (or stop) the scanning sweep over the loaded image."""
        on = bool(on)
        if on == self._scanning:
            return
        self._scanning = on
        if on:
            self._scan_t = 0.0
            self._scan_timer.start()
        else:
            self._scan_timer.stop()
        self.update()

    def is_scanning(self) -> bool:
        return self._scanning

    def _advance_scan(self) -> None:
        # 33ms per tick across a ~2s full sweep (ping-pong feels alive).
        self._scan_t += 1.0 / 60.0
        if self._scan_t >= 2.0:
            self._scan_t -= 2.0
        self.update()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _set_placeholder(self) -> None:
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self.setText(
            "\u2315  No image selected\n"
            "Upload a PERT/CPM network diagram to begin"
        )
        self.update()

    def set_image(self, path: str) -> tuple[int, int]:
        """Load and display an image. Returns (width, height) or (0,0) on failure."""
        self._pixmap = QPixmap(path)
        if self._pixmap.isNull():
            # Fall back to PIL for formats Qt cannot decode (e.g. TIFF).
            self._pixmap = _pixmap_from_pil(path)
        if self._pixmap is None or self._pixmap.isNull():
            self._set_placeholder()
            return (0, 0)
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self.setText("")
        self._update_cursor()
        self.update()
        return (self._pixmap.width(), self._pixmap.height())

    def clear_image(self) -> None:
        self._pixmap = None
        self._set_placeholder()

    def zoom_in(self) -> None:
        self._zoom_around(self.width() / 2, self.height() / 2, _ZOOM_STEP)

    def zoom_out(self) -> None:
        self._zoom_around(self.width() / 2, self.height() / 2, 1.0 / _ZOOM_STEP)

    def fit_image(self) -> None:
        self.reset_zoom()

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self.update()

    def set_zoom(self, factor: float) -> None:
        """Set an absolute zoom factor, clamped to the supported range."""
        self._set_zoom_at(factor)

    def _set_zoom_at(self, factor: float) -> None:
        self._zoom = min(_MAX_ZOOM, max(1.0, float(factor)))
        self._clamp_pan()
        self.update()

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    @property
    def is_zoomed(self) -> bool:
        return self._zoom > 1.0

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    @staticmethod
    def drop_path_from_mime(mime: Any) -> Optional[str]:
        """Return the first local image path found in a drag/paste payload."""
        if mime is None or not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.splitext(path)[1].lower() in _IMAGE_EXTS:
                return path
        return None

    def accepts_drop(self, mime: Any) -> bool:
        """Whether an incoming drag payload can be loaded as a diagram."""
        return self.drop_path_from_mime(mime) is not None

    def load_dropped(self, mime: Any) -> Optional[str]:
        """Consume a drop payload, emitting ``image_dropped`` for the page."""
        path = self.drop_path_from_mime(mime)
        if path:
            self.image_dropped.emit(path)
        return path

    def set_drag_hover(self, on: bool) -> None:
        if on != self._drag_hover:
            self._drag_hover = on
            self._update_cursor()
            self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self.accepts_drop(event.mimeData()):
            self.set_drag_hover(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_drag_hover(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        path = self.drop_path_from_mime(event.mimeData())
        self.set_drag_hover(False)
        if path:
            self.load_dropped(event.mimeData())
            event.acceptProposedAction()
        else:
            event.ignore()

    # ------------------------------------------------------------------
    # Zoom / pan internals
    # ------------------------------------------------------------------

    def _content_size(self) -> tuple[float, float]:
        if self._pixmap is None or self._pixmap.isNull():
            return (0, 0)
        view_w, view_h = max(1, self.width()), max(1, self.height())
        fit = min(
            view_w / self._pixmap.width(), view_h / self._pixmap.height()
        )
        total = fit * self._zoom
        return total * self._pixmap.width(), total * self._pixmap.height()

    def _zoom_around(self, cx: float, cy: float, factor: float) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()
        view_w, view_h = max(1, self.width()), max(1, self.height())
        fit = min(view_w / pix_w, view_h / pix_h)
        new_zoom = min(_MAX_ZOOM, max(1.0, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        old_w, old_h = self._content_size()
        new_total = fit * new_zoom
        new_w, new_h = new_total * pix_w, new_total * pix_h
        if old_w > 1 and old_h > 1:
            fx = (cx - (view_w - old_w) / 2 - self._pan.x()) / old_w
            fy = (cy - (view_h - old_h) / 2 - self._pan.y()) / old_h
        else:
            fx = fy = 0.5
        self._zoom = new_zoom
        self._pan = QPoint(
            int(round((view_w - new_w) / 2 + fx * new_w - cx)),
            int(round((view_h - new_h) / 2 + fy * new_h - cy)),
        )
        self._clamp_pan()
        self._update_cursor()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def _clamp_pan(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self._pan = QPoint(0, 0)
            return
        view_w, view_h = max(1, self.width()), max(1, self.height())
        disp_w, disp_h = self._content_size()
        slip_x = disp_w - view_w
        slip_y = disp_h - view_h
        lo_x, hi_x = -max(0, slip_x / 2), max(0, slip_x / 2)
        lo_y, hi_y = -max(0, slip_y / 2), max(0, slip_y / 2)
        if disp_w <= view_w:
            lo_x = hi_x = int(round((view_w - disp_w) / 2))
        if disp_h <= view_h:
            lo_y = hi_y = int(round((view_h - disp_h) / 2))
        self._pan.setX(max(int(lo_x), min(int(hi_x), self._pan.x())))
        self._pan.setY(max(int(lo_y), min(int(hi_y), self._pan.y())))

    def _update_cursor(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.unsetCursor()
            return
        if self._panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.is_zoomed:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        del event  # unused
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(SURFACE))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        edge = self.rect().adjusted(1, 1, -1, -1)

        if self._pixmap is None or self._pixmap.isNull():
            border = QColor(ACCENT if self._drag_hover else BORDER)
            pen = QPen(border)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(edge, RADIUS_LG, RADIUS_LG)
            painter.setFont(QFont(*BODY_SMALL_FONT))
            painter.setPen(QColor(ACCENT if self._drag_hover else TEXT_MUTED))
            if self._drag_hover:
                text = "\u2913  Drop diagram here\nRelease to load this image"
            else:
                text = self.text() or "\u2315  No image selected"
            painter.drawText(
                edge,
                Qt.AlignmentFlag.AlignCenter,
                text,
            )
            painter.end()
            return

        painter.setClipRect(edge)
        disp_w, disp_h = self._content_size()
        target_w = max(1, int(round(disp_w)))
        target_h = max(1, int(round(disp_h)))
        scaled = self._pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (edge.width() - target_w) / 2 + self._pan.x()
        y = (edge.height() - target_h) / 2 + self._pan.y()
        painter.drawPixmap(int(round(x)), int(round(y)), scaled)

        if self._scanning:
            self._paint_scan_overlay(
                painter, x, y, target_w, target_h, edge
            )

        if self._drag_hover:
            pen = QPen(QColor(ACCENT), 2)
            painter.setPen(pen)
            painter.drawRoundedRect(edge, RADIUS_LG, RADIUS_LG)

        painter.end()

    def _paint_scan_overlay(
        self,
        painter: QPainter,
        img_x: float,
        img_y: float,
        img_w: float,
        img_h: float,
        frame: "QRect",
    ) -> None:
        """Machine-eye sweep: corner brackets + a glowing beam riding
        the image while the pipeline reads it."""
        painter.save()
        # Soft veil so the beam pops against the diagram.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(6, 12, 22, 54))
        painter.drawRect(frame)

        band = max(12, int(img_h / 90))
        # 0..1..0 ping-pong so the eye travels down and returns.
        y_frac = min(1.0, max(0.0, 1.0 - abs(1.0 - self._scan_t)))
        y_center = img_y + y_frac * img_h
        top = y_center - band
        grad = QLinearGradient(
            0, float(top), 0, float(top + band * 2)
        )
        grad.setColorAt(0.0, _accent_color(0))
        grad.setColorAt(0.5, _accent_color(70))
        grad.setColorAt(1.0, _accent_color(0))
        painter.setBrush(grad)
        x0 = max(frame.left(), int(img_x))
        x1 = min(frame.right(), int(img_x + img_w))
        if x1 > x0 and top + band > frame.top() and top - band < frame.bottom():
            painter.drawRect(x0, int(max(frame.top(), top)), x1 - x0, band * 2)
            # Core line of the beam.
            pen = QPen(_accent_color(210), 2)
            painter.setPen(pen)
            line_y = min(max(float(y_center), frame.top() + 1),
                         frame.bottom() - 1)
            painter.drawLine(
                x0, int(line_y), x1, int(line_y)
            )

        # Corner brackets framing the area being read.
        margin = 18
        length = 26
        pen = QPen(_accent_color(200), 2)
        painter.setPen(pen)
        bx0, by0 = int(img_x + margin), int(img_y + margin)
        bx1, by1 = int(img_x + img_w - margin), int(img_y + img_h - margin)
        if bx1 > bx0 and by1 > by0:
            painter.drawLine(bx0, by0 + length, bx0, by0)
            painter.drawLine(bx0, by0, bx0 + length, by0)
            painter.drawLine(bx1 - length, by1, bx1, by1)
            painter.drawLine(bx1, by1, bx1, by1 - length)
            painter.drawLine(bx1, by0, bx1, by0 + length)
            painter.drawLine(bx1 - length, by0, bx1, by0)
            painter.drawLine(bx0 + length, by1, bx0, by1)
            painter.drawLine(bx0, by1 - length, bx0, by1)
        painter.restore()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._clamp_pan()
        self.update()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._pixmap is None or self._pixmap.isNull():
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = _ZOOM_STEP if delta > 0 else 1.0 / _ZOOM_STEP
        pos = event.position().toPoint()
        self._zoom_around(pos.x(), pos.y(), factor)
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._pixmap is None or self._pixmap.isNull():
            if event.button() == Qt.MouseButton.LeftButton:
                self.activate_requested.emit()
                event.accept()
                return
            super().mousePressEvent(event)
            return
        if (
            self.is_zoomed
            and event.button() == Qt.MouseButton.LeftButton
            and self._pixmap is not None
        ):
            self._panning = True
            self._press_pos = event.position().toPoint()
            self._pan_origin = QPoint(self._pan)
            self._update_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning and self._press_pos is not None:
            pos = event.position().toPoint()
            delta = pos - self._press_pos
            self._pan = QPoint(self._pan_origin.x() + delta.x(), self._pan_origin.y() + delta.y())
            self._clamp_pan()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._press_pos = None
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class StatusPanel(QWidget):
    """Coloured status text panel at the bottom of the Analysis page."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SM, 0, 0)
        self._label = QLabel("Ready")
        self._label.setFont(QFont(*BODY_SMALL_FONT))
        self._label.setWordWrap(True)
        self._label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self._label)
        self.set_status("Ready")

    def set_status(self, text: str, kind: str = "muted") -> None:
        color = {
            "muted": TEXT_MUTED,
            "accent": ACCENT,
            "danger": DANGER,
            "warning": WARNING,
            "success": SUCCESS,
        }.get(kind, TEXT_MUTED)
        self._label.setStyleSheet(f"color: {color}; padding: 4px 0px;")
        self._label.setText(text)


def _info_card_row(label: str, value: QLabel) -> QWidget:
    """A single label/value row inside an info card."""
    row = QWidget()
    row.setObjectName("infoRow")
    row.setStyleSheet("QWidget#infoRow { background: transparent; border: none; }")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(MD)
    caption = QLabel(label)
    caption.setFont(QFont(*BODY_SMALL_FONT))
    caption.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none; background: transparent;")
    rl.addWidget(caption)
    rl.addStretch()
    value.setFont(QFont(*BODY_FONT))
    value.setStyleSheet(f"color: {TEXT}; border: none; background: transparent;")
    rl.addWidget(value)
    return row


def _info_card(title: str) -> QWidget:
    """A bordered info card frame with a title."""
    card = QFrame()
    card.setObjectName("infoCard")
    card.setStyleSheet(
        f"QFrame#infoCard {{ background-color: {SURFACE_LIGHT};"
        f" border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; }}"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(LG, MD, LG, MD)
    layout.setSpacing(SM)
    header = QLabel(title)
    header.setFont(QFont(*BODY_SMALL_FONT))
    header.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none; background: transparent;")
    layout.addWidget(header)
    return card


class AnalysisPage(QWidget):
    """Analysis page with upload, preview, analyze, and status."""

    analyze_requested = Signal()
    image_selected_signal = Signal(str)
    image_removed_signal = Signal()
    review_center_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        page = QVBoxLayout(self)
        page.setContentsMargins(XL, XL, XL, XL)
        page.setSpacing(MD)

        # page header
        title = QLabel("Analyze Diagram")
        title.setFont(QFont(*TITLE_FONT))
        page.addWidget(title)

        subtitle = QLabel("Upload a PERT/CPM network diagram for analysis.")
        subtitle.setFont(QFont(*SUBTITLE_FONT))
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        page.addWidget(subtitle)
        page.addSpacing(SM)

        # body: preview left, info panel right
        # NOTE: plain-declaration stylesheets (no selector) on a container
        # cascade to ALL descendants, wiping their backgrounds/borders — that
        # is what flattened every button on this page. Scope everything to the
        # widget itself so app-level QSS buttons render correctly.
        body = QWidget()
        body.setObjectName("analysisBody")
        body.setStyleSheet(
            "QWidget#analysisBody { background: transparent; border: none; }"
        )
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(MD)

        # ── left column: image preview ──────────────────────────
        left = QVBoxLayout()
        left.setSpacing(MD)

        self._upload_btn = QPushButton("\u2191  Upload Diagram...")
        self._upload_btn.clicked.connect(self._on_upload)
        left.addWidget(self._upload_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._image_view = ImageView()
        self._image_view.image_dropped.connect(self.load_image)
        self._image_view.activate_requested.connect(self._on_upload)
        left.addWidget(self._image_view, stretch=1)

        # zoom toolbar below the preview
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(XS)
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setObjectName("ghost")
        self._fit_btn.setEnabled(False)
        self._fit_btn.clicked.connect(self._image_view.fit_image)
        self._zoom_out_btn = QPushButton("\u2212")
        self._zoom_out_btn.setObjectName("ghost")
        self._zoom_out_btn.setEnabled(False)
        self._zoom_out_btn.setToolTip("Zoom out")
        self._zoom_out_btn.clicked.connect(self._image_view.zoom_out)
        self._zoom_in_btn = QPushButton("+")
        self._zoom_in_btn.setObjectName("ghost")
        self._zoom_in_btn.setEnabled(False)
        self._zoom_in_btn.setToolTip("Zoom in")
        self._zoom_in_btn.clicked.connect(self._image_view.zoom_in)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFont(QFont(*MUTED_FONT))
        self._zoom_label.setStyleSheet(f"color: {TEXT_MUTED}; border: none;")
        zoom_row.addWidget(self._fit_btn)
        zoom_row.addWidget(self._zoom_out_btn)
        zoom_row.addWidget(self._zoom_in_btn)
        zoom_row.addSpacing(SM)
        zoom_row.addWidget(self._zoom_label)
        zoom_row.addStretch()
        self._image_view.zoom_changed.connect(self._on_zoom_changed)
        left.addLayout(zoom_row)

        # analyze row below preview
        analyze_row = QHBoxLayout()
        analyze_row.setSpacing(MD)
        self._remove_btn = QPushButton("Remove Image")
        self._remove_btn.setObjectName("ghost")
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove)
        analyze_row.addWidget(self._remove_btn)
        analyze_row.addStretch()
        self._open_review_btn = QPushButton("Open Review Center")
        self._open_review_btn.setObjectName("secondary")
        self._open_review_btn.setVisible(False)
        self._open_review_btn.clicked.connect(self._on_open_review_center)
        analyze_row.addWidget(self._open_review_btn)
        self._analyze_btn = QPushButton("Analyze Diagram")
        self._analyze_btn.setObjectName("primary")
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.setFixedWidth(180)
        self._analyze_btn.clicked.connect(self._on_analyze)
        analyze_row.addWidget(self._analyze_btn)
        left.addLayout(analyze_row)

        body_layout.addLayout(left, stretch=3)

        # ── right column: file information card ─────────────────
        right = QWidget()
        right.setFixedWidth(280)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(MD)

        info_card = _info_card("FILE INFORMATION")
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(LG, 0, LG, MD)
        info_layout.setSpacing(SM)

        self._file_info = QLabel("None")
        info_layout.addWidget(_info_card_row("File", self._file_info))
        self._file_name = self._file_info

        self._dims_value = QLabel("-")
        info_layout.addWidget(_info_card_row("Dimensions", self._dims_value))

        self._size_value = QLabel("-")
        info_layout.addWidget(_info_card_row("File size", self._size_value))

        self._diagram_type_value = QLabel("\u2014")
        info_layout.addWidget(_info_card_row("Diagram type", self._diagram_type_value))

        status_row = QWidget()
        status_row.setObjectName("statusRow")
        status_row.setStyleSheet(
            "QWidget#statusRow { background: transparent; border: none; }"
        )
        sr = QHBoxLayout(status_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(MD)
        cap = QLabel("Status")
        cap.setFont(QFont(*BODY_SMALL_FONT))
        cap.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent; border: none;"
        )
        sr.addWidget(cap)
        sr.addStretch()
        self._status_badge = QLabel("READY")
        self._status_badge.setFont(QFont(*BODY_SMALL_FONT))
        self._status_badge.setStyleSheet(
            f"color: {TEXT_MUTED}; background-color: {SURFACE_LIGHT};"
            f" border: 1px solid {BORDER}; border-radius: 6px; padding: 2px 8px;"
        )
        sr.addWidget(self._status_badge)
        info_layout.addWidget(status_row)

        info_group = QWidget()
        info_group.setLayout(info_layout)
        info_group.setObjectName("infoGroup")
        info_group.setStyleSheet(
            "QWidget#infoGroup { background: transparent; border: none; }"
        )
        info_card.layout().addWidget(info_group)
        right_layout.addWidget(info_card)

        right_layout.addStretch()

        body_layout.addWidget(right, stretch=0)

        page.addWidget(body, stretch=1)

        # status panel
        self._status_panel = StatusPanel()
        page.addWidget(self._status_panel)

        # live pipeline progress panel (shown while analyzing)
        self._progress_model = AnalysisProgressModel(self)
        self._progress_panel = StageProgressPanel()
        self._progress_panel.set_model(self._progress_model)
        self._progress_panel.setVisible(False)
        page.addWidget(self._progress_panel)

        self._image_path: Optional[str] = None
        self._analyzing = False
        self._image_dims: tuple[int, int] = (0, 0)

        # paste-from-clipboard shortcut (Ctrl+V / Cmd+V)
        paste_shortcut = QShortcut(
            QKeySequence.StandardKey.Paste,
            self,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        paste_shortcut.activated.connect(self._on_paste)

    # ------------------------------------------------------------------
    # Public API (called by MainWindow)
    # ------------------------------------------------------------------

    def begin_analysis(self) -> None:
        """Reset and reveal the live progress panel for a new run."""
        self._progress_model.reset()
        self._progress_panel.setVisible(True)
        # Machine eye: sweep the diagram while the pipeline reads it.
        self._image_view.set_scanning(True)
        self._status_panel.set_status("Analyzing... processing diagram", "accent")

    def on_progress(self, stage_progress: Any) -> None:
        """Forward a real pipeline StageProgress event into the model."""
        if stage_progress is None:
            return
        self._progress_panel.setVisible(True)
        self._progress_model.handle_stage(stage_progress)

    def show_completed(
        self, workflow: Any, review_item_total: int = 0
    ) -> None:
        """Finalize the model after a successful analysis run."""
        self._progress_model.finish(ok=True)
        if review_item_total and "review_items" not in (
            self._progress_model.collect_metrics()
        ):
            self._progress_model.note_metric("review_items", review_item_total)
        self._image_view.set_scanning(False)
        self._status_panel.set_status("Analysis completed", "success")

    def show_failed(self, message: str) -> None:
        """Finalize the model after a failed analysis run."""
        self._progress_model.finish(ok=False, message=message)
        self._image_view.set_scanning(False)
        self._status_panel.set_status(f"Analysis failed: {message}", "danger")

    def reset_analysis_progress(self) -> None:
        """Reset and hide the progress panel (image changed/removed)."""
        self._progress_model.reset()
        self._progress_panel.setVisible(False)
        self._image_view.set_scanning(False)

    def progress_panel(self) -> Optional[StageProgressPanel]:
        return self._progress_panel

    def progress_model(self) -> AnalysisProgressModel:
        return self._progress_model

    def set_state(self, state_name: str) -> None:
        """Update button enabled/disabled according to the session state."""
        if state_name == "ANALYZING":
            self._analyzing = True
            self._analyze_btn.setEnabled(False)
            self._upload_btn.setEnabled(False)
            self._remove_btn.setEnabled(False)
            self._status_panel.set_status("Analyzing... processing diagram", "accent")
            self._set_badge("ANALYZING", ACCENT)
        elif state_name == "ERROR":
            self._analyzing = False
            self._upload_btn.setEnabled(self._image_path is not None)
            self._remove_btn.setEnabled(self._image_path is not None)
            self._analyze_btn.setEnabled(self._image_path is not None)
            self._set_badge("ERROR", DANGER)
        elif state_name in {
            "REVIEW_REQUIRED",
            "VALIDATION_REQUIRED",
            "ANALYSIS_COMPLETE",
            "RESULTS_AVAILABLE",
            "READY_FOR_RESULTS",
        }:
            self._analyzing = False
            self._upload_btn.setEnabled(True)
            self._remove_btn.setEnabled(True)
            self._analyze_btn.setEnabled(True)
            if state_name == "REVIEW_REQUIRED":
                self._open_review_btn.setVisible(True)
                self._set_badge("REVIEW", WARNING)
            elif state_name == "VALIDATION_REQUIRED":
                self._open_review_btn.setVisible(False)
                self._set_badge("VALIDATION", WARNING)
            else:
                self._open_review_btn.setVisible(False)
                self._set_badge("READY", SUCCESS)
        else:
            self._analyzing = False
            self._upload_btn.setEnabled(True)
            self._remove_btn.setEnabled(self._image_path is not None)
            self._analyze_btn.setEnabled(self._image_path is not None)
            self._set_badge("READY", TEXT_MUTED)

    def _set_badge(self, text: str, color: str) -> None:
        self._status_badge.setText(text)
        self._status_badge.setStyleSheet(
            f"color: {color}; background-color: {color}18;"
            f" border: 1px solid {color}44; border-radius: 6px; padding: 2px 8px;"
            f" font-weight: 600;"
        )

    def set_error(self, msg: str) -> None:
        self._status_panel.set_status(f"Analysis failed: {msg}", "danger")
        self._set_badge("ERROR", DANGER)

    def set_analysis_result_status(
        self, state_name: str, activity_count: Optional[int] = None
    ) -> None:
        if state_name == "REVIEW_REQUIRED":
            message = "Analysis completed - review required"
            if activity_count:
                message += (
                    f" ({activity_count} activities detected. "
                    "Some results need review before CPM can run.)"
                )
            self._open_review_btn.setVisible(True)
            self._status_panel.set_status(message, "warning")
            self._set_badge("REVIEW", WARNING)
        elif state_name == "VALIDATION_REQUIRED":
            self._open_review_btn.setVisible(False)
            self._status_panel.set_status("Analysis completed", "success")
            self._set_badge("VALIDATION", WARNING)
        else:
            self._open_review_btn.setVisible(False)
            self._status_panel.set_status("Analysis completed", "success")
            self._set_badge("READY", SUCCESS)

    def refresh(self, session: Any) -> None:
        """Keep the page in sync when the user returns to it."""
        state = getattr(session, "state", None)
        if state is None:
            return
        state_name = getattr(state, "value", state)
        if state_name == "REVIEW_REQUIRED":
            summary = getattr(session, "review_summary", None) or {}
            count = summary.get("total_activities") or None
            self.set_analysis_result_status("REVIEW_REQUIRED", activity_count=count)
            self.set_diagram_type(summary.get("diagram_type") or "")
        elif state_name == "ERROR":
            self.set_error(getattr(session, "error_message", "") or "Analysis failed")
        elif state_name in {"VALIDATION_REQUIRED"}:
            self.set_analysis_result_status("VALIDATION_REQUIRED")
        elif state_name == "IMAGE_SELECTED":
            self._status_panel.set_status("Ready")
            self._set_badge("READY", SUCCESS)
            self._open_review_btn.setVisible(False)

    def load_image(self, path: str) -> None:
        """Load an image from an explicit path (bypasses file dialog)."""
        w, h = self._image_view.set_image(path)
        if w == 0:
            self._status_panel.set_status("Failed to load image", "danger")
            return
        self._image_path = path
        self._image_dims = (w, h)
        size_kb = os.path.getsize(path) // 1024
        self._file_info.setText(f"{os.path.basename(path)}")
        self._file_info.setToolTip(path)
        self._dims_value.setText(f"{w} \u00d7 {h} px")
        self._size_value.setText(f"{size_kb} KB")
        self._diagram_type_value.setText("\u2014")
        self._diagram_type_value.setToolTip("")
        self._remove_btn.setEnabled(True)
        self._analyze_btn.setEnabled(True)
        self._fit_btn.setEnabled(True)
        self._zoom_out_btn.setEnabled(True)
        self._zoom_in_btn.setEnabled(True)
        self._status_panel.set_status("Ready")
        self._set_badge("READY", SUCCESS)
        self._on_zoom_changed(self._image_view.zoom_factor)
        self.reset_analysis_progress()
        self.image_selected_signal.emit(path)

    def set_diagram_type(self, text: str) -> None:
        """Show the detected diagram type when the backend reports one."""
        label = (text or "").strip()
        self._diagram_type_value.setText(label or "\u2014")
        self._diagram_type_value.setToolTip(label)

    def _on_zoom_changed(self, factor: float) -> None:
        self._zoom_label.setText(f"{int(round(max(1.0, factor) * 100))}%")
        self._fit_btn.setEnabled(self._image_view._pixmap is not None)
        self._zoom_out_btn.setEnabled(self._image_view._pixmap is not None)
        self._zoom_in_btn.setEnabled(self._image_view._pixmap is not None)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Diagram Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*)",
        )
        if path:
            self.load_image(path)

    def _on_remove(self) -> None:
        self._image_path = None
        self._image_dims = (0, 0)
        self._file_info.setText("None")
        self._dims_value.setText("-")
        self._size_value.setText("-")
        self._diagram_type_value.setText("\u2014")
        self._fit_btn.setEnabled(False)
        self._zoom_out_btn.setEnabled(False)
        self._zoom_in_btn.setEnabled(False)
        self._zoom_label.setText("100%")
        self._image_view.clear_image()
        self._analyze_btn.setEnabled(False)
        self._remove_btn.setEnabled(False)
        self._set_badge("READY", TEXT_MUTED)
        self._status_panel.set_status("Ready")
        self.reset_analysis_progress()
        self.image_removed_signal.emit()

    def _on_paste(self) -> bool:
        """Paste a diagram image from the clipboard (saved to a temp PNG)."""
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        image = clipboard.image()
        if image.isNull():
            return False
        filename = os.path.join(
            tempfile.gettempdir(), f"pert_paste_{uuid.uuid4().hex}.png"
        )
        if not image.save(filename, "PNG"):
            return False
        self.load_image(filename)
        return True

    def _on_analyze(self) -> None:
        if self._image_path and not self._analyzing:
            self.analyze_requested.emit()

    def _on_open_review_center(self) -> None:
        self.review_center_requested.emit()
