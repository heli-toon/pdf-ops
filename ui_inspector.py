"""Contextual Document Inspector and Interactive Thumbnail Canvas.

Operate Mode: High scanability, tabular metrics, in-memory zero-leakage rendering,
instant page orientation & metadata feedback.
"""

from collections.abc import Callable
import os
from pathlib import Path
import flet as ft
import pymupdf as fitz
from pdf_engine import inspect_pdf_forms
from theme import ThemeTokens, make_badge, padding_only, padding_symmetric


def format_file_size(num_bytes: int) -> str:
    """Format bytes into human-readable metric with tabular precision."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"


class DocumentInspector:
    """Inspector panel showing active document metadata and interactive thumbnail strip."""

    def __init__(self, page: ft.Page, is_dark_supplier: Callable[[], bool]):
        self.page = page
        self.is_dark_supplier = is_dark_supplier
        self.current_file: str | None = None
        self.max_preview_pages = 12
        self.last_form_summary: dict | None = None

        # Inspector root container
        self.container = ft.Container(
            content=self._build_empty_state(),
            expand=True,
            padding=14,
        )

    def _is_dark(self) -> bool:
        return self.is_dark_supplier()

    def set_file(self, file_path: str | None) -> None:
        """Reactive callback triggered by AppState."""
        self.current_file = file_path
        self.refresh()

    def refresh(self) -> None:
        """Re-render inspector contents based on active state."""
        if not self.current_file or not os.path.exists(self.current_file):
            self.container.content = self._build_empty_state()
        else:
            self.container.content = self._build_document_state(self.current_file)
        try:
            if self.container.page:
                self.container.update()
        except Exception:
            pass

    def _build_empty_state(self) -> ft.Control:
        is_dark = self._is_dark()
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.ANALYTICS_OUTLINED, size=18, color=ThemeTokens.text_secondary(is_dark)),
                        ft.Text(
                            "Document Inspector",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ThemeTokens.text_primary(is_dark),
                        ),
                        ft.Container(expand=True),
                        make_badge("Idle", ThemeTokens.bg_card(is_dark), ThemeTokens.text_muted(is_dark)),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.DESCRIPTION_OUTLINED,
                                size=48,
                                color=ThemeTokens.text_muted(is_dark),
                            ),
                            ft.Text(
                                "No Document Selected",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_secondary(is_dark),
                            ),
                            ft.Text(
                                "Drop a file in the workspace or press Ctrl+O to inspect metadata and preview pages.",
                                size=11,
                                color=ThemeTokens.text_muted(is_dark),
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    padding=20,
                ),
            ],
            spacing=10,
            expand=True,
        )

    def _build_document_state(self, file_path: str) -> ft.Control:
        is_dark = self._is_dark()
        file_name = os.path.basename(file_path)
        is_pdf = file_path.lower().endswith(".pdf")
        file_size_str = "0 B"
        try:
            file_size_str = format_file_size(os.path.getsize(file_path))
        except OSError:
            pass

        # Inspect PDF metadata safely with PyMuPDF
        page_count = 0
        is_encrypted = False
        page_dims_str = "N/A"
        fillable_form_count = 0
        total_form_count = 0
        self.last_form_summary = None
        thumbnails: list[ft.Control] = []

        if is_pdf:
            try:
                with fitz.open(file_path) as doc:
                    page_count = doc.page_count
                    is_encrypted = doc.is_encrypted
                    if page_count > 0:
                        first_page = doc[0]
                        rect = first_page.rect
                        page_dims_str = f"{int(rect.width)} × {int(rect.height)} pt"

                    if not (doc.is_encrypted and doc.needs_pass):
                        try:
                            form_summary = inspect_pdf_forms(file_path)
                            self.last_form_summary = form_summary
                            fillable_form_count = int(form_summary.get("fillable_count", 0))
                            total_form_count = int(form_summary.get("total_fields", 0))
                        except Exception:
                            self.last_form_summary = None

                    # Generate in-memory byte previews for thumbnail reel
                    show_count = min(page_count, self.max_preview_pages)
                    for idx in range(show_count):
                        p = doc[idx]
                        pix = p.get_pixmap(matrix=fitz.Matrix(0.35, 0.35))
                        img_bytes = pix.tobytes("png")
                        thumbnails.append(self._build_thumbnail_card(idx + 1, img_bytes, is_dark))

                    if page_count > show_count:
                        remaining = page_count - show_count
                        thumbnails.append(
                            ft.Container(
                                content=ft.Text(
                                    f"+ {remaining} more pages",
                                    size=11,
                                    weight=ft.FontWeight.W_600,
                                    color=ThemeTokens.ACCENT_PRIMARY,
                                ),
                                alignment=ft.Alignment.CENTER,
                                padding=8,
                                border_radius=ThemeTokens.RADIUS_SM,
                                bgcolor=ThemeTokens.bg_card(is_dark),
                            )
                        )
            except Exception as e:
                thumbnails.append(
                    ft.Text(
                        f"Preview unavailable: {e}",
                        size=11,
                        color=ThemeTokens.ACCENT_WARNING,
                    )
                )

        # Build Metadata Summary Grid
        form_metric_val = (
            f"{fillable_form_count} fillable"
            if fillable_form_count > 0
            else (f"{total_form_count} read-only" if total_form_count > 0 else "None")
        )
        meta_items = [
            ("Size", file_size_str, ft.Icons.DATA_USAGE),
            ("Pages", f"{page_count}" if is_pdf else "1", ft.Icons.LAYERS_OUTLINED),
            ("Dimensions", page_dims_str, ft.Icons.ASPECT_RATIO),
            ("AcroForm", form_metric_val if is_pdf else "N/A", ft.Icons.DYNAMIC_FORM),
        ]

        summary_controls = []
        for label, val, icon in meta_items:
            summary_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(icon, size=14, color=ThemeTokens.text_muted(is_dark)),
                            ft.Text(label, size=11, color=ThemeTokens.text_muted(is_dark)),
                            ft.Container(expand=True),
                            ft.Text(
                                val,
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=padding_symmetric(horizontal=8, vertical=4),
                    border_radius=ThemeTokens.RADIUS_XS,
                    bgcolor=ThemeTokens.bg_card(is_dark),
                )
            )

        # Header with Security & Form Detection Pills
        sec_badge = (
            make_badge("Encrypted", ThemeTokens.ACCENT_DANGER, ThemeTokens.DARK_TEXT_PRIMARY, ft.Icons.LOCK)
            if is_encrypted
            else make_badge("Accessible", ThemeTokens.ACCENT_SUCCESS, ThemeTokens.DARK_TEXT_PRIMARY, ft.Icons.LOCK_OPEN)
        )
        form_badge = None
        if is_pdf and not is_encrypted:
            if fillable_form_count > 0:
                label = f"{fillable_form_count} Form Field{'s' if fillable_form_count != 1 else ''}"
                form_badge = make_badge(
                    label,
                    ThemeTokens.ACCENT_PRIMARY,
                    ThemeTokens.DARK_TEXT_PRIMARY,
                    ft.Icons.DYNAMIC_FORM,
                )
            else:
                form_badge = make_badge(
                    "No Form Fields",
                    ThemeTokens.bg_hover(is_dark),
                    ThemeTokens.text_muted(is_dark),
                    ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                )

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.ANALYTICS_OUTLINED, size=16, color=ThemeTokens.ACCENT_PRIMARY),
                        ft.Text(
                            "Document Details",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ThemeTokens.text_primary(is_dark),
                        ),
                        ft.Container(expand=True),
                        sec_badge,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                *([ft.Row([form_badge], spacing=6)] if form_badge is not None else []),
                # File Name Pill
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.PICTURE_AS_PDF if is_pdf else ft.Icons.INSERT_DRIVE_FILE,
                                size=18,
                                color=ThemeTokens.ACCENT_PRIMARY,
                            ),
                            ft.Text(
                                file_name,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=padding_symmetric(horizontal=10, vertical=6),
                    border_radius=ThemeTokens.RADIUS_SM,
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                    bgcolor=ThemeTokens.bg_card(is_dark),
                ),
                # Metrics
                ft.Column(summary_controls, spacing=4),
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                # Thumbnail Header
                ft.Row(
                    [
                        ft.Text(
                            "Page Thumbnails",
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                        ft.Text(
                            f"{len(thumbnails)} rendered",
                            size=11,
                            color=ThemeTokens.text_muted(is_dark),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # Scrollable Thumbnail Reel
                ft.Container(
                    content=ft.Column(thumbnails, spacing=10, scroll=ft.ScrollMode.AUTO),
                    expand=True,
                    border_radius=ThemeTokens.RADIUS_SM,
                    border=ft.Border.all(1, ThemeTokens.border(is_dark)),
                    padding=8,
                    bgcolor=ThemeTokens.bg_surface(is_dark),
                ),
            ],
            spacing=10,
            expand=True,
        )

    def _build_thumbnail_card(self, page_num: int, img_bytes: bytes, is_dark: bool) -> ft.Control:
        """Build an individual page thumbnail card with page label and quick hover border."""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            make_badge(f"P.{page_num}", ThemeTokens.bg_hover(is_dark), ThemeTokens.text_secondary(is_dark)),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    ft.Container(
                        content=ft.Image(
                            src=img_bytes,
                            fit=ft.BoxFit.CONTAIN,
                            border_radius=ThemeTokens.RADIUS_XS,
                        ),
                        alignment=ft.Alignment.CENTER,
                        padding=4,
                    ),
                ],
                spacing=4,
            ),
            padding=6,
            border_radius=ThemeTokens.RADIUS_SM,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )
