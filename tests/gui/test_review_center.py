"""
Tests for the interactive Human Review Center.

Exercises the ReviewPage workspace, categories, item lists, detail
panels, decision forwarding to the real ReviewSession, progress,
completion states, apply workflow, unsaved-decision guards, evidence
display, and image context overlays.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from pert_analyzer.gui.main_window import MainWindow
from pert_analyzer.gui.navigation import NavDestination
from pert_analyzer.gui.pages.review_page import ReviewPage
from pert_analyzer.gui.reviews import context as review_context
from pert_analyzer.gui.reviews.categories import ReviewCategory
from pert_analyzer.gui.reviews.detail_panels import ReviewActionRequest
from pert_analyzer.gui.reviews.widgets import EvidencePanel, ImageContextView
from pert_analyzer.gui.session import AppState, GuiSession
from pert_analyzer.pipeline.human_review import ReviewStatus
from tests.gui.fakes import (
    FakeReviewedWorkflow,
    make_reconstruction,
    make_review_session,
    reviewed_session,
)


@pytest.fixture()
def page(qapp: QApplication) -> ReviewPage:
    return ReviewPage()


@pytest.fixture()
def session(qapp: QApplication) -> GuiSession:
    return reviewed_session()


@pytest.fixture()
def dep_session(qapp: QApplication) -> GuiSession:
    return reviewed_session(
        reconstruction=make_reconstruction([("N0", "A0"), ("N1", "A1"), ("N2", "A2")])
    )


def wait_for(app: QApplication, condition, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for _ in range(20):
            app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def _resolve_all(session: GuiSession) -> None:
    wf = session.workflow
    rs = session.review_session
    for it in list(rs.activities):
        session.decide_activity(it.geometric_node_id, "ACCEPT")
    for it in list(rs.dependencies):
        session.decide_dependency(it.arrow_id, "ACCEPT")
    for it in list(rs.durations):
        session.decide_duration(it.geometric_node_id, "ACCEPT")


# ---------------------------------------------------------------------------
# Layout / empty states
# ---------------------------------------------------------------------------


def test_review_page_no_analysis_empty_state(page: ReviewPage) -> None:
    page.refresh(GuiSession())
    assert "No analysis available" in page.empty_message
    assert page.stack_index == page._EMPTY


def test_review_page_no_review_session_empty_state(page: ReviewPage) -> None:
    session = GuiSession()
    session.workflow = SimpleNamespace(review_session=None, pipeline_result=None)
    page.refresh(session)
    assert "No review session" in page.empty_message
    assert page.empty_go_validation_visible


def test_review_page_no_review_items_state(page: ReviewPage) -> None:
    session = GuiSession()
    session.complete_analysis(FakeReviewedWorkflow(make_review_session(
        n_activities=0, n_dependencies=0, n_durations=0
    )))
    page.refresh(session)
    assert "No review items" in page.empty_message


def test_categories_buttons_present(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    labels = {
        btn.text().split(" ")[0]
        for btn in page._categories._buttons.values()
    }
    assert labels == {"Activities", "Dependencies", "Durations"}


def test_category_pending_counts_shown(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    assert page._categories._buttons[ReviewCategory.ACTIVITIES].text() == "Activities (2)"
    assert page._categories._buttons[ReviewCategory.DEPENDENCIES].text() == "Dependencies (1)"
    assert page._categories._buttons[ReviewCategory.DURATIONS].text() == "Durations (1)"


# ---------------------------------------------------------------------------
# List population + selection
# ---------------------------------------------------------------------------


def test_pending_items_populate_activites(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    assert page.stack_index == page._WORKSPACE
    assert page._category == ReviewCategory.ACTIVITIES
    assert len(page.current_items()) == 2
    assert page._item_list.count() == 2


def test_switch_category_populates_items(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    page._on_category_selected(ReviewCategory.DEPENDENCIES)
    assert page._category == ReviewCategory.DEPENDENCIES
    assert len(page.current_items()) == 1


def test_selecting_activity_shows_panel(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    assert page._detail_stack.currentWidget() is page._activity_panel
    assert page._activity_panel._item is page.current_items()[0]


# ---------------------------------------------------------------------------
# Activity decisions
# ---------------------------------------------------------------------------


def test_accept_activity_decision(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    item = page._activity_panel._item
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.ACTIVITIES, item, "ACCEPT"))
    assert item.status == ReviewStatus.ACCEPTED
    assert session.review_session.pending_activity_count == 1
    assert len(page.current_items()) == 1
    assert session.reviews_dirty


def test_correct_activity_decision(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    item = page._activity_panel._item
    page._on_detail_decision(
        ReviewActionRequest(ReviewCategory.ACTIVITIES, item, "CORRECT", corrected_value="X9")
    )
    assert item.status == ReviewStatus.CORRECTED
    assert item.corrected_activity_id == "X9"
    assert session.review_session.pending_activity_count == 1


def test_invalid_activity_id_rejected_inline(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    item = page._activity_panel._item
    panel = page._activity_panel
    panel._on_action("CORRECT", "Correct...")
    panel._id_edit.setText("bad id!")
    panel._apply_edit.click()
    assert "Invalid identifier" in panel._feedback.text()
    assert item.status == ReviewStatus.PENDING


def test_duplicate_activity_id_rejected(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    first = page._activity_panel._item
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.ACTIVITIES, first, "ACCEPT"))
    second = page._activity_panel._item
    assert second is not first
    panel = page._activity_panel
    panel._on_action("CORRECT", "Correct...")
    panel._id_edit.setText(first.current_activity_id)
    panel._apply_edit.click()
    assert "Duplicate ID" in panel._feedback.text()
    assert second.status == ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# Dependency decisions
# ---------------------------------------------------------------------------


def test_accept_dependency(page: ReviewPage, dep_session: GuiSession) -> None:
    page.refresh(dep_session)
    page._on_category_selected(ReviewCategory.DEPENDENCIES)
    item = page._dependency_panel._item
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.DEPENDENCIES, item, "ACCEPT"))
    assert item.status == ReviewStatus.ACCEPTED
    assert dep_session.review_session.pending_dependency_count == 0


def test_reject_dependency(page: ReviewPage, dep_session: GuiSession) -> None:
    page.refresh(dep_session)
    page._on_category_selected(ReviewCategory.DEPENDENCIES)
    item = page._dependency_panel._item
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.DEPENDENCIES, item, "REJECT"))
    assert item.status == ReviewStatus.REJECTED


def test_reverse_dependency(page: ReviewPage, dep_session: GuiSession) -> None:
    page.refresh(dep_session)
    page._on_category_selected(ReviewCategory.DEPENDENCIES)
    item = page._dependency_panel._item
    old_src, old_tgt = item.current_source_id, item.current_target_id
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.DEPENDENCIES, item, "REVERSE"))
    assert item.status == ReviewStatus.CORRECTED
    assert item.corrected_source_id == old_tgt
    assert item.corrected_target_id == old_src


def test_change_source_dependency(page: ReviewPage, dep_session: GuiSession) -> None:
    page.refresh(dep_session)
    page._on_category_selected(ReviewCategory.DEPENDENCIES)
    item = page._dependency_panel._item
    panel = page._dependency_panel
    panel._on_action("CHANGE_SOURCE", "Change Source...")
    assert panel._node_combo.count() >= 2
    idx = panel._node_combo.findData("A1")
    assert idx >= 0
    panel._node_combo.setCurrentIndex(idx)
    panel._node_apply.click()
    assert item.status == ReviewStatus.CORRECTED
    assert item.corrected_source_id == "A1"


def test_change_target_dependency(page: ReviewPage, dep_session: GuiSession) -> None:
    page.refresh(dep_session)
    page._on_category_selected(ReviewCategory.DEPENDENCIES)
    item = page._dependency_panel._item
    panel = page._dependency_panel
    panel._on_action("CHANGE_TARGET", "Change Target...")
    idx = panel._node_combo.findData("A1")
    panel._node_combo.setCurrentIndex(idx)
    panel._node_apply.click()
    assert item.status == ReviewStatus.CORRECTED
    assert item.corrected_target_id == "A1"


# ---------------------------------------------------------------------------
# Duration decisions
# ---------------------------------------------------------------------------


def test_duration_category_and_accept(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    page._on_category_selected(ReviewCategory.DURATIONS)
    assert page._detail_stack.currentWidget() is page._duration_panel
    item = page._duration_panel._item
    day = session.review_session.durations[0]
    assert item is day
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.DURATIONS, item, "ACCEPT"))
    assert day.status == ReviewStatus.ACCEPTED
    assert session.review_session.pending_duration_count == 0


def test_correct_duration(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    page._on_category_selected(ReviewCategory.DURATIONS)
    item = page._duration_panel._item
    page._on_detail_decision(
        ReviewActionRequest(ReviewCategory.DURATIONS, item, "CORRECT", corrected_value=5.0)
    )
    assert item.status == ReviewStatus.CORRECTED
    assert item.corrected_duration == 5.0


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("0", "zero"),
        ("-3", "positive"),
        ("abc", "Not a valid number"),
        ("nan", "NaN"),
        ("1e999", "infinite"),
    ],
)
def test_invalid_duration_rejected_inline(
    page: ReviewPage, session: GuiSession, text: str, fragment: str
) -> None:
    page.refresh(session)
    page._on_category_selected(ReviewCategory.DURATIONS)
    item = page._duration_panel._item
    panel = page._duration_panel
    panel._on_action("CORRECT", "Correct...")
    panel._dur_edit.setText(text)
    panel._apply_edit.click()
    assert fragment.lower() in panel._feedback.text().lower()
    assert item.status == ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# Navigation / leave unresolved / progress
# ---------------------------------------------------------------------------


def test_leave_unresolved_advances_without_decision(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    page._item_list.setCurrentRow(1)
    current = page._activity_panel._item
    assert current is page.current_items()[1]
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.ACTIVITIES, current, "LEAVE_UNRESOLVED"))
    assert current.status == ReviewStatus.PENDING
    assert session.review_session.pending_activity_count == 2
    assert not session.reviews_dirty
    assert page._activity_panel._item is page.current_items()[0]


def test_progress_label_tracks_reviewed(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    label = page._progress_label.text()
    assert "Resolved" in label and "Pending" in label
    assert "0" in label.split("/")[0]
    item = page._activity_panel._item
    page._on_detail_decision(ReviewActionRequest(ReviewCategory.ACTIVITIES, item, "ACCEPT"))
    label2 = page._progress_label.text()
    assert "1" in label2.split("/")[0]


def test_review_complete_state_after_all_resolved(
    page: ReviewPage, session: GuiSession
) -> None:
    page.refresh(session)
    for cat in ReviewCategory:
        page._on_category_selected(cat)
        for _ in range(len(page.current_items())):
            item = page._panel_for(cat)._item
            page._on_detail_decision(
                ReviewActionRequest(cat, item, "ACCEPT")
            )
            if page.is_complete:
                break
    assert page.is_complete
    count_label = page._complete_state._tiles[ReviewCategory.ACTIVITIES]["count"].text()
    assert "2 / 2" in count_label
    assert session.pending_review_total() == 0


# ---------------------------------------------------------------------------
# Unsaved-decision guards
# ---------------------------------------------------------------------------


def _guarded_window(qapp: QApplication, session: GuiSession) -> MainWindow:
    window = MainWindow(backend=lambda path: None)
    window._session = session
    return window


def test_unsaved_decisions_guard_blocks_image_remove(qapp: QApplication) -> None:
    session = reviewed_session()
    window = _guarded_window(qapp, session)
    window._session.current_image_path = "C:/tmp/review_fixture.png"
    window._session.reviews_dirty = True
    window._confirm_discard_fn = lambda: False
    window._on_image_removed()
    assert window._session.current_image_path == "C:/tmp/review_fixture.png"
    assert window._session.workflow is not None

    window._confirm_discard_fn = lambda: True
    window._on_image_removed()
    assert window._session.workflow is None


def test_close_event_respects_guard(qapp: QApplication) -> None:
    session = reviewed_session()
    session.reviews_dirty = True
    window = _guarded_window(qapp, session)
    window._confirm_discard_fn = lambda: False
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()

    window._confirm_discard_fn = lambda: True
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


# ---------------------------------------------------------------------------
# Evidence + image context
# ---------------------------------------------------------------------------


def test_evidence_panel_shows_markers_and_confidence(qapp: QApplication) -> None:
    from pert_analyzer.pipeline.human_review import ReviewEvidence

    panel = EvidencePanel()
    panel.set_evidence(
        [
            ReviewEvidence("ocr", ["1"], "Boundary contact", 0.7),
            ReviewEvidence("ocr", [], "Weak arrowhead", 0.2),
        ],
        confidence=0.62,
        reason="Visual check",
    )
    text = panel._compact.text()
    assert "\u2713 Boundary contact" in text
    assert "\u2717 Weak arrowhead" in text
    assert "62%" in panel._confidence.text()

    panel._tech_btn.click()
    assert not panel._technical.isHidden()
    assert panel._technical.isVisibleTo(panel)
    assert "Boundary contact" in panel._technical.toPlainText()


def test_image_context_overlay_renders(tmp_path, qapp: QApplication) -> None:
    img_path = tmp_path / "diagram.png"
    from PIL import Image

    Image.new("RGB", (400, 300), "white").save(img_path)

    view = ImageContextView()
    view.setMinimumSize(200, 150)
    shown = view.set_context(
        str(img_path),
        [review_context.HighlightRect(40, 40, 120, 60, color="accent", label="A0")]
        + [
            review_context.HighlightLine(100, 100, 260, 140, color="accent"),
        ],
    )
    assert shown
    assert view.highlight_count == 2
    assert view._pixmap is not None and not view._pixmap.isNull()


def test_image_context_view_survives_resize_with_live_geometry(tmp_path, qapp: QApplication) -> None:
    """Regression: setting a context on a visible layout-managed view must not
    recurse through layout size-hint negotiation. The previous implementation
    re-set the scaled pixmap from resizeEvent, which overflowed the native
    stack once the review page became visible after an async analysis."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from PIL import Image

    img_path = tmp_path / "diagram.png"
    Image.new("RGB", (600, 400), "white").save(img_path)

    host = QWidget()
    layout = QVBoxLayout(host)
    view = ImageContextView()
    layout.addWidget(view)
    host.resize(320, 240)
    host.show()
    qapp.processEvents()

    shown = view.set_context(
        str(img_path),
        [review_context.HighlightRect(40, 40, 120, 60, color="accent", label="A0")],
    )
    assert shown
    qapp.processEvents()

    for size in [(300, 300), (280, 280), (260, 260), (240, 240)]:
        host.resize(*size)
        qapp.processEvents()

    assert view.highlight_count == 1
    assert view._pixmap is not None and not view._pixmap.isNull()
    assert not hasattr(view, "_image_label")
    assert not hasattr(view, "_repaint_scaled")


