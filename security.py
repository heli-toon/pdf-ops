import flet as ft
import os
import time
import PyPDF2
import pymupdf as fitz
from pdf_engine import decrypt_pdf as engine_decrypt_pdf, encrypt_pdf as engine_encrypt_pdf

from utils import (
    generate_output_filename, 
    show_snackbar, 
    update_progress, 
    reset_progress,
    run_background,
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
            on_select=self.on_operation_change,
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
                ft.Text("Document Permissions", theme_style=ft.TextThemeStyle.TITLE_SMALL),
                ft.Checkbox(label="Allow printing", value=True),
                ft.Checkbox(label="Allow copying text and images", value=True),
                ft.Checkbox(label="Allow editing", value=False),
                ft.Checkbox(label="Allow adding comments", value=True),
                ft.Checkbox(label="Allow form filling", value=True),
            ]),
            visible=False,
            padding=10,
            border_radius=5,
            border=ft.Border.all(1, ft.Colors.GREY_400),
            margin=ft.Margin.only(top=10, bottom=10),
        )
        
        # Button for applying security operation
        self.apply_button = ft.Button(
            "Apply",
            icon=ft.Icons.SECURITY,
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
                    theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
                ),
                ft.Text(
                    "Encrypt, decrypt, and manage PDF security",
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM,
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
        run_background(self.page, self.security_operations[operation])

    def set_current_file(self, file_path):
        """Receive the active file selection from the application shell."""
        self.current_file = file_path
    
    def encrypt_pdf(self):
        """Encrypt a PDF file with modern AES-256 and granular permissions."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF encryption...")
            
            password = self.password_input.value
            permissions = self.permissions_container.content.controls
            allow_printing = permissions[1].value
            allow_copying = permissions[2].value
            allow_editing = permissions[3].value
            allow_comments = permissions[4].value
            allow_forms = permissions[5].value
            
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "encrypted", ".pdf")
            )
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Securing document with AES-256...")
            engine_encrypt_pdf(
                self.current_file,
                output_file,
                user_password=password,
                allow_printing=allow_printing,
                allow_copying=allow_copying,
                allow_editing=allow_editing,
                allow_annotations=allow_comments,
                allow_forms=allow_forms,
            )
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Encryption complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"PDF successfully encrypted (AES-256): {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error encrypting PDF: {str(e)}", "error")
    
    def decrypt_pdf(self):
        """Decrypt a PDF file using a password."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting PDF decryption...")
            
            password = self.password_input.value
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "decrypted", ".pdf")
            )
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Authenticating and decrypting...")
            engine_decrypt_pdf(self.current_file, output_file, password)
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Decryption complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"PDF successfully decrypted: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error decrypting PDF: {str(e)}", "error")
    
    def add_permission_password(self):
        """Add an owner permission password to a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting permission password addition...")
            
            password = self.password_input.value
            permissions = self.permissions_container.content.controls
            allow_printing = permissions[1].value
            allow_copying = permissions[2].value
            allow_editing = permissions[3].value
            allow_comments = permissions[4].value
            allow_forms = permissions[5].value
            
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "permission_added", ".pdf")
            )
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Setting document permissions...")
            engine_encrypt_pdf(
                self.current_file,
                output_file,
                user_password="",
                owner_password=password,
                allow_printing=allow_printing,
                allow_copying=allow_copying,
                allow_editing=allow_editing,
                allow_annotations=allow_comments,
                allow_forms=allow_forms,
            )
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Permission password addition complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Permission password successfully added: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error adding permission password: {str(e)}", "error")
    
    def remove_password(self):
        """Remove password protection from a PDF file."""
        try:
            update_progress(self.progress_bar, self.progress_text, 0.1, "Starting password removal...")
            
            password = self.password_input.value
            output_file = os.path.join(
                self.output_dir, 
                generate_output_filename(self.current_file, "password_removed", ".pdf")
            )
            
            update_progress(self.progress_bar, self.progress_text, 0.5, "Validating password and removing security...")
            engine_decrypt_pdf(self.current_file, output_file, password)
            
            update_progress(self.progress_bar, self.progress_text, 1.0, "Password removal complete!")
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Password successfully removed: {output_file}", "success")
            
        except Exception as e:
            reset_progress(self.progress_bar, self.progress_text)
            show_snackbar(self.page, f"Error removing password: {str(e)}", "error")
