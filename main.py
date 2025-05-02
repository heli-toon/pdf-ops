import flet as ft
import os

from utils import get_output_dir, show_snackbar, create_pdf_preview
from convert import PDFConverter
from edit import PDFEditor
from merge import PDFMerger
from security import PDFSecurity

class PDFOpsApp:
    def __init__(self):
        self.output_dir = get_output_dir()
        self.current_file = None
        self.current_files = []
        self.current_operation = None
        self.is_dark_theme = False

    def main(self, page: ft.Page):
        # App setup
        page.title = "PDF Ops"
        page.theme_mode = ft.ThemeMode.SYSTEM
        page.padding = 0
        page.window_width = 1100
        page.window_height = 800
        page.window_min_width = 450
        page.window_min_height = 600
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Theme toggle
        def toggle_theme(e):
            self.is_dark_theme = not self.is_dark_theme
            page.theme_mode = ft.ThemeMode.DARK if self.is_dark_theme else ft.ThemeMode.LIGHT
            theme_icon.icon = ft.icons.LIGHT_MODE if self.is_dark_theme else ft.icons.DARK_MODE
            page.update()
        
        theme_icon = ft.IconButton(
            icon=ft.icons.DARK_MODE,
            icon_color=ft.colors.BLUE_400,
            tooltip="Toggle theme",
            on_click=toggle_theme,
        )
        # File drag & drop area
        def on_file_drop(e: ft.FilePickerResultEvent):
            if e.files:
                self.current_file = e.files[0]
                file_name.value = f"File: {self.current_file.name}"
                file_drop_container.content.bgcolor = ft.colors.BLUE_50 if not self.is_dark_theme else ft.colors.BLUE_900
                file_drop_container.content.border = ft.border.all(2, ft.colors.BLUE_400)
                preview_container.content = create_pdf_preview(self.current_file.path, page)
                page.update()
                
        def on_file_drag_enter(e):
            file_drop_container.content.bgcolor = ft.colors.BLUE_50 if not self.is_dark_theme else ft.colors.BLUE_900
            file_drop_container.content.border = ft.border.all(2, ft.colors.BLUE_400)
            page.update()
            
        def on_file_drag_exit(e):
            file_drop_container.content.bgcolor = ft.colors.WHITE if not self.is_dark_theme else ft.colors.GREY_900
            file_drop_container.content.border = ft.border.all(1, ft.colors.GREY_400)
            page.update()
        
        file_picker = ft.FilePicker(on_result=on_file_drop)
        page.overlay.append(file_picker)
        
        file_name = ft.Text("Drag & drop a PDF file here or click to select", style=ft.TextThemeStyle.BODY_MEDIUM)
        
        def pick_files(e):
            file_picker.pick_files(
                allowed_extensions=["pdf", "docx", "xlsx", "pptx", "jpg", "jpeg", "png"],
                allow_multiple=False
            )
        file_drop_container = ft.Container(
            content=ft.Container(
                ft.Column([
                    ft.Icon(ft.icons.UPLOAD_FILE, size=60, color=ft.colors.BLUE_400),
                    file_name,
                    ft.FilledButton(
                        "Select File",
                        icon=ft.icons.FILE_OPEN,
                        on_click=pick_files
                    )
                ], 
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20),
                padding=50,
                border_radius=10,
                border=ft.border.all(1, ft.colors.GREY_400),
            ),
            padding=20,
            on_hover=lambda e: setattr(e.control, "scale", 1.01 if e.data == "true" else 1),
            animate_scale=ft.animation.Animation(300, ft.AnimationCurve.FAST_OUT_SLOWIN),
        )
        # File Preview Container
        preview_container = ft.Container(
            content=ft.Container(
                ft.Text("File preview will appear here", style=ft.TextThemeStyle.BODY_MEDIUM),
                alignment=ft.alignment.center,
                padding=20,
                border_radius=10,
                bgcolor=ft.colors.WHITE if not self.is_dark_theme else ft.colors.GREY_900,
                border=ft.border.all(1, ft.colors.GREY_400),
            ),
            expand=True,
        )
        # Operation progress
        progress_bar = ft.ProgressBar(visible=False, width=600)
        progress_text = ft.Text("", style=ft.TextThemeStyle.BODY_SMALL)
        
        # Setup operation tabs
        converter = PDFConverter(page, progress_bar, progress_text, self.output_dir)
        editor = PDFEditor(page, progress_bar, progress_text, self.output_dir)
        merger = PDFMerger(page, progress_bar, progress_text, self.output_dir)
        security = PDFSecurity(page, progress_bar, progress_text, self.output_dir)
        
        # Tabs for different operations
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(
                    text="Convert",
                    icon=ft.icons.SWAP_HORIZ,
                    content=converter.build_ui(),
                ),
                ft.Tab(
                    text="Edit", 
                    icon=ft.icons.EDIT_NOTE,
                    content=editor.build_ui(),
                ),
                ft.Tab(
                    text="Merge & Split",
                    icon=ft.icons.MERGE_TYPE,
                    content=merger.build_ui(),
                ),
                ft.Tab(
                    text="Security",
                    icon=ft.icons.SECURITY,
                    content=security.build_ui(),
                ),
            ],
            expand=1,
        )
        
        # Main layout
        page.add(
            ft.AppBar(
                title=ft.Text("PDF Operations", style=ft.TextThemeStyle.HEADLINE_MEDIUM),
                center_title=False,
                bgcolor=ft.colors.SURFACE_VARIANT,
                actions=[theme_icon],
            ),
            ft.Row(
                [
                    # Left panel (operations)
                    ft.Container(
                        content=ft.Column(
                            [
                                tabs,
                            ],
                            spacing=15,
                        ),
                        padding=20,
                        expand=3,
                    ),
                    ft.VerticalDivider(),
                    # Right panel (file upload & preview)
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("File Upload & Preview", style=ft.TextThemeStyle.TITLE_LARGE),
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
    ft.app(target=app.main, view=ft.FLET_APP)