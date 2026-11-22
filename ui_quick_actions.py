"""Quick Actions Dashboard for PDF-Ops.

Operate Mode: 1-click workflows for high-frequency operations:
Convert to Word, Compress, Fast Encrypt, and Export Images.
"""

from collections.abc import Callable
import os
from pathlib import Path
import flet as ft

from app_state import AppState
from pdf_engine import compress_pdf, export_pdf_images, inspect_pdf
from theme import ThemeTokens, make_badge
from utils import generate_output_filename, open_folder, run_background, show_snackbar, update_progress, reset_progress


class QuickActionsView:
    """High-density 1-click action dashboard."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        output_dir: str,
        progress_bar: ft.ProgressBar,
        progress_text: ft.Text,
        is_dark_supplier: Callable[[], bool],
        navigate_callback: Callable[[str], None],
    ):
        self.page = page
        self.app_state = app_state
        self.output_dir = output_dir
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.is_dark_supplier = is_dark_supplier
        self.navigate_callback = navigate_callback

    def _is_dark(self) -> bool:
        return self.is_dark_supplier()

    def build_ui(self) -> ft.Control:
        is_dark = self._is_dark()

        cards = [
            (
                "Convert to Word",
                "Extract structured text, tables, and images into editable .docx format",
                ft.Icons.DESCRIPTION_OUTLINED,
                ThemeTokens.ACCENT_PRIMARY,
                self._quick_pdf_to_word,
                "Convert Now",
            ),
            (
                "Compress & Optimize",
                "Reduce file size with stream deflation and image downsampling",
                ft.Icons.COMPRESS,
                ThemeTokens.ACCENT_SUCCESS,
                self._quick_compress,
                "Compress Now",
            ),
            (
                "AES-256 Protect",
                "Apply enterprise-grade encryption with custom viewing password",
                ft.Icons.LOCK_OUTLINE,
                ThemeTokens.ACCENT_WARNING,
                self._quick_encrypt_prompt,
                "Secure Document",
            ),
            (
                "Extract Page Images",
                "Render all pages to high-resolution PNG images at 150 DPI",
                ft.Icons.IMAGE_OUTLINED,
                ThemeTokens.ACCENT_CYAN,
                self._quick_extract_images,
                "Export Images",
            ),
        ]

        card_controls = []
        for title, desc, icon, accent, on_click, btn_label in cards:
            card_controls.append(
                self._build_action_card(title, desc, icon, accent, on_click, btn_label, is_dark)
            )

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "⚡ Quick Action Presets",
                                    size=16,
                                    weight=ft.FontWeight.W_700,
                                    color=ThemeTokens.text_primary(is_dark),
                                ),
                                ft.Text(
                                    "Instant 1-click operations on the active document with zero configuration",
                                    size=12,
                                    color=ThemeTokens.text_secondary(is_dark),
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Container(expand=True),
                        make_badge("Operate Mode", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                ft.ResponsiveRow(
                    [
                        ft.Container(c, col={"sm": 12, "md": 6}) for c in card_controls
                    ],
                    spacing=12,
                    run_spacing=12,
                ),
                ft.Container(height=10),
                # Batch Automation Teaser Card
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.AUTO_AWESOME_MOTION_OUTLINED, color=ThemeTokens.ACCENT_PRIMARY, size=24),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Need to process multiple files simultaneously?",
                                        size=13,
                                        weight=ft.FontWeight.W_600,
                                        color=ThemeTokens.text_primary(is_dark),
                                    ),
                                    ft.Text(
                                        "Use Merge & Split or Batch Pipeline to queue hundreds of documents locally.",
                                        size=11,
                                        color=ThemeTokens.text_secondary(is_dark),
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.OutlinedButton(
                                "Open Merge & Split",
                                icon=ft.Icons.CALL_MERGE,
                                on_click=lambda e: self.navigate_callback("merge"),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=14,
                    border_radius=ThemeTokens.RADIUS_MD,
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                    bgcolor=ThemeTokens.bg_card(is_dark),
                ),
            ],
            spacing=12,
            expand=True,
        )

    def _build_action_card(
        self,
        title: str,
        desc: str,
        icon: str,
        accent: str,
        action_fn: Callable,
        btn_label: str,
        is_dark: bool,
    ) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(icon, size=20, color=accent),
                                bgcolor=ThemeTokens.bg_surface(is_dark),
                                border_radius=ThemeTokens.RADIUS_SM,
                                padding=8,
                            ),
                            ft.Text(
                                title,
                                size=14,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Text(
                        desc,
                        size=11,
                        color=ThemeTokens.text_secondary(is_dark),
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Container(expand=True),
                    ft.FilledButton(
                        btn_label,
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=action_fn,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM),
                        ),
                    ),
                ],
                spacing=8,
            ),
            padding=14,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
            height=150,
        )

    def _check_file(self) -> str | None:
        file_path = self.app_state.current_file
        if not file_path or not os.path.exists(file_path):
            show_snackbar(self.page, "Please select or drop a PDF file first", "warning")
            return None
        if not file_path.lower().endswith(".pdf"):
            show_snackbar(self.page, "Quick actions require a valid PDF file", "error")
            return None
        return file_path

    def _quick_pdf_to_word(self, e):
        file_path = self._check_file()
        if not file_path:
            return

        def work():
            try:
                update_progress(self.progress_bar, self.progress_text, 0.2, "Converting PDF to Word layout...")
                from pdf2docx import Converter
                output_name = generate_output_filename(file_path, "word", ".docx")
                out_path = os.path.join(self.output_dir, output_name)
                cv = Converter(file_path)
                cv.convert(out_path)
                cv.close()
                update_progress(self.progress_bar, self.progress_text, 1.0, "Word document generated successfully!")
                show_snackbar(
                    self.page,
                    f"Converted to {output_name}",
                    "success",
                    action="Open Folder",
                    on_action=lambda e: open_folder(self.output_dir),
                )
            except Exception as err:
                show_snackbar(self.page, f"Conversion failed: {err}", "error")
            finally:
                self.page.after(2.0, lambda: reset_progress(self.progress_bar, self.progress_text))

        run_background(self.page, work)

    def _quick_compress(self, e):
        file_path = self._check_file()
        if not file_path:
            return

        def work():
            try:
                update_progress(self.progress_bar, self.progress_text, 0.3, "Deflating font streams & compressing...")
                output_name = generate_output_filename(file_path, "compressed", ".pdf")
                out_path = os.path.join(self.output_dir, output_name)
                compress_pdf(file_path, out_path)
                orig_size = os.path.getsize(file_path)
                new_size = os.path.getsize(out_path)
                saved_pct = max(0, int((1 - (new_size / orig_size)) * 100))
                update_progress(self.progress_bar, self.progress_text, 1.0, f"Compressed! Reduced by {saved_pct}%")
                show_snackbar(
                    self.page,
                    f"Saved {saved_pct}%: {output_name}",
                    "success",
                    action="Open Folder",
                    on_action=lambda e: open_folder(self.output_dir),
                )
            except Exception as err:
                show_snackbar(self.page, f"Compression failed: {err}", "error")
            finally:
                self.page.after(2.0, lambda: reset_progress(self.progress_bar, self.progress_text))

        run_background(self.page, work)

    def _quick_extract_images(self, e):
        file_path = self._check_file()
        if not file_path:
            return

        def work():
            try:
                update_progress(self.progress_bar, self.progress_text, 0.3, "Rendering pages at 150 DPI...")
                exported = export_pdf_images(file_path, self.output_dir, dpi=150, image_format="png")
                update_progress(self.progress_bar, self.progress_text, 1.0, f"Exported {len(exported)} images")
                show_snackbar(
                    self.page,
                    f"Exported {len(exported)} page images to output folder",
                    "success",
                    action="Open Folder",
                    on_action=lambda e: open_folder(self.output_dir),
                )
            except Exception as err:
                show_snackbar(self.page, f"Export failed: {err}", "error")
            finally:
                self.page.after(2.0, lambda: reset_progress(self.progress_bar, self.progress_text))

        run_background(self.page, work)

    def _quick_encrypt_prompt(self, e):
        file_path = self._check_file()
        if not file_path:
            return

        # Modal dialog for password
        pwd_field = ft.TextField(
            label="Password",
            password=True,
            can_reveal_password=True,
            autofocus=True,
        )

        def on_confirm(dialog_e):
            pwd = pwd_field.value
            if not pwd:
                show_snackbar(self.page, "Password cannot be empty", "warning")
                return
            dialog.open = False
            self.page.update()

            def work():
                try:
                    update_progress(self.progress_bar, self.progress_text, 0.4, "Applying AES-256 encryption...")
                    from pdf_engine import encrypt_pdf
                    output_name = generate_output_filename(file_path, "encrypted", ".pdf")
                    out_path = os.path.join(self.output_dir, output_name)
                    encrypt_pdf(file_path, out_path, user_password=pwd)
                    update_progress(self.progress_bar, self.progress_text, 1.0, "Document encrypted successfully")
                    show_snackbar(
                        self.page,
                        f"Encrypted as {output_name}",
                        "success",
                        action="Open Folder",
                        on_action=lambda e: open_folder(self.output_dir),
                    )
                except Exception as err:
                    show_snackbar(self.page, f"Encryption failed: {err}", "error")
                finally:
                    self.page.after(2.0, lambda: reset_progress(self.progress_bar, self.progress_text))

            run_background(self.page, work)

        dialog = ft.AlertDialog(
            title=ft.Text("Quick AES-256 Encryption", size=14, weight=ft.FontWeight.W_600),
            content=ft.Column(
                [
                    ft.Text("Enter a passphrase to protect this PDF document:", size=12),
                    pwd_field,
                ],
                tight=True,
                spacing=10,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: setattr(dialog, "open", False) or self.page.update()),
                ft.FilledButton("Encrypt Document", on_click=on_confirm),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()
