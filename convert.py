import flet as ft
import os
import time
from pathlib import Path
import tempfile
import sys

from pdf_engine import convert_images_to_pdf, convert_office_to_pdf, export_pdf_images, find_office_converter

# Import conversion libraries
try:
    import pymupdf as fitz
    # pdf2docx still imports PyMuPDF through its legacy ``fitz`` module name.
    # Provide the current module before importing it to avoid that deprecated
    # compatibility package (and its warning).
    sys.modules.setdefault("fitz", fitz)
    from pdf2docx import Converter as PDFToDocxConverter
    from docx import Document
    from PIL import Image
    import PyPDF2
    from pdf2image import convert_from_path
    # For Excel conversion
    import openpyxl
    # For PowerPoint conversion
    from pptx import Presentation
    
    LIBRARIES_LOADED = True
except ImportError as e:
    print(f"Warning: Some conversion libraries could not be imported: {e}")
    LIBRARIES_LOADED = False

# Import utilities
from utils import (
    generate_output_filename, 
    show_snackbar, 
    update_progress, 
    reset_progress,
    simulate_progress,
    run_background,
)

class PDFConverter:
    """Handles conversion between PDF and other formats."""
    
    def __init__(self, page, progress_bar, progress_text, output_dir):
        self.page = page
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.output_dir = output_dir
        self.current_file = None
        
        # Conversion options
        self.conversion_types = {
            "PDF to Word": self.pdf_to_word,
            "Word to PDF": self.word_to_pdf,
            "PDF to Images": self.pdf_to_images,
            "Images to PDF": self.images_to_pdf,
            "PDF to Excel": self.pdf_to_excel,
            "Excel to PDF": self.excel_to_pdf,
            "PDF to PowerPoint": self.pdf_to_ppt,
            "PowerPoint to PDF": self.ppt_to_pdf,
        }
        
        # File extensions for different formats
        self.format_extensions = {
            "PDF": ".pdf",
            "Word": ".docx",
            "Excel": ".xlsx",
            "PowerPoint": ".pptx",
            "Images": [".jpg", ".jpeg", ".png", ".webp"],
        }
        self.image_files = []

    def _allowed_conversions_for_file(self, file_path: str | None) -> list[str]:
        """Return conversion types compatible with the active file's extension."""
        if not file_path:
            return list(self.conversion_types.keys())

        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return ["PDF to Word", "PDF to Images", "PDF to Excel", "PDF to PowerPoint"]
        if ext in (".docx", ".doc"):
            return ["Word to PDF"]
        if ext in (".xlsx", ".xls"):
            return ["Excel to PDF"]
        if ext in (".pptx", ".ppt"):
            return ["PowerPoint to PDF"]
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            return ["Images to PDF"]
        return []

    def _set_status_banner(self, message: str | None, level: str = "info") -> None:
        """Show or hide an inline status/capability notice in the Convert workspace."""
        if not hasattr(self, "status_banner"):
            return
        if not message:
            self.status_banner.visible = False
            self.status_banner.content = None
            return

        color_map = {
            "info": ft.Colors.BLUE_400,
            "warning": ft.Colors.AMBER_400,
            "error": ft.Colors.RED_400,
            "success": ft.Colors.GREEN_400,
        }
        icon_map = {
            "info": ft.Icons.INFO_OUTLINE,
            "warning": ft.Icons.WARNING_AMBER_ROUNDED,
            "error": ft.Icons.ERROR_OUTLINE,
            "success": ft.Icons.CHECK_CIRCLE_OUTLINE,
        }
        accent = color_map.get(level, ft.Colors.BLUE_400)
        self.status_banner.content = ft.Row(
            [
                ft.Icon(icon_map.get(level, ft.Icons.INFO_OUTLINE), size=18, color=accent),
                ft.Text(message, size=12, expand=True),
            ],
            spacing=8,
        )
        self.status_banner.border = ft.Border.all(1, accent)
        self.status_banner.visible = True

    def _sync_conversion_state(self, update_page: bool = True) -> None:
        """Filter dropdown options, toggle option controls, and validate readiness."""
        if not hasattr(self, "conversion_dropdown"):
            return

        allowed = self._allowed_conversions_for_file(self.current_file)
        self.conversion_dropdown.options = [
            ft.dropdown.Option(conv_type) for conv_type in allowed
        ]

        if not allowed:
            self.conversion_dropdown.value = None
        elif self.conversion_dropdown.value not in allowed:
            self.conversion_dropdown.value = allowed[0]

        selected = self.conversion_dropdown.value

        # If an image file is loaded as active document, pre-seed image_files for Images to PDF
        if self.current_file and Path(self.current_file).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            if self.current_file not in self.image_files:
                self.image_files = [self.current_file]

        is_images_to_pdf = selected == "Images to PDF"
        is_pdf_to_images = selected == "PDF to Images"

        self.select_images_button.visible = is_images_to_pdf
        self.image_dpi.visible = is_pdf_to_images
        self.image_format.visible = is_pdf_to_images

        if is_images_to_pdf and self.image_files:
            self.selected_files_text.value = f"Selected {len(self.image_files)} image(s)"
            self.selected_files_text.visible = True
        else:
            self.selected_files_text.visible = False

        # Determine whether the selected conversion can actually run
        if not LIBRARIES_LOADED:
            self.convert_button.disabled = True
            self._set_status_banner(
                "Conversion libraries failed to load. Please reinstall requirements and restart.",
                "error",
            )
        elif self.current_file and not allowed:
            ext = Path(self.current_file).suffix or "unknown"
            self.convert_button.disabled = True
            self._set_status_banner(
                f"No conversions are supported for '{ext}' files.",
                "warning",
            )
        elif not selected:
            self.convert_button.disabled = True
            self._set_status_banner("Select a conversion type to continue.", "info")
        elif selected == "PDF to PowerPoint":
            self.convert_button.disabled = True
            self._set_status_banner(
                "PDF to PowerPoint conversion is not supported locally yet. Choose PDF to Word, PDF to Images, or PDF to Excel instead.",
                "warning",
            )
        elif selected in ("Word to PDF", "Excel to PDF", "PowerPoint to PDF") and not find_office_converter():
            self.convert_button.disabled = True
            self._set_status_banner(
                f"{selected} requires LibreOffice (soffice) on PATH, which was not detected on this system.",
                "warning",
            )
        elif is_images_to_pdf:
            has_images = bool(self.image_files)
            self.convert_button.disabled = not has_images
            self._set_status_banner(
                None if has_images else "Click 'Select Images' to choose one or more image files to combine into a PDF.",
                "info",
            )
        elif not self.current_file or not os.path.exists(self.current_file):
            self.convert_button.disabled = True
            self._set_status_banner(
                "Select a document above (Ctrl+O) to run this conversion.",
                "info",
            )
        else:
            self.convert_button.disabled = False
            self._set_status_banner(None)

        if update_page:
            try:
                if self.page:
                    self.page.update()
            except Exception:
                pass

    def _on_conversion_change(self, e):
        """Handle conversion dropdown selection in Flet 1.x."""
        self._sync_conversion_state(update_page=True)
    
    def build_ui(self):
        """Build the conversion UI."""
        # Dropdown for conversion type
        self.conversion_dropdown = ft.Dropdown(
            label="Conversion Type",
            hint_text="Select conversion type",
            options=[ft.dropdown.Option(conv_type) for conv_type in self.conversion_types.keys()],
            width=400,
            autofocus=True,
            on_select=self._on_conversion_change,
        )

        self.image_dpi = ft.Dropdown(
            label="Image DPI",
            options=[ft.dropdown.Option(str(value)) for value in (72, 150, 300)],
            value="150",
            width=190,
            visible=False,
        )
        self.image_format = ft.Dropdown(
            label="Image format",
            options=[ft.dropdown.Option(value.upper()) for value in ("png", "jpeg", "webp")],
            value="PNG",
            width=190,
            visible=False,
        )
        
        # Button for conversion
        self.convert_button = ft.Button(
            "Convert",
            icon=ft.Icons.SWAP_HORIZ,
            on_click=self.start_conversion,
            disabled=True,
        )
        
        # Multiple file picker for image to PDF
        self.multiple_file_picker = ft.FilePicker(on_result=self.on_multiple_files_selected)
        self.page.services.append(self.multiple_file_picker)
        
        # Button for selecting multiple images
        self.select_images_button = ft.Button(
            "Select Images",
            icon=ft.Icons.PHOTO_LIBRARY,
            action=ft.PickFiles(
                self.multiple_file_picker,
                dialog_title="Select Images — PDF-Ops",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp"],
                allow_multiple=True,
            ),
            visible=False,
        )
        
        # Text showing selected files
        self.selected_files_text = ft.Text(
            "No files selected",
            visible=False,
        )

        # Inline capability / warning notice
        self.status_banner = ft.Container(
            visible=False,
            padding=10,
            border_radius=8,
            width=520,
        )

        self._sync_conversion_state(update_page=False)
        
        # Main container
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "Convert between PDF and other formats",
                    theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Convert PDF to and from Word, Excel, PowerPoint, and Images",
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM,
                ),
                ft.Divider(),
                self.conversion_dropdown,
                self.status_banner,
                ft.Row([self.image_dpi, self.image_format]),
                self.select_images_button,
                self.selected_files_text,
                ft.Container(height=20),  # Spacer
                self.convert_button,
                ft.Container(
                    content=ft.Text(
                        "📝 Note: PDF to Excel works best with structured tables; Office-to-PDF uses local LibreOffice.",
                        theme_style=ft.TextThemeStyle.BODY_SMALL,
                        italic=True,
                    ),
                    padding=ft.Padding.only(top=20),
                ),
            ], spacing=10),
            padding=20,
        )

    def on_multiple_files_selected(self, e):
        """Handle multiple file selection for image to PDF conversion."""
        if e.files:
            self.image_files = [f.path for f in e.files if f.path]
            self._sync_conversion_state(update_page=True)
        
    def start_conversion(self, e):
        """Start the conversion process in a separate thread."""
        if not LIBRARIES_LOADED:
            show_snackbar(self.page, 
                          "Error: Required libraries are missing. Please install them and restart the app.",
                          "error")
            return
            
        if not self.conversion_dropdown.value:
            show_snackbar(self.page, "Please select a conversion type", "warning")
            return
            
        # Get current file from app
        # Check if we have a file (except for Images to PDF which uses multiple files)
        if self.conversion_dropdown.value != "Images to PDF" and not self.current_file:
            show_snackbar(self.page, "Please select a file first", "warning")
            return
            
        # Check for correct input file format
        if self.conversion_dropdown.value != "Images to PDF":
            input_format = self.conversion_dropdown.value.split(" to ")[0]
            if input_format == "PDF" and not self.current_file.lower().endswith(".pdf"):
                show_snackbar(self.page, "Please select a PDF file", "warning")
                return
            elif input_format == "Word" and not self.current_file.lower().endswith((".docx", ".doc")):
                show_snackbar(self.page, "Please select a Word file", "warning")
                return
            elif input_format == "Excel" and not self.current_file.lower().endswith((".xlsx", ".xls")):
                show_snackbar(self.page, "Please select an Excel file", "warning")
                return
            elif input_format == "PowerPoint" and not self.current_file.lower().endswith((".pptx", ".ppt")):
                show_snackbar(self.page, "Please select a PowerPoint file", "warning")
                return
        
        run_background(self.page, self.conversion_types[self.conversion_dropdown.value])

    def set_current_file(self, file_path):
        """Receive the active file selection from the application shell."""
        self.current_file = file_path or None
        self.image_files = []
        self._sync_conversion_state(update_page=True)
        
    def pdf_to_word(self):
        """Convert PDF to Word document."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF to Word conversion...")
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_word", ".docx")
            )
            
            # Convert PDF to Word
            update_progress(self.progress_bar, self.progress_text, 0.3, "Converting PDF to Word...")
            converter = PDFToDocxConverter(self.current_file)
            converter.convert(output_file)
            converter.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Conversion complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"PDF successfully converted to Word: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting PDF to Word: {str(e)}", "error")
            
    def word_to_pdf(self):
        self._office_to_pdf("Word")
            
    def pdf_to_images(self):
        """Convert PDF to a series of images."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF to Images conversion...")
            
            # Create directory for images
            base_name = os.path.splitext(os.path.basename(self.current_file))[0]
            output_dir = os.path.join(self.output_dir, f"{base_name}_images")
            os.makedirs(output_dir, exist_ok=True)
            
            # Convert PDF to images
            update_progress(self.progress_bar, self.progress_text, 0.3, "Converting PDF pages to images...")
            
            dpi = int(self.image_dpi.value)
            image_format = self.image_format.value.lower()
            image_paths = export_pdf_images(self.current_file, output_dir, dpi, image_format)
            total_pages = len(image_paths)
            for i, _ in enumerate(image_paths):
                progress = 0.3 + 0.6 * ((i + 1) / total_pages)
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    progress, 
                    f"Rendering page {i+1} of {total_pages} at {dpi} DPI..."
                )
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Conversion complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(
                self.page, 
                f"PDF successfully converted to {total_pages} images in: {output_dir}", 
                "success"
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting PDF to images: {str(e)}", "error")
            
    def images_to_pdf(self):
        """Convert a series of images to a PDF."""
        try:
            if not hasattr(self, 'image_files') or not self.image_files:
                show_snackbar(self.page, "Please select images first", "warning")
                return
                
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting Images to PDF conversion...")
            
            # Create output filename
            output_file = os.path.join(
                self.output_dir, 
                f"images_to_pdf_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
            )
            
            # Convert images directly to PDF
            total_images = len(self.image_files)
            update_progress(self.progress_bar, self.progress_text, 0.4, f"Converting {total_images} images to PDF...")
            convert_images_to_pdf(self.image_files, output_file)
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Conversion complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(
                self.page, 
                f"{total_images} images successfully converted to PDF: {output_file}", 
                "success"
            )
            
            # Clear selected images
            self.image_files = []
            self.selected_files_text.value = "No files selected"
            self.page.update()
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting images to PDF: {str(e)}", "error")
    
    def pdf_to_excel(self):
        """Extract detected PDF tables into individual Excel worksheets."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Detecting tables in PDF...")
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_excel", ".xlsx")
            )
            workbook = openpyxl.Workbook()
            workbook.remove(workbook.active)
            table_count = 0
            with fitz.open(self.current_file) as document:
                for page_number, page in enumerate(document, start=1):
                    tables = page.find_tables().tables
                    for table_number, table in enumerate(tables, start=1):
                        worksheet = workbook.create_sheet(f"Page {page_number} Table {table_number}")
                        for row in table.extract():
                            worksheet.append([cell or "" for cell in row])
                        table_count += 1
                    update_progress(
                        self.progress_bar,
                        self.progress_text,
                        0.1 + (0.8 * page_number / document.page_count),
                        f"Scanning page {page_number} of {document.page_count}...",
                    )
            if not table_count:
                raise ValueError("No extractable tables were found in this PDF")
            workbook.save(output_file)
            update_progress(self.progress_bar, self.progress_text, 1.0, "Excel export complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Extracted {table_count} table(s): {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting PDF to Excel: {str(e)}", "error")
    
    def excel_to_pdf(self):
        self._office_to_pdf("Excel")
    
    def pdf_to_ppt(self):
        """Report that this conversion requires a dedicated external engine."""
        show_snackbar(self.page, "PDF to PowerPoint is not available locally yet; no placeholder file was created.", "info")
    
    def ppt_to_pdf(self):
        self._office_to_pdf("PowerPoint")

    def _office_to_pdf(self, source_kind):
        """Convert Office files through an installed local LibreOffice binary."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, f"Starting {source_kind} to PDF conversion...")
            output = convert_office_to_pdf(self.current_file, self.output_dir)
            update_progress(self.progress_bar, self.progress_text, 1.0, "Conversion complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"{source_kind} successfully converted to PDF: {output}", "success")
        except Exception as error:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"{source_kind} to PDF unavailable: {error}", "warning")
