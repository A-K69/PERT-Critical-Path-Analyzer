"""
Tests for session updates, stay-on-analyze navigation, and responsiveness.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from pert_analyzer.gui.main_window import MainWindow
from pert_analyzer.gui.navigation import NavDestination
from pert_analyzer.gui.session import AppState
from tests.gui.fakes import FakeBackend, FakeWorkflow


@pytest.fixture()
def tmp_image(tmp_path: "Path") -> str:  # noqa: F821
    img = QImage(200, 100, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.white)
    p = tmp_path / "test.png"
    img.save(str(p), "PNG")
    return str(p)


@pytest.fixture()
def window(qapp: "QApplication") -> "MainWindow":  # noqa: F821
    w = MainWindow()
    yield w
    w.close()


def test_session_updates_after_analysis(
    window: MainWindow, tmp_image: str, qapp: "QApplication"  # noqa: F821
) -> None:
    wf = FakeWorkflow(pa=2, pd=3, pdr=1, review_required=True)
    window._backend = FakeBackend(workflow=wf)
    window._analysis_page.load_image(tmp_image)
    window._on_analyze_requested()
    qapp.processEvents()
    for _ in range(50):
        qapp.processEvents()
        time.sleep(0.01)

    assert window._session.state == AppState.REVIEW_REQUIRED
    assert window._session.review_summary is not None
    assert window._session.review_summary["activity_reviews_pending"] == 2
    assert window._session.review_summary["pending_dependency_reviews"] == 3
    assert window._session.review_summary["duration_reviews_pending"] == 1


def test_user_stays_on_analyze_when_review_items(
    window: MainWindow, tmp_image: str, qapp: "QApplication"  # noqa: F821
) -> None:
    """Analysis must NOT auto-jump: the user stays to watch the machine."""
    wf = FakeWorkflow(pa=1, pd=0, pdr=0, review_required=True)
    window._backend = FakeBackend(workflow=wf)
    window._analysis_page.load_image(tmp_image)
    window._on_analyze_requested()
    qapp.processEvents()
    for _ in range(50):
        qapp.processEvents()
        time.sleep(0.01)

    assert window._stack.currentIndex() == NavDestination.ANALYZE.value
    assert window._session.state == AppState.REVIEW_REQUIRED


def test_user_stays_on_analyze_when_no_review_items(
    window: MainWindow, tmp_image: str, qapp: "QApplication"  # noqa: F821
) -> None:
    """Same stay-on-analyze rule when validation is the next step."""
    wf = FakeWorkflow(pa=0, pd=0, pdr=0, review_required=False)
    window._backend = FakeBackend(workflow=wf)
    window._analysis_page.load_image(tmp_image)
    window._on_analyze_requested()
    qapp.processEvents()
    for _ in range(50):
        qapp.processEvents()
        time.sleep(0.01)

    assert window._stack.currentIndex() == NavDestination.ANALYZE.value
    assert window._session.state == AppState.VALIDATION_REQUIRED


def test_responsiveness_while_analyzing(
    window: MainWindow, tmp_image: str, qapp: "QApplication"  # noqa: F821
) -> None:
    block = threading.Event()
    window._backend = FakeBackend(block_event=block)
    window._analysis_page.load_image(tmp_image)
    window._on_analyze_requested()

    # allow QThread.start() to fire
    for _ in range(20):
        qapp.processEvents()

    assert window._session.state == AppState.ANALYZING
    assert not window._analysis_page._analyze_btn.isEnabled()
    assert "Analyzing" in window._analysis_page._status_panel._label.text()

    block.set()
    for _ in range(100):
        qapp.processEvents()
        time.sleep(0.01)

    assert window._session.state in (
        AppState.REVIEW_REQUIRED,
        AppState.VALIDATION_REQUIRED,
    )
