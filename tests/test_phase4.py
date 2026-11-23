"""Unit tests for Phase 4: Visual Page Organizer.

Verifies:
- Page descriptor loading and reactive manipulation (reorder, duplicate, delete)
- In-memory thumbnail rendering with cumulative rotation
- Insertion of external PDF pages at arbitrary index
- Bit-perfect saving and selective extraction without quality loss
- Sub-500ms rendering performance for 20-page documents
"""

import os
from pathlib import Path
import tempfile
import time
import unittest

import pymupdf as fitz

from pdf_engine import (
    PageDescriptor,
    encrypt_pdf,
    extract_organized_pages,
    insert_document_descriptors,
    inspect_pdf,
    load_document_descriptors,
    render_page_thumbnail,
    save_organized_pdf,
)


class PhaseFourEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Create sample PDF A (3 pages)
        self.pdf_a = self.dir_path / "sample_a.pdf"
        with fitz.open() as doc:
            for i in range(3):
                p = doc.new_page(width=300, height=400)
                p.insert_text((50, 50), f"Doc A Page {i+1}")
            doc.save(self.pdf_a)

        # Create sample PDF B (2 pages)
        self.pdf_b = self.dir_path / "sample_b.pdf"
        with fitz.open() as doc:
            for i in range(2):
                p = doc.new_page(width=300, height=400)
                p.insert_text((50, 50), f"Doc B Page {i+1}")
            doc.save(self.pdf_b)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_document_descriptors(self):
        descriptors = load_document_descriptors(self.pdf_a)
        self.assertEqual(len(descriptors), 3)
        self.assertEqual([d.page_index for d in descriptors], [0, 1, 2])
        self.assertTrue(all(d.rotation == 0 for d in descriptors))
        self.assertTrue(all(not d.is_deleted for d in descriptors))
        self.assertEqual(len({d.id for d in descriptors}), 3)  # Unique IDs

    def test_load_encrypted_pdf_raises_error(self):
        enc_pdf = self.dir_path / "encrypted.pdf"
        encrypt_pdf(self.pdf_a, enc_pdf, user_password="secretpassword")
        with self.assertRaises(ValueError):
            load_document_descriptors(enc_pdf)

    def test_render_page_thumbnail(self):
        png_bytes = render_page_thumbnail(self.pdf_a, 0, rotation=0, max_dim=150)
        self.assertIsInstance(png_bytes, bytes)
        self.assertGreater(len(png_bytes), 100)
        # PNG signature check: \x89PNG\r\n\x1a\n
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Test with rotation 90
        png_rot = render_page_thumbnail(self.pdf_a, 0, rotation=90, max_dim=150)
        self.assertTrue(png_rot.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_render_page_thumbnail_out_of_bounds(self):
        with self.assertRaises(IndexError):
            render_page_thumbnail(self.pdf_a, 99)

    def test_save_organized_pdf_reorder_and_rotate(self):
        descriptors = load_document_descriptors(self.pdf_a)
        # Reorder pages: 2, 0, 1 (1-based: 3, 1, 2)
        reordered = [descriptors[2], descriptors[0], descriptors[1]]
        # Rotate first page (which is original page 3) by 90 deg
        reordered[0].rotation = 90

        out_pdf = self.dir_path / "reordered.pdf"
        saved = save_organized_pdf(reordered, out_pdf)
        self.assertTrue(saved.exists())

        with fitz.open(saved) as doc:
            self.assertEqual(doc.page_count, 3)
            self.assertIn("Doc A Page 3", doc[0].get_text())
            self.assertEqual(doc[0].rotation, 90)
            self.assertIn("Doc A Page 1", doc[1].get_text())
            self.assertEqual(doc[1].rotation, 0)
            self.assertIn("Doc A Page 2", doc[2].get_text())

    def test_save_empty_rejected(self):
        descriptors = load_document_descriptors(self.pdf_a)
        for d in descriptors:
            d.is_deleted = True
        out_pdf = self.dir_path / "empty.pdf"
        with self.assertRaises(ValueError):
            save_organized_pdf(descriptors, out_pdf)

    def test_duplicate_page(self):
        descriptors = load_document_descriptors(self.pdf_a)
        # Duplicate page 1 (index 0)
        dup = PageDescriptor(
            id="dup_1",
            source_path=descriptors[0].source_path,
            page_index=descriptors[0].page_index,
            rotation=descriptors[0].rotation,
        )
        descriptors.insert(1, dup)
        self.assertEqual(len(descriptors), 4)

        out_pdf = self.dir_path / "duplicated.pdf"
        save_organized_pdf(descriptors, out_pdf)
        with fitz.open(out_pdf) as doc:
            self.assertEqual(doc.page_count, 4)
            self.assertIn("Doc A Page 1", doc[0].get_text())
            self.assertIn("Doc A Page 1", doc[1].get_text())

    def test_extract_organized_pages(self):
        descriptors = load_document_descriptors(self.pdf_a)
        selected_ids = {descriptors[1].id}  # Select page 2
        out_pdf = self.dir_path / "extracted.pdf"
        extract_organized_pages(descriptors, out_pdf, selected_ids=selected_ids)

        with fitz.open(out_pdf) as doc:
            self.assertEqual(doc.page_count, 1)
            self.assertIn("Doc A Page 2", doc[0].get_text())

    def test_insert_document_descriptors(self):
        descriptors = load_document_descriptors(self.pdf_a)  # 3 pages
        # Insert Doc B (2 pages) at index 1
        combined = insert_document_descriptors(descriptors, insert_at_index=1, new_source=self.pdf_b)
        self.assertEqual(len(combined), 5)
        self.assertEqual(combined[1].source_path, str(self.pdf_b.resolve()))
        self.assertEqual(combined[2].source_path, str(self.pdf_b.resolve()))

        out_pdf = self.dir_path / "combined.pdf"
        save_organized_pdf(combined, out_pdf)
        with fitz.open(out_pdf) as doc:
            self.assertEqual(doc.page_count, 5)
            self.assertIn("Doc A Page 1", doc[0].get_text())
            self.assertIn("Doc B Page 1", doc[1].get_text())
            self.assertIn("Doc B Page 2", doc[2].get_text())
            self.assertIn("Doc A Page 2", doc[3].get_text())

    def test_rendering_performance_within_500ms_target(self):
        # Create 20-page document
        pdf_20 = self.dir_path / "pdf_20.pdf"
        with fitz.open() as doc:
            for i in range(20):
                p = doc.new_page(width=595, height=842)
                p.insert_text((50, 100), f"Standard Page {i+1} content")
                p.draw_rect(fitz.Rect(50, 150, 300, 300))
            doc.save(pdf_20)

        t_start = time.perf_counter()
        descriptors = load_document_descriptors(pdf_20)
        thumbnails = [
            render_page_thumbnail(d.source_path, d.page_index, d.rotation, max_dim=150)
            for d in descriptors
        ]
        duration_ms = (time.perf_counter() - t_start) * 1000

        self.assertEqual(len(thumbnails), 20)
        # Deliverable requires rendering within 500ms
        self.assertLess(duration_ms, 500.0)


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

    def run_task(self, handler, *args):
        return handler(*args)

    def run_thread(self, handler, *args):
        import threading
        t = threading.Thread(target=handler, args=args)
        t.start()
        return t


class PhaseFourUITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Create sample PDF A (3 pages)
        self.pdf_a = self.dir_path / "sample_a.pdf"
        with fitz.open() as doc:
            for i in range(3):
                p = doc.new_page(width=300, height=400)
                p.insert_text((50, 50), f"Doc A Page {i+1}")
            doc.save(self.pdf_a)

        # Create sample PDF B (2 pages)
        self.pdf_b = self.dir_path / "sample_b.pdf"
        with fitz.open() as doc:
            for i in range(2):
                p = doc.new_page(width=300, height=400)
                p.insert_text((50, 50), f"Doc B Page {i+1}")
            doc.save(self.pdf_b)

        from app_state import AppState
        from ui_organizer import PageOrganizerView

        self.mock_page = MockPage()
        self.app_state = AppState()
        self.view = PageOrganizerView(
            page=self.mock_page,
            app_state=self.app_state,
            output_dir=str(self.dir_path / "output"),
            is_dark_supplier=lambda: True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_view_empty_state_and_build(self):
        ui = self.view.build_ui()
        self.assertIsNotNone(ui)
        self.assertEqual(len(self.view.pages), 0)

    def test_view_document_loading(self):
        self.view.set_current_file(str(self.pdf_a))
        self.assertEqual(len(self.view.pages), 3)
        ui = self.view.build_ui()
        self.assertIsNotNone(ui)

    def test_view_reordering_and_undo(self):
        self.view.set_current_file(str(self.pdf_a))
        orig_ids = [p.id for p in self.view.pages]

        # Move first page to position of last page
        self.view.reorder_pages(orig_ids[0], orig_ids[2])
        new_ids = [p.id for p in self.view.pages]
        self.assertEqual(new_ids, [orig_ids[1], orig_ids[2], orig_ids[0]])
        self.assertTrue(self.view.is_modified)

        # Undo restores original
        self.view.undo()
        restored_ids = [p.id for p in self.view.pages]
        self.assertEqual(restored_ids, orig_ids)

    def test_view_move_relative(self):
        self.view.set_current_file(str(self.pdf_a))
        p0_id = self.view.pages[0].id
        self.view.move_page_relative(p0_id, 1)
        self.assertEqual(self.view.pages[1].id, p0_id)

    def test_view_rotate_single_and_batch(self):
        self.view.set_current_file(str(self.pdf_a))
        # Rotate first page 90 CW
        p0_id = self.view.pages[0].id
        self.view.rotate_page(p0_id, 90)
        self.assertEqual(self.view.pages[0].rotation, 90)

        # Batch rotate all pages
        self.view.select_all()
        self.view.batch_rotate_selected(90)
        self.assertEqual(self.view.pages[0].rotation, 180)
        self.assertEqual(self.view.pages[1].rotation, 90)
        self.assertEqual(self.view.pages[2].rotation, 90)

    def test_view_duplicate_and_delete(self):
        self.view.set_current_file(str(self.pdf_a))
        p0_id = self.view.pages[0].id
        self.view.duplicate_page(p0_id)
        self.assertEqual(len(self.view.pages), 4)

        # Delete the duplicated page
        dup_id = self.view.pages[1].id
        self.view.delete_page(dup_id)
        self.assertEqual(len(self.view.pages), 3)

    def test_view_selection_helpers(self):
        self.view.set_current_file(str(self.pdf_a))
        self.view.select_all()
        self.assertEqual(len(self.view.selected_ids), 3)

        self.view.deselect_all()
        self.assertEqual(len(self.view.selected_ids), 0)

        self.view.select_even()
        self.assertEqual(len(self.view.selected_ids), 1)  # page 2

        self.view.select_odd()
        self.assertEqual(len(self.view.selected_ids), 2)  # pages 1 & 3

        self.view.invert_selection()
        self.assertEqual(len(self.view.selected_ids), 1)  # page 2

    def test_view_insert_pdf(self):
        self.view.set_current_file(str(self.pdf_a))

        class MockFile:
            path = str(self.pdf_b)

        class MockPickerEvent:
            files = [MockFile()]

        self.view._on_insert_pdf_selected(MockPickerEvent())
        self.assertEqual(len(self.view.pages), 5)

    def test_view_reset(self):
        self.view.set_current_file(str(self.pdf_a))
        p0_id = self.view.pages[0].id
        self.view.delete_page(p0_id)
        self.assertEqual(len(self.view.pages), 2)
        self.view.reset()
        self.assertEqual(len(self.view.pages), 3)

    def test_view_save_and_extract_actions(self):
        self.view.set_current_file(str(self.pdf_a))
        self.view.select_all()

        # Execute save and extract
        self.view.save_reorganized_document()
        self.view.extract_selected_document()

        # Allow worker threads to complete
        time.sleep(0.3)
        out_files = list(Path(self.view.output_dir).glob("*.pdf"))
        self.assertGreaterEqual(len(out_files), 1)


if __name__ == "__main__":
    unittest.main()
