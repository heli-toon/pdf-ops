"""Unit tests for Phase 7: Digital Signatures & Stamp Studio.

Verifies:
- Quadratic Bezier signature stroke smoothing & transparent PNG rendering
- Uploaded image signature automatic white-paper background removal (PIL + NumPy)
- Type-to-sign rendering across all cursive script typography options
- Rubber stamp generator (presets, colors, borders, dynamic date/time/operator, rotation)
- Persistent local Signature Vault (save, list, load, delete)
- Multi-page signing workflows (all pages, initial every page + full signature on final page, custom range)
- PDF signature/stamp embedding & local SHA-256 integrity verification
- Interactive UI ergonomics: drawing pad, tabs, click-to-place, move, resize, and export
"""

from __future__ import annotations

from datetime import datetime
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest

import flet as ft
import flet.canvas as cv
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz

from app_state import AppState
from pdf_engine import (
    PlacementItem,
    STAMP_BORDER_STYLES,
    STAMP_COLORS,
    STAMP_PRESETS,
    apply_signatures_and_stamps,
    build_multipage_placements,
    compute_quadratic_bezier_segments,
    delete_vault_signature,
    encrypt_pdf,
    get_available_signature_fonts,
    list_vault_signatures,
    load_vault_signature_bytes,
    remove_signature_background,
    render_drawn_signature_png,
    render_stamp_image,
    render_typed_signature_png,
    save_signature_to_vault,
    verify_signed_pdf_integrity,
)
from ui_signatures import SignatureStampView


class _DummyOffset:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class _DummyTapEvent:
    def __init__(self, x: float, y: float):
        self.local_position = _DummyOffset(x, y)


class _DummyDragEvent:
    def __init__(self, x: float, y: float):
        self.local_position = _DummyOffset(x, y)
        self.local_delta = _DummyOffset(x, y)


class MockWindow:
    width = 1200
    height = 840
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
        self.height = 840
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
        t.join(timeout=15.0)
        return t


class PhaseSevenEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.sample_pdf = self.dir_path / "agreement.pdf"
        with fitz.open() as doc:
            for idx in range(3):
                page = doc.new_page(width=595, height=842)
                page.insert_text((50, 80), f"Service Agreement — Page {idx + 1}", fontsize=14)
                page.insert_text((50, 720), "Authorized Signature / Initials:", fontsize=11)
            doc.save(self.sample_pdf)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_quadratic_bezier_and_drawn_signature_rendering(self):
        start, segs = compute_quadratic_bezier_segments([])
        self.assertIsNone(start)
        self.assertEqual(segs, [])

        start1, segs1 = compute_quadratic_bezier_segments([(10, 20)])
        self.assertEqual(start1, (10.0, 20.0))
        self.assertEqual(segs1, [])

        strokes = [
            [(20, 90), (60, 40), (110, 110), (170, 50), (240, 85)],
            [(260, 70), (290, 80)],
        ]
        png_bytes = render_drawn_signature_png(
            strokes=strokes,
            stroke_width=4.0,
            ink_color="blue",
        )
        with Image.open(io.BytesIO(png_bytes)) as img:
            self.assertEqual(img.mode, "RGBA")
            self.assertGreater(img.width, 40)
            self.assertGreater(img.height, 20)
            alpha = np.array(img)[:, :, 3]
            self.assertGreater(int(alpha.max()), 200)
            self.assertEqual(int(alpha[0, 0]), 0)  # transparent padding corner

        with self.assertRaises(ValueError):
            render_drawn_signature_png(strokes=[])

    def test_remove_signature_background_preserves_ink_and_clears_paper(self):
        # Simulate photographed signature on off-white paper saved as JPEG
        raw_img = Image.new("RGB", (260, 100), (248, 246, 242))
        draw = ImageDraw.Draw(raw_img)
        draw.line([(25, 65), (90, 30), (155, 70), (230, 35)], fill=(18, 36, 110), width=6)
        jpg_path = self.dir_path / "photo_sig.jpg"
        raw_img.save(jpg_path, format="JPEG", quality=95)

        cleaned_bytes = remove_signature_background(jpg_path, threshold=220)
        with Image.open(io.BytesIO(cleaned_bytes)) as cleaned:
            self.assertEqual(cleaned.mode, "RGBA")
            arr = np.array(cleaned)
            # Corner paper pixels must be transparent
            self.assertEqual(int(arr[0, 0, 3]), 0)
            # Ink pixels must remain solid
            self.assertGreater(int(arr[:, :, 3].max()), 230)
            # Tightly cropped compared to original 260x100
            self.assertLess(cleaned.height, 95)

    def test_typed_signature_all_cursive_fonts(self):
        fonts = get_available_signature_fonts()
        self.assertGreaterEqual(len(fonts), 4)

        for font_info in fonts:
            png_bytes = render_typed_signature_png(
                text="Elena Vance",
                font_style=font_info["id"],
                ink_color="navy",
            )
            with Image.open(io.BytesIO(png_bytes)) as img:
                self.assertEqual(img.mode, "RGBA")
                self.assertGreater(img.width, 30)
                self.assertGreater(img.height, 15)

        with self.assertRaises(ValueError):
            render_typed_signature_png(text="   ")

    def test_stamp_generator_presets_colors_borders_and_variables(self):
        fixed_ts = datetime(2026, 11, 26, 14, 30, 0)
        for preset in STAMP_PRESETS:
            png_bytes = render_stamp_image(
                text=preset,
                color_key="red",
                border_style="double",
                include_date=True,
                include_time=True,
                operator_name="J. DOE",
                custom_subtext="VERIFIED",
                rotation=-12.0,
                opacity=0.9,
                timestamp=fixed_ts,
            )
            with Image.open(io.BytesIO(png_bytes)) as img:
                self.assertEqual(img.mode, "RGBA")
                self.assertGreater(img.width, 80)
                self.assertGreater(img.height, 40)

        for color_key in STAMP_COLORS:
            for border_key in STAMP_BORDER_STYLES:
                png_bytes = render_stamp_image(
                    text="CUSTOM SEAL",
                    color_key=color_key,
                    border_style=border_key,
                    rotation=0.0,
                    timestamp=fixed_ts,
                )
                self.assertTrue(png_bytes.startswith(b"\x89PNG"))

        with self.assertRaises(ValueError):
            render_stamp_image(text="")

    def test_signature_vault_crud_persistence(self):
        vault_dir = self.dir_path / "vault"
        sig_png = render_typed_signature_png("Samira Patel", font_style="chancery")
        saved = save_signature_to_vault(sig_png, name="Samira Full", kind="typed", vault_dir=vault_dir)
        self.assertEqual(saved["name"], "Samira Full")
        self.assertTrue(Path(saved["png_path"]).exists())

        listed = list_vault_signatures(vault_dir=vault_dir)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], saved["id"])

        loaded_bytes = load_vault_signature_bytes(saved["id"], vault_dir=vault_dir)
        self.assertEqual(loaded_bytes, sig_png)

        self.assertTrue(delete_vault_signature(saved["id"], vault_dir=vault_dir))
        self.assertEqual(list_vault_signatures(vault_dir=vault_dir), [])
        self.assertFalse(delete_vault_signature("nonexistent", vault_dir=vault_dir))

    def test_multipage_placements_and_apply_to_pdf_with_integrity(self):
        full_sig = render_drawn_signature_png([[(10, 40), (60, 20), (140, 50)]])
        initials_sig = render_typed_signature_png("A.M.", font_style="script")
        stamp_png = render_stamp_image("APPROVED", color_key="green", border_style="rounded")

        contract_items = build_multipage_placements(
            page_count=3,
            mode="initial_all_sign_last",
            primary_png=full_sig,
            secondary_png=initials_sig,
        )
        self.assertEqual(len(contract_items), 3)
        self.assertEqual(contract_items[0].kind, "initials")
        self.assertEqual(contract_items[1].kind, "initials")
        self.assertEqual(contract_items[2].kind, "signature")
        self.assertEqual([c.page_index for c in contract_items], [0, 1, 2])

        stamp_items = build_multipage_placements(
            page_count=3,
            mode="custom_range",
            primary_png=stamp_png,
            primary_rect=(0.62, 0.12, 0.25, 0.11),
            page_range="1, 3",
            primary_label="APPROVED",
            kind="stamp",
            opacity=0.85,
        )
        self.assertEqual([s.page_index for s in stamp_items], [0, 2])

        out_pdf = self.dir_path / "signed_agreement.pdf"
        report = apply_signatures_and_stamps(
            source=self.sample_pdf,
            output_path=out_pdf,
            placements=contract_items + stamp_items,
        )
        self.assertTrue(out_pdf.exists())
        self.assertEqual(report["pages_signed"], 3)
        self.assertEqual(report["placements_applied"], 5)
        self.assertNotEqual(report["sha256_before"], report["sha256_after"])

        integrity = verify_signed_pdf_integrity(out_pdf)
        self.assertEqual(integrity["sha256"], report["sha256_after"])
        self.assertEqual(integrity["page_count"], 3)
        self.assertEqual(integrity["embedded_image_count"], 5)

        # Encrypted PDFs must fail cleanly
        enc_pdf = self.dir_path / "locked.pdf"
        encrypt_pdf(self.sample_pdf, enc_pdf, user_password="secret")
        with self.assertRaises(ValueError):
            apply_signatures_and_stamps(enc_pdf, self.dir_path / "fail.pdf", contract_items)


class PhaseSevenUITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.output_dir = self.dir_path / "out"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir = self.dir_path / "vault"

        self.sample_pdf = self.dir_path / "contract.pdf"
        with fitz.open() as doc:
            for idx in range(3):
                p = doc.new_page(width=595, height=842)
                p.insert_text((50, 90), f"Contract Page {idx + 1}", fontsize=14)
            doc.save(self.sample_pdf)

        self.page = MockPage()
        self.state = AppState()
        self.is_dark = True
        self.view = SignatureStampView(
            page=self.page,
            app_state=self.state,
            output_dir=str(self.output_dir),
            progress_bar=ft.ProgressBar(),
            progress_text=ft.Text(),
            is_dark_supplier=lambda: self.is_dark,
            vault_dir=self.vault_dir,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_ui_dark_and_light_and_all_studio_tabs(self):
        for dark_flag in (True, False):
            self.is_dark = dark_flag
            for tab in ("draw", "type", "upload", "stamp", "vault"):
                self.view.switch_studio_tab(tab)
                ui = self.view.build_ui()
                self.assertIsInstance(ui, ft.Column)

    def test_drawing_pad_bezier_undo_clear_and_vault_save(self):
        self.view._on_draw_pan_start(_DummyDragEvent(30, 80))
        self.view._on_draw_pan_update(_DummyDragEvent(80, 50))
        self.view._on_draw_pan_update(_DummyDragEvent(140, 95))
        self.view._on_draw_pan_end(_DummyDragEvent(140, 95))

        self.assertEqual(len(self.view._draw_strokes), 1)
        self.assertTrue(any(isinstance(s, cv.Path) for s in self.view._draw_canvas.shapes))

        self.view.undo_drawing_stroke()
        self.assertEqual(len(self.view._draw_strokes), 0)

        # Draw again and save to vault
        self.view._draw_strokes = [[(20, 80), (70, 35), (140, 85), (210, 45)]]
        entry = self.view.save_drawn_to_vault(label="My Executive Sig")
        self.assertIsNotNone(entry)
        self.assertIsNotNone(self.view.active_asset)
        self.assertEqual(len(list_vault_signatures(self.vault_dir)), 1)

        self.view.clear_drawing_pad()
        self.assertEqual(len(self.view._draw_strokes), 0)

    def test_typed_upload_and_stamp_live_previews(self):
        self.view._typed_name_field.value = "Jordan Blake"
        self.view._typed_font_dropdown.value = "calligraphic"
        self.view._refresh_typed_preview()
        self.assertIsNotNone(self.view._typed_preview_bytes)
        self.view.activate_typed_signature()
        self.assertIn("Jordan Blake", self.view.active_asset["label"])

        # Upload image with white paper background
        img = Image.new("RGB", (180, 70), (252, 252, 252))
        d = ImageDraw.Draw(img)
        d.line([(20, 50), (80, 20), (150, 45)], fill=(10, 10, 10), width=5)
        img_path = self.dir_path / "sig_scan.png"
        img.save(img_path)

        cleaned = self.view.load_uploaded_signature_image(img_path)
        with Image.open(io.BytesIO(cleaned)) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(int(np.array(im)[0, 0, 3]), 0)

        # Stamp preset & dynamic operator
        self.view._select_stamp_chip("CONFIDENTIAL")
        self.view._stamp_operator_field.value = "M. CHEN"
        self.view._refresh_stamp_preview()
        self.assertIsNotNone(self.view._stamp_preview_bytes)
        self.view.activate_stamp()
        self.assertEqual(self.view.active_asset["kind"], "stamp")

    def test_interactive_click_to_place_move_resize_and_multipage_export(self):
        self.view.set_current_file(str(self.sample_pdf))
        self.assertEqual(self.view.total_pages, 3)
        self.assertIsNotNone(self.view.preview_data)

        # Activate a typed signature and click-to-place on page 1
        self.view._typed_name_field.value = "Taylor Reed"
        self.view.activate_typed_signature()
        cw = self.view.preview_data["canvas_width"]
        ch = self.view.preview_data["canvas_height"]

        self.view._on_canvas_tap_down(_DummyTapEvent(cw * 0.5, ch * 0.75))
        self.assertEqual(len(self.view.placements), 1)
        placed = self.view.placements[0]
        orig_nx, orig_ny, orig_nw = placed.nx, placed.ny, placed.nw

        # Drag-move and resize handle interaction
        self.view.move_placement_by_delta(placed.id, dx_px=25.0, dy_px=-20.0)
        self.assertGreater(placed.nx, orig_nx)
        self.assertLess(placed.ny, orig_ny)

        self.view.resize_placement_by_delta(placed.id, dw_px=30.0, dh_px=12.0)
        self.assertGreater(placed.nw, orig_nw)

        # Multi-page signing: Initial all + sign final page
        added = self.view.apply_multipage_preset("initial_all_sign_last")
        self.assertEqual(len(added), 3)
        self.assertEqual(len(self.view.placements), 4)

        # Export signed PDF and verify SHA-256 integrity digest
        self.view.apply_and_save_signed_pdf()
        self.assertIsNotNone(self.view._last_integrity_report)
        out_path = Path(self.view._last_integrity_report["output_path"])
        self.assertTrue(out_path.exists())
        self.assertEqual(self.view._last_integrity_report["placements_applied"], 4)
        self.assertEqual(self.view._last_integrity_report["pages_signed"], 3)


if __name__ == "__main__":
    unittest.main()
