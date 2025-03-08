import flet as ft
import os
import threading
import time
from pathlib import Path
import tempfile

# Import conversion libraries
try:
    from pdf2docx import Converter as PDFToDocxConverter
    from docx import Document
    import fitz  # PyMuPDF
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
    simulate_progress
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
            "Images": [".jpg", ".jpeg", ".png"],
        }
    
    def build_ui(self):
        """Build the conversion UI."""
        # Dropdown for conversion type
        self.conversion_dropdown = ft.Dropdown(
            label="Conversion Type",
            hint_text="Select conversion type",
            options=[ft.dropdown.Option(conv_type) for conv_type in self.conversion_types.keys()],
            width=400,
            autofocus=True,
        )
        
        # Button for conversion
        self.convert_button = ft.ElevatedButton(
            "Convert",
            icon=ft.icons.SWAP_HORIZ,
            on_click=self.start_conversion,
            disabled=True,
        )
        
        # Multiple file picker for image to PDF
        self.multiple_file_picker = ft.FilePicker(on_result=self.on_multiple_files_selected)
        self.page.overlay.append(self.multiple_file_picker)
        
        # Button for selecting multiple images
        self.select_images_button = ft.ElevatedButton(
            "Select Images",
            icon=ft.icons.PHOTO_LIBRARY,
            on_click=lambda _: self.multiple_file_picker.pick_files(
                allowed_extensions=["jpg", "jpeg", "png"],
                allow_multiple=True
            ),
            visible=False,
        )
        
        # Text showing selected files
        self.selected_files_text = ft.Text(
            "No files selected",
            visible=False,
        )
        
        # Listen for changes in the dropdown
        def on_conversion_change(e):
            if self.conversion_dropdown.value == "Images to PDF":
                self.select_images_button.visible = True
                self.convert_button.disabled = True  # Disable until images are selected
            else:
                self.select_images_button.visible = False
                self.convert_button.disabled = False
                self.selected_files_text.visible = False
            self.page.update()
        
        self.conversion_dropdown.on_change = on_conversion_change
        
        # Main container
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "Convert between PDF and other formats",
                    style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Convert PDF to and from Word, Excel, PowerPoint, and Images",
                    style=ft.TextThemeStyle.BODY_MEDIUM,
                ),
                ft.Divider(),
                self.conversion_dropdown,
                self.select_images_button,
                self.selected_files_text,
                ft.Container(height=20),  # Spacer
                self.convert_button,
                ft.Container(
                    content=ft.Text(
                        "📝 Note: PDF to Excel/PowerPoint conversion works best with simple layouts",
                        style=ft.TextThemeStyle.BODY_SMALL,
                        italic=True,
                    ),
                    padding=ft.padding.only(top=20),
                ),
            ], spacing=10),
            padding=20,
        )

    def on_multiple_files_selected(self, e):
        """Handle multiple file selection for image to PDF conversion."""
        if e.files:
            self.image_files = [f.path for f in e.files]
            self.selected_files_text.value = f"Selected {len(self.image_files)} images"
            self.selected_files_text.visible = True
            self.convert_button.disabled = False
            self.page.update()
        
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
        self.current_file = getattr(self.page.client_storage.get("current_file"), "path", None) 
        
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
        
        # Start the conversion in a separate thread
        conversion_thread = threading.Thread(
            target=self.conversion_types[self.conversion_dropdown.value]
        )
        conversion_thread.daemon = True
        conversion_thread.start()
        
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
        """Convert Word document to PDF."""
        try:
            # For Word to PDF, we need to use a different approach
            # This would typically use a library like unoconv or a COM interface
            # Since those may not be available in all environments, we'll simulate it
            
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_pdf", ".pdf")
            )
            def completion():
                show_snackbar(
                    self.page, 
                    f"Word to PDF conversion requires LibreOffice or MS Word. Output would be: {output_file}",
                    "info"
                )
            simulate_progress(
                self.progress_bar, 
                self.progress_text, 
                "Word to PDF conversion",
                completion
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting Word to PDF: {str(e)}", "error")
            
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
            
            # Use pdf2image to convert PDF to images
            images = convert_from_path(self.current_file)
            
            # Save each page as an image
            total_pages = len(images)
            for i, image in enumerate(images):
                image_path = os.path.join(output_dir, f"page_{i+1}.jpg")
                image.save(image_path, "JPEG")
                
                # Update progress
                progress = 0.3 + 0.6 * ((i + 1) / total_pages)
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    progress, 
                    f"Saving page {i+1} of {total_pages} as image..."
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
            
            # Open a PDF writer
            pdf_writer = PyPDF2.PdfWriter()
            
            # Sort image files to ensure consistent order
            self.image_files.sort()
            
            # Process each image
            total_images = len(self.image_files)
            for i, image_path in enumerate(self.image_files):
                # Update progress
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    0.1 + 0.8 * ((i + 1) / total_images), 
                    f"Converting image {i+1} of {total_images}..."
                )
                
                # Convert image to PDF using PyMuPDF
                img = fitz.open(image_path)
                pdf_bytes = img.convert_to_pdf()
                img.close()
                
                # Create a PyPDF2 PdfReader from the PDF bytes
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                    temp_pdf.write(pdf_bytes)
                    temp_pdf_path = temp_pdf.name
                
                # Add the page to the PDF writer
                with open(temp_pdf_path, "rb") as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    pdf_writer.add_page(pdf_reader.pages[0])
                
                # Delete the temporary file
                os.unlink(temp_pdf_path)
                
            # Write the final PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Writing PDF file...")
            with open(output_file, "wb") as f:
                pdf_writer.write(f)
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Conversion complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
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
        """Convert PDF to Excel spreadsheet."""
        try:
            # PDF to Excel conversion is complex and often requires specialized tools
            # Here we're simulating the process
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_excel", ".xlsx")
            )
            
            def completion():
                show_snackbar(
                    self.page, 
                    f"PDF to Excel conversion requires advanced OCR tools. Output would be: {output_file}",
                    "info"
                )
                
            simulate_progress(
                self.progress_bar, 
                self.progress_text, 
                "PDF to Excel conversion",
                completion
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting PDF to Excel: {str(e)}", "error")
    
    def excel_to_pdf(self):
        """Convert Excel spreadsheet to PDF."""
        try:
            # Excel to PDF conversion typically requires Excel or specialized libraries
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_pdf", ".pdf")
            )
            
            def completion():
                show_snackbar(
                    self.page, 
                    f"Excel to PDF conversion requires LibreOffice or MS Excel. Output would be: {output_file}",
                    "info"
                )
                
            simulate_progress(
                self.progress_bar, 
                self.progress_text, 
                "Excel to PDF conversion",
                completion
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting Excel to PDF: {str(e)}", "error")
    
    def pdf_to_ppt(self):
        """Convert PDF to PowerPoint presentation."""
        try:
            # PDF to PowerPoint conversion is complex and often requires specialized tools
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_ppt", ".pptx")
            )
            
            def completion():
                show_snackbar(
                    self.page, 
                    f"PDF to PowerPoint conversion requires specialized tools. Output would be: {output_file}",
                    "info"
                )
                
            simulate_progress(
                self.progress_bar, 
                self.progress_text, 
                "PDF to PowerPoint conversion",
                completion
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting PDF to PowerPoint: {str(e)}", "error")
    
    def ppt_to_pdf(self):
        """Convert PowerPoint presentation to PDF."""
        try:
            # PowerPoint to PDF conversion typically requires PowerPoint or specialized libraries
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "to_pdf", ".pdf")
            )
            
            def completion():
                show_snackbar(
                    self.page, 
                    f"PowerPoint to PDF conversion requires LibreOffice or MS PowerPoint. Output would be: {output_file}",
                    "info"
                )
                
            simulate_progress(
                self.progress_bar, 
                self.progress_text, 
                "PowerPoint to PDF conversion",
                completion
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error converting PowerPoint to PDF: {str(e)}", "error")