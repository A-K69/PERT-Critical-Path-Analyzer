"""
Capture screenshots of every GUI page using the reference AON workflow.
Run with: python scripts/capture_screenshots.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from pert_analyzer.gui.main_window import MainWindow
from pert_analyzer.gui.navigation import NavDestination
from pert_analyzer.gui.session import AppState
from pert_analyzer.gui.themes.style import apply_theme
from tests.helpers.reference_gold import (
    REFERENCE_AON,
    build_corrected_session,
    run_reference_analysis,
)

OUT_DIR = _ROOT / "docs" / "ui_review" / "final"
_workflow = None


def pump(app: QApplication, ms: int = 320) -> None:
    """Pump the event loop for wall-clock ms so the nav fade can finish."""
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def _grab(window: MainWindow, name: str) -> None:
    pixmap = window.grab()
    path = OUT_DIR / f"{name}.png"
    pixmap.save(str(path))
    print(f"  saved {path}")


def _grab_page(page_widget, name: str, window: MainWindow) -> None:
    """Save one page (child widget) as a crop of the full-window grab.

    A child widget's own grab() can render freshly-shown tab pages with stale
    child geometry and can skip QGraphicsView viewport contents.  The window's
    grab is the real on-screen composition, so cropping the page rect out of
    it is both accurate and fully opaque.
    """
    win = window
    full = win.grab().toImage()
    dpr = full.devicePixelRatio() or 1.0
    origin = page_widget.mapTo(win, QPoint(0, 0))
    page = full.copy(
        round(origin.x() * dpr),
        round(origin.y() * dpr),
        round(page_widget.width() * dpr),
        round(page_widget.height() * dpr),
    )
    path = OUT_DIR / f"{name}.png"
    page.save(str(path))
    print(f"  saved {path}")


def _set_session_data(window: MainWindow) -> None:
    """Push a fully-resolved reference AON session into the GUI."""
    global _workflow
    print("Running reference analysis...")
    pipeline_result = run_reference_analysis()
    session = build_corrected_session(pipeline_result, source_image_id=REFERENCE_AON.name)

    from pert_analyzer.pipeline.review_api import ReviewWorkflow
    _workflow = ReviewWorkflow(pipeline_result=pipeline_result, review_session=session)

    gui_session = window._session
    gui_session.complete_analysis(_workflow)
    gui_session.current_image_path = str(REFERENCE_AON)
    gui_session.has_applied_reviews = True
    gui_session.reviews_dirty = False

    candidate = _workflow.apply()
    gui_session.complete_apply(candidate)
    cpm_result = _workflow.run_cpm()
    candidate.cpm = cpm_result
    candidate.pure_critical_paths = [
        list(path) for path in (getattr(cpm_result, "critical_paths", None) or [])
    ]
    gui_session.state = AppState.RESULTS_AVAILABLE

    window._refresh_pages()
    window._update_workflow_indicator()

    print(f"Session loaded: {candidate.graph.activity_count} activities, "
          f"{candidate.graph.dependency_count} deps")
    print(f"Validation status: {gui_session.validation_status}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.resize(1500, 900)
    # Load the preview before injecting the completed session.  AnalysisPage
    # emits image_selected_signal from load_image, which intentionally resets
    # a live user session; doing it first keeps these screenshots truthful.
    window._analysis_page.load_image(str(REFERENCE_AON))

    print("Setting up reference AON session...")
    _set_session_data(window)
    window.show()
    app.processEvents()

    # 1. Analyze page - load image and show completed state
    print("\nCapturing: 01_analyze")
    window._on_nav(NavDestination.ANALYZE)
    app.processEvents()
    pump(app, 320)
    analyze_page = window._analysis_page
    app.processEvents()
    pump(app, 320)
    gui_sess = window._session
    summary = getattr(gui_sess, "review_summary", None) or {}
    count = summary.get("total_activities") or None
    analyze_page.set_analysis_result_status("REVIEW_REQUIRED", activity_count=count)
    analyze_page.show_completed(_workflow, review_item_total=gui_sess.review_item_total())
    app.processEvents()
    pump(app, 320)
    _grab(window, "01_analyze")

    # 2. Understanding page
    print("Capturing: 02_understanding")
    window._on_nav(NavDestination.UNDERSTANDING)
    app.processEvents()
    pump(app, 320)
    _grab(window, "02_understanding")

    # 3. Review Center
    print("Capturing: 03_review")
    window._on_nav(NavDestination.REVIEW)
    app.processEvents()
    pump(app, 320)
    _grab(window, "03_review")

    # 4. Validation page
    print("Capturing: 04_validation")
    window._on_nav(NavDestination.VALIDATE)
    app.processEvents()
    pump(app, 320)
    _grab(window, "04_validation")

    # 5. Results Overview
    print("Capturing: 05_results_overview")
    window._on_nav(NavDestination.RESULTS)
    app.processEvents()
    pump(app, 320)
    _grab(window, "05_results_overview")

    # 6. Results sub-tabs
    print("\nCapturing Results sub-tabs...")
    results_page = window._results_page

    for idx, name in [
        (0, "06_results_overview_tab"),
        (1, "07_results_network"),
        (2, "08_results_activities"),
        (3, "09_results_critical_paths"),
        (4, "10_results_pert"),
    ]:
        results_page._tabs.setCurrentIndex(idx)
        app.processEvents()
        pump(app, 320)
        if idx == 3:
            cp_tab = results_page._critical_paths
            if cp_tab._paths:
                cp_tab._selected_index = -1
                cp_tab.select_path(0)
                cp_tab.repaint()
                app.processEvents()
                pump(app, 320)
        _grab_page(results_page, name, window)

    # ── Network Builder (11/12/13) ─────────────────────────────
    # 11: the page exactly as a first-time visitor sees it (empty).
    print("\nCapturing: 11_network_builder")
    window._on_nav(NavDestination.NETWORK_BUILDER)
    app.processEvents()
    pump(app, 320)
    pump(app, 320)
    bpage = window._network_builder_page
    _grab_page(bpage, "11_network_builder", window)

    # 13: the live workspace populated with the classic 4-activity
    # diamond (same shape the builder tests use) after CPM, so the
    # review can judge the working state, not just the empty state.
    print("Capturing: 13_network_builder_populated")
    bmodel = bpage.get_model()
    for aid, dur, preds in (
        ("A", 1, ""), ("B", 2, "A"), ("C", 2, "A"), ("D", 3, "B, C"),
    ):
        bmodel.add_activity(aid, duration=dur, predecessors=preds)
    bpage._reload_from_model()
    bmodel.calculate_cpm()
    app.processEvents()
    pump(app, 320)
    _grab_page(bpage, "13_network_builder_populated", window)

    # 12: the real end-to-end flow — the page's own Analyze button is
    # clicked and the results the user lands on are captured.
    print("Capturing: 12_results_from_builder")
    bpage._analyze_btn.click()
    app.processEvents()
    pump(app, 480)
    # The results engine restores the last-viewed sub-tab; a fresh arrival
    # should be photographed on Overview, exactly what the user sees first.
    window._results_page._tabs.setCurrentIndex(0)
    app.processEvents()
    pump(app, 240)
    _grab_page(window._results_page, "12_results_from_builder", window)

    print("\nDone. Screenshots in:", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())


