import flet as ft
import os

from utils import get_output_dir, show_snackbar, create_pdf_preview
from convert import PDFConverter
from edit import PDFEditor
from merge import PDFMerger
from security import PDFSecurity
from app_state import AppState

class PDFOpsApp:
    def __init__(self):
        self.output_dir = get_output_dir()
        self.current_file = None
        self.current_files = []
        self.current_operation = None
        self.is_dark_theme = False
        self.state = AppState()

    def main(self, page: ft.Page):
        # App setup
        page.title = "PDF Ops"
        page.theme_mode = ft.ThemeMode.SYSTEM
        page.padding = 0
        page.window.width = 1100
        page.window.height = 800
        page.window.min_width = 450
        page.window.min_height = 600
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Theme toggle
        def toggle_theme(e):
            self.is_dark_theme = not self.is_dark_theme
            page.theme_mode = ft.ThemeMode.DARK if self.is_dark_theme else ft.ThemeMode.LIGHT
            theme_icon.icon = ft.Icons.LIGHT_MODE if self.is_dark_theme else ft.Icons.DARK_MODE
            page.update()
        
        theme_icon = ft.IconButton(
            icon=ft.Icons.DARK_MODE,
            icon_color=ft.Colors.BLUE_400,
            tooltip="Toggle theme",
            on_click=toggle_theme,
        )
        # File drag & drop area
        def on_file_drop(e: ft.FilePickerResultEvent):
            if e.files and e.files[0].path:
                self.current_file = e.files[0]
                self.state.select_file(self.current_file.path)
                file_name.value = f"File: {self.current_file.name}"
                file_drop_container.content.bgcolor = ft.Colors.BLUE_50 if not self.is_dark_theme else ft.Colors.BLUE_900
                file_drop_container.content.border = ft.Border.all(2, ft.Colors.BLUE_400)
                preview_container.content = create_pdf_preview(self.current_file.path, page)
                page.update()
                
        def on_file_drag_enter(e):
            file_drop_container.content.bgcolor = ft.Colors.BLUE_50 if not self.is_dark_theme else ft.Colors.BLUE_900
            file_drop_container.content.border = ft.Border.all(2, ft.Colors.BLUE_400)
            page.update()
            
        def on_file_drag_exit(e):
            file_drop_container.content.bgcolor = ft.Colors.WHITE if not self.is_dark_theme else ft.Colors.GREY_900
            file_drop_container.content.border = ft.Border.all(1, ft.Colors.GREY_400)
            page.update()
        
        file_picker = ft.FilePicker(on_result=on_file_drop)
        page.services.append(file_picker)
        
        file_name = ft.Text("Drag & drop a PDF file here or click to select", theme_style=ft.TextThemeStyle.BODY_MEDIUM)
        
        file_drop_container = ft.Container(
            content=ft.Container(
                ft.Column([
                    ft.Icon(ft.Icons.UPLOAD_FILE, size=60, color=ft.Colors.BLUE_400),
                    file_name,
                    ft.FilledButton(
                        "Select File",
                        icon=ft.Icons.FILE_OPEN,
                        action=ft.PickFiles(
                            file_picker,
                            file_type=ft.FilePickerFileType.CUSTOM,
                            allowed_extensions=["pdf", "docx", "xlsx", "pptx", "jpg", "jpeg", "png"],
                        ),
                    )
                ], 
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20),
                padding=50,
                border_radius=10,
                border=ft.Border.all(1, ft.Colors.GREY_400),
            ),
            padding=20,
            on_hover=lambda e: setattr(e.control, "scale", 1.01 if e.data == "true" else 1),
            animate_scale=ft.Animation(300, ft.AnimationCurve.FAST_OUT_SLOWIN),
        )
        # File Preview Container
        preview_container = ft.Container(
            content=ft.Container(
                ft.Text("File preview will appear here", theme_style=ft.TextThemeStyle.BODY_MEDIUM),
                alignment=ft.Alignment.CENTER,
                padding=20,
                border_radius=10,
                bgcolor=ft.Colors.WHITE if not self.is_dark_theme else ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_400),
            ),
            expand=True,
        )
        # Operation progress
        progress_bar = ft.ProgressBar(visible=False, width=600)
        progress_text = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL)
        
        # Setup operation tabs
        converter = PDFConverter(page, progress_bar, progress_text, self.output_dir)
        editor = PDFEditor(page, progress_bar, progress_text, self.output_dir)
        merger = PDFMerger(page, progress_bar, progress_text, self.output_dir)
        security = PDFSecurity(page, progress_bar, progress_text, self.output_dir)
        controllers = [converter, editor, merger, security]
        for controller in controllers:
            self.state.subscribe(controller.set_current_file)
        
        # Tabs for different operations
        tabs = ft.Tabs(
            length=4,
            selected_index=0,
            animation_duration=300,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=[
                        ft.Tab(
                    label="Convert",
                    icon=ft.Icons.SWAP_HORIZ,
                ),
                ft.Tab(
                    label="Edit", 
                    icon=ft.Icons.EDIT_NOTE,
                ),
                ft.Tab(
                    label="Merge & Split",
                    icon=ft.Icons.MERGE_TYPE,
                ),
                ft.Tab(
                    label="Security",
                    icon=ft.Icons.SECURITY,
                ),
                    ]),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            converter.build_ui(),
                            editor.build_ui(),
                            merger.build_ui(),
                            security.build_ui(),
                        ],
                    ),
                ],
            ),
            expand=1,
        )
        
        # Main layout
        page.appbar = ft.AppBar(
            title=ft.Text("PDF Operations", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            center_title=False,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            actions=[theme_icon],
        )
        page.add(
            ft.Row(
                [
                    # Left panel (operations)
                    ft.Container(
                        content=ft.Column(
                            [
                                tabs,
                            ],
                            spacing=15,
                            expand=True,
                        ),
                        padding=20,
                        expand=3,
                    ),
                    ft.VerticalDivider(),
                    # Right panel (file upload & preview)
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("File Upload & Preview", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                                ft.Divider(),
                                file_drop_container,
                                preview_container,
                            ],
                            spacing=15,
                            expand=True,
                        ),
                        padding=20,
                        expand=2,
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            ft.Column(
                [
                    progress_bar,
                    progress_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                visible=False,
            ),
        )

if __name__ == "__main__":
    app = PDFOpsApp()
    # Flet 1.x replaced ``ft.app()`` with ``ft.run()``. ``FLET_APP`` is
    # still the default view, so it does not need to be specified here.
    ft.run(app.main)
