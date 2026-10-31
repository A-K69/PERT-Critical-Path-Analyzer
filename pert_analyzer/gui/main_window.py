"""
Main application window: header + sidebar navigation + QStackedWidget + status bar.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pert_analyzer.gui.navigation import NAV_ITEMS, NavDestination
from pert_analyzer.gui.locale import (
    UiLanguage,
    apply_ui_locale,
    nav_label,
    normalize_language,
    translate_widget_tree,
)
from pert_analyzer.gui.pages import (
    AnalysisPage,
    ResultsPage,
    ReviewPage,
    UnderstandingPage,
    ValidationPage,
)
from pert_analyzer.gui.pages.network_builder_page import NetworkBuilderPage
from pert_analyzer.gui.session import AppState, GuiSession, ValidationCenterStatus
from pert_analyzer.gui.themes.palette import (
    ACCENT,
    BG,
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
    BODY_SMALL_FONT,
    BUTTON_FONT,
    LABEL_FONT,
    MUTED_FONT,
    STATUS_FONT,
    SUBTITLE_FONT,
    TITLE_FONT,
)
from pert_analyzer.gui.themes.spacing import (
    HEADER_HEIGHT,
    LG,
    MD,
    RADIUS_MD,
    RADIUS_SM,
    SIDEBAR_WIDTH,
    SM,
    XS,
    XXL,
)
from pert_analyzer.gui.worker import (
    AnalysisWorker,
    ApplyReviewsWorker,
    CpmWorker,
    default_analyze,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window with navigation and five pages."""

    def __init__(
        self,
        backend: Optional[Callable[[str], Any]] = None,
        apply_reviews_fn: Optional[Callable[[], Any]] = None,
        confirm_discard_fn: Optional[Callable[[], bool]] = None,
        run_cpm_fn: Optional[Callable[[], Any]] = None,
        language: str | UiLanguage = UiLanguage.ENGLISH,
        persist_language: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._backend = backend or default_analyze
        self._apply_reviews_fn = apply_reviews_fn
        self._confirm_discard_fn = confirm_discard_fn
        self._run_cpm_fn = run_cpm_fn
        self._session = GuiSession()
        self._language = normalize_language(language)
        self._persist_language = persist_language
        apply_ui_locale(self, self._language)
        self._worker: Optional[AnalysisWorker] = None
        self._apply_worker: Optional[ApplyReviewsWorker] = None
        self._cpm_worker: Optional[CpmWorker] = None
        self._export_worker: Optional[ExportWorker] = None
        self._report_worker: Optional[ReportWorker] = None

        self.setWindowTitle("PERT & Critical Path Analyzer")
        self.setMinimumSize(1280, 768)

        self._setup_ui()
        if self._language == UiLanguage.ARABIC:
            translate_widget_tree(self, self._language)
            for item in NAV_ITEMS:
                self._nav_buttons[item.destination.value].setText(
                    f"  {item.icon}  {nav_label(item.key, self._language)}"
                )
            self._locale_btn.setText("English")
            self._header_title.setText("محلل PERT وCPM")
        self._connect_signals()
        self._refresh_pages()
        self.statusBar().showMessage("Ready")
        logger.info("Main window initialized")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("mainCentral")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Header bar ────────────────────────────────────────
        header = QWidget()
        header.setObjectName("appHeader")
        header.setFixedHeight(HEADER_HEIGHT)
        header.setStyleSheet(
            f"QWidget#appHeader {{ background-color: {SURFACE};"
            f" border-bottom: 1px solid {BORDER}; }}"
        )
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(LG, 0, XXL, 0)
        hdr_layout.setSpacing(MD)

        self._header_title = QLabel("PERT / CPM Analyzer")
        self._header_title.setFont(QFont(*TITLE_FONT))
        self._header_title.setStyleSheet(f"color: {TEXT}; border: none; background: transparent;")
        hdr_layout.addWidget(self._header_title)

        self._locale_btn = QPushButton("عربي")
        self._locale_btn.setObjectName("secondary")
        self._locale_btn.setToolTip("Switch interface language and direction")
        self._locale_btn.clicked.connect(self._toggle_language)
        hdr_layout.addWidget(self._locale_btn)
        hdr_layout.addSpacing(XXL)

        hdr_layout.addStretch()

        self._workflow_indicator = QLabel()
        self._workflow_indicator.setFont(QFont(*BODY_SMALL_FONT))
        self._workflow_indicator.setStyleSheet(
            f"color: {TEXT_SECONDARY}; border: none; background: transparent;"
        )
        hdr_layout.addWidget(self._workflow_indicator)

        hdr_layout.addSpacing(XXL)

        self._header_status = QLabel("")
        self._header_status.setObjectName("headerStatus")
        self._header_status.setFont(QFont(*STATUS_FONT))
        self._header_status.setStyleSheet(
            f"color: {TEXT_MUTED}; border: none; background: transparent;"
        )
        hdr_layout.addWidget(self._header_status)

        root_layout.addWidget(header)

        # ── Body: sidebar + content ───────────────────────────
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("appSidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar.setStyleSheet(
            f"QWidget#appSidebar {{ background-color: {SURFACE};"
            f" border-right: 1px solid {BORDER}; }}"
        )
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(SM, MD, SM, MD)
        sb_layout.setSpacing(XS)

        self._nav_buttons: dict[int, QPushButton] = {}
        for item in NAV_ITEMS:
            btn = QPushButton(f"  {item.icon}  {item.label}")
            btn.setCheckable(True)
            btn.setObjectName(f"nav_{item.key}")
            btn.setFont(QFont(*BUTTON_FONT))
            btn.setToolTip(item.label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 8px {MD}px;"
                f" border-radius: {RADIUS_SM}px; border: none;"
                f" color: {TEXT_SECONDARY}; background: transparent; }}"
                f"QPushButton:hover {{ background-color: {SURFACE_LIGHT}; color: {TEXT}; }}"
                f"QPushButton:checked {{ background-color: {ACCENT}18;"
                f" color: {ACCENT}; font-weight: 600; }}"
            )
            btn.clicked.connect(
                lambda checked=False, dest=item.destination: self._on_nav(dest)
            )
            sb_layout.addWidget(btn)
            self._nav_buttons[item.destination.value] = btn

        sb_layout.addStretch()

        # sidebar version / info
        ver = QLabel("v1.0")
        ver.setFont(QFont(*MUTED_FONT))
        ver.setStyleSheet(f"color: {TEXT_MUTED}; border: none; background: transparent;")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(ver)

        body_layout.addWidget(sidebar)

        # ── Stacked pages ─────────────────────────────────────
        # Plain (selector-less) declarations on a container cascade to every
        # descendant — this flattened every button on every page before being
        # scoped to the container itself.
        content = QWidget()
        content.setObjectName("mainContent")
        content.setStyleSheet(
            "QWidget#mainContent { background: transparent; border: none; }"
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._analysis_page = AnalysisPage()
        self._understanding_page = UnderstandingPage()
        self._review_page = ReviewPage()
        self._validation_page = ValidationPage()
        self._results_page = ResultsPage()
        self._network_builder_page = NetworkBuilderPage()

        self._stack.addWidget(self._analysis_page)
        self._stack.addWidget(self._understanding_page)
        self._stack.addWidget(self._review_page)
        self._stack.addWidget(self._validation_page)
        self._stack.addWidget(self._results_page)
        self._stack.addWidget(self._network_builder_page)
        content_layout.addWidget(self._stack)

        body_layout.addWidget(content, stretch=1)
        root_layout.addWidget(body, stretch=1)

        self._on_nav(NavDestination.ANALYZE)

    @property
    def language(self) -> UiLanguage:
        return self._language

    def set_language(self, language: str | UiLanguage) -> None:
        """Switch UI language/direction; analysis and review data are untouched."""
        self._language = normalize_language(language)
        apply_ui_locale(self, self._language)
        translate_widget_tree(self, self._language)
        if self._persist_language:
            try:
                from pert_analyzer.config.manager import get_config_manager

                manager = get_config_manager()
                manager.set("gui.language", self._language.value)
                manager.set("gui.direction", "rtl" if self._language == UiLanguage.ARABIC else "ltr")
                manager.save()
            except Exception as exc:  # pragma: no cover - defensive at app boundary
                logger.warning("Could not persist UI language: %s", exc)
        for item in NAV_ITEMS:
            button = self._nav_buttons[item.destination.value]
            button.setText(f"  {item.icon}  {nav_label(item.key, self._language)}")
            button.setToolTip(nav_label(item.key, self._language))
        self._locale_btn.setText("English" if self._language == UiLanguage.ARABIC else "عربي")
        self._header_title.setText(
            "محلل PERT وCPM" if self._language == UiLanguage.ARABIC else "PERT / CPM Analyzer"
        )
        self._update_workflow_indicator()

    def _toggle_language(self) -> None:
        next_language = (
            UiLanguage.ARABIC if self._language == UiLanguage.ENGLISH else UiLanguage.ENGLISH
        )
        self.set_language(next_language)

    def _update_workflow_indicator(self) -> None:
        """State-aware workflow step indicator (done/current/blocked/pending)."""
        steps = [
            (NavDestination.ANALYZE, "Analyze"),
            (NavDestination.UNDERSTANDING, "Understand"),
            (NavDestination.REVIEW, "Review"),
            (NavDestination.VALIDATE, "Validate"),
            (NavDestination.RESULTS, "Results"),
        ]
        current_idx = self._stack.currentIndex()
        state_value = getattr(self._session.state, "value", None)
        status = self._session.validation_status

        def _step_done(dest: NavDestination) -> bool:
            candidate = self._session.current_candidate
            if dest == NavDestination.ANALYZE:
                return (
                    getattr(self._session, "workflow", None) is not None
                    or candidate is not None
                )
            if dest == NavDestination.UNDERSTANDING:
                return (
                    getattr(self._session, "workflow", None) is not None
                    or candidate is not None
                )
            if dest == NavDestination.REVIEW:
                if getattr(self._session, "workflow", None) is None:
                    return candidate is not None
                if getattr(self._session, "has_applied_reviews", False):
                    return True
                return self._session.review_item_total() == 0
            if dest == NavDestination.VALIDATE:
                return status in (
                    ValidationCenterStatus.VALID,
                    ValidationCenterStatus.INVALID,
                )
            if dest == NavDestination.RESULTS:
                return (
                    state_value in ("RESULTS_AVAILABLE", "READY_FOR_RESULTS")
                    and status == ValidationCenterStatus.VALID
                )
            return False

        def _step_blocked(dest: NavDestination) -> bool:
            if dest == NavDestination.ANALYZE:
                return state_value == "ERROR"
            if dest == NavDestination.UNDERSTANDING:
                return False
            if dest == NavDestination.REVIEW:
                return (
                    self._session.pending_review_total() > 0
                    or status == ValidationCenterStatus.BLOCKED_REVIEW
                )
            if dest == NavDestination.VALIDATE:
                return status == ValidationCenterStatus.INVALID
            return False

        parts = []
        for dest, name in steps:
            if _step_blocked(dest) and dest.value != current_idx:
                glyph, color = "\u26a0", WARNING
            elif dest.value == current_idx:
                glyph, color = "\u25CF", ACCENT
            elif _step_done(dest):
                glyph, color = "\u2713", SUCCESS
            else:
                glyph, color = "\u25CB", TEXT_MUTED
            parts.append(f'<font color="{color}">{glyph}</font> {name}')
        self._workflow_indicator.setTextFormat(Qt.TextFormat.RichText)
        self._workflow_indicator.setText(" \u2014 ".join(parts))

    def _connect_signals(self) -> None:
        self._analysis_page.image_selected_signal.connect(self._on_image_selected)
        self._analysis_page.image_removed_signal.connect(self._on_image_removed)
        self._analysis_page.analyze_requested.connect(self._on_analyze_requested)
        self._analysis_page.review_center_requested.connect(
            lambda: self._on_nav(NavDestination.REVIEW)
        )
        self._review_page.apply_requested.connect(self._on_apply_review_decisions)
        self._review_page.validate_requested.connect(
            lambda: self._on_nav(NavDestination.VALIDATE)
        )
        self._validation_page.revalidate_requested.connect(self._on_revalidate)
        self._validation_page.continue_requested.connect(self._on_continue_to_results)
        self._validation_page.back_to_review.connect(
            lambda: self._on_nav(NavDestination.REVIEW)
        )
        self._validation_page.go_analyze.connect(
            lambda: self._on_nav(NavDestination.ANALYZE)
        )
        self._validation_page.review_issue_requested.connect(self._on_review_issue)
        self._results_page.go_review.connect(
            lambda: self._on_nav(NavDestination.REVIEW)
        )
        self._results_page.go_validation.connect(
            lambda: self._on_nav(NavDestination.VALIDATE)
        )
        self._results_page.calculate_requested.connect(self._on_calculate_results)
        self._results_page.export_requested.connect(self._on_export_results)
        self._results_page.report_requested.connect(self._on_report_results)
        self._results_page.pert_run_requested.connect(self._on_run_pert)
        self._network_builder_page.analyze_requested.connect(
            self._on_manual_analyze
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _on_nav(self, dest: NavDestination) -> None:
        self._stack.setCurrentIndex(dest.value)
        for idx, btn in self._nav_buttons.items():
            btn.setChecked(idx == dest.value)
        page = self._stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh(self._session)
        self._update_workflow_indicator()
        self._update_header_status()
        self._fade_in(page)
        logger.info("Navigated to %s", dest.name)

    def _fade_in(self, widget: QWidget) -> None:
        """Subtle, fully guarded opacity fade when switching pages."""
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect as _Effect

            effect = _Effect(widget)
            widget.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", widget)
            animation.setDuration(140)
            animation.setStartValue(0.4)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)

            # Drop the effect once the fade completes.  A lingering
            # QGraphicsOpacityEffect forces every later QWidget::grab()/render()
            # through an offscreen buffer whose unpainted regions return with
            # alpha 0 — turning page grabs (screenshots) transparent.  At
            # opacity 1.0 the effect is visually a no-op, so removing it is
            # invisible on screen.
            def _drop_fade_effect(widget=widget, effect=effect) -> None:
                if widget.graphicsEffect() is effect:
                    widget.setGraphicsEffect(None)

            animation.finished.connect(_drop_fade_effect)
            animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            widget._fade_effect = effect  # keep references alive
            widget._fade_animation = animation
        except Exception:  # noqa: BLE001 (cosmetic only)
            pass

    def _update_header_status(self) -> None:
        """Update the status badge in the header bar."""
        status = self._session.validation_status
        state_value = getattr(self._session.state, "value", None)

        label: str = ""
        color: str = TEXT_MUTED
        if status == ValidationCenterStatus.BLOCKED_REVIEW:
            label, color = "BLOCKED REVIEW", WARNING
        elif status == ValidationCenterStatus.INVALID:
            label, color = "INVALID", DANGER
        elif status == ValidationCenterStatus.VALID:
            label, color = "VALID", SUCCESS
        elif state_value == "ANALYZING":
            label, color = "ANALYZING", ACCENT
        elif state_value == "ERROR":
            label, color = "ERROR", DANGER
        elif state_value == "IMAGE_SELECTED":
            label, color = "READY", TEXT_SECONDARY
        elif state_value == "REVIEW_REQUIRED":
            label, color = "REVIEW REQUIRED", WARNING
        elif state_value == "VALIDATION_REQUIRED":
            label, color = "VALIDATION READY", WARNING
        elif state_value in ("RESULTS_AVAILABLE", "READY_FOR_RESULTS"):
            label, color = "RESULTS READY", SUCCESS

        if label:
            self._header_status.setText(label)
        else:
            self._header_status.setText("")
        self._header_status.setStyleSheet(
            f"color: {color}; border: none; background: transparent;"
            f" font-weight: 600;"
        )

    # ------------------------------------------------------------------
    # Image selection / removal
    # ------------------------------------------------------------------

    def _on_image_selected(self, path: str) -> None:
        if not self._confirm_discard():
            return
        self._session.set_image(path)
        self._analysis_page.set_state(self._session.state.value)
        self._refresh_pages()
        self.statusBar().showMessage(f"Image: {Path(path).name}")

    def _on_image_removed(self) -> None:
        if not self._confirm_discard():
            return
        self._session.clear_image()
        self._analysis_page.set_state(self._session.state.value)
        self._refresh_pages()
        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _on_analyze_requested(self) -> None:
        if self._session.current_image_path is None:
            return
        if not self._confirm_discard():
            return
        self._session.begin_analysis()
        self._analysis_page.set_state("ANALYZING")
        self._analysis_page.begin_analysis()
        self.statusBar().showMessage("Analyzing...")
        self._worker = AnalysisWorker(
            self._session.current_image_path,
            analyze_fn=self._backend,
        )
        self._worker.progress.connect(self._on_analysis_progress)
        self._worker.completed.connect(self._on_analysis_completed)
        self._worker.failed.connect(self._on_analysis_failed)
        self._worker.finished.connect(self._cleanup_worker)
        self._worker.start()

    def _on_analysis_progress(self, stage_progress: Any) -> None:
        """Forward real pipeline StageProgress events into the analysis page."""
        self._analysis_page.on_progress(stage_progress)
        self._update_header_status()
        pct = int(round(float(getattr(stage_progress, "progress", 0.0) or 0.0) * 100))
        name = getattr(stage_progress, "name", "") or getattr(
            stage_progress, "stage_id", ""
        )
        self.statusBar().showMessage(f"Analyzing: {name} ({pct}%)")

    def _on_analysis_completed(self, workflow: Any) -> None:
        self._session.complete_analysis(workflow)
        state = self._session.state
        self._analysis_page.show_completed(
            workflow, review_item_total=self._session.review_item_total()
        )
        if state == AppState.ERROR:
            self._analysis_page.set_state("ERROR")
            self._analysis_page.set_error(self._session.error_message)
        else:
            self._analysis_page.set_state(state.value)
            count = (
                (self._session.review_summary or {}).get("total_activities") or None
            )
            self._analysis_page.set_analysis_result_status(state.value, activity_count=count)
        self._refresh_pages()
        self.statusBar().showMessage(f"Analysis completed: {state.value}")

        # The user asked to stay on the Analyze page and watch the
        # processing machine wind down — navigation to Review/Validation
        # stays manual (sidebar, Open Review Center button).
        logger.info("Analysis completed: state=%s", state.value)

    def _on_analysis_failed(self, msg: str) -> None:
        self._session.fail_analysis(msg)
        self._analysis_page.show_failed(msg)
        self._analysis_page.set_state("ERROR")
        self._analysis_page.set_error(msg)
        self._refresh_pages()
        self.statusBar().showMessage("Analysis failed")

    def _on_export_results(self) -> None:
        if self._export_worker is not None:
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export results",
            "",
            "PDF (*.pdf);;Excel (*.xlsx);;JSON (*.json);;CSV (*.csv)",
        )
        if not path:
            return
        output_format = "pdf"
        if path.lower().endswith(".xlsx"):
            output_format = "excel"
        elif path.lower().endswith(".json"):
            output_format = "json"
        elif path.lower().endswith(".csv"):
            output_format = "csv"
        self.statusBar().showMessage("Exporting...")
        self._results_page.set_busy(True)
        from pert_analyzer.reporting.export.manager import ExportManager
        from pert_analyzer.reporting.export.result import ExportResult

        def _do_export() -> Any:
            report = self._session.report
            manager = ExportManager()
            return manager.export(
                report,
                output_format=output_format,
                output_path=path,
            )

        self._export_worker = ExportWorker(_do_export)
        self._export_worker.completed.connect(
            self._on_export_completed
        )
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.finished.connect(
            self._cleanup_export_worker
        )
        self._export_worker.start()

    def _on_export_completed(self, result: Any) -> None:
        self._results_page.set_busy(False)
        msg = result.description if hasattr(result, "description") else "Export complete"
        self.statusBar().showMessage(f"Exported: {msg}")
        logger.info("Export completed: %s", result)

    def _cleanup_export_worker(self) -> None:
        if self._export_worker is not None:
            self._export_worker.completed.disconnect()
            self._export_worker.failed.disconnect()
            self._export_worker.finished.disconnect()
            self._export_worker = None

    def _on_export_failed(self, msg: str) -> None:
        self._results_page.set_busy(False)
        self.statusBar().showMessage(f"Export failed: {msg}")
        logger.error("Export failed: %s", msg)

    def _on_report_results(self) -> None:
        if self._report_worker is not None:
            return
        self.statusBar().showMessage("Generating report...")
        self._results_page.set_busy(True)
        session = self._session

        def _do_report() -> Any:
            return session.report

        self._report_worker = ReportWorker(_do_report)
        self._report_worker.completed.connect(
            self._on_report_completed
        )
        self._report_worker.failed.connect(self._on_report_failed)
        self._report_worker.finished.connect(
            self._cleanup_report_worker
        )
        self._report_worker.start()

    def _on_report_completed(self, report: Any) -> None:
        self._results_page.set_busy(False)
        self.statusBar().showMessage("Report generated")
        logger.info("Report completed")

    def _cleanup_report_worker(self) -> None:
        if self._report_worker is not None:
            self._report_worker.completed.disconnect()
            self._report_worker.failed.disconnect()
            self._report_worker.finished.disconnect()
            self._report_worker = None

    def _on_report_failed(self, msg: str) -> None:
        self._results_page.set_busy(False)
        self.statusBar().showMessage(f"Report failed: {msg}")
        logger.error("Report failed: %s", msg)

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.progress.disconnect()
            self._worker.completed.disconnect()
            self._worker.failed.disconnect()
            self._worker.finished.disconnect()
            self._worker = None

    # ------------------------------------------------------------------
    # Apply review decisions
    # ------------------------------------------------------------------

    def _on_apply_review_decisions(self) -> None:
        if self._apply_worker is not None:
            return
        workflow = self._session.workflow
        if workflow is None:
            return
        self._review_page.set_busy(True)
        self._session.begin_apply()
        self._apply_worker = ApplyReviewsWorker(
            workflow,
            apply_fn=self._apply_reviews_fn,
        )
        self._apply_worker.completed.connect(self._on_apply_completed)
        self._apply_worker.failed.connect(self._on_apply_failed)
        self._apply_worker.finished.connect(self._cleanup_apply_worker)
        self._apply_worker.start()
        self.statusBar().showMessage("Applying review decisions...")

    def _on_apply_completed(self, candidate: Any) -> None:
        self._review_page.set_busy(False)
        self._session.complete_apply(candidate)
        self._refresh_pages()
        self.statusBar().showMessage("Review decisions applied")
        self._on_nav(NavDestination.VALIDATE)
        logger.info("Review decisions applied")

    def _on_apply_failed(self, msg: str) -> None:
        self._review_page.set_busy(False)
        self._session.fail_apply(msg)
        self._refresh_pages()
        self.statusBar().showMessage(f"Apply failed: {msg}")

    def _cleanup_apply_worker(self) -> None:
        if self._apply_worker is not None:
            self._apply_worker.completed.disconnect()
            self._apply_worker.failed.disconnect()
            self._apply_worker.finished.disconnect()
            self._apply_worker = None

    # ------------------------------------------------------------------
    # CPM results
    # ------------------------------------------------------------------

    def _on_calculate_results(self) -> None:
        if self._cpm_worker is not None:
            return
        workflow = self._session.workflow
        if workflow is None:
            self.statusBar().showMessage("No workflow available for CPM")
            return
        run_cpm = self._run_cpm_fn or getattr(workflow, "run_cpm", None)
        if not callable(run_cpm):
            self.statusBar().showMessage("No workflow available for CPM")
            return
        self._results_page.set_busy(True)
        self.statusBar().showMessage("Calculating results...")
        self._cpm_worker = CpmWorker(
            workflow,
            run_cpm_fn=run_cpm,
        )
        self._cpm_worker.completed.connect(self._on_cpm_completed)
        self._cpm_worker.failed.connect(self._on_cpm_failed)
        self._cpm_worker.finished.connect(self._cleanup_cpm_worker)
        self._cpm_worker.start()

    def _on_cpm_completed(self, result: Any) -> None:
        self._results_page.set_busy(False)
        candidate = self._session.current_candidate
        if candidate is not None:
            candidate.cpm = result
            paths = list(getattr(result, "critical_paths", None) or [])
            candidate.pure_critical_paths = [list(p) for p in paths]
        self._refresh_pages()
        self._results_page.refresh(self._session)
        self.statusBar().showMessage("Results calculated")
        logger.info("CPM calculation completed")

    def _on_cpm_failed(self, msg: str) -> None:
        self._results_page.set_busy(False)
        self._refresh_pages()
        self.statusBar().showMessage(f"Calculation failed: {msg}")
        logger.warning("CPM calculation failed: %s", msg)

    def _cleanup_cpm_worker(self) -> None:
        if self._cpm_worker is not None:
            self._cpm_worker.completed.disconnect()
            self._cpm_worker.failed.disconnect()
            self._cpm_worker.finished.disconnect()
            self._cpm_worker = None

    # ------------------------------------------------------------------
    # PERT results
    # ------------------------------------------------------------------

    def _on_run_pert(self) -> None:
        graph = getattr(self._session, "graph_model", None)
        if graph is None:
            self.statusBar().showMessage("No graph available for PERT")
            return
        estimates = getattr(self._session, "pert_estimates", None) or None
        try:
            from pert_analyzer.analysis.pert_engine import PertEngine

            engine = PertEngine()
            result = engine.analyze(graph, estimates)
        except Exception as exc:
            self._session.pert_result = None
            self._results_page.refresh(self._session)
            self.statusBar().showMessage(f"PERT error: {exc}")
            return
        self._session.pert_result = result
        self._results_page.refresh(self._session)
        self.statusBar().showMessage("PERT analysis completed")

    # ------------------------------------------------------------------
    # Validation center
    # ------------------------------------------------------------------

    def _on_revalidate(self) -> None:
        """Re-run the backend validation path on the current reviewed graph."""
        if self._apply_worker is not None:
            return
        workflow = self._session.workflow
        if workflow is None or not callable(getattr(workflow, "apply", None)):
            return
        if self._session.pending_review_total() > 0:
            self.statusBar().showMessage("Finish the review before revalidating")
            self._on_nav(NavDestination.REVIEW)
            return

        self._validation_page.set_busy(True)
        self.statusBar().showMessage("Revalidating...")
        try:
            candidate = workflow.apply()
        except Exception as exc:  # noqa: BLE001
            self._session.fail_apply(str(exc))
            self._validation_page.set_busy(False)
            self._refresh_pages()
            self._validation_page.set_feedback(f"Revalidation failed: {exc}", error=True)
            self.statusBar().showMessage(f"Revalidation failed: {exc}")
            return

        self._validation_page.set_busy(False)
        if candidate is None:
            self._session.fail_apply("Revalidation returned no candidate")
            self._refresh_pages()
            self._validation_page.set_feedback(
                "Revalidation returned no candidate", error=True
            )
            self.statusBar().showMessage("Revalidation returned no candidate")
            return

        self._session.complete_apply(candidate)
        self._refresh_pages()
        status = self._session.validation_status
        if status == ValidationCenterStatus.VALID:
            self.statusBar().showMessage("Graph is valid and ready for CPM")
        elif status == ValidationCenterStatus.INVALID:
            self.statusBar().showMessage("Graph is invalid; resolve the issues above")
        else:
            self.statusBar().showMessage(f"Graph validation status: {status.value}")
        logger.info("Revalidation completed: %s", status.value)

    def _on_review_issue(self, category, key: str) -> None:
        """Navigate to the Review Center and select the affected item."""
        self._on_nav(NavDestination.REVIEW)
        if not self._review_page.focus_item(category, key):
            self.statusBar().showMessage("Could not open the requested review item")

    def _on_manual_analyze(self) -> None:
        """Handle Analyze from Network Builder — create candidate and go to Results."""
        import logging
        _log = logging.getLogger(__name__)

        _log.info("[BUILDER → SESSION] Creating candidate from manual network...")
        builder_model = self._network_builder_page.get_model()
        candidate = builder_model.create_candidate()
        if candidate is None:
            _log.error("[BUILDER → SESSION] FAILED to create candidate")
            self.statusBar().showMessage("Failed to create project candidate.")
            return

        _log.info("[BUILDER → SESSION] Candidate created: graph=%d activities, %d deps",
                  len(candidate.graph.activities), len(candidate.graph.dependencies))
        _log.info("[BUILDER → SESSION] CPM gate=%s, cpm_exists=%s",
                  candidate.cpm_gate, candidate.cpm is not None)

        self._session.state = AppState.RESULTS_AVAILABLE
        self._session.candidate = candidate
        self._session.has_applied_reviews = True
        self._session.reviews_dirty = False

        _log.info("[SESSION] State=%s, candidate assigned, has_applied=%s",
                  self._session.state.value, self._session.has_applied_reviews)

        self._session.entry_mode = "NETWORK_BUILDER"
        self._network_builder_page.mark_results_ready()

        self._refresh_pages()
        _log.info("[NAV] Navigating to Results...")
        self._on_nav(NavDestination.RESULTS)
        _log.info("[RESULTS] Navigation complete")

    def _on_continue_to_results(self) -> None:
        """Move to Results only when the graph is valid and CPM-ready."""
        if self._session.validation_status != ValidationCenterStatus.VALID:
            self.statusBar().showMessage("Finish validation before viewing results")
            return
        self._on_nav(NavDestination.RESULTS)

    # ------------------------------------------------------------------
    # Unsaved-decision guard
    # ------------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        """Ask before discarding unsaved review decisions."""
        if not getattr(self._session, "reviews_dirty", False):
            return True
        if self._confirm_discard_fn is not None:
            return bool(self._confirm_discard_fn())
        from PySide6.QtWidgets import QMessageBox

        result = QMessageBox.question(
            self,
            "Discard review decisions?",
            "You have unsaved review decisions. Discard them and continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_pages(self) -> None:
        for page in [
            self._analysis_page,
            self._understanding_page,
            self._review_page,
            self._validation_page,
            self._results_page,
        ]:
            if hasattr(page, "refresh"):
                page.refresh(self._session)
