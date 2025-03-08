import flet as ft
import os
import platform
from pathlib import Path
import fitz  # PyMuPDF
import shutil
import tempfile
from datetime import datetime
import time

def get_output_dir():
    """Get the output directory for saving processed files."""
    home = Path.home()
    output_dir = home / "Documents" / "PDF-OPS"
    os.makedirs(output_dir, exist_ok=True)
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

def show_snackbar(page, message, color="success"):
    """Show a snackbar notification."""
    color_map = {
        "success": ft.colors.GREEN_500,
        "error": ft.colors.RED_500,
        "info": ft.colors.BLUE_500,
        "warning": ft.colors.ORANGE_500,
    }
    
    page.snack_bar = ft.SnackBar(
        content=ft.Text(message),
        bgcolor=color_map.get(color, ft.colors.BLUE_500),
        action="Dismiss",
    )
    page.snack_bar.open = True
    page.update()

def create_pdf_preview(file_path, page, max_pages=5):
    """Create a preview of a PDF file."""
    if not file_path or not file_path.lower().endswith('.pdf'):
        return ft.Container(
            ft.Text("No PDF preview available"),
            alignment=ft.alignment.center,
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
                          style=ft.TextThemeStyle.TITLE_MEDIUM),
                    ft.Text(f"Pages: {pdf_document.page_count}", 
                          style=ft.TextThemeStyle.BODY_MEDIUM),
                ]),
                padding=10,
                border_radius=8,
                bgcolor=ft.colors.BLUE_50 if page.theme_mode == ft.ThemeMode.LIGHT else ft.colors.BLUE_900,
            )
        )
        
        # Add a note if we're not showing all pages
        if pages_to_show < pdf_document.page_count:
            pages_column.controls.append(
                ft.Text(f"Showing first {pages_to_show} of {pdf_document.page_count} pages",
                      style=ft.TextThemeStyle.BODY_SMALL, 
                      italic=True)
            )
        
        # Generate preview for each page
        for page_num in range(pages_to_show):
            # Get the page
            page_obj = pdf_document.load_page(page_num)
            
            # Render page to an image
            pix = page_obj.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
            
            # Save the image to a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                pix.save(temp_file.name)
                
                # Create an image control
                img = ft.Image(
                    src=temp_file.name,
                    width=400,
                    fit=ft.ImageFit.CONTAIN,
                )
                
                # Add the image to the column inside a container
                pages_column.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text(f"Page {page_num + 1}", style=ft.TextThemeStyle.BODY_SMALL),
                            img
                        ]),
                        padding=10,
                        border_radius=8,
                        border=ft.border.all(1, ft.colors.GREY_400),
                    )
                )
        
        # Close the PDF document
        pdf_document.close()
        
        return pages_column
        
    except Exception as e:
        return ft.Container(
            ft.Text(f"Error generating preview: {str(e)}"),
            alignment=ft.alignment.center,
            padding=20,
            bgcolor=ft.colors.RED_100 if page.theme_mode == ft.ThemeMode.LIGHT else ft.colors.RED_900,
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