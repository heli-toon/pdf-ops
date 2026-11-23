"""PDF-Ops — Production-Grade Offline Privacy-First PDF Studio.

Phase 3: Impeccable UI/UX Redesign in Operate Mode.
- Adaptive 3-Pane Rail Architecture (Desktop) to Single-Column / Bottom-Nav (Mobile)
- High-Density Neutral Slate Palette (Dark & Light)
- Tool-First Action Wizard with Reactive File State
- Contextual Document Inspector with In-Memory Thumbnail Reel
- Native Keyboard Accelerators (Ctrl+O, Ctrl+D, Escape)
"""

import os
from pathlib import Path
import flet as ft

from app_state import AppState
from convert import PDFConverter
from edit import PDFEditor
from merge import PDFMerger
from security import PDFSecurity
from theme import ThemeTokens, make_badge, padding_only, padding_symmetric
from ui_inspector import DocumentInspector
from ui_organizer import PageOrganizerView
from ui_quick_actions import QuickActionsView
from ui_stubs import OfflineOCRPreview
from utils import get_output_dir, open_folder, show_snackbar


class PDFOpsApp:
    """Master application shell implementing the Phase 3 Impeccable redesign."""

    def __init__(self):
        self.output_dir = get_output_dir()
        self.state = AppState()
        self.is_dark_theme = True  # Default to Slate Dark Mode per Operate specifications
        self.active_tool_id = "quick"
        self.show_inspector = True
        self.is_compact = False

        # Operation progress indicators
        self.progress_bar = ft.ProgressBar(visible=False, height=4, color=ThemeTokens.ACCENT_PRIMARY)
        self.progress_text = ft.Text("", size=11)

        # Build Navigation Items
        self.nav_destinations = [
            ("quick", "Quick Actions", ft.Icons.BOLT, "1-click high-frequency workflows"),
            ("convert", "Convert Studio", ft.Icons.SWAP_HORIZ, "Word, Images, Excel, PPT"),
            ("edit", "Edit & Stamp", ft.Icons.EDIT_NOTE, "Watermarks, Rotations, Crops"),
            ("merge", "Merge & Split", ft.Icons.CALL_MERGE, "Reorder, Ranges, Chapters, Compress"),
            ("security", "Security", ft.Icons.SECURITY, "AES-256 Encryption & Permissions"),
            ("organizer", "Page Manager", ft.Icons.GRID_VIEW, "Visual page reorder, rotate & extract"),
            ("ocr", "Offline OCR", ft.Icons.DOCUMENT_SCANNER, "100% on-device text recognition"),
        ]

    def main(self, page: ft.Page):
        self.page = page
        page.title = "PDF-Ops — Offline Privacy Studio"
        page.theme_mode = ft.ThemeMode.DARK if self.is_dark_theme else ft.ThemeMode.LIGHT
        page.padding = 0
        page.spacing = 0
        page.window.width = 1200
        page.window.height = 840
        page.window.min_width = 480
        page.window.min_height = 620

        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError:
            pass

        # File Picker setup
        def on_file_selected(e: ft.FilePickerResultEvent):
            if e.files and e.files[0].path:
                selected_path = e.files[0].path
                self.state.select_file(selected_path)
                self.update_file_dropzone()
                show_snackbar(page, f"Loaded: {os.path.basename(selected_path)}", "info")

        self.file_picker = ft.FilePicker(on_result=on_file_selected)
        page.services.append(self.file_picker)

        # Module controllers
        self.converter = PDFConverter(page, self.progress_bar, self.progress_text, self.output_dir)
        self.editor = PDFEditor(page, self.progress_bar, self.progress_text, self.output_dir)
        self.merger = PDFMerger(page, self.progress_bar, self.progress_text, self.output_dir)
        self.security = PDFSecurity(page, self.progress_bar, self.progress_text, self.output_dir)

        # Subscribe controllers to central AppState
        controllers = [self.converter, self.editor, self.merger, self.security]
        for ctrl in controllers:
            self.state.subscribe(ctrl.set_current_file)

        # Specialized Views
        self.quick_actions = QuickActionsView(
            page=page,
            app_state=self.state,
            output_dir=self.output_dir,
            progress_bar=self.progress_bar,
            progress_text=self.progress_text,
            is_dark_supplier=lambda: self.is_dark_theme,
            navigate_callback=self.switch_tool,
        )
        self.page_organizer = PageOrganizerView(
            page=page,
            app_state=self.state,
            output_dir=self.output_dir,
            progress_bar=self.progress_bar,
            progress_text=self.progress_text,
            is_dark_supplier=lambda: self.is_dark_theme,
        )
        self.ocr_view = OfflineOCRPreview(page, self.state, lambda: self.is_dark_theme)

        # Contextual Inspector (Pane 3)
        self.inspector = DocumentInspector(page, lambda: self.is_dark_theme)
        self.state.subscribe(self.inspector.set_file)
        self.state.subscribe(self.page_organizer.set_current_file)

        # Build Navigation Items
        self.nav_destinations = [
            ("quick", "Quick Actions", ft.Icons.BOLT, "1-click high-frequency workflows"),
            ("convert", "Convert Studio", ft.Icons.SWAP_HORIZ, "Word, Images, Excel, PPT"),
            ("edit", "Edit & Stamp", ft.Icons.EDIT_NOTE, "Watermarks, Rotations, Crops"),
            ("merge", "Merge & Split", ft.Icons.CALL_MERGE, "Reorder, Ranges, Chapters, Compress"),
            ("security", "Security", ft.Icons.SECURITY, "AES-256 Encryption & Permissions"),
            ("organizer", "Page Manager", ft.Icons.GRID_VIEW, "Visual page reorder, rotate & extract"),
            ("ocr", "Offline OCR", ft.Icons.DOCUMENT_SCANNER, "100% on-device text recognition"),
        ]

        # Setup Containers
        self.nav_rail_container = ft.Container(width=220, padding=12)
        self.stage_content_container = ft.Container(expand=True, padding=16)
        self.inspector_container = ft.Container(width=300, padding=12)
        self.file_dropzone_container = ft.Container(padding=padding_symmetric(horizontal=16, vertical=10))

        # Keyboard shortcuts
        def handle_keyboard(e: ft.KeyboardEvent):
            if e.ctrl or e.meta:
                if e.key.lower() == "o":
                    self.trigger_file_browser()
                elif e.key.lower() == "d":
                    self.toggle_theme(None)
            elif e.key == "Escape":
                if self.state.current_file:
                    self.state.select_file("")
                    self.update_file_dropzone()
                    show_snackbar(page, "Cleared active file selection", "info")

        page.on_keyboard_event = handle_keyboard

        # Responsive window resize listener
        def handle_resize(e):
            width = page.width or 1200
            new_is_compact = width < 780
            if new_is_compact != self.is_compact:
                self.is_compact = new_is_compact
                self.render_layout()

        page.on_resize = handle_resize

        # Initial layout rendering
        self.render_layout()

    def trigger_file_browser(self):
        """Open native file dialog."""
        self.file_picker.pick_files(
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["pdf", "docx", "xlsx", "pptx", "png", "jpg", "jpeg", "webp"],
            allow_multiple=False,
        )

    def toggle_theme(self, e):
        """Toggle between Slate Dark and Crisp Paper Light themes."""
        self.is_dark_theme = not self.is_dark_theme
        self.page.theme_mode = ft.ThemeMode.DARK if self.is_dark_theme else ft.ThemeMode.LIGHT
        self.inspector.refresh()
        self.render_layout()

    def switch_tool(self, tool_id: str):
        """Switch active primary workspace tool."""
        self.active_tool_id = tool_id
        self.render_stage_content()
        self.render_nav_rail()
        self.page.update()

    def update_file_dropzone(self):
        """Re-render the file dropzone based on active file selection."""
        is_dark = self.is_dark_theme
        current_file = self.state.current_file

        if not current_file or not os.path.exists(current_file):
            content = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CLOUD_UPLOAD_OUTLINED, size=28, color=ThemeTokens.ACCENT_PRIMARY),
                        ft.Column(
                            [
                                ft.Text(
                                    "Drop PDF here or click Browse",
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    color=ThemeTokens.text_primary(is_dark),
                                ),
                                ft.Text(
                                    "Supports PDF, Word, Excel, Images (Ctrl+O)",
                                    size=10,
                                    color=ThemeTokens.text_muted(is_dark),
                                ),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.FilledButton(
                            "Select File",
                            icon=ft.Icons.FILE_OPEN,
                            on_click=lambda e: self.trigger_file_browser(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=12,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.ACCENT_PRIMARY if is_dark else ThemeTokens.border_muted(is_dark)),
                bgcolor=ThemeTokens.bg_card(is_dark),
            )
        else:
            base_name = os.path.basename(current_file)
            size_mb = os.path.getsize(current_file) / (1024 * 1024)
            content = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=22, color=ThemeTokens.ACCENT_SUCCESS),
                        ft.Column(
                            [
                                ft.Text(
                                    base_name,
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    color=ThemeTokens.text_primary(is_dark),
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    f"Active Document • {size_mb:.2f} MB",
                                    size=10,
                                    color=ThemeTokens.text_secondary(is_dark),
                                ),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.OutlinedButton(
                            "Change",
                            icon=ft.Icons.SYNC,
                            on_click=lambda e: self.trigger_file_browser(),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=10,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.ACCENT_SUCCESS),
                bgcolor=ThemeTokens.bg_card(is_dark),
            )

        self.file_dropzone_container.content = content
        try:
            if self.file_dropzone_container.page:
                self.file_dropzone_container.update()
        except Exception:
            pass

    def render_nav_rail(self):
        """Render left navigation rail destinations and output footer."""
        is_dark = self.is_dark_theme
        dest_controls = []

        for tid, title, icon, subtitle in self.nav_destinations:
            is_active = self.active_tool_id == tid
            bg_col = ThemeTokens.ACCENT_PRIMARY if is_active else "transparent"
            text_col = ft.Colors.WHITE if is_active else ThemeTokens.text_primary(is_dark)
            icon_col = ft.Colors.WHITE if is_active else (ThemeTokens.ACCENT_PRIMARY if not is_active else ThemeTokens.text_secondary(is_dark))

            dest_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(icon, size=18, color=icon_col),
                            ft.Text(title, size=12, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500, color=text_col),
                        ],
                        spacing=10,
                    ),
                    padding=padding_symmetric(horizontal=12, vertical=10),
                    border_radius=ThemeTokens.RADIUS_SM,
                    bgcolor=bg_col,
                    on_click=lambda e, target_id=tid: self.switch_tool(target_id),
                )
            )

        self.nav_rail_container.content = ft.Column(
            [
                # App Branding Pill
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PICTURE_AS_PDF, size=24, color=ThemeTokens.ACCENT_PRIMARY),
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text("PDF-Ops", size=15, weight=ft.FontWeight.W_800, color=ThemeTokens.text_primary(is_dark)),
                                        make_badge("v1.0", ThemeTokens.bg_card(is_dark), ThemeTokens.ACCENT_PRIMARY),
                                    ],
                                    spacing=4,
                                ),
                                ft.Text("Privacy PDF Studio", size=10, color=ThemeTokens.text_muted(is_dark)),
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                # Navigation items
                ft.Column(dest_controls, spacing=4, expand=True),
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                # Output Directory shortcut
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.FOLDER_OUTLINED, size=14, color=ThemeTokens.text_muted(is_dark)),
                                    ft.Text("Output Folder", size=10, weight=ft.FontWeight.W_600, color=ThemeTokens.text_muted(is_dark)),
                                    ft.Container(expand=True),
                                    ft.IconButton(
                                        ft.Icons.OPEN_IN_NEW,
                                        icon_size=14,
                                        tooltip="Open in File Manager",
                                        on_click=lambda e: open_folder(self.output_dir),
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(
                                os.path.basename(self.output_dir) or "PDF-OPS",
                                size=11,
                                color=ThemeTokens.text_secondary(is_dark),
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=2,
                    ),
                    padding=8,
                    border_radius=ThemeTokens.RADIUS_SM,
                    bgcolor=ThemeTokens.bg_card(is_dark),
                ),
                # Privacy Status Badge
                ft.Row(
                    [
                        ft.Icon(ft.Icons.LOCK, size=12, color=ThemeTokens.ACCENT_SUCCESS),
                        ft.Text("100% Offline Processing", size=10, color=ThemeTokens.ACCENT_SUCCESS, weight=ft.FontWeight.W_600),
                    ],
                    spacing=4,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=10,
            expand=True,
        )
        self.nav_rail_container.bgcolor = ThemeTokens.bg_surface(is_dark)
        self.nav_rail_container.border = ft.Border.only(right=ft.BorderSide(1, ThemeTokens.border(is_dark)))

    def render_stage_content(self):
        """Render the primary action stage depending on active tool."""
        is_dark = self.is_dark_theme
        tool_view_map = {
            "quick": self.quick_actions.build_ui,
            "convert": self.converter.build_ui,
            "edit": self.editor.build_ui,
            "merge": self.merger.build_ui,
            "security": self.security.build_ui,
            "organizer": self.page_organizer.build_ui,
            "ocr": self.ocr_view.build_ui,
        }

        active_builder = tool_view_map.get(self.active_tool_id, self.quick_actions.build_ui)
        content_control = active_builder()

        self.stage_content_container.content = ft.Column(
            [
                content_control,
                # Progress Bar
                ft.Container(
                    content=ft.Column(
                        [
                            self.progress_bar,
                            self.progress_text,
                        ],
                        spacing=4,
                    ),
                    padding=padding_only(top=8),
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self.stage_content_container.bgcolor = ThemeTokens.bg_app(is_dark)

    def render_layout(self):
        """Construct the top-level view hierarchy (Adaptive Desktop vs Mobile)."""
        is_dark = self.is_dark_theme
        self.render_nav_rail()
        self.update_file_dropzone()
        self.render_stage_content()

        # Update Inspector container styling
        self.inspector_container.bgcolor = ThemeTokens.bg_surface(is_dark)
        self.inspector_container.border = ft.Border.only(left=ft.BorderSide(1, ThemeTokens.border(is_dark)))
        self.inspector_container.content = self.inspector.container

        # Top App Bar
        theme_icon = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE if self.is_dark_theme else ft.Icons.DARK_MODE,
            icon_color=ThemeTokens.ACCENT_PRIMARY,
            tooltip=f"Switch to {'Light' if self.is_dark_theme else 'Dark'} Theme (Ctrl+D)",
            on_click=self.toggle_theme,
        )

        app_bar = ft.AppBar(
            title=ft.Row(
                [
                    ft.Text("PDF-Ops", size=18, weight=ft.FontWeight.W_800),
                    make_badge("Operate", ThemeTokens.bg_card(is_dark), ThemeTokens.ACCENT_PRIMARY),
                ],
                spacing=8,
            ),
            bgcolor=ThemeTokens.bg_surface(is_dark),
            actions=[
                ft.IconButton(
                    icon=ft.Icons.FOLDER_OUTLINED,
                    tooltip="Open Output Directory",
                    on_click=lambda e: open_folder(self.output_dir),
                ),
                theme_icon,
                ft.IconButton(
                    icon=ft.Icons.INFO_OUTLINE,
                    tooltip="About PDF-Ops & Master Roadmap",
                    on_click=lambda e: self.show_about_dialog(),
                ),
            ],
        )
        self.page.appbar = app_bar

        self.page.clean()

        if self.is_compact:
            # Android / Mobile 1-Column Responsive View
            bottom_bar_items = [
                ft.NavigationBarDestination(icon=ft.Icons.BOLT, label="Quick"),
                ft.NavigationBarDestination(icon=ft.Icons.SWAP_HORIZ, label="Convert"),
                ft.NavigationBarDestination(icon=ft.Icons.EDIT_NOTE, label="Edit"),
                ft.NavigationBarDestination(icon=ft.Icons.CALL_MERGE, label="Merge"),
                ft.NavigationBarDestination(icon=ft.Icons.SECURITY, label="Security"),
            ]

            def on_nav_change(e):
                idx = e.control.selected_index
                targets = ["quick", "convert", "edit", "merge", "security"]
                if idx < len(targets):
                    self.switch_tool(targets[idx])

            self.page.navigation_bar = ft.NavigationBar(
                destinations=bottom_bar_items,
                on_change=on_nav_change,
                bgcolor=ThemeTokens.bg_surface(is_dark),
            )

            self.page.add(
                ft.Column(
                    [
                        self.file_dropzone_container,
                        self.stage_content_container,
                    ],
                    expand=True,
                    spacing=0,
                )
            )
        else:
            # Desktop 3-Pane Adaptive Rail View
            self.page.navigation_bar = None
            self.page.add(
                ft.Row(
                    [
                        self.nav_rail_container,
                        ft.Container(
                            content=ft.Column(
                                [
                                    self.file_dropzone_container,
                                    self.stage_content_container,
                                ],
                                spacing=0,
                                expand=True,
                            ),
                            expand=True,
                        ),
                        self.inspector_container,
                    ],
                    spacing=0,
                    expand=True,
                )
            )

        self.page.update()

    def show_about_dialog(self):
        """Display about & master roadmap dialog."""
        is_dark = self.is_dark_theme
        dialog = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ThemeTokens.ACCENT_PRIMARY),
                    ft.Text("About PDF-Ops", weight=ft.FontWeight.W_700),
                ],
                spacing=8,
            ),
            content=ft.Column(
                [
                    ft.Text(
                        "PDF-Ops is an offline, privacy-first PDF utility suite engineered for maximum task efficiency.",
                        size=12,
                    ),
                    ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                    ft.Text("Architecture Highlights:", size=12, weight=ft.FontWeight.W_600),
                    ft.Text("• Core Engine: PyMuPDF (fitz) + pypdf + Pillow", size=11),
                    ft.Text("• UI Framework: Flet 1.1+ (Flutter Engine)", size=11),
                    ft.Text("• Phase 3 Redesign: Impeccable Operate Mode", size=11),
                    ft.Text("• Privacy Guarantee: 100% On-Device, zero telemetry", size=11),
                    ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                    ft.Text("Keyboard Accelerators:", size=12, weight=ft.FontWeight.W_600),
                    ft.Text("• Ctrl+O: Open / Select Document", size=11),
                    ft.Text("• Ctrl+D: Toggle Dark / Light Slate Palette", size=11),
                    ft.Text("• Escape: Deselect / Clear Active Document", size=11),
                ],
                tight=True,
                spacing=6,
            ),
            actions=[
                ft.FilledButton("Close", on_click=lambda e: setattr(dialog, "open", False) or self.page.update())
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()


if __name__ == "__main__":
    app = PDFOpsApp()
    ft.run(app.main)
