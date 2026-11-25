"""Unit tests for Phase 6: Permanent Redaction & Metadata Sanitizer.

Verifies:
- Pattern auto-redaction scanner (Email, Phone, SSN, Credit Card, Custom Regex)
- Permanent stream-level redaction of text, vectors, and bitmap image pixels
- Zero-leakage verification (cannot copy, search, extract, or read from streams)
- Metadata inspection & 1-click purge (Info dict, timestamps, XMP XML, thumbnails,
  color profiles / OutputIntents, embedded files) with deletion report
- Interactive UI ergonomics: RedactionSanitizerView canvas drag selection,
  pattern match toggles, 1-click sanitize, and combined export
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import unittest

import flet as ft
import numpy as np
from PIL import Image
import pymupdf as fitz

from app_state import AppState
from pdf_engine import (
    RedactionBox,
    apply_pdf_redactions,
    encrypt_pdf,
    inspect_pdf_metadata,
    render_redaction_page_preview,
    sanitize_pdf_metadata,
    scan_pdf_patterns,
    verify_zero_leakage,
)
from ui_redaction import RedactionSanitizerView


class _DummyOffset:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class _DummyDragEvent:
    def __init__(self, x: float, y: float):
        self.local_position = _DummyOffset(x, y)


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

    def run_thread(self, handler, *args):
        t = threading.Thread(target=handler, args=args)
        t.start()
        t.join(timeout=10.0)
        return t


class PhaseSixEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Create multi-page PDF with sensitive patterns, vector art, and rich metadata
        self.sample_pdf = self.dir_path / "confidential_contract.pdf"
        with fitz.open() as doc:
            p1 = doc.new_page(width=595, height=842)
            p1.insert_text((50, 80), "CONFIDENTIAL EMPLOYEE RECORD", fontsize=16)
            p1.insert_text((50, 120), "Contact Email: jane.doe@secretcorp.org", fontsize=12)
            p1.insert_text((50, 150), "Direct Phone: (415) 555-0198", fontsize=12)
            p1.insert_text((50, 180), "SSN: 123-45-6789", fontsize=12)
            p1.insert_text((50, 210), "Corporate Card: 4532-0155-1234-5678", fontsize=12)
            p1.insert_text((50, 250), "Codename: PROJECT-FALCON", fontsize=12)
            p1.draw_rect(fitz.Rect(50, 290, 220, 340), color=(1, 0, 0), fill=(0.9, 0.2, 0.2))

            p2 = doc.new_page(width=595, height=842)
            p2.insert_text((50, 80), "Page 2 Backup Contact: ops@internal.example.com", fontsize=12)
            p2.insert_text((50, 120), "Public Reference: Normal visible text", fontsize=12)

            doc.set_metadata(
                {
                    "title": "Top Secret Personnel File",
                    "author": "Jane Smith",
                    "subject": "HR Confidential",
                    "keywords": "ssn, payroll, private",
                    "creator": "Internal HR Exporter v2.4",
                    "producer": "PyMuPDF Test Producer",
                    "creationDate": "D:20261101120000Z",
                    "modDate": "D:20261110153000Z",
                }
            )
            doc.set_xml_metadata(
                '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
                '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                "<dc:creator><rdf:Seq><rdf:li>Jane Smith</rdf:li></rdf:Seq></dc:creator>"
                "</rdf:Description></rdf:RDF></x:xmpmeta>"
            )
            doc.embfile_add("audit_note.txt", b"secret attachment payload")

            # Attach an OutputIntents dictionary and a page /Thumb xref to verify removal
            cat_xref = doc.pdf_catalog()
            oi_xref = doc.get_new_xref()
            doc.update_object(oi_xref, "<< /Type /OutputIntent /S /GTS_PDFA1 /OutputConditionIdentifier (sRGB) >>")
            doc.xref_set_key(cat_xref, "OutputIntents", f"[{oi_xref} 0 R]")

            thumb_xref = doc.get_new_xref()
            doc.update_object(thumb_xref, "<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /BitsPerComponent 8 /ColorSpace /DeviceGray >>")
            doc.update_stream(thumb_xref, b"\xff")
            doc.xref_set_key(doc[0].xref, "Thumb", f"{thumb_xref} 0 R")

            doc.save(self.sample_pdf)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scan_pdf_patterns_builtin_presets(self):
        matches = scan_pdf_patterns(self.sample_pdf)
        categories = {m.category for m in matches}
        texts = {m.matched_text for m in matches}

        self.assertIn("email", categories)
        self.assertIn("phone", categories)
        self.assertIn("ssn", categories)
        self.assertIn("credit_card", categories)

        self.assertIn("jane.doe@secretcorp.org", texts)
        self.assertIn("ops@internal.example.com", texts)
        self.assertIn("(415) 555-0198", texts)
        self.assertIn("123-45-6789", texts)
        self.assertIn("4532-0155-1234-5678", texts)

        for match in matches:
            self.assertGreater(len(match.rects), 0)

    def test_scan_pdf_patterns_custom_regex_and_invalid(self):
        matches = scan_pdf_patterns(
            self.sample_pdf,
            categories=[],
            custom_regex=r"\bPROJECT-[A-Z]+\b",
            case_sensitive=True,
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].category, "custom")
        self.assertEqual(matches[0].matched_text, "PROJECT-FALCON")

        with self.assertRaises(ValueError):
            scan_pdf_patterns(self.sample_pdf, categories=[], custom_regex="[unclosed")

    def test_apply_pdf_redactions_manual_and_zero_leakage(self):
        out_pdf = self.dir_path / "manual_redacted.pdf"
        with fitz.open(self.sample_pdf) as doc:
            codename_rects = doc[0].search_for("PROJECT-FALCON")
            self.assertEqual(len(codename_rects), 1)
            r = codename_rects[0]

        boxes = [
            RedactionBox(
                id="m1",
                page_index=0,
                rect=(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2),
                label="Manual Codename",
                matched_text="PROJECT-FALCON",
            ),
            # Redact over vector rectangle
            RedactionBox(
                id="m2",
                page_index=0,
                rect=(48, 288, 222, 342),
                label="Vector Graphic",
            ),
        ]

        res = apply_pdf_redactions(self.sample_pdf, out_pdf, redactions=boxes)
        self.assertTrue(Path(res["output_path"]).exists())
        self.assertEqual(res["pages_redacted"], 1)
        self.assertEqual(res["regions_applied"], 2)

        leak = verify_zero_leakage(out_pdf, ["PROJECT-FALCON"])
        self.assertTrue(leak["verified"])
        self.assertEqual(leak["leaked_strings"], [])

        # Confirm public text on page 2 remains intact
        with fitz.open(out_pdf) as doc_after:
            self.assertNotIn("PROJECT-FALCON", doc_after[0].get_text())
            self.assertEqual(doc_after[0].search_for("PROJECT-FALCON"), [])
            self.assertIn("Normal visible text", doc_after[1].get_text())

    def test_apply_pdf_redactions_patterns_and_image_pixels(self):
        # Create a PDF with a bright red bitmap image and redact half of it
        img_pdf = self.dir_path / "with_image.pdf"
        img_path = self.dir_path / "red_block.png"
        Image.new("RGB", (200, 100), color=(220, 20, 20)).save(img_path)

        with fitz.open() as doc:
            p = doc.new_page(width=400, height=300)
            p.insert_image(fitz.Rect(50, 50, 250, 150), filename=str(img_path))
            p.insert_text((50, 200), "Secret SSN 987-65-4321", fontsize=12)
            doc.save(img_pdf)

        matches = scan_pdf_patterns(img_pdf, categories=["ssn"])
        boxes = [
            RedactionBox(id="ssn1", page_index=0, rect=matches[0].rects[0], matched_text=matches[0].matched_text),
            RedactionBox(id="img1", page_index=0, rect=(50, 50, 150, 150), label="Left Image Half"),
        ]
        out_pdf = self.dir_path / "image_redacted.pdf"
        apply_pdf_redactions(img_pdf, out_pdf, redactions=boxes, fill_color=(0.0, 0.0, 0.0), redact_images=True)

        leak = verify_zero_leakage(out_pdf, ["987-65-4321"])
        self.assertTrue(leak["verified"])

        # Render output page and confirm left image half is black while right half remains red
        with fitz.open(out_pdf) as doc:
            pix = doc[0].get_pixmap(dpi=72, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
            left_sample = arr[100, 90]   # inside redacted half
            right_sample = arr[100, 200]  # outside redacted half
            self.assertLess(int(left_sample[0]), 30)
            self.assertGreater(int(right_sample[0]), 180)

    def test_inspect_and_sanitize_pdf_metadata(self):
        before = inspect_pdf_metadata(self.sample_pdf)
        self.assertGreaterEqual(len(before["info_fields"]), 6)
        self.assertEqual(before["info_fields"]["author"], "Jane Smith")
        self.assertTrue(before["has_xmp"])
        self.assertEqual(before["thumbnail_pages"], [1])
        self.assertTrue(before["has_output_intents"])
        self.assertEqual(before["embedded_files"], ["audit_note.txt"])

        sanitized_pdf = self.dir_path / "sanitized.pdf"
        report = sanitize_pdf_metadata(self.sample_pdf, sanitized_pdf)
        self.assertTrue(Path(report["output_path"]).exists())
        self.assertTrue(report["removed_xmp"])
        self.assertEqual(report["removed_thumbnails_count"], 1)
        self.assertGreaterEqual(report["removed_color_profiles_count"], 1)
        self.assertEqual(report["removed_embedded_files_count"], 1)
        self.assertGreater(len(report["deleted_items"]), 5)

        after = inspect_pdf_metadata(sanitized_pdf)
        self.assertEqual(after["info_fields"], {})
        self.assertFalse(after["has_xmp"])
        self.assertEqual(after["thumbnail_pages"], [])
        self.assertFalse(after["has_output_intents"])
        self.assertEqual(after["embedded_files"], [])
        self.assertEqual(after["total_findings"], 0)

    def test_combined_redaction_and_metadata_sanitization(self):
        matches = scan_pdf_patterns(self.sample_pdf)
        boxes = [
            RedactionBox(id=f"{m.id}_{i}", page_index=m.page_index, rect=r, matched_text=m.matched_text)
            for m in matches
            for i, r in enumerate(m.rects)
        ]
        out_pdf = self.dir_path / "redacted_and_sanitized.pdf"
        res = apply_pdf_redactions(self.sample_pdf, out_pdf, redactions=boxes, sanitize_metadata=True)

        self.assertIsNotNone(res["metadata_report"])
        leak = verify_zero_leakage(out_pdf, [m.matched_text for m in matches])
        self.assertTrue(leak["verified"])

        after_meta = inspect_pdf_metadata(out_pdf)
        self.assertEqual(after_meta["total_findings"], 0)

    def test_encrypted_pdf_rejected(self):
        enc_pdf = self.dir_path / "encrypted.pdf"
        encrypt_pdf(self.sample_pdf, enc_pdf, user_password="secret")

        with self.assertRaises(ValueError):
            scan_pdf_patterns(enc_pdf)
        with self.assertRaises(ValueError):
            inspect_pdf_metadata(enc_pdf)
        with self.assertRaises(ValueError):
            sanitize_pdf_metadata(enc_pdf, self.dir_path / "out.pdf")
        with self.assertRaises(ValueError):
            apply_pdf_redactions(
                enc_pdf,
                self.dir_path / "out2.pdf",
                [RedactionBox(id="1", page_index=0, rect=(10, 10, 50, 50))],
            )

    def test_render_redaction_page_preview(self):
        preview = render_redaction_page_preview(self.sample_pdf, page_index=0, max_width=400, max_height=500)
        self.assertIsInstance(preview["png_bytes"], bytes)
        self.assertGreater(len(preview["png_bytes"]), 100)
        self.assertEqual(preview["page_count"], 2)
        self.assertGreater(preview["scale"], 0.0)


class PhaseSixUITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        self.sample_pdf = self.dir_path / "ui_redaction_sample.pdf"
        with fitz.open() as doc:
            p1 = doc.new_page(width=500, height=700)
            p1.insert_text((50, 80), "Client Email: alice@acme.org", fontsize=14)
            p1.insert_text((50, 120), "SSN: 555-12-3456", fontsize=14)
            p1.insert_text((50, 160), "Public Footer Info", fontsize=12)
            doc.set_metadata({"author": "Confidential Author", "creator": "Secret Tool"})
            doc.save(self.sample_pdf)

        self.mock_page = MockPage()
        self.app_state = AppState()
        self.pb = ft.ProgressBar()
        self.pt = ft.Text()

        self.view = RedactionSanitizerView(
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
        self.assertIsNotNone(self.view.build_ui())
        self.view.set_current_file(str(self.sample_pdf))
        self.assertIsNotNone(self.view.build_ui())

        self.view.is_dark_supplier = lambda: False
        self.assertIsNotNone(self.view.build_ui())

    def test_reactive_file_load_and_metadata_audit(self):
        self.view.set_current_file(str(self.sample_pdf))
        self.assertEqual(self.view.total_pages, 1)
        self.assertIsNotNone(self.view.preview_data)
        self.assertIsNotNone(self.view.metadata_info)
        self.assertEqual(self.view.metadata_info["info_fields"]["author"], "Confidential Author")

    def test_manual_bounding_box_drag_and_remove(self):
        self.view.set_current_file(str(self.sample_pdf))
        self.view._on_canvas_pan_start(_DummyDragEvent(40, 60))
        self.view._on_canvas_pan_update(_DummyDragEvent(200, 120))
        self.view._on_canvas_pan_end(_DummyDragEvent(200, 120))

        self.assertEqual(len(self.view.manual_boxes), 1)
        box = self.view.manual_boxes[0]
        self.assertEqual(box.page_index, 0)
        self.assertGreater(box.rect[2], box.rect[0])
        self.assertGreater(box.rect[3], box.rect[1])

        self.view.remove_manual_box(box.id)
        self.assertEqual(len(self.view.manual_boxes), 0)

    def test_ui_pattern_scan_and_apply_redactions(self):
        self.app_state.select_file(str(self.sample_pdf))
        self.view.set_current_file(str(self.sample_pdf))

        # Scan patterns
        self.view._on_scan_patterns_clicked(None)
        self.assertGreaterEqual(len(self.view.pattern_matches), 2)

        # Keep email selected, deselect SSN to test selective preview toggle
        for m in self.view.pattern_matches:
            if m.category == "ssn":
                self.view._toggle_pattern_match(m.id, False)

        # Apply redactions + sanitize metadata
        self.view._sanitize_meta_switch.value = True
        self.view._on_apply_redactions_clicked(None)

        self.assertIsNotNone(self.view.last_output_path)
        self.assertTrue(os.path.exists(self.view.last_output_path))
        self.assertIsNotNone(self.view.last_leakage_report)
        self.assertTrue(self.view.last_leakage_report["verified"])
        self.assertIsNotNone(self.view.last_sanitization_report)

        with fitz.open(self.view.last_output_path) as out_doc:
            out_text = out_doc[0].get_text()
            self.assertNotIn("alice@acme.org", out_text)
            self.assertIn("555-12-3456", out_text)
            self.assertIn("Public Footer Info", out_text)

        meta_after = inspect_pdf_metadata(self.view.last_output_path)
        self.assertEqual(meta_after["total_findings"], 0)

    def test_ui_one_click_sanitize_metadata(self):
        self.app_state.select_file(str(self.sample_pdf))
        self.view.set_current_file(str(self.sample_pdf))

        self.view._on_sanitize_only_clicked(None)
        self.assertIsNotNone(self.view.last_output_path)
        self.assertTrue(os.path.exists(self.view.last_output_path))
        self.assertIsNotNone(self.view.last_sanitization_report)
        self.assertGreaterEqual(len(self.view.last_sanitization_report["deleted_items"]), 2)

        meta_after = inspect_pdf_metadata(self.view.last_output_path)
        self.assertEqual(meta_after["total_findings"], 0)


if __name__ == "__main__":
    unittest.main()
