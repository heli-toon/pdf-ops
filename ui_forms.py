"""Interactive Form Filler & Flattener workspace (Phase 8).

Operate Mode:
- Automatic AcroForm parsing (text boxes, multiline text, checkboxes,
  radio button groups, dropdowns, list boxes, read-only & signature fields)
- Form detection badge displaying count of fillable fields upon document load
- Auto-generated form inspector sidebar mirroring document structure with
  keyboard tab-order navigation (Prev / Next / Jump to Next Empty / Enter-to-advance)
- Live interactive PDF page canvas showing pending field values & clickable hotspots
- Dual export actions:
  - "Save as Editable Form" (preserves interactive AcroForm fields)
  - "Save & Flatten (Read-Only)" (bakes fields into immutable static PDF streams)
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import time

import flet as ft

from app_state import AppState
from pdf_engine import (
    FormFieldDescriptor,
    fill_and_save_pdf_form,
    inspect_pdf_forms,
    render_form_page_preview,
)
from theme import ThemeTokens, make_badge, padding_symmetric
from utils import (
    generate_output_filename,
    open_folder,
    reset_progress,
    run_background,
    show_snackbar,
    update_progress,
)


class FormFillerView:
    """Phase 8 Interactive Form Filler & Flattener workspace."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        output_dir: str,
        progress_bar: ft.ProgressBar | None = None,
        progress_text: ft.Text | None = None,
        is_dark_supplier: Callable[[], bool] = lambda: True,
    ):
        self.page = page
        self.app_state = app_state
        self.output_dir = output_dir
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.is_dark_supplier = is_dark_supplier

        # Document & form state
        self.current_file: str | None = getattr(app_state, "current_file", None)
        self.current_page_index: int = 0
        self.total_pages: int = 0
        self.form_summary: dict | None = None
        self.fields: list[FormFieldDescriptor] = []
        self.pending_values: dict[str, object] = {}
        self.active_field_key: str | None = None
        self.preview_data: dict | None = None
        self.is_processing: bool = False
        self.last_export_report: dict | None = None

        # Sidebar view options
        self.current_page_only: bool = False
        self.search_query: str = ""
        self._field_controls: dict[str, ft.Control] = {}

        self._build_controls()
        if self.current_file and os.path.exists(self.current_file):
            self._load_document_state(self.current_file)

    def _is_dark(self) -> bool:
        return self.is_dark_supplier()

    def _safe_page_update(self) -> None:
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass

    def _build_controls(self) -> None:
        """Instantiate reusable containers and filter controls."""
        self._header_badge_slot = ft.Row(spacing=6, tight=True)
        self._metrics_strip = ft.Row(spacing=8, wrap=True)
        self._canvas_host = ft.Container()
        self._sidebar_host = ft.Container()
        self._export_bar_host = ft.Container()
        self._feedback_container = ft.Container(visible=False)

        self._search_field = ft.TextField(
            hint_text="Filter fields by name...",
            prefix_icon=ft.Icons.SEARCH,
            text_size=12,
            dense=True,
            expand=True,
            border_radius=ThemeTokens.RADIUS_SM,
            on_change=self._on_search_change,
        )
        self._page_filter_switch = ft.Switch(
            label="This Page Only",
            value=False,
            on_change=self._on_page_filter_toggle,
        )

    # -------------------------------------------------------------------------
    # Reactive Document Loading
    # -------------------------------------------------------------------------

    def set_current_file(self, file_path: str | None) -> None:
        """Reactive callback triggered by central AppState."""
        if file_path == self.current_file:
            return

        self.current_file = file_path
        self.current_page_index = 0
        self.total_pages = 0
        self.form_summary = None
        self.fields = []
        self.pending_values = {}
        self.active_field_key = None
        self.preview_data = None
        self.last_export_report = None
        self._field_controls.clear()
        self._feedback_container.visible = False

        if file_path and os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
            self._load_document_state(file_path)
        else:
            self._refresh_all_panels()

        self._safe_page_update()

    def _load_document_state(self, file_path: str) -> None:
        """Parse AcroForm structure and render the initial page preview."""
        try:
            summary = inspect_pdf_forms(file_path)
            self.form_summary = summary
            self.total_pages = int(summary.get("page_count", 0))
            self.fields = list(summary.get("fields", []))
            self.pending_values = {f.key: f.value for f in self.fields}
            first_fillable = next((f for f in self.fields if f.is_fillable), None)
            self.active_field_key = first_fillable.key if first_fillable else (self.fields[0].key if self.fields else None)

            if self.total_pages > 0:
                self.current_page_index = max(0, min(self.current_page_index, self.total_pages - 1))
                self._refresh_preview_data()
        except Exception as err:
            self.form_summary = None
            self.fields = []
            self.pending_values = {}
            self.preview_data = None
            self._show_feedback(f"Could not inspect PDF form: {err}", "error")

        self._refresh_all_panels()

    def _refresh_preview_data(self) -> None:
        if not self.current_file or self.total_pages < 1:
            self.preview_data = None
            return
        self.preview_data = render_form_page_preview(
            self.current_file,
            page_index=self.current_page_index,
            pending_values=self.pending_values,
            active_field_key=self.active_field_key,
        )

    # -------------------------------------------------------------------------
    # Field Value & Tab-Order Navigation
    # -------------------------------------------------------------------------

    def _get_field_by_key(self, key: str | None) -> FormFieldDescriptor | None:
        if not key:
            return None
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def _is_field_filled(self, field_desc: FormFieldDescriptor) -> bool:
        val = self.pending_values.get(field_desc.key, field_desc.value)
        if field_desc.field_type == "checkbox":
            return bool(val)
        return bool(str(val or "").strip())

    def _filled_stats(self) -> tuple[int, int]:
        fillable = [f for f in self.fields if f.is_fillable]
        filled = sum(1 for f in fillable if self._is_field_filled(f))
        return filled, len(fillable)

    def set_field_value(self, key: str, value: object, refresh_preview: bool = True) -> None:
        """Update a form field's pending value and refresh the live PDF preview."""
        desc = self._get_field_by_key(key)
        if desc is None or desc.is_read_only:
            return

        self.pending_values[key] = value
        self.active_field_key = key

        ctrl = self._field_controls.get(key)
        if ctrl is not None:
            try:
                if isinstance(ctrl, ft.Checkbox):
                    ctrl.value = bool(value)
                elif isinstance(ctrl, (ft.TextField, ft.Dropdown, ft.RadioGroup)):
                    ctrl.value = "" if value is None else str(value)
            except Exception:
                pass

        if refresh_preview:
            try:
                self._refresh_preview_data()
            except Exception:
                pass
            self._render_metrics_strip()
            self._render_canvas()
            self._render_export_bar()
            self._safe_page_update()

    def focus_field(self, key: str, attempt_control_focus: bool = True) -> None:
        """Focus a specific field in the sidebar and jump to its page if needed."""
        desc = self._get_field_by_key(key)
        if desc is None:
            return

        self.active_field_key = key
        if desc.page_index != self.current_page_index and 0 <= desc.page_index < self.total_pages:
            self.current_page_index = desc.page_index

        try:
            self._refresh_preview_data()
        except Exception:
            pass

        self._render_metrics_strip()
        self._render_canvas()
        self._render_sidebar()
        self._safe_page_update()

        if attempt_control_focus:
            ctrl = self._field_controls.get(key)
            if ctrl is not None and hasattr(ctrl, "focus"):
                try:
                    if ctrl.page is not None:
                        ctrl.focus()
                except Exception:
                    pass

    def step_tab_order(self, delta: int) -> str | None:
        """Navigate to the next (+1) or previous (-1) fillable field in tab order."""
        fillable = [f for f in self.fields if f.is_fillable]
        if not fillable:
            return None

        keys = [f.key for f in fillable]
        if self.active_field_key in keys:
            idx = keys.index(self.active_field_key)
            next_idx = (idx + delta) % len(keys)
        else:
            next_idx = 0 if delta >= 0 else len(keys) - 1

        target_key = keys[next_idx]
        self.focus_field(target_key)
        return target_key

    def jump_to_next_empty(self) -> str | None:
        """Jump to the next unfilled fillable field in tab order."""
        fillable = [f for f in self.fields if f.is_fillable]
        if not fillable:
            return None

        start_idx = 0
        keys = [f.key for f in fillable]
        if self.active_field_key in keys:
            start_idx = (keys.index(self.active_field_key) + 1) % len(fillable)

        ordered = fillable[start_idx:] + fillable[:start_idx]
        target = next((f for f in ordered if not self._is_field_filled(f)), None)
        if target is None:
            self._show_feedback("All fillable fields already have values.", "success")
            self._safe_page_update()
            return None

        self.focus_field(target.key)
        return target.key

    def change_page(self, delta: int) -> None:
        if not self.current_file or self.total_pages < 1:
            return
        target = max(0, min(self.current_page_index + delta, self.total_pages - 1))
        if target == self.current_page_index:
            return
        self.current_page_index = target
        try:
            self._refresh_preview_data()
        except Exception as err:
            self._show_feedback(f"Failed to render page {target + 1}: {err}", "error")
        self._render_canvas()
        if self.current_page_only:
            self._render_sidebar()
        self._safe_page_update()

    def on_overlay_click(self, key: str, option_value: str | None = None) -> None:
        """Handle clicking an interactive hotspot on the PDF page preview."""
        desc = self._get_field_by_key(key)
        if desc is None:
            return

        if not desc.is_read_only:
            if desc.field_type == "checkbox":
                current = bool(self.pending_values.get(key, False))
                self.pending_values[key] = not current
            elif desc.field_type == "radio" and option_value:
                self.pending_values[key] = option_value

        self.focus_field(key)

    def reset_form_edits(self) -> None:
        """Restore all pending values back to the original loaded PDF values."""
        self.pending_values = {f.key: f.default_value for f in self.fields}
        try:
            self._refresh_preview_data()
        except Exception:
            pass
        self._refresh_all_panels()
        self._show_feedback("Restored original PDF form values.", "info")
        self._safe_page_update()

    def clear_form_fields(self) -> None:
        """Clear all fillable field values (keeps read-only fields untouched)."""
        for f in self.fields:
            if f.is_read_only or not f.is_fillable:
                continue
            self.pending_values[f.key] = False if f.field_type == "checkbox" else ""
        try:
            self._refresh_preview_data()
        except Exception:
            pass
        self._refresh_all_panels()
        self._show_feedback("Cleared all fillable form fields.", "info")
        self._safe_page_update()

    def _on_search_change(self, e) -> None:
        self.search_query = (self._search_field.value or "").strip().lower()
        self._render_sidebar()
        self._safe_page_update()

    def _on_page_filter_toggle(self, e) -> None:
        self.current_page_only = bool(self._page_filter_switch.value)
        self._render_sidebar()
        self._safe_page_update()

    # -------------------------------------------------------------------------
    # Save & Flatten Actions
    # -------------------------------------------------------------------------

    def _trigger_save(self, flatten: bool) -> None:
        if self.is_processing:
            return
        if not self.current_file or not os.path.exists(self.current_file):
            show_snackbar(self.page, "Please select a PDF form first.", "error")
            return
        if not self.fields:
            show_snackbar(self.page, "No interactive AcroForm fields found in this document.", "warning")
            return

        self.is_processing = True
        self._render_export_bar()
        self._safe_page_update()

        def worker():
            self.save_form_pdf(flatten=flatten)

        run_background(self.page, worker)

    def save_form_pdf(self, flatten: bool = False) -> dict | None:
        """Fill and save either an editable form PDF or a flattened read-only PDF."""
        if not self.current_file or not os.path.exists(self.current_file):
            self._show_feedback("Please select a valid PDF file first.", "error")
            return None
        if not self.fields:
            self._show_feedback("No AcroForm fields detected to export.", "error")
            return None

        op_slug = "flattened_form" if flatten else "filled_form"
        out_name = generate_output_filename(self.current_file, op_slug, ".pdf")
        out_path = str(Path(self.output_dir) / out_name)

        def on_progress(step: int, total: int, message: str):
            update_progress(self.progress_bar, self.progress_text, step / max(total, 1), message)

        try:
            update_progress(self.progress_bar, self.progress_text, 0.05, "Preparing AcroForm export...")
            report = fill_and_save_pdf_form(
                source=self.current_file,
                output_path=out_path,
                field_values=self.pending_values,
                flatten=flatten,
                progress_callback=on_progress,
            )
            self.last_export_report = report

            mode_label = "Flattened (Read-Only)" if flatten else "Editable AcroForm"
            update_progress(self.progress_bar, self.progress_text, 1.0, f"{mode_label} saved!")
            time.sleep(0.15)
            reset_progress(self.progress_bar, self.progress_text)

            self._show_feedback(
                f"Saved {mode_label}: {Path(out_path).name} "
                f"({report['fields_updated']} fields applied, {report['remaining_widgets']} interactive widgets remaining).",
                "success",
                output_path=out_path,
            )
            try:
                show_snackbar(self.page, f"Exported {Path(out_path).name}", "success")
            except Exception:
                pass
            return report
        except Exception as err:
            reset_progress(self.progress_bar, self.progress_text)
            self._show_feedback(f"Form export failed: {err}", "error")
            return None
        finally:
            self.is_processing = False
            self._render_export_bar()
            self._safe_page_update()

    # -------------------------------------------------------------------------
    # UI Rendering
    # -------------------------------------------------------------------------

    def _show_feedback(self, message: str, level: str = "info", output_path: str | None = None) -> None:
        is_dark = self._is_dark()
        color_map = {
            "success": (ThemeTokens.ACCENT_SUCCESS, ft.Icons.CHECK_CIRCLE_OUTLINE),
            "error": (ThemeTokens.ACCENT_DANGER, ft.Icons.ERROR_OUTLINE),
            "warning": (ThemeTokens.ACCENT_WARNING, ft.Icons.WARNING_AMBER),
            "info": (ThemeTokens.ACCENT_PRIMARY, ft.Icons.INFO_OUTLINE),
        }
        accent, icon = color_map.get(level, color_map["info"])

        row_items: list[ft.Control] = [
            ft.Icon(icon, size=18, color=accent),
            ft.Text(message, size=12, color=ThemeTokens.text_primary(is_dark), expand=True),
        ]
        if output_path and os.path.exists(output_path):
            row_items.append(
                ft.OutlinedButton(
                    "Open Folder",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda e, p=str(Path(output_path).parent): open_folder(p),
                )
            )

        self._feedback_container.content = ft.Row(row_items, spacing=10, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        self._feedback_container.padding = padding_symmetric(horizontal=12, vertical=8)
        self._feedback_container.border_radius = ThemeTokens.RADIUS_SM
        self._feedback_container.border = ft.Border.all(1, accent)
        self._feedback_container.bgcolor = ThemeTokens.bg_card(is_dark)
        self._feedback_container.visible = True

    def _refresh_all_panels(self) -> None:
        self._render_header_badge()
        self._render_metrics_strip()
        self._render_canvas()
        self._render_sidebar()
        self._render_export_bar()

    def _render_header_badge(self) -> None:
        is_dark = self._is_dark()
        self._header_badge_slot.controls.clear()

        if not self.current_file or not self.current_file.lower().endswith(".pdf"):
            self._header_badge_slot.controls.append(
                make_badge("No PDF Loaded", ThemeTokens.bg_hover(is_dark), ThemeTokens.text_muted(is_dark))
            )
            return

        if self.form_summary is None:
            self._header_badge_slot.controls.append(
                make_badge("Form Unavailable", ThemeTokens.ACCENT_DANGER, ThemeTokens.DARK_TEXT_PRIMARY, ft.Icons.LOCK)
            )
            return

        fillable = int(self.form_summary.get("fillable_count", 0))
        total = int(self.form_summary.get("total_fields", 0))
        if fillable > 0:
            self._header_badge_slot.controls.append(
                make_badge(
                    f"{fillable} Fillable Field{'s' if fillable != 1 else ''}",
                    ThemeTokens.ACCENT_PRIMARY,
                    ThemeTokens.DARK_TEXT_PRIMARY,
                    ft.Icons.DYNAMIC_FORM,
                )
            )
        elif total > 0:
            self._header_badge_slot.controls.append(
                make_badge(
                    f"{total} Read-Only Fields",
                    ThemeTokens.ACCENT_WARNING,
                    ThemeTokens.DARK_TEXT_PRIMARY,
                    ft.Icons.LOCK_OUTLINE,
                )
            )
        else:
            self._header_badge_slot.controls.append(
                make_badge(
                    "No Form Fields",
                    ThemeTokens.bg_hover(is_dark),
                    ThemeTokens.text_muted(is_dark),
                    ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                )
            )

    def _render_metrics_strip(self) -> None:
        is_dark = self._is_dark()
        self._metrics_strip.controls.clear()

        if not self.fields:
            return

        filled, fillable = self._filled_stats()
        t_counts = (self.form_summary or {}).get("type_counts", {})
        chips = [
            make_badge(
                f"Progress: {filled}/{fillable} filled",
                ThemeTokens.ACCENT_SUCCESS if filled == fillable and fillable > 0 else ThemeTokens.bg_hover(is_dark),
                ThemeTokens.DARK_TEXT_PRIMARY if filled == fillable and fillable > 0 else ThemeTokens.text_primary(is_dark),
                ft.Icons.TASK_ALT,
            ),
        ]
        type_labels = [
            ("text", "Text"),
            ("checkbox", "Checkboxes"),
            ("radio", "Radio Groups"),
            ("combobox", "Dropdowns"),
            ("listbox", "Lists"),
        ]
        for key, label in type_labels:
            cnt = int(t_counts.get(key, 0))
            if cnt > 0:
                chips.append(make_badge(f"{cnt} {label}", ThemeTokens.bg_card(is_dark), ThemeTokens.text_secondary(is_dark)))

        self._metrics_strip.controls.extend(chips)

    def _render_canvas(self) -> None:
        is_dark = self._is_dark()

        if not self.current_file or not self.current_file.lower().endswith(".pdf"):
            self._canvas_host.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.DYNAMIC_FORM_OUTLINED, size=42, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text("Select a PDF Document", size=14, weight=ft.FontWeight.W_600, color=ThemeTokens.text_secondary(is_dark)),
                        ft.Text(
                            "Load an AcroForm PDF (Ctrl+O) to inspect fields, preview edits live, and flatten to read-only.",
                            size=11,
                            color=ThemeTokens.text_muted(is_dark),
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                ),
                height=420,
                alignment=ft.Alignment.CENTER,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                bgcolor=ThemeTokens.bg_card(is_dark),
                padding=20,
            )
            return

        if not self.preview_data:
            self._canvas_host.content = ft.Container(
                content=ft.Text("Preview unavailable for this document.", size=12, color=ThemeTokens.ACCENT_WARNING),
                height=320,
                alignment=ft.Alignment.CENTER,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                bgcolor=ThemeTokens.bg_card(is_dark),
            )
            return

        cw = float(self.preview_data["canvas_width"])
        ch = float(self.preview_data["canvas_height"])
        overlays = self.preview_data.get("overlays", [])

        stack_children: list[ft.Control] = [
            ft.Image(
                src=self.preview_data["png_bytes"],
                width=cw,
                height=ch,
                fit=ft.BoxFit.CONTAIN,
            )
        ]

        for ov in overlays:
            nx, ny, nw, nh = ov["norm_rect"]
            left = nx * cw
            top = ny * ch
            w = max(14.0, nw * cw)
            h = max(12.0, nh * ch)
            is_active = bool(ov["is_active"])
            is_ro = bool(ov["is_read_only"])

            if is_active:
                border_color = ThemeTokens.ACCENT_PRIMARY
                bg_color = "#3B82F633"
                border_w = 2.0
            elif is_ro:
                border_color = ThemeTokens.text_muted(is_dark)
                bg_color = "#64748B18"
                border_w = 1.0
            else:
                border_color = "#10B981AA" if ov["key"] in self.pending_values and self.pending_values[ov["key"]] else "#3B82F666"
                bg_color = "#3B82F612"
                border_w = 1.0

            hotspot = ft.Container(
                left=left,
                top=top,
                width=w,
                height=h,
                border=ft.Border.all(border_w, border_color),
                bgcolor=bg_color,
                border_radius=3,
                tooltip=f"#{ov['tab_index']} {ov['label']}",
                on_click=lambda e, k=ov["key"], opt=ov.get("option_value"): self.on_overlay_click(k, opt),
            )
            stack_children.append(hotspot)

            if is_active:
                stack_children.append(
                    ft.Container(
                        left=left,
                        top=max(0.0, top - 16.0),
                        content=ft.Text(f"#{ov['tab_index']}", size=9, weight=ft.FontWeight.W_700, color=ft.Colors.WHITE),
                        bgcolor=ThemeTokens.ACCENT_PRIMARY,
                        padding=padding_symmetric(horizontal=4, vertical=1),
                        border_radius=3,
                    )
                )

        page_nav = ft.Row(
            [
                ft.IconButton(
                    ft.Icons.CHEVRON_LEFT,
                    icon_size=18,
                    disabled=self.current_page_index <= 0,
                    on_click=lambda e: self.change_page(-1),
                    tooltip="Previous Page",
                ),
                ft.Text(
                    f"Page {self.current_page_index + 1} / {max(self.total_pages, 1)}",
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=ThemeTokens.text_primary(is_dark),
                ),
                ft.IconButton(
                    ft.Icons.CHEVRON_RIGHT,
                    icon_size=18,
                    disabled=self.current_page_index >= self.total_pages - 1,
                    on_click=lambda e: self.change_page(1),
                    tooltip="Next Page",
                ),
                ft.Container(expand=True),
                ft.Text(
                    f"{len(overlays)} field{'s' if len(overlays) != 1 else ''} on page",
                    size=11,
                    color=ThemeTokens.text_muted(is_dark),
                ),
            ],
            spacing=4,
            alignment=ft.MainAxisAlignment.START,
        )

        self._canvas_host.content = ft.Container(
            content=ft.Column(
                [
                    page_nav,
                    ft.Container(
                        content=ft.Stack(stack_children, width=cw, height=ch),
                        alignment=ft.Alignment.CENTER,
                        padding=8,
                        border_radius=ThemeTokens.RADIUS_SM,
                        bgcolor=ThemeTokens.bg_surface(is_dark),
                        border=ft.Border.all(1, ThemeTokens.border(is_dark)),
                    ),
                    ft.Text(
                        "Tip: Click any highlighted field box on the document to focus or toggle it.",
                        size=10,
                        color=ThemeTokens.text_muted(is_dark),
                    ),
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

    def _build_field_input_control(self, desc: FormFieldDescriptor, is_dark: bool) -> ft.Control:
        """Dynamically generate the Flet input control bound to a PDF field descriptor."""
        current_val = self.pending_values.get(desc.key, desc.value)
        is_disabled = desc.is_read_only

        if desc.field_type == "text":
            ctrl = ft.TextField(
                value="" if current_val is None else str(current_val),
                hint_text=f"Enter {desc.field_label}...",
                multiline=desc.is_multiline,
                min_lines=2 if desc.is_multiline else 1,
                max_lines=4 if desc.is_multiline else 1,
                password=desc.is_password,
                can_reveal_password=desc.is_password,
                read_only=is_disabled,
                text_size=12,
                dense=True,
                border_radius=ThemeTokens.RADIUS_SM,
                on_focus=lambda e, k=desc.key: self._on_control_focus(k),
                on_change=lambda e, k=desc.key: self.set_field_value(k, e.control.value, refresh_preview=True),
                on_submit=lambda e, k=desc.key: self.step_tab_order(1),
            )
            self._field_controls[desc.key] = ctrl
            return ctrl

        if desc.field_type == "checkbox":
            ctrl = ft.Checkbox(
                label=desc.field_label,
                value=bool(current_val),
                disabled=is_disabled,
                on_change=lambda e, k=desc.key: self.set_field_value(k, bool(e.control.value), refresh_preview=True),
            )
            self._field_controls[desc.key] = ctrl
            return ctrl

        if desc.field_type == "radio":
            radios = [
                ft.Radio(value=opt, label=opt, disabled=is_disabled)
                for opt in desc.options
            ]
            ctrl = ft.RadioGroup(
                value="" if current_val is None else str(current_val),
                content=ft.Column(radios, spacing=2),
                disabled=is_disabled,
                on_change=lambda e, k=desc.key: self.set_field_value(k, e.control.value, refresh_preview=True),
            )
            self._field_controls[desc.key] = ctrl
            return ctrl

        if desc.field_type in ("combobox", "listbox"):
            options = [ft.dropdown.Option(key=opt, text=opt) for opt in desc.options]
            val_str = "" if current_val is None else str(current_val)
            if val_str and val_str not in desc.options:
                options.insert(0, ft.dropdown.Option(key=val_str, text=val_str))
            ctrl = ft.Dropdown(
                options=options,
                value=val_str if val_str else None,
                hint_text="Select an option...",
                dense=True,
                disabled=is_disabled,
                expand=True,
                on_select=lambda e, k=desc.key: self.set_field_value(k, e.control.value, refresh_preview=True),
            )
            self._field_controls[desc.key] = ctrl
            return ctrl

        return ft.Text(
            f"Interactive {desc.field_type_label} field (preserved on editable save, baked on flatten).",
            size=11,
            color=ThemeTokens.text_muted(is_dark),
        )

    def _on_control_focus(self, key: str) -> None:
        if self.active_field_key == key:
            return
        self.active_field_key = key
        desc = self._get_field_by_key(key)
        if desc and desc.page_index != self.current_page_index and 0 <= desc.page_index < self.total_pages:
            self.current_page_index = desc.page_index
        try:
            self._refresh_preview_data()
            self._render_canvas()
            self._safe_page_update()
        except Exception:
            pass

    def _render_sidebar(self) -> None:
        is_dark = self._is_dark()
        self._field_controls.clear()

        if not self.current_file or not self.current_file.lower().endswith(".pdf"):
            self._sidebar_host.content = ft.Container(
                content=ft.Text(
                    "Form structure will appear here once a PDF is loaded.",
                    size=12,
                    color=ThemeTokens.text_muted(is_dark),
                ),
                padding=16,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                bgcolor=ThemeTokens.bg_card(is_dark),
            )
            return

        if not self.fields:
            self._sidebar_host.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.FIND_IN_PAGE_OUTLINED, size=32, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text("No AcroForm Fields Detected", size=13, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                        ft.Text(
                            "This PDF does not contain interactive form widgets. Use Sign & Stamp or Edit & Stamp for flat documents.",
                            size=11,
                            color=ThemeTokens.text_muted(is_dark),
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=20,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                bgcolor=ThemeTokens.bg_card(is_dark),
            )
            return

        filtered_fields = []
        for f in self.fields:
            if self.current_page_only and f.page_index != self.current_page_index:
                continue
            if self.search_query:
                hay = f"{f.field_label} {f.field_name} {f.field_type_label}".lower()
                if self.search_query not in hay:
                    continue
            filtered_fields.append(f)

        tab_nav_bar = ft.Row(
            [
                ft.OutlinedButton(
                    "Prev",
                    icon=ft.Icons.ARROW_UPWARD,
                    on_click=lambda e: self.step_tab_order(-1),
                    tooltip="Previous field in tab order",
                ),
                ft.OutlinedButton(
                    "Next",
                    icon=ft.Icons.ARROW_DOWNWARD,
                    on_click=lambda e: self.step_tab_order(1),
                    tooltip="Next field in tab order",
                ),
                ft.FilledTonalButton(
                    "Next Empty",
                    icon=ft.Icons.SKIP_NEXT,
                    on_click=lambda e: self.jump_to_next_empty(),
                    tooltip="Jump to next unfilled field",
                ),
            ],
            spacing=6,
            wrap=True,
        )

        field_cards: list[ft.Control] = []
        last_page_seen: int | None = None
        for desc in filtered_fields:
            if desc.page_index != last_page_seen:
                last_page_seen = desc.page_index
                field_cards.append(
                    ft.Container(
                        content=ft.Text(
                            f"PAGE {desc.page_index + 1}",
                            size=10,
                            weight=ft.FontWeight.W_700,
                            color=ThemeTokens.text_muted(is_dark),
                        ),
                        padding=padding_symmetric(horizontal=4, vertical=2),
                    )
                )

            is_active = desc.key == self.active_field_key
            badges: list[ft.Control] = [
                make_badge(f"#{desc.tab_index}", ThemeTokens.ACCENT_PRIMARY if is_active else ThemeTokens.bg_hover(is_dark), ft.Colors.WHITE if is_active else ThemeTokens.text_secondary(is_dark)),
                make_badge(desc.field_type_label, ThemeTokens.bg_surface(is_dark), ThemeTokens.text_secondary(is_dark)),
            ]
            if desc.is_required:
                badges.append(make_badge("Required", ThemeTokens.ACCENT_WARNING, ThemeTokens.DARK_TEXT_PRIMARY))
            if desc.is_read_only:
                badges.append(make_badge("Read-Only", ThemeTokens.bg_hover(is_dark), ThemeTokens.text_muted(is_dark)))

            input_control = self._build_field_input_control(desc, is_dark)

            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    desc.field_label,
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    color=ThemeTokens.text_primary(is_dark),
                                    expand=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Row(badges, spacing=4, tight=True),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        input_control,
                    ],
                    spacing=6,
                ),
                padding=10,
                border_radius=ThemeTokens.RADIUS_SM,
                border=ft.Border.all(
                    1.5 if is_active else 1,
                    ThemeTokens.ACCENT_PRIMARY if is_active else ThemeTokens.border_muted(is_dark),
                ),
                bgcolor=ThemeTokens.bg_surface(is_dark),
                on_click=lambda e, k=desc.key: self.focus_field(k, attempt_control_focus=False),
            )
            field_cards.append(card)

        if not field_cards:
            field_cards.append(
                ft.Container(
                    content=ft.Text("No fields match the current filter.", size=12, color=ThemeTokens.text_muted(is_dark)),
                    padding=14,
                    alignment=ft.Alignment.CENTER,
                )
            )

        self._sidebar_host.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Form Inspector", size=14, weight=ft.FontWeight.W_700, color=ThemeTokens.text_primary(is_dark)),
                            ft.Container(expand=True),
                            ft.TextButton("Reset", icon=ft.Icons.RESTART_ALT, on_click=lambda e: self.reset_form_edits()),
                            ft.TextButton("Clear", icon=ft.Icons.CLEAR_ALL, on_click=lambda e: self.clear_form_fields()),
                        ],
                        spacing=4,
                    ),
                    tab_nav_bar,
                    ft.Row(
                        [
                            self._search_field,
                            self._page_filter_switch,
                        ],
                        spacing=8,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                    ft.Container(
                        content=ft.Column(field_cards, spacing=8, scroll=ft.ScrollMode.AUTO),
                        height=470,
                    ),
                ],
                spacing=8,
            ),
            padding=12,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

    def _render_export_bar(self) -> None:
        is_dark = self._is_dark()
        has_fields = bool(self.current_file and self.fields)
        disabled = self.is_processing or not has_fields

        self._export_bar_host.content = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(
                                "Finalize & Export",
                                size=13,
                                weight=ft.FontWeight.W_700,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                            ft.Text(
                                "Save editable AcroForm values or flatten widgets into immutable page content.",
                                size=11,
                                color=ThemeTokens.text_secondary(is_dark),
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.OutlinedButton(
                        "Save as Editable Form",
                        icon=ft.Icons.SAVE_AS,
                        disabled=disabled,
                        on_click=lambda e: self._trigger_save(flatten=False),
                    ),
                    ft.FilledButton(
                        "Save & Flatten (Read-Only)",
                        icon=ft.Icons.LOCK_OUTLINE,
                        disabled=disabled,
                        on_click=lambda e: self._trigger_save(flatten=True),
                        style=ft.ButtonStyle(
                            bgcolor=ThemeTokens.ACCENT_PRIMARY,
                            color=ft.Colors.WHITE,
                            shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM),
                        ),
                    ),
                ],
                spacing=10,
                wrap=True,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=12,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

    def build_ui(self) -> ft.Control:
        """Build the Phase 8 Interactive Form Filler & Flattener workspace."""
        is_dark = self._is_dark()
        self._refresh_all_panels()

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "Interactive Form Filler & Flattener",
                                    size=16,
                                    weight=ft.FontWeight.W_700,
                                    color=ThemeTokens.text_primary(is_dark),
                                ),
                                ft.Text(
                                    "Inspect AcroForm fields, fill values in tab order, and export editable or flattened read-only PDFs.",
                                    size=12,
                                    color=ThemeTokens.text_secondary(is_dark),
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        self._header_badge_slot,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self._metrics_strip,
                self._feedback_container,
                ft.ResponsiveRow(
                    [
                        ft.Container(self._canvas_host, col={"sm": 12, "lg": 7}),
                        ft.Container(self._sidebar_host, col={"sm": 12, "lg": 5}),
                    ],
                    spacing=12,
                    run_spacing=12,
                ),
                self._export_bar_host,
            ],
            spacing=12,
            expand=True,
        )
