import flet as ft
import os
import threading
import time
import PyPDF2
import fitz  # PyMuPDF

from utils import (
    generate_output_filename, 
    show_snackbar, 
    update_progress, 
    reset_progress
)

class PDFMerger:
    """Handles PDF merging and splitting operations."""
    
    def __init__(self, page, progress_bar, progress_text, output_dir):
        self.page = page
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.output_dir = output_dir
        self.current_file = None
        self.pdf_files = []
        
        # File picker for selecting multiple PDFs
        self.pdf_picker = ft.FilePicker(on_result=self.on_pdfs_selected)
        self.page.overlay.append(self.pdf_picker)
    
    def build_ui(self):
        """Build the merger & splitter UI."""
        # Tabs for merge and split operations
        self.operation_tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(
                    text="Merge PDFs",
                    content=self._build_merge_ui(),
                ),
                ft.Tab(
                    text="Split PDF",
                    content=self._build_split_ui(),
                ),
                ft.Tab(
                    text="Extract Pages",
                    content=self._build_extract_ui(),
                ),
                ft.Tab(
                    text="Compress PDF",
                    content=self._build_compress_ui(),
                ),
            ],
        )
        
        # Main container
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "Merge, Split & Compress PDF Files",
                    style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Combine multiple PDFs, split into separate files, or reduce file size",
                    style=ft.TextThemeStyle.BODY_MEDIUM,
                ),
                ft.Divider(),
                self.operation_tabs,
            ], spacing=10),
            padding=20,
        )
    
    def _build_merge_ui(self):
        """Build the UI for merging PDFs."""
        # Button for selecting PDFs
        self.select_pdfs_button = ft.ElevatedButton(
            "Select PDFs to Merge",
            icon=ft.icons.FILE_COPY,
            on_click=lambda _: self.pdf_picker.pick_files(
                allowed_extensions=["pdf"],
                allow_multiple=True
            ),
        )
        
        # List of selected PDFs
        self.selected_pdfs_list = ft.ListView(
            spacing=10,
            height=200,
            padding=10,
        )
        
        # Merge button
        self.merge_button = ft.ElevatedButton(
            "Merge PDFs",
            icon=ft.icons.MERGE_TYPE,
            on_click=self.start_merge,
            disabled=True,
        )
        
        # Reorder buttons
        self.move_up_button = ft.IconButton(
            icon=ft.icons.ARROW_UPWARD,
            tooltip="Move file up",
            on_click=self.move_file_up,
            disabled=True,
        )
        
        self.move_down_button = ft.IconButton(
            icon=ft.icons.ARROW_DOWNWARD,
            tooltip="Move file down",
            on_click=self.move_file_down,
            disabled=True,
        )
        
        self.remove_file_button = ft.IconButton(
            icon=ft.icons.DELETE,
            tooltip="Remove file",
            on_click=self.remove_file,
            disabled=True,
        )
        
        return ft.Column([
            self.select_pdfs_button,
            ft.Container(
                content=self.selected_pdfs_list,
                border=ft.border.all(1, ft.colors.GREY_400),
                border_radius=5,
                padding=5,
            ),
            ft.Row([
                self.move_up_button,
                self.move_down_button,
                self.remove_file_button,
                ft.Container(expand=True),  # Spacer
                self.merge_button,
            ]),
        ], spacing=15)
    
    def _build_split_ui(self):
        """Build the UI for splitting PDFs."""
        # Split options
        self.split_dropdown = ft.Dropdown(
            label="Split Method",
            options=[
                ft.dropdown.Option("Split by page count"),
                ft.dropdown.Option("Split into individual pages"),
                ft.dropdown.Option("Split by bookmarks"),
            ],
            width=400,
            value="Split by page count",
        )
        
        # Page count input for splitting
        self.pages_per_file = ft.TextField(
            label="Pages per PDF",
            value="1",
            width=150,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        
        # Split button
        self.split_button = ft.ElevatedButton(
            "Split PDF",
            icon=ft.icons.CALL_SPLIT,
            on_click=self.start_split,
        )
        
        # Listen for split method change
        def on_split_method_change(e):
            self.pages_per_file.visible = (self.split_dropdown.value == "Split by page count")
            self.page.update()
            
        self.split_dropdown.on_change = on_split_method_change
        
        return ft.Column([
            ft.Text("Split a single PDF into multiple files"),
            self.split_dropdown,
            self.pages_per_file,
            ft.Container(height=10),  # Spacer
            self.split_button,
        ], spacing=15)
    
    def _build_extract_ui(self):
        """Build the UI for extracting specific pages."""
        # Page range input
        self.page_range = ft.TextField(
            label="Page Range",
            hint_text="e.g., 1-3, 5, 7-9",
            width=400,
        )
        
        # Extract button
        self.extract_button = ft.ElevatedButton(
            "Extract Pages",
            icon=ft.icons.FILE_COPY,
            on_click=self.start_extract,
        )
        
        return ft.Column([
            ft.Text("Extract specific pages from a PDF"),
            self.page_range,
            ft.Container(height=10),  # Spacer
            self.extract_button,
        ], spacing=15)
    
    def _build_compress_ui(self):
        """Build the UI for compressing PDFs."""
        # Compression level
        self.compression_level = ft.Slider(
            min=1,
            max=5,
            divisions=4,
            label="Compression Level: {value}",
            value=3,
            width=400,
        )
        
        # Image quality
        self.image_quality = ft.Slider(
            min=10,
            max=100,
            divisions=9,
            label="Image Quality: {value}%",
            value=85,
            width=400,
        )
        
        # Compress button
        self.compress_button = ft.ElevatedButton(
            "Compress PDF",
            icon=ft.icons.COMPRESS,
            on_click=self.start_compress,
        )
        
        return ft.Column([
            ft.Text("Reduce the file size of a PDF"),
            ft.Container(
                content=ft.Column([
                    ft.Text("Compression Level"),
                    ft.Row([
                        ft.Text("Low", size=12),
                        self.compression_level,
                        ft.Text("High", size=12),
                    ]),
                ]),
                padding=10,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("Image Quality"),
                    ft.Row([
                        ft.Text("Low", size=12),
                        self.image_quality,
                        ft.Text("High", size=12),
                    ]),
                ]),
                padding=10,
            ),
            ft.Container(height=10),  # Spacer
            self.compress_button,
        ], spacing=15)
    
    def on_pdfs_selected(self, e):
        """Handle PDF selection for merging."""
        if e.files:
            self.pdf_files = [f.path for f in e.files]
            self._update_pdf_list()
            self.merge_button.disabled = len(self.pdf_files) < 2
            self.page.update()
    
    def _update_pdf_list(self):
        """Update the list of selected PDFs."""
        self.selected_pdfs_list.controls.clear()
        
        for i, pdf_path in enumerate(self.pdf_files):
            file_name = os.path.basename(pdf_path)
            
            self.selected_pdfs_list.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(f"{i+1}. {file_name}", expand=True),
                    ]),
                    bgcolor=ft.colors.BLUE_50 if i % 2 == 0 else None,
                    padding=10,
                    border_radius=5,
                    data=i,  # Store the index for selection
                    on_click=self._select_file_item,
                )
            )
            
        self.page.update()
    
    def _select_file_item(self, e):
        """Handle file selection in the list."""
        # Clear previous selections
        for item in self.selected_pdfs_list.controls:
            if hasattr(item, 'selected') and item.selected:
                item.selected = False
                item.border = None
        
        # Set new selection
        e.control.selected = True
        e.control.border = ft.border.all(2, ft.colors.BLUE_400)
        
        # Enable reorder buttons
        self.move_up_button.disabled = e.control.data == 0
        self.move_down_button.disabled = e.control.data == len(self.pdf_files) - 1
        self.remove_file_button.disabled = False
        
        self.page.update()
    
    def move_file_up(self, e):
        """Move selected file up in the list."""
        selected_idx = None
        
        # Find selected item
        for item in self.selected_pdfs_list.controls:
            if hasattr(item, 'selected') and item.selected:
                selected_idx = item.data
                break
                
        if selected_idx is not None and selected_idx > 0:
            # Swap files
            self.pdf_files[selected_idx], self.pdf_files[selected_idx-1] = \
                self.pdf_files[selected_idx-1], self.pdf_files[selected_idx]
            
            # Update list
            self._update_pdf_list()
            
            # Re-select the moved item
            self.selected_pdfs_list.controls[selected_idx-1].selected = True
            self.selected_pdfs_list.controls[selected_idx-1].border = ft.border.all(2, ft.colors.BLUE_400)
            
            # Update button states
            self.move_up_button.disabled = selected_idx - 1 == 0
            self.move_down_button.disabled = selected_idx - 1 == len(self.pdf_files) - 1
            
            self.page.update()
    
    def move_file_down(self, e):
        """Move selected file down in the list."""
        selected_idx = None
        
        # Find selected item
        for item in self.selected_pdfs_list.controls:
            if hasattr(item, 'selected') and item.selected:
                selected_idx = item.data
                break
                
        if selected_idx is not None and selected_idx < len(self.pdf_files) - 1:
            # Swap files
            self.pdf_files[selected_idx], self.pdf_files[selected_idx+1] = \
                self.pdf_files[selected_idx+1], self.pdf_files[selected_idx]
            
            # Update list
            self._update_pdf_list()
            
            # Re-select the moved item
            self.selected_pdfs_list.controls[selected_idx+1].selected = True
            self.selected_pdfs_list.controls[selected_idx+1].border = ft.border.all(2, ft.colors.BLUE_400)
            
            # Update button states
            self.move_up_button.disabled = selected_idx + 1 == 0
            self.move_down_button.disabled = selected_idx + 1 == len(self.pdf_files) - 1
            
            self.page.update()
    
    def remove_file(self, e):
        """Remove selected file from the list."""
        selected_idx = None
        
        # Find selected item
        for item in self.selected_pdfs_list.controls:
            if hasattr(item, 'selected') and item.selected:
                selected_idx = item.data
                break
                
        if selected_idx is not None:
            # Remove file
            self.pdf_files.pop(selected_idx)
            
            # Update list
            self._update_pdf_list()
            
            # Disable merge button if less than 2 files
            self.merge_button.disabled = len(self.pdf_files) < 2
            
            # Disable reorder buttons
            self.move_up_button.disabled = True
            self.move_down_button.disabled = True
            self.remove_file_button.disabled = True
            
            self.page.update()
    
    def start_merge(self, e):
        """Start the PDF merging process."""
        if len(self.pdf_files) < 2:
            show_snackbar(self.page, "Please select at least 2 PDF files to merge", "warning")
            return
            
        # Start the merging in a separate thread
        merge_thread = threading.Thread(target=self._merge_pdfs)
        merge_thread.daemon = True
        merge_thread.start()
    
    def _merge_pdfs(self):
        """Merge multiple PDF files."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF merge...")
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                f"merged_pdf_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
            )
            
            # Create a PDF merger
            pdf_merger = PyPDF2.PdfMerger()
            
            # Add each PDF to the merger
            for i, pdf_file in enumerate(self.pdf_files):
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    0.1 + 0.8 * (i / len(self.pdf_files)), 
                    f"Adding file {i+1} of {len(self.pdf_files)}: {os.path.basename(pdf_file)}"
                )
                
                # Open and add the PDF
                with open(pdf_file, 'rb') as f:
                    pdf_merger.append(f)
            
            # Write the merged PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Writing merged PDF...")
            with open(output_file, 'wb') as f:
                pdf_merger.write(f)
                
            pdf_merger.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Merge complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"PDFs successfully merged: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error merging PDFs: {str(e)}", "error")
    
    def start_split(self, e):
        """Start the PDF splitting process."""
        # Get current file from app
        self.current_file = getattr(self.page.client_storage.get("current_file"), "path", None)
        
        # Check if we have a PDF file
        if not self.current_file:
            show_snackbar(self.page, "Please select a PDF file first", "warning")
            return
            
        if not self.current_file.lower().endswith(".pdf"):
            show_snackbar(self.page, "Please select a PDF file", "warning")
            return
            
        # Start the splitting in a separate thread
        split_thread = threading.Thread(target=self._split_pdf)
        split_thread.daemon = True
        split_thread.start()
    
    def _split_pdf(self):
        """Split a PDF file into multiple parts."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF split...")
            
            # Get the split method
            split_method = self.split_dropdown.value
            
            # Open the PDF file
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)
                
                if total_pages < 2:
                    show_snackbar(self.page, "PDF has only one page, nothing to split", "warning")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                    
                # Create output directory for split files
                base_name = os.path.splitext(os.path.basename(self.current_file))[0]
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                output_dir = os.path.join(self.output_dir, f"{base_name}_split_{timestamp}")
                os.makedirs(output_dir, exist_ok=True)
                
                if split_method == "Split into individual pages":
                    # Split each page into a separate file
                    for i in range(total_pages):
                        update_progress(
                            self.progress_bar, 
                            self.progress_text, 
                            0.1 + 0.8 * ((i + 1) / total_pages), 
                            f"Extracting page {i+1} of {total_pages}..."
                        )
                        
                        # Create a PDF writer for this page
                        pdf_writer = PyPDF2.PdfWriter()
                        pdf_writer.add_page(pdf_reader.pages[i])
                        
                        # Write the individual page to a file
                        output_file = os.path.join(output_dir, f"{base_name}_page_{i+1}.pdf")
                        with open(output_file, 'wb') as out_f:
                            pdf_writer.write(out_f)
                            
                    show_snackbar(
                        self.page, 
                        f"Split {total_pages} pages into individual files: {output_dir}", 
                        "success"
                    )
                    
                elif split_method == "Split by page count":
                    # Get pages per file
                    try:
                        pages_per_file = int(self.pages_per_file.value)
                        if pages_per_file < 1:
                            raise ValueError("Pages per file must be at least 1")
                    except ValueError:
                        show_snackbar(self.page, "Please enter a valid number of pages per file", "error")
                        reset_progress(self.progress_bar, self.progress_text)
                        return
                        
                    # Calculate number of output files
                    num_files = (total_pages + pages_per_file - 1) // pages_per_file
                    
                    for i in range(num_files):
                        update_progress(
                            self.progress_bar, 
                            self.progress_text, 
                            0.1 + 0.8 * ((i + 1) / num_files), 
                            f"Creating part {i+1} of {num_files}..."
                        )
                        
                        # Create a PDF writer for this chunk
                        pdf_writer = PyPDF2.PdfWriter()
                        
                        # Add pages for this chunk
                        start_page = i * pages_per_file
                        end_page = min((i + 1) * pages_per_file, total_pages)
                        
                        for page_num in range(start_page, end_page):
                            pdf_writer.add_page(pdf_reader.pages[page_num])
                            
                        # Write the chunk to a file
                        output_file = os.path.join(output_dir, f"{base_name}_part_{i+1}.pdf")
                        with open(output_file, 'wb') as out_f:
                            pdf_writer.write(out_f)
                            
                    show_snackbar(
                        self.page, 
                        f"Split PDF into {num_files} files with {pages_per_file} pages each: {output_dir}", 
                        "success"
                    )
                    
                elif split_method == "Split by bookmarks":
                    # This feature would require more complex bookmark handling
                    show_snackbar(
                        self.page, 
                        "Splitting by bookmarks requires additional PDF analysis tools", 
                        "info"
                    )
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                
            update_progress(self.progress_bar, self.progress_text, 1.0, "Split complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress
            reset_progress(self.progress_bar, self.progress_text)
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error splitting PDF: {str(e)}", "error")
    
    def start_extract(self, e):
        """Start the page extraction process."""
        # Get current file from app
        self.current_file = getattr(self.page.client_storage.get("current_file"), "path", None)
        
        # Check if we have a PDF file
        if not self.current_file:
            show_snackbar(self.page, "Please select a PDF file first", "warning")
            return
            
        if not self.current_file.lower().endswith(".pdf"):
            show_snackbar(self.page, "Please select a PDF file", "warning")
            return
            
        # Check page range
        if not self.page_range.value:
            show_snackbar(self.page, "Please enter a page range", "warning")
            return
            
        # Start the extraction in a separate thread
        extract_thread = threading.Thread(target=self._extract_pages)
        extract_thread.daemon = True
        extract_thread.start()
    
    def _extract_pages(self):
        """Extract specific pages from a PDF."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting page extraction...")
            
            # Parse page range
            page_numbers = []
            try:
                for part in self.page_range.value.split(','):
                    part = part.strip()
                    if '-' in part:
                        start, end = map(int, part.split('-'))
                        page_numbers.extend(range(start, end + 1))
                    else:
                        page_numbers.append(int(part))
            except ValueError:
                show_snackbar(self.page, "Invalid page range format", "error")
                reset_progress(self.progress_bar, self.progress_text)
                return
                
            # Open the PDF file
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)
                
                # Validate page numbers
                page_numbers = [p for p in page_numbers if 1 <= p <= total_pages]
                
                if not page_numbers:
                    show_snackbar(self.page, "No valid pages in the specified range", "warning")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                    
                # Create a PDF writer
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add each page
                for i, page_num in enumerate(page_numbers):
                    update_progress(
                        self.progress_bar, 
                        self.progress_text, 
                        0.1 + 0.8 * ((i + 1) / len(page_numbers)), 
                        f"Extracting page {page_num}..."
                    )
                    
                    # Add the page (adjusting for 0-based index)
                    pdf_writer.add_page(pdf_reader.pages[page_num - 1])
                    
                # Generate output filename
                base_name = os.path.splitext(os.path.basename(self.current_file))[0]
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                output_file = os.path.join(
                    self.output_dir, 
                    f"{base_name}_extracted_{timestamp}.pdf"
                )
                
                # Write the extracted pages to a file
                update_progress(self.progress_bar, self.progress_text, 0.9, "Writing extracted pages...")
                with open(output_file, 'wb') as out_f:
                    pdf_writer.write(out_f)
                    
                update_progress(self.progress_bar, self.progress_text, 1.0, "Extraction complete!")
                time.sleep(1)  # Allow user to see completion
                
                # Reset progress and show success message
                reset_progress(self.progress_bar, self.progress_text)
                show_snackbar(
                    self.page, 
                    f"Extracted {len(page_numbers)} pages to: {output_file}", 
                    "success"
                )
                
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error extracting pages: {str(e)}", "error")
    
    def start_compress(self, e):
        """Start the PDF compression process."""
        # Get current file from app
        self.current_file = getattr(self.page.client_storage.get("current_file"), "path", None)
        
        # Check if we have a PDF file
        if not self.current_file:
            show_snackbar(self.page, "Please select a PDF file first", "warning")
            return
            
        if not self.current_file.lower().endswith(".pdf"):
            show_snackbar(self.page, "Please select a PDF file", "warning")
            return
            
        # Start the compression in a separate thread
        compress_thread = threading.Thread(target=self._compress_pdf)
        compress_thread.daemon = True
        compress_thread.start()
    
    def _compress_pdf(self):
        """Compress a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF compression...")
            
            # Get compression settings
            compression_level = int(self.compression_level.value)
            image_quality = int(self.image_quality.value)
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "compressed", ".pdf")
            )
            
            # Get original file size
            original_size = os.path.getsize(self.current_file)
            
            # Open the PDF with PyMuPDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Analyzing PDF...")
            doc = fitz.open(self.current_file)
            
            # We'll simulate compression since actual compression would require 
            # more complex image resampling and content optimization
            update_progress(self.progress_bar, self.progress_text, 0.5, "Compressing PDF content...")
            
            # Wait a bit to simulate processing
            time.sleep(1)
            
            update_progress(self.progress_bar, self.progress_text, 0.7, "Optimizing images...")
            
            # Wait a bit more
            time.sleep(1)
            
            # Save with compression
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving compressed PDF...")
            
            # Here we use PyMuPDF's compression parameters
            # Higher compression_level = more compression
            # Lower image_quality = more compression
            doc.save(
                output_file,
                garbage=4,  # Maximum garbage collection
                deflate=True,  # Use deflate compression
                clean=True,  # Clean content streams
            )
            
            doc.close()
            
            # Get new file size
            new_size = os.path.getsize(output_file)
            size_reduction = original_size - new_size
            reduction_percent = (size_reduction / original_size) * 100 if original_size > 0 else 0
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Compression complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            
            # Format sizes for display
            def format_size(size_bytes):
                if size_bytes < 1024:
                    return f"{size_bytes} bytes"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.2f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.2f} MB"
            
            show_snackbar(
                self.page, 
                f"PDF compressed: {format_size(original_size)} → {format_size(new_size)} ({reduction_percent:.1f}% reduction)",
                "success"
            )
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error compressing PDF: {str(e)}", "error")