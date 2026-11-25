import flet as ft
import os
import time
import PyPDF2
import pymupdf as fitz
from pdf_engine import compress_pdf, inspect_pdf, parse_page_ranges

from utils import (
    generate_output_filename, 
    show_snackbar, 
    update_progress, 
    reset_progress,
    run_background,
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
        self.page.services.append(self.pdf_picker)

    def set_current_file(self, file_path):
        """Receive the active file selection from the application shell."""
        self.current_file = file_path
    
    def build_ui(self):
        """Build the merger & splitter UI."""
        # Tabs for merge and split operations
        self.operation_tabs = ft.Tabs(
            length=4,
            selected_index=0,
            animation_duration=300,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=[
                        ft.Tab(label="Merge PDFs"),
                        ft.Tab(label="Split PDF"),
                        ft.Tab(label="Extract Pages"),
                        ft.Tab(label="Compress PDF"),
                    ]),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            self._build_merge_ui(),
                            self._build_split_ui(),
                            self._build_extract_ui(),
                            self._build_compress_ui(),
                        ],
                    ),
                ],
            ),
        )
        
        # Main container
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "Merge, Split & Compress PDF Files",
                    theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Combine multiple PDFs, split into separate files, or reduce file size",
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM,
                ),
                ft.Divider(),
                self.operation_tabs,
            ], spacing=10, expand=True),
            padding=20,
            expand=True,
        )
    
    def _build_merge_ui(self):
        """Build the UI for merging PDFs."""
        # Button for selecting PDFs
        self.select_pdfs_button = ft.Button(
            "Select PDFs to Merge",
            icon=ft.Icons.FILE_COPY,
            action=ft.PickFiles(
                self.pdf_picker,
                dialog_title="Select PDFs to Merge — PDF-Ops",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["pdf"],
                allow_multiple=True,
            ),
        )
        
        # List of selected PDFs
        self.selected_pdfs_list = ft.ListView(
            spacing=10,
            height=200,
            padding=10,
        )
        
        # Merge button
        self.merge_button = ft.Button(
            "Merge PDFs",
            icon=ft.Icons.MERGE_TYPE,
            on_click=self.start_merge,
            disabled=True,
        )
        
        # Reorder buttons
        self.move_up_button = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD,
            tooltip="Move file up",
            on_click=self.move_file_up,
            disabled=True,
        )
        
        self.move_down_button = ft.IconButton(
            icon=ft.Icons.ARROW_DOWNWARD,
            tooltip="Move file down",
            on_click=self.move_file_down,
            disabled=True,
        )
        
        self.remove_file_button = ft.IconButton(
            icon=ft.Icons.DELETE,
            tooltip="Remove file",
            on_click=self.remove_file,
            disabled=True,
        )
        
        return ft.Column([
            self.select_pdfs_button,
            ft.Container(
                content=self.selected_pdfs_list,
                border=ft.Border.all(1, ft.Colors.GREY_400),
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
                ft.dropdown.Option("Split by custom range"),
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
        self.split_range = ft.TextField(
            label="Page ranges",
            hint_text="e.g., 1-3, 5, 8-end",
            width=400,
            visible=False,
        )
        
        # Split button
        self.split_button = ft.Button(
            "Split PDF",
            icon=ft.Icons.CALL_SPLIT,
            on_click=self.start_split,
        )
        
        # Listen for split method change
        def on_split_method_change(e):
            self.pages_per_file.visible = (self.split_dropdown.value == "Split by page count")
            self.split_range.visible = (self.split_dropdown.value == "Split by custom range")
            self.page.update()
            
        self.split_dropdown.on_select = on_split_method_change
        
        return ft.Column([
            ft.Text("Split a single PDF into multiple files"),
            self.split_dropdown,
            self.pages_per_file,
            self.split_range,
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
        self.extract_button = ft.Button(
            "Extract Pages",
            icon=ft.Icons.FILE_COPY,
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
        self.compress_button = ft.Button(
            "Compress PDF",
            icon=ft.Icons.COMPRESS,
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
        """Update the list of selected PDFs with inspected page counts and file sizes."""
        self.selected_pdfs_list.controls.clear()
        
        for i, pdf_path in enumerate(self.pdf_files):
            file_name = os.path.basename(pdf_path)
            detail = ""
            try:
                info = inspect_pdf(pdf_path)
                page_count = info["page_count"]
                size_kb = info["file_size"] / 1024
                pages_label = f"{page_count} page{'s' if page_count != 1 else ''}"
                detail = f" ({pages_label}, {size_kb:.1f} KB)"
            except Exception:
                pass
            
            self.selected_pdfs_list.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(f"{i+1}. {file_name}{detail}", expand=True),
                    ]),
                    bgcolor=ft.Colors.BLUE_50 if i % 2 == 0 else None,
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
        e.control.border = ft.Border.all(2, ft.Colors.BLUE_400)
        
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
            self.selected_pdfs_list.controls[selected_idx-1].border = ft.Border.all(2, ft.Colors.BLUE_400)
            
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
            self.selected_pdfs_list.controls[selected_idx+1].border = ft.Border.all(2, ft.Colors.BLUE_400)
            
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
        run_background(self.page, self._merge_pdfs)
    
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
        # Check if we have a PDF file
        if not self.current_file:
            show_snackbar(self.page, "Please select a PDF file first", "warning")
            return
            
        if not self.current_file.lower().endswith(".pdf"):
            show_snackbar(self.page, "Please select a PDF file", "warning")
            return
            
        # Start the splitting in a separate thread
        run_background(self.page, self._split_pdf)
    
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
                    starts = self._bookmark_starts(pdf_reader)
                    if not starts:
                        raise ValueError("No top-level bookmarks were found")
                    if 0 not in starts:
                        starts.insert(0, 0)
                    for index, start in enumerate(starts):
                        end = starts[index + 1] if index + 1 < len(starts) else total_pages
                        writer = PyPDF2.PdfWriter()
                        for page_number in range(start, end):
                            writer.add_page(pdf_reader.pages[page_number])
                        with open(os.path.join(output_dir, f"{base_name}_chapter_{index + 1}.pdf"), "wb") as out_f:
                            writer.write(out_f)
                    show_snackbar(
                        self.page,
                        f"Split PDF into {len(starts)} chapter files by bookmarks: {output_dir}",
                        "success",
                    )
                elif split_method == "Split by custom range":
                    page_numbers = parse_page_ranges(self.split_range.value, total_pages)
                    writer = PyPDF2.PdfWriter()
                    for page_number in page_numbers:
                        writer.add_page(pdf_reader.pages[page_number - 1])
                    selected_output = os.path.join(output_dir, f"{base_name}_selected_pages.pdf")
                    with open(selected_output, "wb") as out_f:
                        writer.write(out_f)
                    show_snackbar(
                        self.page,
                        f"Extracted {len(page_numbers)} pages: {selected_output}",
                        "success",
                    )
                
            update_progress(self.progress_bar, self.progress_text, 1.0, "Split complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress
            reset_progress(self.progress_bar, self.progress_text)
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error splitting PDF: {str(e)}", "error")
    
    def start_extract(self, e):
        """Start the page extraction process."""
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
        run_background(self.page, self._extract_pages)
    
    def _extract_pages(self):
        """Extract specific pages from a PDF."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting page extraction...")
            
            # Open the PDF file
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)
                
                page_numbers = parse_page_ranges(self.page_range.value, total_pages)
                
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
        # Check if we have a PDF file
        if not self.current_file:
            show_snackbar(self.page, "Please select a PDF file first", "warning")
            return
            
        if not self.current_file.lower().endswith(".pdf"):
            show_snackbar(self.page, "Please select a PDF file", "warning")
            return
            
        # Start the compression in a separate thread
        run_background(self.page, self._compress_pdf)
    
    def _compress_pdf(self):
        """Compress a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF compression...")
            
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "compressed", ".pdf")
            )
            
            # Get original file size
            original_size = os.path.getsize(self.current_file)
            
            update_progress(self.progress_bar, self.progress_text, 0.3, "Analyzing PDF...")
            update_progress(self.progress_bar, self.progress_text, 0.5, "Compressing PDF content...")
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving compressed PDF...")
            compress_pdf(self.current_file, output_file)
            
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

    @staticmethod
    def _bookmark_starts(reader):
        """Return zero-based locations for top-level bookmark destinations."""
        starts = []
        for entry in getattr(reader, "outline", []):
            if isinstance(entry, list):
                continue
            try:
                page_number = reader.get_destination_page_number(entry)
            except Exception:
                continue
            if page_number not in starts:
                starts.append(page_number)
        return sorted(starts)
