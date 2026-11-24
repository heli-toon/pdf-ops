"""True Offline OCR & Searchable PDF Engine workspace (Phase 5).

Operate Mode:
- 100% on-device local OCR processing with zero data leakage.
- Language selector dynamically populated with installed models.
- Pre-processing controls: DPI presets (150/300), deskew toggle, contrast binarization.
- Dual-layer Searchable PDF generator verifiable via Adobe Reader / Chrome Ctrl+F.
- Interactive Text Extraction Studio with live preview, Markdown/Plain formatting,
  clipboard copy, and direct disk export.
"""

from collections.abc import Callable
import os
from pathlib import Path
import time
import flet as ft

from app_state import AppState
from pdf_engine import (
    export_ocr_text_file,
    extract_document_ocr_text,
    generate_searchable_pdf,
    get_available_ocr_languages,
    inspect_pdf,
)
from theme import ThemeTokens, make_badge, padding_only, padding_symmetric
from utils import (
    generate_output_filename,
    open_folder,
    reset_progress,
    run_background,
    show_snackbar,
    update_progress,
)


class OfflineOCRView:
    """Production-grade offline OCR workspace for PDF-Ops."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        output_dir: str,
        progress_bar: ft.ProgressBar | None = None,
        progress_text: ft.Text | None = None,
        is_dark_supplier: Callable[[], bool] = lambda: True,
    ):
        self.page = page
        self.app_state = app_state
        self.output_dir = output_dir
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.is_dark_supplier = is_dark_supplier

        # State
        self.current_file: str | None = getattr(app_state, "current_file", None)
        self.is_processing: bool = False
        self.extracted_text: str = ""
        self.last_searchable_output: str | None = None

        # Discovered languages
        self.available_languages = get_available_ocr_languages()

        # UI Controls
        self._build_controls()

    def _is_dark(self) -> bool:
        return self.is_dark_supplier()

    def set_current_file(self, file_path: str | None) -> None:
        """Reactive callback triggered by central AppState."""
        if file_path == self.current_file:
            return

        self.current_file = file_path
        self.extracted_text = ""
        self.last_searchable_output = None
        self._text_preview.value = ""
        self._text_meta.value = "No text extracted yet"
        self._refresh_active_doc_card()
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass

    def _build_controls(self):
        """Instantiate interactive parameter controls."""
        # Language dropdown
        options = [
            ft.dropdown.Option(key=code, text=label)
            for code, label in self.available_languages
        ]
        default_val = options[0].key if options else "eng"
        self._language_dropdown = ft.Dropdown(
            label="Recognition Language",
            options=options,
            value=default_val,
            width=260,
        )

        # DPI preset
        self._dpi_dropdown = ft.Dropdown(
            label="DPI Resolution",
            options=[
                ft.dropdown.Option(key="150", text="150 DPI (Fast)"),
                ft.dropdown.Option(key="300", text="300 DPI (High Precision)"),
            ],
            value="300",
            width=200,
        )

        # Image Preprocessing Toggles
        self._deskew_switch = ft.Switch(
            label="Automatic Image Deskew",
            value=True,
            tooltip="Detects rotation tilt in scanned pages and straightens them",
        )
        self._binarize_switch = ft.Switch(
            label="Contrast Binarization Filter",
            value=False,
            tooltip="Applies Otsu adaptive thresholding for low-contrast/faint scans",
        )

        # Text Format Selector
        self._format_dropdown = ft.Dropdown(
            label="Export Format",
            options=[
                ft.dropdown.Option(key="plain", text="Plain Text (.txt)"),
                ft.dropdown.Option(key="markdown", text="Markdown Document (.md)"),
            ],
            value="plain",
            width=200,
        )

        # Extracted Text Field & Status
        self._text_preview = ft.TextField(
            multiline=True,
            min_lines=8,
            max_lines=16,
            read_only=False,
            text_size=12,
            hint_text="Extracted document text will appear here. You can edit before copying or saving.",
            border_radius=ThemeTokens.RADIUS_SM,
        )
        self._text_meta = ft.Text("No text extracted yet", size=11)

        # Active document container
        self._active_doc_container = ft.Container()
        self._refresh_active_doc_card()

        # Output feedback container
        self._feedback_container = ft.Container(visible=False)

    def _refresh_active_doc_card(self):
        """Update the file header info banner."""
        is_dark = self._is_dark()
        if not self.current_file or not os.path.exists(self.current_file):
            self._active_doc_container.content = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text(
                            "Select a document or image above to begin offline OCR",
                            size=12,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                    ],
                    spacing=8,
                ),
                padding=10,
                border_radius=ThemeTokens.RADIUS_SM,
                bgcolor=ThemeTokens.bg_hover(is_dark),
                border=ft.Border.all(1, ThemeTokens.border(is_dark)),
            )
            return

        name = os.path.basename(self.current_file)
        size_mb = os.path.getsize(self.current_file) / (1024 * 1024)
        page_info = ""
        try:
            info = inspect_pdf(self.current_file)
            page_info = f" • {info['page_count']} Pages"
        except Exception:
            pass

        self._active_doc_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=20, color=ThemeTokens.ACCENT_SUCCESS),
                    ft.Column(
                        [
                            ft.Text(name, size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Text(f"Ready for OCR • {size_mb:.2f} MB{page_info}", size=11, color=ThemeTokens.text_secondary(is_dark)),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    make_badge("Offline", ThemeTokens.bg_surface(is_dark), ThemeTokens.ACCENT_SUCCESS),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_hover(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_SUCCESS if is_dark else ThemeTokens.border_muted(is_dark)),
        )

    def build_ui(self) -> ft.Control:
        """Construct the complete Phase 5 Operate workspace."""
        is_dark = self._is_dark()
        self._refresh_active_doc_card()

        # Update styling of controls
        self._text_preview.bgcolor = ThemeTokens.bg_card(is_dark)
        self._text_preview.border_color = ThemeTokens.border_muted(is_dark)
        self._text_preview.color = ThemeTokens.text_primary(is_dark)
        self._text_meta.color = ThemeTokens.text_secondary(is_dark)

        # Header
        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    "🔍 True Offline OCR Engine",
                                    size=16,
                                    weight=ft.FontWeight.W_700,
                                    color=ThemeTokens.text_primary(is_dark),
                                ),
                                make_badge("Phase 5", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                                make_badge("100% Offline", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_SUCCESS),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            "On-device optical character recognition — no cloud uploads, telemetry, or data leakage",
                            size=12,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Settings Card
        settings_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TUNE, size=18, color=ThemeTokens.ACCENT_PRIMARY),
                            ft.Text(
                                "OCR Configuration & Pre-processing",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            self._language_dropdown,
                            self._dpi_dropdown,
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            self._deskew_switch,
                            self._binarize_switch,
                        ],
                        spacing=20,
                        wrap=True,
                    ),
                ],
                spacing=12,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        # Workspace Tab 1: Searchable PDF Studio
        searchable_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SEARCH, size=18, color=ThemeTokens.ACCENT_PRIMARY),
                            ft.Text(
                                "Dual-Layer Searchable PDF",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                            make_badge("Ctrl+F Ready", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_CYAN),
                        ],
                        spacing=8,
                    ),
                    ft.Text(
                        "Produces a production-grade dual-layer PDF: high-resolution visible scan on top, perfectly aligned invisible selectable text layer underneath. Full search fidelity across Adobe Reader, Chrome, and Evince.",
                        size=11,
                        color=ThemeTokens.text_secondary(is_dark),
                    ),
                    ft.Row(
                        [
                            ft.FilledButton(
                                "Generate Searchable PDF",
                                icon=ft.Icons.AUTO_AWESOME,
                                on_click=self._on_generate_searchable_clicked,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM),
                                ),
                            ),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        # Workspace Tab 2: Text Extraction & Export Studio
        extraction_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TEXT_SNIPPET, size=18, color=ThemeTokens.ACCENT_PRIMARY),
                            ft.Text(
                                "Text Extraction & Export Studio",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Text(
                        "Extract recognized text directly from scanned pages to your clipboard or structured local files.",
                        size=11,
                        color=ThemeTokens.text_secondary(is_dark),
                    ),
                    ft.Row(
                        [
                            self._format_dropdown,
                            ft.FilledButton(
                                "Extract Text",
                                icon=ft.Icons.DOCUMENT_SCANNER,
                                on_click=self._on_extract_text_clicked,
                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                            ),
                            ft.OutlinedButton(
                                "Copy to Clipboard",
                                icon=ft.Icons.COPY,
                                on_click=self._on_copy_clipboard_clicked,
                            ),
                            ft.OutlinedButton(
                                "Save to Disk",
                                icon=ft.Icons.SAVE_ALT,
                                on_click=self._on_save_file_clicked,
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    self._text_preview,
                    ft.Row(
                        [
                            self._text_meta,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=12,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        return ft.Column(
            [
                header,
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                self._active_doc_container,
                self._feedback_container,
                settings_card,
                searchable_card,
                extraction_card,
            ],
            spacing=14,
            expand=True,
        )

    # -------------------------------------------------------------------------
    # Execution Handlers
    # -------------------------------------------------------------------------

    def _validate_source(self) -> str | None:
        file_path = self.app_state.current_file or self.current_file
        if not file_path or not os.path.exists(file_path):
            show_snackbar(self.page, "Please select a document or image first", "warning")
            return None
        return file_path

    def _on_generate_searchable_clicked(self, e):
        src = self._validate_source()
        if not src or self.is_processing:
            return

        dpi = int(self._dpi_dropdown.value or "300")
        lang = self._language_dropdown.value or "eng"
        deskew = bool(self._deskew_switch.value)
        binarize = bool(self._binarize_switch.value)

        out_name = generate_output_filename(src, "searchable", ".pdf")
        out_path = os.path.join(self.output_dir, out_name)

        self.is_processing = True
        self._show_feedback("Starting OCR processing...", "info")

        def worker():
            t_start = time.perf_counter()
            try:
                def progress(current, total, msg):
                    ratio = current / max(total, 1)
                    if self.progress_bar and self.progress_text:
                        update_progress(self.progress_bar, self.progress_text, ratio, f"OCR: {msg}")

                saved_path = generate_searchable_pdf(
                    source=src,
                    output_path=out_path,
                    language=lang,
                    dpi=dpi,
                    deskew=deskew,
                    binarize=binarize,
                    progress_callback=progress,
                )
                self.last_searchable_output = str(saved_path)
                elapsed = time.perf_counter() - t_start

                self._show_success_banner(
                    f"Searchable PDF created successfully in {elapsed:.1f}s!",
                    str(saved_path),
                )
                show_snackbar(self.page, f"Searchable PDF saved: {os.path.basename(str(saved_path))}", "success")
            except Exception as err:
                self._show_feedback(f"OCR generation failed: {err}", "error")
                show_snackbar(self.page, f"OCR failed: {err}", "error")
            finally:
                self.is_processing = False
                if self.progress_bar and self.progress_text:
                    reset_progress(self.progress_bar, self.progress_text)
                try:
                    self.page.update()
                except Exception:
                    pass

        run_background(self.page, worker)

    def _on_extract_text_clicked(self, e):
        src = self._validate_source()
        if not src or self.is_processing:
            return

        dpi = int(self._dpi_dropdown.value or "150")
        lang = self._language_dropdown.value or "eng"
        deskew = bool(self._deskew_switch.value)
        binarize = bool(self._binarize_switch.value)
        fmt = self._format_dropdown.value or "plain"

        self.is_processing = True
        self._show_feedback("Extracting text via local OCR...", "info")

        def worker():
            t_start = time.perf_counter()
            try:
                def progress(current, total, msg):
                    ratio = current / max(total, 1)
                    if self.progress_bar and self.progress_text:
                        update_progress(self.progress_bar, self.progress_text, ratio, f"OCR: {msg}")

                text = extract_document_ocr_text(
                    source=src,
                    language=lang,
                    dpi=dpi,
                    deskew=deskew,
                    binarize=binarize,
                    format_type=fmt,
                    progress_callback=progress,
                )
                self.extracted_text = text
                elapsed = time.perf_counter() - t_start

                # Update UI controls
                self._text_preview.value = text
                char_count = len(text)
                word_count = len(text.split())
                self._text_meta.value = (
                    f"Extracted {char_count:,} characters • {word_count:,} words • Completed in {elapsed:.1f}s"
                )
                self._hide_feedback()
                show_snackbar(self.page, f"Extracted {word_count:,} words successfully!", "success")
            except Exception as err:
                self._show_feedback(f"Text extraction failed: {err}", "error")
                show_snackbar(self.page, f"Extraction failed: {err}", "error")
            finally:
                self.is_processing = False
                if self.progress_bar and self.progress_text:
                    reset_progress(self.progress_bar, self.progress_text)
                try:
                    self.page.update()
                except Exception:
                    pass

        run_background(self.page, worker)

    def _on_copy_clipboard_clicked(self, e):
        text = self._text_preview.value or self.extracted_text
        if not text:
            show_snackbar(self.page, "No text to copy. Click 'Extract Text' first.", "warning")
            return
        try:
            self.page.set_clipboard(text)
            show_snackbar(self.page, f"Copied {len(text):,} characters to clipboard!", "success")
        except Exception as err:
            show_snackbar(self.page, f"Clipboard copy failed: {err}", "error")

    def _on_save_file_clicked(self, e):
        text = self._text_preview.value or self.extracted_text
        if not text:
            show_snackbar(self.page, "No extracted text to save. Click 'Extract Text' first.", "warning")
            return

        src = self._validate_source()
        if not src:
            return

        fmt = self._format_dropdown.value or "plain"
        ext = ".md" if fmt == "markdown" else ".txt"
        out_name = generate_output_filename(src, "ocr_text", ext)
        out_path = os.path.join(self.output_dir, out_name)

        try:
            Path(out_path).write_text(text, encoding="utf-8")
            show_snackbar(self.page, f"Saved text file: {out_name}", "success")
            self._show_success_banner("Text file saved to disk!", out_path)
        except Exception as err:
            show_snackbar(self.page, f"Failed to save text file: {err}", "error")

    # -------------------------------------------------------------------------
    # Banner & Feedback Helpers
    # -------------------------------------------------------------------------

    def _show_feedback(self, message: str, status_type: str = "info"):
        is_dark = self._is_dark()
        color = ThemeTokens.ACCENT_PRIMARY if status_type == "info" else ThemeTokens.ACCENT_DANGER
        self._feedback_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=color),
                    ft.Text(message, size=12, color=ThemeTokens.text_primary(is_dark), expand=True),
                ],
                spacing=8,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_hover(is_dark),
            border=ft.Border.all(1, color),
        )
        self._feedback_container.visible = True
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass

    def _hide_feedback(self):
        self._feedback_container.visible = False
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass

    def _show_success_banner(self, title: str, output_path: str):
        is_dark = self._is_dark()
        self._feedback_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=20, color=ThemeTokens.ACCENT_SUCCESS),
                    ft.Column(
                        [
                            ft.Text(title, size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Text(f"Saved: {os.path.basename(output_path)}", size=11, color=ThemeTokens.text_secondary(is_dark)),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.OutlinedButton(
                        "Open Folder",
                        icon=ft.Icons.FOLDER_OPEN,
                        on_click=lambda e: open_folder(os.path.dirname(output_path)),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=12,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_card(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_SUCCESS),
        )
        self._feedback_container.visible = True
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass
