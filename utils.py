import flet as ft
import os
import platform
from pathlib import Path
import pymupdf as fitz
import shutil
from datetime import datetime
import time


def run_background(page, operation):
    """Run a blocking operation through Flet's page-managed worker executor."""
    def guarded_operation():
        try:
            operation()
        except Exception as error:
            show_snackbar(page, f"Unexpected background error: {error}", "error")

    page.run_thread(guarded_operation)

def get_output_dir():
    """Get the output directory for saving processed files."""
    home = Path.home()
    output_dir = home / "Documents" / "PDF-OPS"
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError:
        pass
    return str(output_dir)

def generate_output_filename(input_filename, operation, extension=None):
    """Generate an output filename with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Get the base name without extension
    base_name = os.path.splitext(os.path.basename(input_filename))[0]
    
    # Use the provided extension or keep the original
    if not extension:
        extension = os.path.splitext(input_filename)[1]
    
    # Make sure extension starts with a dot
    if not extension.startswith('.'):
        extension = f".{extension}"
        
    return f"{base_name}_{operation}_{timestamp}{extension}"

def open_folder(folder_path: str):
    """Open folder in OS default file manager safely."""
    try:
        if platform.system() == "Windows":
            os.startfile(folder_path)
        elif platform.system() == "Darwin":
            import subprocess
            subprocess.Popen(["open", folder_path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder_path])
    except Exception as e:
        print(f"Could not open folder {folder_path}: {e}")

def show_snackbar(page, message, color="success", action="Dismiss", on_action=None):
    """Show a snackbar notification."""
    color_map = {
        "success": ft.Colors.GREEN_600,
        "error": ft.Colors.RED_600,
        "info": ft.Colors.BLUE_600,
        "warning": ft.Colors.ORANGE_600,
    }
    
    page.snack_bar = ft.SnackBar(
        content=ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.W_500),
        bgcolor=color_map.get(color, ft.Colors.BLUE_600),
        action=action,
        on_action=on_action,
    )
    page.snack_bar.open = True
    page.update()

def create_pdf_preview(file_path, page, max_pages=5):
    """Create a preview of a PDF file."""
    if not file_path or not file_path.lower().endswith('.pdf'):
        return ft.Container(
            ft.Text("No PDF preview available"),
            alignment=ft.Alignment.CENTER,
            padding=20
        )
    
    try:
        # Open the PDF file
        pdf_document = fitz.open(file_path)
        
        # Create a column for the PDF pages
        pages_column = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10)
        
        # Limit the number of pages to preview
        pages_to_show = min(max_pages, pdf_document.page_count)
        
        # Add information about the PDF
        pages_column.controls.append(
            ft.Container(
                ft.Column([
                    ft.Text(f"Document: {os.path.basename(file_path)}", 
                          theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                    ft.Text(f"Pages: {pdf_document.page_count}", 
                          theme_style=ft.TextThemeStyle.BODY_MEDIUM),
                ]),
                padding=10,
                border_radius=8,
                bgcolor=ft.Colors.BLUE_50 if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.BLUE_900,
            )
        )
        
        # Add a note if we're not showing all pages
        if pages_to_show < pdf_document.page_count:
            pages_column.controls.append(
                ft.Text(f"Showing first {pages_to_show} of {pdf_document.page_count} pages",
                      theme_style=ft.TextThemeStyle.BODY_SMALL, 
                      italic=True)
            )
        
        # Generate preview for each page
        for page_num in range(pages_to_show):
            # Get the page
            page_obj = pdf_document.load_page(page_num)
            
            # Render page to an image
            pix = page_obj.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
            
            img = ft.Image(
                src=pix.tobytes("png"),
                width=400,
                fit=ft.BoxFit.CONTAIN,
            )
            pages_column.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(f"Page {page_num + 1}", theme_style=ft.TextThemeStyle.BODY_SMALL),
                        img,
                    ]),
                    padding=10,
                    border_radius=8,
                    border=ft.Border.all(1, ft.Colors.GREY_400),
                )
            )
        
        # Close the PDF document
        pdf_document.close()
        
        return pages_column
        
    except Exception as e:
        return ft.Container(
            ft.Text(f"Error generating preview: {str(e)}"),
            alignment=ft.Alignment.CENTER,
            padding=20,
            bgcolor=ft.Colors.RED_100 if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.RED_900,
            border_radius=8,
        )

def update_progress(progress_bar, progress_text, value, text=""):
    """Update the progress bar and text."""
    progress_bar.value = value
    progress_text.value = text
    
    # Make sure progress controls are visible
    if not progress_bar.visible:
        progress_bar.visible = True
        progress_bar.parent.visible = True
    
    # Update the progress bar and text
    progress_bar.update()
    progress_text.update()

def reset_progress(progress_bar, progress_text):
    """Reset the progress bar and hide it."""
    progress_bar.value = 0
    progress_text.value = ""
    progress_bar.visible = False
    progress_bar.parent.visible = False
    progress_bar.update()
    progress_text.update()

def simulate_progress(progress_bar, progress_text, operation_name, callback=None):
    """Simulate progress for operations that don't report progress."""
    update_progress(progress_bar, progress_text, 0.1, f"{operation_name} starting...")
    
    for i in range(1, 10):
        time.sleep(0.2)  # Simulate processing time
        update_progress(progress_bar, progress_text, i/10, f"{operation_name} in progress...")
    
    update_progress(progress_bar, progress_text, 1, f"{operation_name} completing...")
    
    if callback:
        callback()
    
    reset_progress(progress_bar, progress_text)
