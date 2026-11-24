"""Unit tests for Phase 5: True Offline OCR & Searchable PDF Engine.

Verifies:
- Tessdata discovery and multi-language model listing (English, French, German, Spanish)
- Image pre-processing: deskewing algorithm, binarization, and format compatibility
- Dual-layer searchable PDF generation with pixel-perfect visual scans & Ctrl+F selectable text
- Text extraction tool to plain string, structured Markdown, and local file exports
- UI ergonomics: OfflineOCRView controls, reactive file updates, clipboard actions
"""

import os
from pathlib import Path
import tempfile
import time
import unittest

import cv2
import numpy as np
from PIL import Image
import pymupdf as fitz

from app_state import AppState
from pdf_engine import (
    encrypt_pdf,
    export_ocr_text_file,
    extract_document_ocr_text,
    generate_searchable_pdf,
    get_available_ocr_languages,
    get_tessdata_path,
    preprocess_image_for_ocr,
)
from ui_ocr import OfflineOCRView


class PhaseFiveEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Create sample PDF with rendered text (2 pages)
        self.pdf_sample = self.dir_path / "sample_scanned.pdf"
        with fitz.open() as doc:
            p1 = doc.new_page(width=500, height=300)
            p1.insert_text((50, 80), "PURCHASE ORDER INVOICE #98765", fontsize=18)
            p1.insert_text((50, 140), "Total Payable: USD $1,250.00", fontsize=14)

            p2 = doc.new_page(width=500, height=300)
            p2.insert_text((50, 80), "CONFIDENTIAL AGREEMENT TERMS", fontsize=18)
            p2.insert_text((50, 140), "Authorized Signature: Verified", fontsize=14)
            doc.save(self.pdf_sample)

        # Create sample image
        self.img_sample = self.dir_path / "sample_receipt.png"
        img = Image.new("RGB", (400, 150), color=(255, 255, 255))
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        d.text((30, 50), "OFFLINE RECEIPT RECEIPT123", fill=(0, 0, 0))
        img.save(self.img_sample)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_tessdata_path(self):
        tess_path = get_tessdata_path()
        self.assertTrue(os.path.isdir(tess_path))
        # Ensure at least eng.traineddata exists
        self.assertTrue(os.path.exists(os.path.join(tess_path, "eng.traineddata")))

    def test_get_tessdata_path_custom_and_invalid(self):
        # Custom valid
        tess_path = get_tessdata_path(self.dir_path)
        self.assertEqual(tess_path, str(self.dir_path.resolve()))

        # Non-existent custom path raises FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            get_tessdata_path("/non/existent/path/for/ocr/tests/xyz")

    def test_get_available_ocr_languages(self):
        langs = get_available_ocr_languages()
        self.assertIsInstance(langs, list)
        self.assertGreaterEqual(len(langs), 1)

        codes = [code for code, _ in langs]
        self.assertIn("eng", codes)
        self.assertNotIn("osd", codes)  # osd filtered from primary list

        # If fra, deu, spa are present, verify them
        tess_dir = Path(get_tessdata_path())
        if (tess_dir / "fra.traineddata").exists():
            self.assertIn("fra", codes)
        if (tess_dir / "deu.traineddata").exists():
            self.assertIn("deu", codes)
        if (tess_dir / "spa.traineddata").exists():
            self.assertIn("spa", codes)

    def test_preprocess_image_straight(self):
        # Straight image test
        img = np.ones((200, 400, 3), dtype=np.uint8) * 255
        cv2.putText(img, "Straight Text Testing 123", (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        pix, angle = preprocess_image_for_ocr(img, deskew=True, binarize=False)
        self.assertIsInstance(pix, fitz.Pixmap)
        self.assertEqual(pix.width, 400)
        self.assertEqual(pix.height, 200)
        self.assertLess(abs(angle), 1.0)

    def test_preprocess_image_skewed(self):
        # Skewed image test (~7 degrees)
        img = np.ones((300, 500, 3), dtype=np.uint8) * 255
        cv2.putText(img, "Skewed Agreement Document Title", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        M = cv2.getRotationMatrix2D((250, 150), 7.0, 1.0)
        skewed = cv2.warpAffine(img, M, (500, 300), borderValue=(255, 255, 255))

        pix, angle = preprocess_image_for_ocr(skewed, deskew=True, binarize=True)
        self.assertIsInstance(pix, fitz.Pixmap)
        self.assertNotEqual(angle, 0.0)
        self.assertGreaterEqual(abs(angle), 3.0)

    def test_preprocess_image_with_pil_and_pixmap_inputs(self):
        # PIL input
        pil_img = Image.new("RGB", (200, 100), (255, 255, 255))
        pix1, _ = preprocess_image_for_ocr(pil_img, deskew=False, binarize=True)
        self.assertEqual(pix1.width, 200)

        # Pixmap input
        with fitz.open(self.pdf_sample) as doc:
            orig_pix = doc[0].get_pixmap()
            pix2, _ = preprocess_image_for_ocr(orig_pix, deskew=True, binarize=False)
            self.assertEqual(pix2.width, orig_pix.width)

    def test_generate_searchable_pdf_success(self):
        out_pdf = self.dir_path / "searchable_output.pdf"
        progress_events = []

        def on_progress(cur, tot, msg):
            progress_events.append((cur, tot, msg))

        result = generate_searchable_pdf(
            source=self.pdf_sample,
            output_path=out_pdf,
            language="eng",
            dpi=150,
            deskew=False,
            binarize=False,
            progress_callback=on_progress,
        )
        self.assertTrue(result.exists())
        self.assertGreater(len(progress_events), 0)

        # Verify dual-layer searchable PDF structure
        with fitz.open(result) as doc:
            self.assertEqual(doc.page_count, 2)

            # Check Page 1
            p1 = doc[0]
            self.assertGreaterEqual(len(p1.get_images()), 1)  # High-res scan image
            p1_text = p1.get_text()
            self.assertIn("INVOICE", p1_text)
            self.assertIn("98765", p1_text)

            # Search with Ctrl+F coordinates
            p1_rects = p1.search_for("INVOICE")
            self.assertGreater(len(p1_rects), 0)

            # Check Page 2
            p2 = doc[1]
            p2_text = p2.get_text()
            self.assertIn("AGREEMENT", p2_text)
            p2_rects = p2.search_for("AGREEMENT")
            self.assertGreater(len(p2_rects), 0)

    def test_generate_searchable_pdf_from_image_input(self):
        out_pdf = self.dir_path / "receipt_searchable.pdf"
        result = generate_searchable_pdf(
            source=self.img_sample,
            output_path=out_pdf,
            language="eng",
            dpi=150,
            deskew=False,
            binarize=False,
        )
        self.assertTrue(result.exists())
        with fitz.open(result) as doc:
            self.assertEqual(doc.page_count, 1)
            text = doc[0].get_text()
            self.assertIn("RECEIPT", text)

    def test_generate_searchable_pdf_encrypted_fails(self):
        enc_pdf = self.dir_path / "locked.pdf"
        encrypt_pdf(self.pdf_sample, enc_pdf, user_password="secretpassword")

        with self.assertRaises(ValueError):
            generate_searchable_pdf(enc_pdf, self.dir_path / "out.pdf")

    def test_extract_document_ocr_text_plain(self):
        text = extract_document_ocr_text(
            source=self.pdf_sample,
            language="eng",
            dpi=150,
            deskew=False,
            binarize=False,
            format_type="plain",
        )
        self.assertIsInstance(text, str)
        self.assertIn("INVOICE", text)
        self.assertIn("AGREEMENT", text)
        self.assertIn("--- Page 1 ---", text)
        self.assertIn("--- Page 2 ---", text)

    def test_extract_document_ocr_text_markdown(self):
        text = extract_document_ocr_text(
            source=self.pdf_sample,
            language="eng",
            dpi=150,
            deskew=False,
            binarize=False,
            format_type="markdown",
        )
        self.assertIn("## Page 1", text)
        self.assertIn("## Page 2", text)
        self.assertIn("---", text)
        self.assertIn("INVOICE", text)

    def test_export_ocr_text_file(self):
        # Plain text export
        txt_path = self.dir_path / "extracted.txt"
        saved_txt = export_ocr_text_file(self.pdf_sample, txt_path, format_type="plain")
        self.assertTrue(saved_txt.exists())
        content = saved_txt.read_text(encoding="utf-8")
        self.assertIn("INVOICE", content)

        # Markdown export
        md_path = self.dir_path / "extracted.md"
        saved_md = export_ocr_text_file(self.pdf_sample, md_path, format_type="markdown")
        self.assertTrue(saved_md.exists())
        md_content = saved_md.read_text(encoding="utf-8")
        self.assertIn("## Page 1", md_content)


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
        self.clipboard = ""

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
        t.join(timeout=10.0)  # Wait for thread completion during testing
        return t

    def set_clipboard(self, text):
        self.clipboard = text


class PhaseFiveUITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Create sample document
        self.sample_pdf = self.dir_path / "test_ui_sample.pdf"
        with fitz.open() as doc:
            p = doc.new_page(width=400, height=200)
            p.insert_text((40, 60), "UI TEST OCR DOCUMENT", fontsize=16)
            doc.save(self.sample_pdf)

        self.mock_page = MockPage()
        self.app_state = AppState()
        self.progress_bar = fitz.open  # dummy placeholder
        import flet as ft
        self.pb = ft.ProgressBar()
        self.pt = ft.Text()

        self.view = OfflineOCRView(
            page=self.mock_page,
            app_state=self.app_state,
            output_dir=str(self.dir_path),
            progress_bar=self.pb,
            progress_text=self.pt,
            is_dark_supplier=lambda: True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_ui_dark_and_light(self):
        # Dark mode build
        ui_dark = self.view.build_ui()
        self.assertIsNotNone(ui_dark)

        # Light mode build
        self.view.is_dark_supplier = lambda: False
        ui_light = self.view.build_ui()
        self.assertIsNotNone(ui_light)

    def test_reactive_set_current_file(self):
        self.view.set_current_file(str(self.sample_pdf))
        self.assertEqual(self.view.current_file, str(self.sample_pdf))
        self.assertEqual(self.view.extracted_text, "")

    def test_ui_generate_searchable_pdf(self):
        self.app_state.select_file(str(self.sample_pdf))
        self.view.set_current_file(str(self.sample_pdf))
        self.view._dpi_dropdown.value = "150"
        self.view._deskew_switch.value = False
        self.view._binarize_switch.value = False

        self.view._on_generate_searchable_clicked(None)
        self.assertIsNotNone(self.view.last_searchable_output)
        self.assertTrue(os.path.exists(self.view.last_searchable_output))

    def test_ui_extract_text_and_clipboard_copy(self):
        self.app_state.select_file(str(self.sample_pdf))
        self.view.set_current_file(str(self.sample_pdf))
        self.view._dpi_dropdown.value = "150"
        self.view._deskew_switch.value = False
        self.view._binarize_switch.value = False

        # Run text extraction
        self.view._on_extract_text_clicked(None)
        self.assertIn("UI TEST OCR DOCUMENT", self.view.extracted_text)
        self.assertEqual(self.view._text_preview.value, self.view.extracted_text)

        # Copy to clipboard
        self.view._on_copy_clipboard_clicked(None)
        self.assertEqual(self.mock_page.clipboard, self.view.extracted_text)

    def test_ui_save_file_to_disk(self):
        self.app_state.select_file(str(self.sample_pdf))
        self.view.set_current_file(str(self.sample_pdf))
        self.view.extracted_text = "Recognized text to be saved directly to disk"
        self.view._text_preview.value = self.view.extracted_text

        self.view._on_save_file_clicked(None)
        # Verify a file was created in output_dir
        saved_files = list(self.dir_path.glob("test_ui_sample_ocr_text_*.txt"))
        self.assertEqual(len(saved_files), 1)
        self.assertIn("Recognized text to be saved", saved_files[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
