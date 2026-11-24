"""Preview views for Phase 4 (Visual Page Organizer) & Phase 5 (Offline OCR).

Provides complete UI ergonomics, parameter selectors, and interactive feedback
aligned with the WAY Forward master roadmap.
"""

from collections.abc import Callable
import os
import flet as ft
import pymupdf as fitz

from app_state import AppState
from theme import ThemeTokens, make_badge
from ui_ocr import OfflineOCRView
from ui_organizer import PageOrganizerView
from utils import get_output_dir, show_snackbar


class PageOrganizerPreview(PageOrganizerView):
    """Visual Page Organizer workspace (Phase 4)."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        is_dark_supplier: Callable[[], bool],
        output_dir: str | None = None,
        **kwargs,
    ):
        super().__init__(
            page=page,
            app_state=app_state,
            output_dir=output_dir or get_output_dir(),
            is_dark_supplier=is_dark_supplier,
        )

class OfflineOCRPreview(OfflineOCRView):
    """True Offline OCR & Text Extraction workspace (Phase 5)."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        is_dark_supplier: Callable[[], bool],
        output_dir: str | None = None,
        progress_bar: ft.ProgressBar | None = None,
        progress_text: ft.Text | None = None,
        **kwargs,
    ):
        super().__init__(
            page=page,
            app_state=app_state,
            output_dir=output_dir or get_output_dir(),
            progress_bar=progress_bar,
            progress_text=progress_text,
            is_dark_supplier=is_dark_supplier,
        )

