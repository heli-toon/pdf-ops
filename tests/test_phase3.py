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


if __name__ == "__main__":
    unittest.main()
