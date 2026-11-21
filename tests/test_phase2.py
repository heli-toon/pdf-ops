import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import pymupdf as fitz

from pdf_engine import (
    add_watermark_to_pdf,
    compress_pdf,
    convert_images_to_pdf,
    crop_pdf_pages,
    decrypt_pdf,
    encrypt_pdf,
    export_pdf_images,
    export_pdf_tables_to_excel,
    inspect_pdf,
    parse_page_ranges,
    rotate_pdf_pages,
)


class PhaseTwoEngineTests(unittest.TestCase):
    def test_page_ranges_allow_end_and_preserve_requested_order(self):
        self.assertEqual(parse_page_ranges("1-3, 5, 8-end", 10), [1, 2, 3, 5, 8, 9, 10])
        self.assertEqual(parse_page_ranges("3, 1", 3), [3, 1])
        self.assertEqual(parse_page_ranges("end", 5), [5])

    def test_page_ranges_reject_invalid_bounds_and_syntax(self):
        with self.assertRaises(ValueError):
            parse_page_ranges("3-1", 3)
        with self.assertRaises(ValueError):
            parse_page_ranges("4", 3)
        with self.assertRaises(ValueError):
            parse_page_ranges("", 3)
        with self.assertRaises(ValueError):
            parse_page_ranges("1, , 2", 3)

    def test_pdf_image_export_honors_formats_and_dpis(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                document.new_page(width=72, height=72)
                document.save(source)

            # Test PNG, JPEG, and WEBP formats at 72 and 150 DPI
            for fmt in ("png", "jpeg", "webp"):
                out_dir = Path(temporary) / fmt
                outputs = export_pdf_images(source, out_dir, 72, fmt)
                self.assertEqual(len(outputs), 1)
                expected_ext = ".jpg" if fmt == "jpeg" else f".{fmt}"
                self.assertEqual(outputs[0].suffix, expected_ext)
                self.assertTrue(outputs[0].exists())
                self.assertGreater(outputs[0].stat().st_size, 0)

    def test_pdf_image_export_rejects_unsupported_dpi_or_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                document.new_page(width=72, height=72)
                document.save(source)

            with self.assertRaises(ValueError):
                export_pdf_images(source, temporary, 100, "png")
            with self.assertRaises(ValueError):
                export_pdf_images(source, temporary, 150, "gif")

    def test_convert_images_to_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            p1 = Path(temporary) / "img1.png"
            p2 = Path(temporary) / "img2.jpg"
            Image.new("RGB", (100, 100), color="blue").save(p1)
            Image.new("RGB", (150, 200), color="green").save(p2)

            out_pdf = Path(temporary) / "combined.pdf"
            convert_images_to_pdf([p1, p2], out_pdf)
            self.assertTrue(out_pdf.exists())

            info = inspect_pdf(out_pdf)
            self.assertEqual(info["page_count"], 2)
            self.assertFalse(info["is_encrypted"])

    def test_compress_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                p = document.new_page()
                p.draw_rect(fitz.Rect(10, 10, 200, 200), color=(1, 0, 0), fill=(0, 1, 0))
                document.save(source)

            compressed = Path(temporary) / "compressed.pdf"
            compress_pdf(source, compressed)
            self.assertTrue(compressed.exists())
            self.assertGreater(compressed.stat().st_size, 0)

    def test_rotate_pdf_pages_cumulative(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                p = document.new_page()
                p.set_rotation(90)
                document.save(source)

            rotated = Path(temporary) / "rotated.pdf"
            # Rotate by 90 CW -> 90 + 90 = 180
            rotate_pdf_pages(source, rotated, 90, page_numbers=[1])
            with fitz.open(rotated) as document:
                self.assertEqual(document[0].rotation, 180)

    def test_crop_pdf_pages_syncs_boxes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                document.new_page(width=200, height=200)
                document.save(source)

            cropped = Path(temporary) / "cropped.pdf"
            crop_pdf_pages(source, cropped, margins=(0.1, 0.1, 0.1, 0.1), page_numbers=[1])
            with fitz.open(cropped) as document:
                rect = document[0].rect
                self.assertAlmostEqual(rect.width, 160.0)
                self.assertAlmostEqual(rect.height, 160.0)

    def test_watermark_addition(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                document.new_page(width=600, height=800)
                document.save(source)

            watermarked = Path(temporary) / "watermarked.pdf"
            add_watermark_to_pdf(source, watermarked, "CONFIDENTIAL", font_size=36, opacity=0.5, angle=45)
            self.assertTrue(watermarked.exists())
            with fitz.open(watermarked) as document:
                self.assertIn("CONFIDENTIAL", document[0].get_text())

    def test_aes_256_encryption_and_decryption(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            with fitz.open() as document:
                p = document.new_page()
                p.insert_text(fitz.Point(50, 50), "Top Secret Data")
                document.save(source)

            encrypted = Path(temporary) / "encrypted.pdf"
            encrypt_pdf(
                source,
                encrypted,
                user_password="userpass",
                owner_password="adminpass",
                allow_printing=True,
                allow_copying=False,
            )

            # Verification of encryption
            info = inspect_pdf(encrypted)
            self.assertTrue(info["is_encrypted"])

            # Verification of failed decryption with wrong password
            decrypted = Path(temporary) / "decrypted.pdf"
            with self.assertRaises(ValueError):
                decrypt_pdf(encrypted, decrypted, "wrongpass")

            # Verification of successful decryption
            decrypt_pdf(encrypted, decrypted, "userpass")
            self.assertTrue(decrypted.exists())
            dec_info = inspect_pdf(decrypted)
            self.assertFalse(dec_info["is_encrypted"])
            with fitz.open(decrypted) as document:
                self.assertIn("Top Secret Data", document[0].get_text())

    def test_table_extraction_to_excel(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "table.pdf"
            with fitz.open() as document:
                page = document.new_page()
                page.draw_rect(fitz.Rect(50, 50, 200, 150))
                page.draw_line(fitz.Point(50, 100), fitz.Point(200, 100))
                page.draw_line(fitz.Point(125, 50), fitz.Point(125, 150))
                page.insert_text(fitz.Point(60, 80), "Header 1")
                page.insert_text(fitz.Point(135, 80), "Header 2")
                page.insert_text(fitz.Point(60, 130), "Val 1")
                page.insert_text(fitz.Point(135, 130), "Val 2")
                document.save(source)

            excel_out = Path(temporary) / "tables.xlsx"
            tables = export_pdf_tables_to_excel(source, excel_out)
            self.assertGreaterEqual(tables, 1)
            self.assertTrue(excel_out.exists())


if __name__ == "__main__":
    unittest.main()
