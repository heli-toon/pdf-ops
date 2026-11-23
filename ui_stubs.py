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

class OfflineOCRPreview:
    """True Offline OCR & Text Extraction workspace (Phase 5)."""

    def __init__(self, page: ft.Page, app_state: AppState, is_dark_supplier: Callable[[], bool]):
        self.page = page
        self.app_state = app_state
        self.is_dark_supplier = is_dark_supplier

    def _is_dark(self) -> bool:
        return self.is_dark_supplier()

    def build_ui(self) -> ft.Control:
        is_dark = self._is_dark()
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text("🔍 True Offline OCR Engine", size=16, weight=ft.FontWeight.W_700, color=ThemeTokens.text_primary(is_dark)),
                                        make_badge("Phase 5 Roadmap", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text("100% on-device optical character recognition — no cloud uploads or data telemetry", size=12, color=ThemeTokens.text_secondary(is_dark)),
                            ],
                            spacing=2,
                        ),
                    ],
                ),
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("OCR Engine Parameters", size=13, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Row(
                                [
                                    ft.Dropdown(
                                        label="Primary Language",
                                        options=[
                                            ft.dropdown.Option("English (eng)"),
                                            ft.dropdown.Option("French (fra)"),
                                            ft.dropdown.Option("German (deu)"),
                                            ft.dropdown.Option("Spanish (spa)"),
                                            ft.dropdown.Option("Multi-Language Auto"),
                                        ],
                                        value="English (eng)",
                                        width=250,
                                    ),
                                    ft.Dropdown(
                                        label="DPI Pre-processing",
                                        options=[ft.dropdown.Option("150 DPI (Fast)"), ft.dropdown.Option("300 DPI (High Precision)")],
                                        value="300 DPI (High Precision)",
                                        width=220,
                                    ),
                                ],
                                spacing=12,
                            ),
                            ft.Row(
                                [
                                    ft.Switch(label="Automatic Image Deskew", value=True),
                                    ft.Switch(label="Contrast Binarization Filter", value=True),
                                ],
                                spacing=20,
                            ),
                            ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                            ft.Text("Extraction Targets", size=13, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Row(
                                [
                                    ft.FilledButton(
                                        "Generate Searchable PDF",
                                        icon=ft.Icons.SEARCH,
                                        on_click=lambda e: show_snackbar(self.page, "OCR scheduled for Phase 5", "info"),
                                    ),
                                    ft.OutlinedButton(
                                        "Extract Text to Clipboard",
                                        icon=ft.Icons.COPY,
                                        on_click=lambda e: self._copy_extracted_text(),
                                    ),
                                ],
                                spacing=12,
                            ),
                        ],
                        spacing=14,
                    ),
                    padding=20,
                    border_radius=ThemeTokens.RADIUS_MD,
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                    bgcolor=ThemeTokens.bg_card(is_dark),
                ),
            ],
            spacing=12,
            expand=True,
        )

    def _copy_extracted_text(self):
        file_path = self.app_state.current_file
        if not file_path or not os.path.exists(file_path):
            show_snackbar(self.page, "Select a document first", "warning")
            return
        try:
            with fitz.open(file_path) as doc:
                text = ""
                for p in doc:
                    text += p.get_text()
                self.page.set_clipboard(text)
                show_snackbar(self.page, f"Copied {len(text)} characters to clipboard!", "success")
        except Exception as e:
            show_snackbar(self.page, f"Extraction failed: {e}", "error")
