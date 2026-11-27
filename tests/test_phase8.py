"""Unit tests for Phase 8: Interactive Form Filler & Flattener (AcroForms).

Verifies:
- AcroForm widget parsing (text, multiline, password, read-only, checkbox, radio group, combobox, listbox)
- Natural reading / keyboard tab-order indexing across multi-page forms
- Live in-memory form preview rendering without mutating source PDF
- Saving filled forms as Editable AcroForm PDFs
- Flattening filled forms into static page vector/text streams (zero remaining widgets)
- Form detection badge in DocumentInspector and FormFillerView
- Dynamic sidebar control generation, tab-order navigation, canvas click-to-focus/toggle, and export actions
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

import flet as ft
import pymupdf as fitz

from app_state import AppState
from main import PDFOpsApp
from pdf_engine import (
    encrypt_pdf,
    fill_and_save_pdf_form,
    inspect_pdf_forms,
    render_form_page_preview,
)
from ui_forms import FormFillerView
from ui_inspector import DocumentInspector


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


def _create_sample_acroform_pdf(path: Path) -> Path:
    """Create a realistic 2-page AcroForm PDF covering all supported field types."""
    with fitz.open() as doc:
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 45), "Employee Onboarding Form", fontsize=16)

        # 1. Text box (required)
        w_name = fitz.Widget()
        w_name.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_name.field_name = "full_name"
        w_name.field_label = "Full Name"
        w_name.field_flags = fitz.PDF_FIELD_IS_REQUIRED
        w_name.rect = fitz.Rect(50, 70, 280, 95)
        w_name.field_value = ""
        p1.add_widget(w_name)

        # 2. Combobox / Dropdown
        w_dept = fitz.Widget()
        w_dept.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w_dept.field_name = "department"
        w_dept.field_label = "Department"
        w_dept.rect = fitz.Rect(310, 70, 520, 95)
        w_dept.choice_values = ["Engineering", "Design", "Legal", "Operations"]
        w_dept.field_value = "Engineering"
        p1.add_widget(w_dept)

        # 3. Checkbox
        w_agree = fitz.Widget()
        w_agree.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w_agree.field_name = "accept_policy"
        w_agree.field_label = "Accept Privacy Policy"
        w_agree.rect = fitz.Rect(50, 120, 70, 140)
        w_agree.field_value = False
        p1.add_widget(w_agree)

        # 4. Radio button group with distinct on-states
        radio_specs = [
            ("Remote", fitz.Rect(50, 170, 70, 190)),
            ("Hybrid", fitz.Rect(140, 170, 160, 190)),
            ("Onsite", fitz.Rect(230, 170, 250, 190)),
        ]
        for _, rect in radio_specs:
            wr = fitz.Widget()
            wr.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
            wr.field_name = "work_mode"
            wr.field_label = "Work Mode"
            wr.rect = rect
            p1.add_widget(wr)

        radio_widgets = [w for w in p1.widgets() if w.field_name == "work_mode"]
        for widget, (state_name, _) in zip(radio_widgets, radio_specs):
            obj_str = doc.xref_object(widget.xref)
            obj_str = obj_str.replace("/None ", f"/{state_name} ").replace("/AS /None", "/AS /Off")
            doc.update_object(widget.xref, obj_str)

        # 5. Read-only text field
        w_ro = fitz.Widget()
        w_ro.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_ro.field_name = "form_id"
        w_ro.field_label = "Form Reference ID"
        w_ro.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
        w_ro.rect = fitz.Rect(50, 220, 220, 245)
        w_ro.field_value = "FORM-2026-001"
        p1.add_widget(w_ro)

        # Page 2 fields
        p2 = doc.new_page(width=595, height=842)
        p2.insert_text((50, 45), "Additional Details", fontsize=14)

        # 6. Multiline notes field
        w_notes = fitz.Widget()
        w_notes.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_notes.field_name = "notes"
        w_notes.field_label = "Notes"
        w_notes.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
        w_notes.rect = fitz.Rect(50, 80, 400, 160)
        w_notes.field_value = ""
        p2.add_widget(w_notes)

        # 7. Listbox
        w_region = fitz.Widget()
        w_region.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
        w_region.field_name = "office_region"
        w_region.field_label = "Office Region"
        w_region.rect = fitz.Rect(50, 190, 220, 250)
        w_region.choice_values = ["North America", "Europe", "APAC"]
        w_region.field_value = "Europe"
        p2.add_widget(w_region)

        doc.save(str(path))
    return path


def _collect_badges(control) -> list[str]:
    """Recursively gather text labels inside Flet controls for assertions."""
    found: list[str] = []
    if isinstance(control, ft.Text) and control.value:
        found.append(str(control.value))
    content = getattr(control, "content", None)
    if content is not None:
        found.extend(_collect_badges(content))
    for child in getattr(control, "controls", None) or []:
        found.extend(_collect_badges(child))
    return found


class PhaseEightEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.form_pdf = _create_sample_acroform_pdf(self.dir_path / "onboarding.pdf")
        self.flat_pdf = self.dir_path / "flat.pdf"
        with fitz.open() as doc:
            p = doc.new_page(width=595, height=842)
            p.insert_text((50, 60), "Plain non-form PDF document", fontsize=14)
            doc.save(self.flat_pdf)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_pdf_forms_parses_types_groups_and_tab_order(self):
        summary = inspect_pdf_forms(self.form_pdf)
        self.assertTrue(summary["is_form_pdf"])
        self.assertEqual(summary["page_count"], 2)
        self.assertEqual(summary["total_fields"], 7)
        self.assertEqual(summary["fillable_count"], 6)  # form_id is read-only

        fields = summary["fields"]
        self.assertEqual([f.tab_index for f in fields], [1, 2, 3, 4, 5, 6, 7])

        by_key = {f.key: f for f in fields}
        self.assertEqual(by_key["full_name"].field_type, "text")
        self.assertTrue(by_key["full_name"].is_required)
        self.assertEqual(by_key["department"].field_type, "combobox")
        self.assertEqual(by_key["department"].options, ["Engineering", "Design", "Legal", "Operations"])
        self.assertEqual(by_key["accept_policy"].field_type, "checkbox")
        self.assertFalse(by_key["accept_policy"].value)
        self.assertEqual(by_key["work_mode"].field_type, "radio")
        self.assertEqual(by_key["work_mode"].options, ["Remote", "Hybrid", "Onsite"])
        self.assertTrue(by_key["form_id"].is_read_only)
        self.assertFalse(by_key["form_id"].is_fillable)
        self.assertTrue(by_key["notes"].is_multiline)
        self.assertEqual(by_key["office_region"].field_type, "listbox")

        flat_summary = inspect_pdf_forms(self.flat_pdf)
        self.assertFalse(flat_summary["is_form_pdf"])
        self.assertEqual(flat_summary["total_fields"], 0)
        self.assertEqual(flat_summary["fillable_count"], 0)

    def test_render_form_page_preview_live_values_and_overlays(self):
        preview = render_form_page_preview(
            self.form_pdf,
            page_index=0,
            pending_values={"full_name": "Jordan Mercer", "accept_policy": True, "work_mode": "Hybrid"},
            active_field_key="work_mode",
        )
        self.assertTrue(preview["png_bytes"].startswith(b"\x89PNG"))
        self.assertGreater(preview["canvas_width"], 100)
        overlays = preview["overlays"]
        # Page 1 has 4 standalone fields + 3 radio options = 7 overlays
        self.assertEqual(len(overlays), 7)
        active_overlays = [ov for ov in overlays if ov["is_active"]]
        self.assertEqual(len(active_overlays), 3)  # all 3 radio options belong to work_mode

        # Source file on disk must remain untouched
        orig_summary = inspect_pdf_forms(self.form_pdf)
        orig_map = {f.key: f.value for f in orig_summary["fields"]}
        self.assertEqual(orig_map["full_name"], "")
        self.assertFalse(orig_map["accept_policy"])

    def test_fill_and_save_editable_vs_flattened_pdf(self):
        values = {
            "full_name": "Maya Lin",
            "department": "Legal",
            "accept_policy": True,
            "work_mode": "Hybrid",
            "form_id": "TAMPERED-VALUE",  # read-only must be ignored
            "notes": "Approved for Q4 start.",
            "office_region": "APAC",
        }

        editable_out = self.dir_path / "editable_filled.pdf"
        edit_report = fill_and_save_pdf_form(self.form_pdf, editable_out, values, flatten=False)
        self.assertTrue(editable_out.exists())
        self.assertFalse(edit_report["flattened"])
        self.assertTrue(edit_report["is_form_pdf_after"])
        self.assertGreater(edit_report["remaining_widgets"], 0)
        self.assertEqual(edit_report["fields_updated"], 6)

        re_inspected = inspect_pdf_forms(editable_out)
        re_map = {f.key: f.value for f in re_inspected["fields"]}
        self.assertEqual(re_map["full_name"], "Maya Lin")
        self.assertEqual(re_map["department"], "Legal")
        self.assertTrue(re_map["accept_policy"])
        self.assertEqual(re_map["work_mode"], "Hybrid")
        self.assertEqual(re_map["form_id"], "FORM-2026-001")
        self.assertEqual(re_map["notes"], "Approved for Q4 start.")
        self.assertEqual(re_map["office_region"], "APAC")

        flat_out = self.dir_path / "flattened_readonly.pdf"
        flat_report = fill_and_save_pdf_form(self.form_pdf, flat_out, values, flatten=True)
        self.assertTrue(flat_out.exists())
        self.assertTrue(flat_report["flattened"])
        self.assertFalse(flat_report["is_form_pdf_after"])
        self.assertEqual(flat_report["remaining_widgets"], 0)

        with fitz.open(flat_out) as doc:
            self.assertFalse(doc.is_form_pdf)
            for page in doc:
                self.assertEqual(list(page.widgets()), [])
            p1_text = doc[0].get_text()
            p2_text = doc[1].get_text()
            self.assertIn("Maya Lin", p1_text)
            self.assertIn("Legal", p1_text)
            self.assertIn("Approved for Q4 start.", p2_text)

    def test_encrypted_and_non_form_pdfs_rejected_cleanly(self):
        enc_pdf = self.dir_path / "locked_form.pdf"
        encrypt_pdf(self.form_pdf, enc_pdf, user_password="secret")
        with self.assertRaises(ValueError):
            inspect_pdf_forms(enc_pdf)
        with self.assertRaises(ValueError):
            fill_and_save_pdf_form(enc_pdf, self.dir_path / "out.pdf", {"full_name": "Test"})
        with self.assertRaises(ValueError):
            fill_and_save_pdf_form(self.flat_pdf, self.dir_path / "out2.pdf", {"full_name": "Test"})


class PhaseEightUITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.output_dir = self.dir_path / "out"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.form_pdf = _create_sample_acroform_pdf(self.dir_path / "ui_form.pdf")
        self.flat_pdf = self.dir_path / "ui_flat.pdf"
        with fitz.open() as doc:
            doc.new_page(width=400, height=500).insert_text((40, 40), "Flat PDF")
            doc.save(self.flat_pdf)

        self.page = MockPage()
        self.state = AppState()
        self.is_dark = True
        self.view = FormFillerView(
            page=self.page,
            app_state=self.state,
            output_dir=str(self.output_dir),
            progress_bar=ft.ProgressBar(),
            progress_text=ft.Text(),
            is_dark_supplier=lambda: self.is_dark,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_document_inspector_displays_form_detection_badge(self):
        inspector = DocumentInspector(self.page, lambda: True)
        inspector.set_file(str(self.form_pdf))
        self.assertIsNotNone(inspector.last_form_summary)
        self.assertEqual(inspector.last_form_summary["fillable_count"], 6)
        texts = _collect_badges(inspector.container)
        self.assertIn("6 Form Fields", texts)

        inspector.set_file(str(self.flat_pdf))
        self.assertEqual(inspector.last_form_summary["fillable_count"], 0)
        flat_texts = _collect_badges(inspector.container)
        self.assertIn("No Form Fields", flat_texts)

    def test_build_ui_dark_and_light_and_form_detection_badge(self):
        for dark in (True, False):
            self.is_dark = dark
            empty_ui = self.view.build_ui()
            self.assertIsInstance(empty_ui, ft.Column)

        self.view.set_current_file(str(self.form_pdf))
        for dark in (True, False):
            self.is_dark = dark
            ui = self.view.build_ui()
            texts = _collect_badges(ui)
            self.assertIn("6 Fillable Fields", texts)
            self.assertIn("Full Name", texts)
            self.assertIn("Department", texts)
            self.assertIn("Work Mode", texts)

        # Dynamic controls map covers every fillable field
        self.assertIsInstance(self.view._field_controls["full_name"], ft.TextField)
        self.assertIsInstance(self.view._field_controls["accept_policy"], ft.Checkbox)
        self.assertIsInstance(self.view._field_controls["work_mode"], ft.RadioGroup)
        self.assertIsInstance(self.view._field_controls["department"], ft.Dropdown)

    def test_tab_order_navigation_overlay_interaction_and_exports(self):
        self.view.set_current_file(str(self.form_pdf))
        self.assertEqual(self.view.active_field_key, "full_name")

        # Step through tab order forward & backward, including crossing to Page 2
        seen_keys = [self.view.active_field_key]
        for _ in range(5):
            seen_keys.append(self.view.step_tab_order(1))
        self.assertEqual(
            seen_keys,
            ["full_name", "department", "accept_policy", "work_mode", "notes", "office_region"],
        )
        self.assertEqual(self.view.current_page_index, 1)  # stepped onto page 2

        prev_key = self.view.step_tab_order(-1)
        self.assertEqual(prev_key, "notes")

        # Canvas hotspot click toggles checkbox & selects radio option
        self.view.on_overlay_click("accept_policy")
        self.assertTrue(self.view.pending_values["accept_policy"])
        self.assertEqual(self.view.current_page_index, 0)

        self.view.on_overlay_click("work_mode", option_value="Onsite")
        self.assertEqual(self.view.pending_values["work_mode"], "Onsite")

        # Fill remaining fields and jump_to_next_empty
        self.view.set_field_value("full_name", "Alex Rivera")
        next_empty = self.view.jump_to_next_empty()
        self.assertEqual(next_empty, "notes")
        self.view.set_field_value("notes", "Completed onboarding paperwork.")

        # Export Editable Form
        edit_report = self.view.save_form_pdf(flatten=False)
        self.assertIsNotNone(edit_report)
        self.assertTrue(Path(edit_report["output_path"]).exists())
        self.assertTrue(edit_report["is_form_pdf_after"])

        # Export Flattened (Read-Only) Form
        flat_report = self.view.save_form_pdf(flatten=True)
        self.assertIsNotNone(flat_report)
        self.assertTrue(Path(flat_report["output_path"]).exists())
        self.assertFalse(flat_report["is_form_pdf_after"])
        self.assertEqual(flat_report["remaining_widgets"], 0)

    def test_main_app_includes_forms_tool_and_reactive_handoff(self):
        app = PDFOpsApp()
        app.main(self.page)
        tool_ids = [tid for tid, _, _, _ in app.nav_destinations]
        self.assertIn("forms", tool_ids)

        app.state.select_file(str(self.form_pdf))
        app.switch_tool("forms")
        self.assertEqual(app.active_tool_id, "forms")
        self.assertEqual(app.forms_view.current_file, str(self.form_pdf))
        self.assertEqual(len(app.forms_view.fields), 7)


if __name__ == "__main__":
    unittest.main()
