import os
from pathlib import Path
import tempfile
import unittest
import pymupdf as fitz

from app_state import AppState
from theme import ThemeTokens, make_badge
from ui_inspector import DocumentInspector, format_file_size
from main import PDFOpsApp


class PhaseThreeUITests(unittest.TestCase):
    def test_theme_tokens_and_badge(self):
        self.assertEqual(ThemeTokens.bg_app(is_dark=True), ThemeTokens.DARK_BG_APP)
        self.assertEqual(ThemeTokens.bg_app(is_dark=False), ThemeTokens.LIGHT_BG_APP)
        self.assertEqual(ThemeTokens.text_primary(is_dark=True), ThemeTokens.DARK_TEXT_PRIMARY)
        self.assertEqual(ThemeTokens.text_primary(is_dark=False), ThemeTokens.LIGHT_TEXT_PRIMARY)

        badge = make_badge("Active", "#10B981", "#FFFFFF")
        self.assertIsNotNone(badge)
        self.assertEqual(badge.bgcolor, "#10B981")

    def test_format_file_size(self):
        self.assertEqual(format_file_size(500), "500 B")
        self.assertEqual(format_file_size(1500), "1.5 KB")
        self.assertEqual(format_file_size(4 * 1024 * 1024), "4.00 MB")

    def test_inspector_empty_and_active_states(self):
        class MockPage:
            def update(self):
                pass

        inspector = DocumentInspector(MockPage(), lambda: True)
        self.assertIsNone(inspector.current_file)
        # Empty state renders without crash
        inspector.refresh()

        # Active PDF state renders without crash
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "test.pdf"
            with fitz.open() as doc:
                doc.new_page(width=200, height=300)
                doc.save(pdf_path)

            inspector.set_file(str(pdf_path))
            self.assertEqual(inspector.current_file, str(pdf_path))

    def test_main_app_initialization(self):
        app = PDFOpsApp()
        self.assertTrue(app.is_dark_theme)
        self.assertEqual(app.active_tool_id, "quick")
        self.assertGreater(len(app.nav_destinations), 4)

        # Verify state subscription
        app.state.select_file("/tmp/doc.pdf")
        self.assertEqual(app.state.current_file, "/tmp/doc.pdf")

    def test_main_app_render_all_layouts_and_tools(self):
        class MockWindow:
            width = 1200
            height = 800
            min_width = 400
            min_height = 400

        class MockPage:
            def __init__(self):
                self.title = ""
                self.theme_mode = None
                self.padding = 0
                self.spacing = 0
                self.window = MockWindow()
                self.services = []
                self.overlay = []
                self.controls = []
                self.width = 1200
                self.height = 800
                self.appbar = None
                self.navigation_bar = None
                self.on_keyboard_event = None
                self.on_resize = None
                self.snack_bar = None

            def clean(self):
                self.controls.clear()

            def add(self, *controls):
                self.controls.extend(controls)

            def update(self):
                pass

        page = MockPage()
        app = PDFOpsApp()
        app.main(page)

        # Verify all tools render cleanly
        for tid, _, _, _ in app.nav_destinations:
            app.switch_tool(tid)
            self.assertEqual(app.active_tool_id, tid)

        # Verify compact layout (Android mode)
        app.is_compact = True
        app.render_layout()
        self.assertIsNotNone(page.navigation_bar)

        # Verify desktop layout restore
        app.is_compact = False
        app.render_layout()
        self.assertIsNone(page.navigation_bar)

        # Verify theme toggle
        app.toggle_theme(None)
        self.assertFalse(app.is_dark_theme)

    def test_trigger_file_browser_awaits_pick_files(self):
        import asyncio
        import types

        class MockWindow:
            width = 1200
            height = 800
            min_width = 400
            min_height = 400

        class MockPage:
            def __init__(self):
                self.title = ""
                self.theme_mode = None
                self.padding = 0
                self.spacing = 0
                self.window = MockWindow()
                self.services = []
                self.overlay = []
                self.controls = []
                self.width = 1200
                self.height = 800
                self.appbar = None
                self.navigation_bar = None
                self.on_keyboard_event = None
                self.on_resize = None
                self.snack_bar = None

            def clean(self):
                self.controls.clear()

            def add(self, *controls):
                self.controls.extend(controls)

            def update(self):
                pass

            def run_task(self, handler, *args, **kwargs):
                return asyncio.run(handler(*args, **kwargs))

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "picked.pdf"
            with fitz.open() as doc:
                doc.new_page(width=200, height=200)
                doc.save(pdf_path)

            page = MockPage()
            app = PDFOpsApp()
            app.main(page)

            captured_kwargs = {}

            async def fake_pick_files(**kwargs):
                captured_kwargs.update(kwargs)
                return [types.SimpleNamespace(path=str(pdf_path))]

            app.file_picker.pick_files = fake_pick_files
            app.trigger_file_browser()
            self.assertEqual(app.state.current_file, str(pdf_path))
            self.assertEqual(captured_kwargs.get("dialog_title"), "Select Document — PDF-Ops")

    def test_converter_filters_options_and_reports_capability(self):
        from unittest.mock import patch
        import flet as ft
        from convert import PDFConverter

        class MockPage:
            def __init__(self):
                self.services = []
                self.snack_bar = None

            def update(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            docx_path = Path(temp_dir) / "sample.docx"
            with fitz.open() as doc:
                doc.new_page(width=200, height=200)
                doc.save(pdf_path)
            docx_path.write_bytes(b"dummy")

            page = MockPage()
            converter = PDFConverter(page, ft.ProgressBar(), ft.Text(), temp_dir)
            converter.build_ui()

            # Load PDF -> only PDF-* options shown, Word/Excel/PPT-to-PDF excluded
            converter.set_current_file(str(pdf_path))
            option_keys = [opt.key or opt.text for opt in converter.conversion_dropdown.options]
            self.assertEqual(
                option_keys,
                ["PDF to Word", "PDF to Images", "PDF to Excel", "PDF to PowerPoint"],
            )
            self.assertNotIn("Word to PDF", option_keys)
            self.assertEqual(converter.conversion_dropdown.value, "PDF to Word")
            self.assertFalse(converter.convert_button.disabled)
            self.assertFalse(converter.status_banner.visible)

            # Selecting unsupported PDF to PowerPoint disables button & shows explanation
            converter.conversion_dropdown.value = "PDF to PowerPoint"
            converter._on_conversion_change(None)
            self.assertTrue(converter.convert_button.disabled)
            self.assertTrue(converter.status_banner.visible)

            # Selecting PDF to Images re-enables button and shows DPI/format
            converter.conversion_dropdown.value = "PDF to Images"
            converter._on_conversion_change(None)
            self.assertFalse(converter.convert_button.disabled)
            self.assertTrue(converter.image_dpi.visible)

            # Load DOCX with no LibreOffice -> only Word to PDF shown, disabled with notice
            with patch("convert.find_office_converter", return_value=None):
                converter.set_current_file(str(docx_path))
                docx_options = [opt.key or opt.text for opt in converter.conversion_dropdown.options]
                self.assertEqual(docx_options, ["Word to PDF"])
                self.assertTrue(converter.convert_button.disabled)
                self.assertTrue(converter.status_banner.visible)


if __name__ == "__main__":
    unittest.main()