def test_detail_panel_placeholder_without_image(page: ReviewPage, session: GuiSession) -> None:
    page.refresh(session)
    assert page._activity_panel._context.highlight_count == 0
    assert page._activity_panel._context._pixmap is None


def _prepare_image(tmp_path) -> str:
    from PIL import Image as PILImage

    img_path = tmp_path / "diagram.png"
    PILImage.new("RGB", (64, 64), "white").save(str(img_path))
    return str(img_path)


def test_apply_decisions_updates_state_and_navigates(
    qapp: QApplication, tmp_path
) -> None:
    rs = make_review_session()
    window = MainWindow(
        backend=lambda path: FakeReviewedWorkflow(rs, review_required=True)
    )
    window._analysis_page.load_image(_prepare_image(tmp_path))
    window._on_analyze_requested()
    try:
        wait_for(qapp, lambda: window._worker is None)
    finally:
        if window._worker is not None:
            window._worker.wait(3000)

    _resolve_all(window._session)
    window._review_page.refresh(window._session)
    assert window._review_page.is_complete

    window._on_apply_review_decisions()
    assert wait_for(qapp, lambda: window._apply_worker is None, timeout=10.0)
    assert window._session.has_applied_reviews
    assert window._session.state == AppState.VALIDATION_REQUIRED
    assert window._stack.currentIndex() == NavDestination.VALIDATE.value


def test_apply_failure_returns_to_review(
    qapp: QApplication, tmp_path
) -> None:
    rs = make_review_session(n_activities=1, n_dependencies=1, n_durations=1)

    def failing_apply():
        raise RuntimeError("apply boom")

    window = MainWindow(
        backend=lambda path: FakeReviewedWorkflow(rs, review_required=True),
        apply_reviews_fn=failing_apply,
    )
    window._analysis_page.load_image(_prepare_image(tmp_path))
    window._on_analyze_requested()
    try:
        wait_for(qapp, lambda: window._worker is None)
    finally:
        if window._worker is not None:
            window._worker.wait(3000)

    window._review_page.refresh(window._session)
    window._on_apply_review_decisions()
    assert wait_for(qapp, lambda: window._apply_worker is None, timeout=10.0)
    assert window._session.state == AppState.REVIEW_REQUIRED
    assert not window._review_page.is_busy