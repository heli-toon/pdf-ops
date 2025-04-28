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

class PDFSecurity:
    """Handles PDF security operations like encryption and decryption."""
    
    def __init__(self, page, progress_bar, progress_text, output_dir):
        self.page = page
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.output_dir = output_dir
        self.current_file = None
        
        # Security operations
        self.security_operations = {
            "Encrypt PDF": self.encrypt_pdf,
            "Decrypt PDF": self.decrypt_pdf,
            "Add Permission Password": self.add_permission_password,
            "Remove Password": self.remove_password,
        }
    
    def build_ui(self):
        """Build the security UI."""
        # Dropdown for security operation
        self.security_dropdown = ft.Dropdown(
            label="Security Operation",
            hint_text="Select security operation",
            options=[ft.dropdown.Option(op) for op in self.security_operations.keys()],
            width=400,
            autofocus=True,
            on_change=self.on_operation_change,
        )
        
        # Password inputs
        self.password_input = ft.TextField(
            label="Password",
            hint_text="Enter password",
            password=True,
            width=400,
        )
        
        self.confirm_password = ft.TextField(
            label="Confirm Password",
            hint_text="Confirm password",
            password=True,
            width=400,
        )
        
        self.current_password = ft.TextField(
            label="Current Password",
            hint_text="Enter current password",
            password=True,
            width=400,
            visible=False,
        )
        
        # Permission settings for owner password
        self.permissions_container = ft.Container(
            content=ft.Column([
                ft.Text("Document Permissions", style=ft.TextThemeStyle.TITLE_SMALL),
                ft.Checkbox(label="Allow printing", value=True),
                ft.Checkbox(label="Allow copying text and images", value=True),
                ft.Checkbox(label="Allow editing", value=False),
                ft.Checkbox(label="Allow adding comments", value=True),
                ft.Checkbox(label="Allow form filling", value=True),
            ]),
            visible=False,
            padding=10,
            border_radius=5,
            border=ft.border.all(1, ft.colors.GREY_400),
            margin=ft.margin.only(top=10, bottom=10),
        )
        
        # Button for applying security operation
        self.apply_button = ft.ElevatedButton(
            "Apply",
            icon=ft.icons.SECURITY,
            on_click=self.start_security_operation,
            disabled=True,
        )
        
        # Show password checkbox
        self.show_password = ft.Checkbox(
            label="Show password",
            value=False,
            on_change=self.toggle_password_visibility,
        )
        
        # Main container
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "PDF Security",
                    style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Encrypt, decrypt, and manage PDF security",
                    style=ft.TextThemeStyle.BODY_MEDIUM,
                ),
                ft.Divider(),
                self.security_dropdown,
                ft.Container(height=10),  # Spacer
                self.current_password,
                self.password_input,
                self.confirm_password,
                self.show_password,
                self.permissions_container,
                ft.Container(height=10),  # Spacer
                self.apply_button,
            ], spacing=10),
            padding=20,
        )
    
    def on_operation_change(self, e):
        """Update UI based on selected operation."""
        # Reset visibility
        self.permissions_container.visible = False
        self.current_password.visible = False
        self.password_input.visible = True
        self.confirm_password.visible = True
        
        # Update UI based on selected operation
        operation = self.security_dropdown.value
        if operation == "Encrypt PDF":
            self.password_input.label = "Password"
            self.confirm_password.visible = True
            self.permissions_container.visible = True
        elif operation == "Decrypt PDF":
            self.password_input.label = "Password"
            self.confirm_password.visible = False
        elif operation == "Add Permission Password":
            self.password_input.label = "Owner Password"
            self.confirm_password.visible = True
            self.permissions_container.visible = True
        elif operation == "Remove Password":
            self.password_input.label = "Current Password"
            self.confirm_password.visible = False
        
        # Enable button if operation is selected
        self.apply_button.disabled = not operation
        self.page.update()
    
    def toggle_password_visibility(self, e):
        """Toggle password field visibility."""
        self.password_input.password = not self.show_password.value
        self.confirm_password.password = not self.show_password.value
        self.current_password.password = not self.show_password.value
        self.page.update()
    
    def start_security_operation(self, e):
        """Start the selected security operation."""
        if not self.security_dropdown.value:
            show_snackbar(self.page, "Please select a security operation", "warning")
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
            
        # Validate passwords for operations that require them
        operation = self.security_dropdown.value
        if operation in ["Encrypt PDF", "Add Permission Password"]:
            if not self.password_input.value:
                show_snackbar(self.page, "Please enter a password", "warning")
                return
                
            if self.password_input.value != self.confirm_password.value:
                show_snackbar(self.page, "Passwords do not match", "error")
                return
                
        elif operation in ["Decrypt PDF", "Remove Password"]:
            if not self.password_input.value:
                show_snackbar(self.page, "Please enter the current password", "warning")
                return
        
        # Start the operation in a separate thread
        security_thread = threading.Thread(
            target=self.security_operations[operation]
        )
        security_thread.daemon = True
        security_thread.start()
    
    def encrypt_pdf(self):
        """Encrypt a PDF file with a password."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF encryption...")
            
            # Get the password
            password = self.password_input.value
            
            # Get permissions
            permissions = self.permissions_container.content.controls
            allow_printing = permissions[1].value
            allow_copying = permissions[2].value
            allow_editing = permissions[3].value
            allow_comments = permissions[4].value
            allow_forms = permissions[5].value
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "encrypted", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Reading PDF...")
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                
                # Check if already encrypted
                if pdf_reader.is_encrypted:
                    show_snackbar(self.page, "PDF is already encrypted", "warning")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                    
                # Create a PDF writer
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add all pages to the writer
                update_progress(self.progress_bar, self.progress_text, 0.5, "Preparing document...")
                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)
                
                # Set up encryption flags
                update_progress(self.progress_bar, self.progress_text, 0.7, "Setting security...")
                encryption_flags = 0
                if allow_printing:
                    encryption_flags |= PyPDF2.PageObject.PRINT
                if allow_copying:
                    encryption_flags |= PyPDF2.PageObject.EXTRACT
                if allow_editing:
                    encryption_flags |= PyPDF2.PageObject.MODIFY
                if allow_comments:
                    encryption_flags |= PyPDF2.PageObject.ANNOTATE
                if allow_forms:
                    encryption_flags |= PyPDF2.PageObject.FILL_FORM
                
                # Encrypt the PDF
                pdf_writer.encrypt(password, password, use_128bit=True, permissions_flag=encryption_flags)
                
                # Write the encrypted PDF
                update_progress(self.progress_bar, self.progress_text, 0.9, "Writing encrypted PDF...")
                with open(output_file, 'wb') as out_f:
                    pdf_writer.write(out_f)
                
            update_progress(self.progress_bar, self.progress_text, 1.0, "Encryption complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"PDF successfully encrypted: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error encrypting PDF: {str(e)}", "error")
    
    def decrypt_pdf(self):
        """Decrypt a PDF file using a password."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF decryption...")
            
            # Get the password
            password = self.password_input.value
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "decrypted", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Reading PDF...")
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                
                # Check if encrypted
                if not pdf_reader.is_encrypted:
                    show_snackbar(self.page, "PDF is not encrypted", "warning")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                    
                # Try to decrypt with the provided password
                try:
                    pdf_reader.decrypt(password)
                except:
                    show_snackbar(self.page, "Incorrect password", "error")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                
                # Create a PDF writer
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add all pages to the writer
                update_progress(self.progress_bar, self.progress_text, 0.6, "Copying decrypted content...")
                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)
                
                # Write the decrypted PDF
                update_progress(self.progress_bar, self.progress_text, 0.9, "Writing decrypted PDF...")
                with open(output_file, 'wb') as out_f:
                    pdf_writer.write(out_f)
                
            update_progress(self.progress_bar, self.progress_text, 1.0, "Decryption complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"PDF successfully decrypted: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error decrypting PDF: {str(e)}", "error")
    
    def add_permission_password(self):
        """Add an owner password to a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting permission password addition...")
            
            # Get the password
            password = self.password_input.value
            
            # Get permissions
            permissions = self.permissions_container.content.controls
            allow_printing = permissions[1].value
            allow_copying = permissions[2].value
            allow_editing = permissions[3].value
            allow_comments = permissions[4].value
            allow_forms = permissions[5].value
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "permission_added", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Reading PDF...")
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                
                # Check if already encrypted
                if pdf_reader.is_encrypted:
                    show_snackbar(self.page, "PDF is already encrypted", "warning")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                    
                # Create a PDF writer
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add all pages to the writer
                update_progress(self.progress_bar, self.progress_text, 0.5, "Preparing document...")
                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)
                
                # Set up encryption flags
                update_progress(self.progress_bar, self.progress_text, 0.7, "Setting permissions...")
                encryption_flags = 0
                if allow_printing:
                    encryption_flags |= PyPDF2.PageObject.PRINT
                if allow_copying:
                    encryption_flags |= PyPDF2.PageObject.EXTRACT
                if allow_editing:
                    encryption_flags |= PyPDF2.PageObject.MODIFY
                if allow_comments:
                    encryption_flags |= PyPDF2.PageObject.ANNOTATE
                if allow_forms:
                    encryption_flags |= PyPDF2.PageObject.FILL_FORM
                
                # Encrypt with user and owner password
                pdf_writer.encrypt("", password, use_128bit=True, permissions_flag=encryption_flags)
                
                # Write the secured PDF
                update_progress(self.progress_bar, self.progress_text, 0.9, "Writing secured PDF...")
                with open(output_file, 'wb') as out_f:
                    pdf_writer.write(out_f)
                
            update_progress(self.progress_bar, self.progress_text, 1.0, "Permission password addition complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Permission password successfully added: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error adding permission password: {str(e)}", "error")
    
    def remove_password(self):
        """Remove password protection from a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting password removal...")
            
            # Get the password
            password = self.password_input.value
            
            # Generate output filename
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "password_removed", ".pdf")
            )
            
            # Open the PDF
            update_progress(self.progress_bar, self.progress_text, 0.3, "Reading PDF...")
            with open(self.current_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                
                # Check if encrypted
                if not pdf_reader.is_encrypted:
                    show_snackbar(self.page, "PDF is not encrypted", "warning")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                    
                # Try to decrypt with the provided password
                try:
                    pdf_reader.decrypt(password)
                except:
                    show_snackbar(self.page, "Incorrect password", "error")
                    reset_progress(self.progress_bar, self.progress_text)
                    return
                
                # Create a PDF writer
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add all pages to the writer
                update_progress(self.progress_bar, self.progress_text, 0.6, "Copying decrypted content...")
                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)
                
                # Write the unprotected PDF
                update_progress(self.progress_bar, self.progress_text, 0.9, "Writing unprotected PDF...")
                with open(output_file, 'wb') as out_f:
                    pdf_writer.write(out_f)
                
            update_progress(self.progress_bar, self.progress_text, 1.0, "Password removal complete!")
            time.sleep(1)  # Allow user to see completion
            
            # Reset progress and show success message
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Password successfully removed: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error removing password: {str(e)}", "error")