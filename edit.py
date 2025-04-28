import flet as ft
import os
import threading
import time
import tempfile
from PIL import Image, ImageDraw, ImageFont
import PyPDF2
import fitz  # PyMuPDF

from utils import (
    generate_output_filename, 
    show_snackbar, 
    update_progress, 
    reset_progress,
    simulate_progress
)

class PDFEditor:
    """Handles PDF editing operations."""
    
    def __init__(self, page, progress_bar, progress_text, output_dir):
        self.page = page
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.output_dir = output_dir
        self.current_file = None
        
        # Editing options
        self.edit_operations = {
            "Add Text": self.add_text,
            "Add Image": self.add_image,
            "Add Watermark": self.add_watermark,
            "Rotate Pages": self.rotate_pages,
            "Crop Pages": self.crop_pages,
        }
        
        # File picker for image selection
        self.image_picker = ft.FilePicker(on_result=self.on_image_selected)
        self.page.overlay.append(self.image_picker)
        
        # Selected image path
        self.selected_image = None
    
    def build_ui(self):
        """Build the editor UI."""
        # Dropdown for edit operation
        self.edit_dropdown = ft.Dropdown(
            label="Edit Operation",
            hint_text="Select edit operation",
            options=[ft.dropdown.Option(op) for op in self.edit_operations.keys()],
            width=400,
            autofocus=True,
        )
        
        # Text editing controls
        self.text_controls = ft.Column([
            ft.TextField(
                label="Text",
                hint_text="Enter text to add",
                width=400,
            ),
            ft.Row([
                ft.Dropdown(
                    label="Font Size",
                    options=[
                        ft.dropdown.Option("12"),
                        ft.dropdown.Option("14"),
                        ft.dropdown.Option("16"),
                        ft.dropdown.Option("18"),
                        ft.dropdown.Option("20"),
                        ft.dropdown.Option("24"),
                        ft.dropdown.Option("28"),
                        ft.dropdown.Option("32"),
                        ft.dropdown.Option("36"),
                        ft.dropdown.Option("48"),
                    ],
                    value="16",
                    width=150,
                ),
                ft.Dropdown(
                    label="Font Color",
                    options=[
                        ft.dropdown.Option("Black"),
                        ft.dropdown.Option("Red"),
                        ft.dropdown.Option("Blue"),
                        ft.dropdown.Option("Green"),
                        ft.dropdown.Option("Gray"),
                    ],
                    value="Black",
                    width=150,
                ),
            ]),
            ft.Row([
                ft.TextField(
                    label="X Position (0-100%)",
                    value="50",
                    width=150,
                ),
                ft.TextField(
                    label="Y Position (0-100%)",
                    value="50",
                    width=150,
                ),
            ]),
        ], visible=False, spacing=10)
        
        # Image editing controls
        self.image_controls = ft.Column([
            ft.ElevatedButton(
                "Select Image",
                icon=ft.icons.IMAGE,
                on_click=lambda _: self.image_picker.pick_files(
                    allowed_extensions=["jpg", "jpeg", "png"],
                    allow_multiple=False
                ),
            ),
            ft.Text("No image selected", size=12),
            ft.Row([
                ft.TextField(
                    label="X Position (0-100%)",
                    value="50",
                    width=150,
                ),
                ft.TextField(
                    label="Y Position (0-100%)",
                    value="50",
                    width=150,
                ),
            ]),
            ft.Row([
                ft.TextField(
                    label="Width (0-100%)",
                    value="30",
                    width=150,
                ),
                ft.TextField(
                    label="Height (0-100%)",
                    value="30",
                    width=150,
                ),
            ]),
        ], visible=False, spacing=10)
        
        # Watermark controls
        self.watermark_controls = ft.Column([
            ft.TextField(
                label="Watermark Text",
                hint_text="Enter watermark text",
                value="CONFIDENTIAL",
                width=400,
            ),
            ft.Row([
                ft.Dropdown(
                    label="Font Size",
                    options=[
                        ft.dropdown.Option("24"),
                        ft.dropdown.Option("36"),
                        ft.dropdown.Option("48"),
                        ft.dropdown.Option("60"),
                        ft.dropdown.Option("72"),
                    ],
                    value="48",
                    width=150,
                ),
                ft.Dropdown(
                    label="Opacity",
                    options=[
                        ft.dropdown.Option("10%"),
                        ft.dropdown.Option("20%"),
                        ft.dropdown.Option("30%"),
                        ft.dropdown.Option("40%"),
                        ft.dropdown.Option("50%"),
                    ],
                    value="30%",
                    width=150,
                ),
            ]),
            ft.Dropdown(
                label="Color",
                options=[
                    ft.dropdown.Option("Light Gray"),
                    ft.dropdown.Option("Gray"),
                    ft.dropdown.Option("Red"),
                    ft.dropdown.Option("Blue"),
                ],
                value="Light Gray",
                width=300,
            ),
            ft.Dropdown(
                label="Angle",
                options=[
                    ft.dropdown.Option("0°"),
                    ft.dropdown.Option("45°"),
                    ft.dropdown.Option("-45°"),
                    ft.dropdown.Option("90°"),
                ],
                value="45°",
                width=300,
            ),
        ], visible=False, spacing=10)
        
        # Rotate controls
        self.rotate_controls = ft.Column([
            ft.Dropdown(
                label="Rotation Angle",
                options=[
                    ft.dropdown.Option("90° Clockwise"),
                    ft.dropdown.Option("90° Counter-Clockwise"),
                    ft.dropdown.Option("180°"),
                ],
                value="90° Clockwise",
                width=300,
            ),
            ft.Dropdown(
                label="Pages",
                options=[
                    ft.dropdown.Option("All Pages"),
                    ft.dropdown.Option("First Page"),
                    ft.dropdown.Option("Last Page"),
                    ft.dropdown.Option("Custom Range"),
                ],
                value="All Pages",
                width=300,
            ),
            ft.TextField(
                label="Page Range (e.g., '1-3, 5, 7-9')",
                hint_text="Enter page range",
                visible=False,
                width=400,
            ),
        ], visible=False, spacing=10)
        
        # Crop controls
        self.crop_controls = ft.Column([
            ft.Text("Set crop margins (% of page size)"),
            ft.Row([
                ft.TextField(
                    label="Left",
                    value="10",
                    width=90,
                ),
                ft.TextField(
                    label="Right",
                    value="10",
                    width=90,
                ),
                ft.TextField(
                    label="Top",
                    value="10",
                    width=90,
                ),
                ft.TextField(
                    label="Bottom",
                    value="10",
                    width=90,
                ),
            ]),
            ft.Dropdown(
                label="Pages",
                options=[
                    ft.dropdown.Option("All Pages"),
                    ft.dropdown.Option("First Page"),
                    ft.dropdown.Option("Last Page"),
                    ft.dropdown.Option("Custom Range"),
                ],
                value="All Pages",
                width=300,
            ),
            ft.TextField(
                label="Page Range (e.g., '1-3, 5, 7-9')",
                hint_text="Enter page range",
                visible=False,
                width=400,
            ),
        ], visible=False, spacing=10)
        
        # Button for applying edits
        self.apply_button = ft.ElevatedButton(
            "Apply",
            icon=ft.icons.CHECK,
            on_click=self.start_editing,
            disabled=True,
        )
        
        # Listen for changes in the dropdown
        def on_edit_change(e):
            # Reset visibility of all control groups
            for controls in [self.text_controls, self.image_controls, self.watermark_controls, 
                           self.rotate_controls, self.crop_controls]:
                controls.visible = False
            
            # Show the appropriate controls based on the selection
            if self.edit_dropdown.value == "Add Text":
                self.text_controls.visible = True
            elif self.edit_dropdown.value == "Add Image":
                self.image_controls.visible = True
            elif self.edit_dropdown.value == "Add Watermark":
                self.watermark_controls.visible = True
            elif self.edit_dropdown.value == "Rotate Pages":
                self.rotate_controls.visible = True
            elif self.edit_dropdown.value == "Crop Pages":
                self.crop_controls.visible = True
                
            # Enable apply button if an operation is selected
            self.apply_button.disabled = not bool(self.edit_dropdown.value)
            self.page.update()
        
        # Listen for changes in the pages dropdown for rotate
        def on_rotate_pages_change(e):
            rotate_page_range = self.rotate_controls.controls[2]
            rotate_page_range.visible = (self.rotate_controls.controls[1].value == "Custom Range")
            self.page.update()
            
        # Listen for changes in the pages dropdown for crop
        def on_crop_pages_change(e):
            crop_page_range = self.crop_controls.controls[3]
            crop_page_range.visible = (self.crop_controls.controls[2].value == "Custom Range")
            self.page.update()
            
        self.edit_dropdown.on_change = on_edit_change
        self.rotate_controls.controls[1].on_change = on_rotate_pages_change
        self.crop_controls.controls[2].on_change = on_crop_pages_change
        
        # Main container
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "Edit PDF Files",
                    style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Add text, images, watermarks, or modify pages",
                    style=ft.TextThemeStyle.BODY_MEDIUM,
                ),
                ft.Divider(),
                self.edit_dropdown,
                ft.Container(height=10),  # Spacer
                self.text_controls,
                self.image_controls,
                self.watermark_controls,
                self.rotate_controls,
                self.crop_controls,
                ft.Container(height=10),  # Spacer
                self.apply_button,
            ], spacing=10),
            padding=20,
        )
    
    def on_image_selected(self, e):
        """Handle image selection for adding images to PDF."""
        if e.files and len(e.files) > 0:
            self.selected_image = e.files[0].path
            self.image_controls.controls[1].value = f"Selected: {os.path.basename(self.selected_image)}"
            self.page.update()
    
    def start_editing(self, e):
        """Start the editing process in a separate thread."""
        if not self.edit_dropdown.value:
            show_snackbar(self.page, "Please select an edit operation", "warning")
            return
            
        # Get current file from app
        self.current_file = getattr(self.page.client_storage.get("current_file"), "path", None)
        
        # Check if we have a PDF file
        if not self.current_file:
            show_snackbar(self.page, "Please select a PDF file first", "warning")
            return
            
        if not self.current_file.lower().endswith(".pdf"):
            show_snackbar(self.page, "Please select a PDF file", "warning")
            return
            
        # Start the editing in a separate thread
        editing_thread = threading.Thread(
            target=self.edit_operations[self.edit_dropdown.value]
        )
        editing_thread.daemon = True
        editing_thread.start()
    
    def add_text(self):
        """Add text to a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting text addition...")
            
            # Get text parameters
            text = self.text_controls.controls[0].value
            font_size = int(self.text_controls.controls[1].controls[0].value)
            font_color = self.text_controls.controls[1].controls[1].value.lower()
            x_pos = float(self.text_controls.controls[2].controls[0].value) / 100
            y_pos = float(self.text_controls.controls[2].controls[1].value) / 100
            
            if not text:
                show_snackbar(self.page, "Please enter text to add", "warning")
                reset_progress(self.progress_bar, self.progress_text)
                return
                
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "text_added", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Opening PDF...")
            doc = fitz.open(self.current_file)
            
            # Map font colors
            color_map = {
                "black": (0, 0, 0),
                "red": (1, 0, 0),
                "blue": (0, 0, 1),
                "green": (0, 1, 0),
                "gray": (0.5, 0.5, 0.5),
            }
            rgb = color_map.get(font_color.lower(), (0, 0, 0))
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Adding text to PDF...")
            
            # Add text to each page
            for i, page in enumerate(doc):
                # Get page dimensions
                rect = page.rect
                
                # Calculate text position
                text_x = rect.width * x_pos
                text_y = rect.height * y_pos
                
                # Add text to page
                page.insert_text(
                    fitz.Point(text_x, text_y), 
                    text, 
                    fontsize=font_size, 
                    color=rgb
                )
                
                # Update progress
                progress = 0.5 + 0.4 * ((i + 1) / len(doc))
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    progress, 
                    f"Adding text to page {i+1} of {len(doc)}..."
                )
                
            # Save the modified PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving modified PDF...")
            doc.save(output_file)
            doc.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Text addition complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Text successfully added to PDF: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error adding text to PDF: {str(e)}", "error")
    
    def add_image(self):
        """Add an image to a PDF file."""
        try:
            if not self.selected_image:
                show_snackbar(self.page, "Please select an image first", "warning")
                return
                
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting image addition...")
            
            # Get image parameters
            x_pos = float(self.image_controls.controls[2].controls[0].value) / 100
            y_pos = float(self.image_controls.controls[2].controls[1].value) / 100
            width_pct = float(self.image_controls.controls[3].controls[0].value) / 100
            height_pct = float(self.image_controls.controls[3].controls[1].value) / 100
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "image_added", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Opening PDF...")
            doc = fitz.open(self.current_file)
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Adding image to PDF...")
            
            # Add image to each page
            for i, page in enumerate(doc):
                # Get page dimensions
                rect = page.rect
                
                # Calculate image position and size
                img_x = rect.width * x_pos
                img_y = rect.height * y_pos
                img_width = rect.width * width_pct
                img_height = rect.height * height_pct
                
                # Create rectangle for image placement
                img_rect = fitz.Rect(
                    img_x - img_width/2, 
                    img_y - img_height/2, 
                    img_x + img_width/2, 
                    img_y + img_height/2
                )
                
                # Insert image
                page.insert_image(img_rect, filename=self.selected_image)
                
                # Update progress
                progress = 0.5 + 0.4 * ((i + 1) / len(doc))
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    progress, 
                    f"Adding image to page {i+1} of {len(doc)}..."
                )
                
            # Save the modified PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving modified PDF...")
            doc.save(output_file)
            doc.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Image addition complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Image successfully added to PDF: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error adding image to PDF: {str(e)}", "error")
    
    def add_watermark(self):
        """Add a watermark to a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting watermark addition...")
            
            # Get watermark parameters
            watermark_text = self.watermark_controls.controls[0].value
            font_size = int(self.watermark_controls.controls[1].controls[0].value)
            opacity_str = self.watermark_controls.controls[1].controls[1].value
            opacity = float(opacity_str.strip('%')) / 100
            color_str = self.watermark_controls.controls[2].value.lower()
            angle_str = self.watermark_controls.controls[3].value
            
            if not watermark_text:
                show_snackbar(self.page, "Please enter watermark text", "warning")
                reset_progress(self.progress_bar, self.progress_text)
                return
                
            # Parse angle
            if angle_str == "0°":
                angle = 0
            elif angle_str == "45°":
                angle = 45
            elif angle_str == "-45°":
                angle = -45
            elif angle_str == "90°":
                angle = 90
            else:
                angle = 0
                
            # Map colors
            color_map = {
                "light gray": (0.8, 0.8, 0.8),
                "gray": (0.5, 0.5, 0.5),
                "red": (1, 0, 0),
                "blue": (0, 0, 1),
            }
            rgb = color_map.get(color_str, (0.8, 0.8, 0.8))
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "watermarked", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Opening PDF...")
            doc = fitz.open(self.current_file)
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Adding watermark to PDF...")
            
            # Add watermark to each page
            for i, page in enumerate(doc):
                # Get page dimensions
                rect = page.rect
                center_x = rect.width / 2
                center_y = rect.height / 2
                
                # Create watermark
                page.insert_text(
                    fitz.Point(center_x, center_y),
                    watermark_text,
                    fontsize=font_size,
                    color=rgb,
                    alpha=opacity,
                    rotate=angle,
                    overlay=True
                )
                
                # Update progress
                progress = 0.5 + 0.4 * ((i + 1) / len(doc))
                update_progress(
                    self.progress_bar, 
                    self.progress_text, 
                    progress, 
                    f"Adding watermark to page {i+1} of {len(doc)}..."
                )
                
            # Save the modified PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving watermarked PDF...")
            doc.save(output_file)
            doc.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Watermark addition complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Watermark successfully added to PDF: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error adding watermark to PDF: {str(e)}", "error")
    
    def rotate_pages(self):
        """Rotate pages in a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting page rotation...")
            
            # Get rotation parameters
            rotation_str = self.rotate_controls.controls[0].value
            pages_option = self.rotate_controls.controls[1].value
            page_range_str = self.rotate_controls.controls[2].value if self.rotate_controls.controls[2].visible else ""
            
            # Determine rotation angle
            if rotation_str == "90° Clockwise":
                rotation = 90
            elif rotation_str == "90° Counter-Clockwise":
                rotation = -90
            elif rotation_str == "180°":
                rotation = 180
            else:
                rotation = 90
                
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "rotated", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Opening PDF...")
            doc = fitz.open(self.current_file)
            
            # Determine which pages to rotate
            pages_to_rotate = []
            if pages_option == "All Pages":
                pages_to_rotate = list(range(len(doc)))
            elif pages_option == "First Page":
                pages_to_rotate = [0]
            elif pages_option == "Last Page":
                pages_to_rotate = [len(doc) - 1]
            elif pages_option == "Custom Range" and page_range_str:
                # Parse page range string (e.g., "1-3, 5, 7-9")
                try:
                    for part in page_range_str.split(','):
                        part = part.strip()
                        if '-' in part:
                            start, end = part.split('-')
                            pages_to_rotate.extend(range(int(start) - 1, int(end)))
                        else:
                            pages_to_rotate.append(int(part) - 1)
                except:
                    show_snackbar(self.page, "Invalid page range format", "error")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
            
            update_progress(self.progress_bar, self.progress_text, 0.5, f"Rotating {len(pages_to_rotate)} pages...")
            
            # Rotate the specified pages
            for i, page_num in enumerate(pages_to_rotate):
                if 0 <= page_num < len(doc):
                    page = doc[page_num]
                    page.set_rotation(rotation)
                    
                    # Update progress
                    progress = 0.5 + 0.4 * ((i + 1) / len(pages_to_rotate))
                    update_progress(
                        self.progress_bar, 
                        self.progress_text, 
                        progress, 
                        f"Rotating page {page_num + 1}..."
                    )
                
            # Save the modified PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving rotated PDF...")
            doc.save(output_file)
            doc.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Page rotation complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Pages successfully rotated: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error rotating pages: {str(e)}", "error")
    
    def crop_pages(self):
        """Crop pages in a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting page cropping...")
            
            # Get crop parameters
            left = float(self.crop_controls.controls[1].controls[0].value) / 100
            right = float(self.crop_controls.controls[1].controls[1].value) / 100
            top = float(self.crop_controls.controls[1].controls[2].value) / 100
            bottom = float(self.crop_controls.controls[1].controls[3].value) / 100
            
            pages_option = self.crop_controls.controls[2].value
            page_range_str = self.crop_controls.controls[3].value if self.crop_controls.controls[3].visible else ""
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "cropped", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Opening PDF...")
            doc = fitz.open(self.current_file)
            
            # Determine which pages to crop
            pages_to_crop = []
            if pages_option == "All Pages":
                pages_to_crop = list(range(len(doc)))
            elif pages_option == "First Page":
                pages_to_crop = [0]
            elif pages_option == "Last Page":
                pages_to_crop = [len(doc) - 1]
            elif pages_option == "Custom Range" and page_range_str:
                # Parse page range string (e.g., "1-3, 5, 7-9")
                try:
                    for part in page_range_str.split(','):
                        part = part.strip()
                        if '-' in part:
                            start, end = part.split('-')
                            pages_to_crop.extend(range(int(start) - 1, int(end)))
                        else:
                            pages_to_crop.append(int(part) - 1)
                except:
                    show_snackbar(self.page, "Invalid page range format", "error")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
            
            update_progress(self.progress_bar, self.progress_text, 0.5, f"Cropping {len(pages_to_crop)} pages...")
            
            # Crop the specified pages
            for i, page_num in enumerate(pages_to_crop):
                if 0 <= page_num < len(doc):
                    page = doc[page_num]
                    rect = page.rect
                    
                    # Calculate crop box
                    crop_rect = fitz.Rect(
                        rect.x0 + rect.width * left,
                        rect.y0 + rect.height * top,
                        rect.x1 - rect.width * right,
                        rect.y1 - rect.height * bottom
                    )
                    
                    # Set the cropbox
                    page.set_cropbox(crop_rect)
                    
                    # Update progress
                    progress = 0.5 + 0.4 * ((i + 1) / len(pages_to_crop))
                    update_progress(
                        self.progress_bar, 
                        self.progress_text, 
                        progress, 
                        f"Cropping page {page_num + 1}..."
                    )
                
            # Save the modified PDF
            update_progress(self.progress_bar, self.progress_text, 0.9, "Saving cropped PDF...")
            doc.save(output_file)
            doc.close()
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Page cropping complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Pages successfully cropped: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error cropping pages: {str(e)}", "error")