"""Permanent Redaction & Metadata Sanitizer workspace (Phase 6).

Operate Mode:
- True stream-level PDF redaction (permanently eliminates text, vectors, and pixels).
- Interactive page canvas for drawing manual bounding-box redactions.
- Configurable regex pattern detector (Email, Phone, SSN, Credit Card, Custom)
  with instant preview list of matched confidential strings.
- One-click Metadata Sanitizer (Info dict, timestamps, XMP XML, thumbnails,
  color profiles / OutputIntents, embedded files) with deletion report.
- Automated Zero-Leakage verification on exported PDFs.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import time
import uuid
import flet as ft

from app_state import AppState
from pdf_engine import (
    PatternMatch,
    RedactionBox,
    apply_pdf_redactions,
    inspect_pdf,
    inspect_pdf_metadata,
    render_redaction_page_preview,
    sanitize_pdf_metadata,
    scan_pdf_patterns,
    verify_zero_leakage,
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


_FILL_COLOR_OPTIONS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "black": ("Solid Black (#000000)", (0.0, 0.0, 0.0)),
    "slate": ("Dark Slate (#1E293B)", (0.118, 0.161, 0.231)),
    "white": ("Blank White (#FFFFFF)", (1.0, 1.0, 1.0)),
}


class RedactionSanitizerView:
    """Enterprise-grade Permanent Redaction & Metadata Sanitizer workspace."""

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

        # Document & Redaction State
        self.current_file: str | None = getattr(app_state, "current_file", None)
        self.current_page_index: int = 0
        self.total_pages: int = 0
        self.preview_data: dict | None = None
        self.manual_boxes: list[RedactionBox] = []
        self.pattern_matches: list[PatternMatch] = []
        self.metadata_info: dict | None = None
        self.last_sanitization_report: dict | None = None
        self.last_leakage_report: dict | None = None
        self.last_output_path: str | None = None
        self.is_processing: bool = False

        # Drag state on interactive canvas
        self._drag_start: tuple[float, float] | None = None
        self._drag_current: tuple[float, float] | None = None

        self._build_controls()
        if self.current_file and os.path.exists(self.current_file):
            self._load_document_state(self.current_file)

    def _is_dark(self) -> bool:
        return self.is_dark_supplier()

    def set_current_file(self, file_path: str | None) -> None:
        """Reactive callback triggered by central AppState."""
        if file_path == self.current_file:
            return

        self.current_file = file_path
        self.current_page_index = 0
        self.total_pages = 0
        self.preview_data = None
        self.manual_boxes.clear()
        self.pattern_matches.clear()
        self.metadata_info = None
        self.last_sanitization_report = None
        self.last_leakage_report = None
        self.last_output_path = None
        self._feedback_container.visible = False

        if file_path and os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
            self._load_document_state(file_path)
        else:
            self._refresh_all_panels()

        self._safe_page_update()

    def _load_document_state(self, file_path: str) -> None:
        """Load preview page and metadata audit for a PDF document."""
        try:
            info = inspect_pdf(file_path)
            self.total_pages = int(info.get("page_count", 0))
            if self.total_pages > 0:
                self.current_page_index = max(0, min(self.current_page_index, self.total_pages - 1))
                self.preview_data = render_redaction_page_preview(
                    file_path, page_index=self.current_page_index
                )
            self.metadata_info = inspect_pdf_metadata(file_path)
        except Exception as err:
            self.preview_data = None
            self.metadata_info = None
            self._show_feedback(f"Could not inspect PDF: {err}", "error")

        self._refresh_all_panels()

    def _safe_page_update(self) -> None:
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass

    def _build_controls(self) -> None:
        """Instantiate interactive UI controls."""
        # Pattern preset checkboxes
        self._cat_email = ft.Checkbox(label="Emails", value=True)
        self._cat_phone = ft.Checkbox(label="Phones", value=True)
        self._cat_ssn = ft.Checkbox(label="SSN / IDs", value=True)
        self._cat_card = ft.Checkbox(label="Credit Cards", value=True)

        self._custom_regex_field = ft.TextField(
            label="Custom Regex Pattern (Optional)",
            hint_text=r"e.g. \bCONFIDENTIAL\b or Project-[A-Z0-9]+",
            text_size=12,
            expand=True,
            border_radius=ThemeTokens.RADIUS_SM,
        )
        self._case_sensitive_switch = ft.Switch(
            label="Case Sensitive",
            value=False,
        )

        # Export & Redaction options
        self._fill_color_dropdown = ft.Dropdown(
            label="Redaction Fill",
            options=[
                ft.dropdown.Option(key=k, text=label)
                for k, (label, _) in _FILL_COLOR_OPTIONS.items()
            ],
            value="black",
            width=210,
        )
        self._redact_images_switch = ft.Switch(
            label="Redact Image Pixels",
            value=True,
            tooltip="Blank out bitmap image regions overlapped by redaction boxes",
        )
        self._sanitize_meta_switch = ft.Switch(
            label="Sanitize Metadata on Export",
            value=True,
            tooltip="Purge Author, Creator, Timestamps, XMP XML, Thumbnails & Color Profiles",
        )

        # Dynamic containers
        self._active_doc_container = ft.Container()
        self._feedback_container = ft.Container(visible=False)
        self._canvas_container = ft.Container()
        self._manual_list_container = ft.Container()
        self._matches_list_container = ft.Container()
        self._metadata_panel_container = ft.Container()
        self._sanitization_report_container = ft.Container(visible=False)
        self._leakage_report_container = ft.Container(visible=False)

        self._drag_overlay = ft.Container(
            visible=False,
            left=0,
            top=0,
            width=0,
            height=0,
            bgcolor="#44EF4444",
            border=ft.Border.all(2, ThemeTokens.ACCENT_DANGER),
            border_radius=2,
        )

        self._refresh_all_panels()

    def _refresh_all_panels(self) -> None:
        self._refresh_active_doc_card()
        self._refresh_canvas_panel()
        self._refresh_manual_list()
        self._refresh_matches_list()
        self._refresh_metadata_panel()
        self._refresh_sanitization_report()
        self._refresh_leakage_report()

    # -------------------------------------------------------------------------
    # Active Document Banner
    # -------------------------------------------------------------------------

    def _refresh_active_doc_card(self) -> None:
        is_dark = self._is_dark()
        if not self.current_file or not os.path.exists(self.current_file):
            self._active_doc_container.content = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text(
                            "Select a PDF document above to redact sensitive data and sanitize metadata",
                            size=12,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                    ],
                    spacing=8,
                ),
                padding=10,
                border_radius=ThemeTokens.RADIUS_SM,
                bgcolor=ThemeTokens.bg_hover(is_dark),
                border=ft.Border.all(1, ThemeTokens.border(is_dark)),
            )
            return

        name = os.path.basename(self.current_file)
        size_mb = os.path.getsize(self.current_file) / (1024 * 1024)
        page_label = f" • {self.total_pages} Pages" if self.total_pages else ""
        queued_count = self._active_redaction_count()
        badge_text = f"{queued_count} Queued" if queued_count else "Ready"
        badge_color = ThemeTokens.ACCENT_WARNING if queued_count else ThemeTokens.ACCENT_SUCCESS

        self._active_doc_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PRIVACY_TIP, size=20, color=ThemeTokens.ACCENT_DANGER),
                    ft.Column(
                        [
                            ft.Text(name, size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Text(
                                f"Offline Redaction Studio • {size_mb:.2f} MB{page_label}",
                                size=11,
                                color=ThemeTokens.text_secondary(is_dark),
                            ),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    make_badge(badge_text, ThemeTokens.bg_surface(is_dark), badge_color),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_hover(is_dark),
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
        )

    def _active_redaction_count(self) -> int:
        match_rects = sum(len(m.rects) for m in self.pattern_matches if m.selected)
        return len([b for b in self.manual_boxes if b.enabled]) + match_rects

    # -------------------------------------------------------------------------
    # Interactive Manual Redaction Canvas
    # -------------------------------------------------------------------------

    def add_manual_box(
        self,
        page_index: int,
        rect: tuple[float, float, float, float],
        label: str = "Manual Region",
    ) -> RedactionBox:
        """Programmatically or interactively add a manual redaction region in PDF points."""
        x0, y0, x1, y1 = rect
        norm_rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        box = RedactionBox(
            id=str(uuid.uuid4())[:8],
            page_index=page_index,
            rect=norm_rect,
            label=label,
            category="manual",
        )
        self.manual_boxes.append(box)
        self._refresh_active_doc_card()
        self._refresh_canvas_panel()
        self._refresh_manual_list()
        self._safe_page_update()
        return box

    def remove_manual_box(self, box_id: str) -> None:
        self.manual_boxes = [b for b in self.manual_boxes if b.id != box_id]
        self._refresh_active_doc_card()
        self._refresh_canvas_panel()
        self._refresh_manual_list()
        self._safe_page_update()

    def clear_manual_boxes(self, current_page_only: bool = False) -> None:
        if current_page_only:
            self.manual_boxes = [b for b in self.manual_boxes if b.page_index != self.current_page_index]
        else:
            self.manual_boxes.clear()
        self._refresh_active_doc_card()
        self._refresh_canvas_panel()
        self._refresh_manual_list()
        self._safe_page_update()

    def change_page(self, delta: int) -> None:
        if not self.current_file or self.total_pages < 1:
            return
        target = max(0, min(self.current_page_index + delta, self.total_pages - 1))
        if target == self.current_page_index:
            return
        self.current_page_index = target
        try:
            self.preview_data = render_redaction_page_preview(
                self.current_file, page_index=self.current_page_index
            )
        except Exception as err:
            show_snackbar(self.page, f"Could not render page {target + 1}: {err}", "error")
            return
        self._refresh_canvas_panel()
        self._safe_page_update()

    def _on_canvas_pan_start(self, e: ft.DragStartEvent) -> None:
        if not self.preview_data:
            return
        cw = self.preview_data["canvas_width"]
        ch = self.preview_data["canvas_height"]
        x = max(0.0, min(float(e.local_position.x), cw))
        y = max(0.0, min(float(e.local_position.y), ch))
        self._drag_start = (x, y)
        self._drag_current = (x, y)
        self._drag_overlay.left = x
        self._drag_overlay.top = y
        self._drag_overlay.width = 0
        self._drag_overlay.height = 0
        self._drag_overlay.visible = True
        try:
            self._drag_overlay.update()
        except Exception:
            pass

    def _on_canvas_pan_update(self, e: ft.DragUpdateEvent) -> None:
        if not self._drag_start or not self.preview_data:
            return
        cw = self.preview_data["canvas_width"]
        ch = self.preview_data["canvas_height"]
        x = max(0.0, min(float(e.local_position.x), cw))
        y = max(0.0, min(float(e.local_position.y), ch))
        self._drag_current = (x, y)

        sx, sy = self._drag_start
        self._drag_overlay.left = min(sx, x)
        self._drag_overlay.top = min(sy, y)
        self._drag_overlay.width = abs(x - sx)
        self._drag_overlay.height = abs(y - sy)
        self._drag_overlay.visible = True
        try:
            self._drag_overlay.update()
        except Exception:
            pass

    def _on_canvas_pan_end(self, e: ft.DragEndEvent) -> None:
        if not self._drag_start or not self.preview_data:
            return
        cw = self.preview_data["canvas_width"]
        ch = self.preview_data["canvas_height"]
        scale = self.preview_data["scale"]

        end_pos = getattr(e, "local_position", None)
        if end_pos is not None:
            ex = max(0.0, min(float(end_pos.x), cw))
            ey = max(0.0, min(float(end_pos.y), ch))
        elif self._drag_current is not None:
            ex, ey = self._drag_current
        else:
            ex, ey = self._drag_start

        sx, sy = self._drag_start
        self._drag_start = None
        self._drag_current = None
        self._drag_overlay.visible = False

        box_w = abs(ex - sx)
        box_h = abs(ey - sy)
        if box_w >= 6.0 and box_h >= 6.0 and scale > 0:
            pdf_rect = (
                min(sx, ex) / scale,
                min(sy, ey) / scale,
                max(sx, ex) / scale,
                max(sy, ey) / scale,
            )
            page_boxes_count = len([b for b in self.manual_boxes if b.page_index == self.current_page_index]) + 1
            self.add_manual_box(
                page_index=self.current_page_index,
                rect=pdf_rect,
                label=f"Manual Box P{self.current_page_index + 1} #{page_boxes_count}",
            )
            show_snackbar(
                self.page,
                f"Added redaction region on Page {self.current_page_index + 1}",
                "info",
            )
        else:
            try:
                self._drag_overlay.update()
            except Exception:
                pass

    def _refresh_canvas_panel(self) -> None:
        is_dark = self._is_dark()
        if not self.current_file or not self.preview_data:
            self._canvas_container.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.DRAW, size=36, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text(
                            "Interactive Redaction Selector",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                        ft.Text(
                            "Load a PDF to render pages and drag bounding boxes over confidential areas.",
                            size=11,
                            color=ThemeTokens.text_muted(is_dark),
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                ),
                alignment=ft.Alignment.CENTER,
                padding=28,
                border_radius=ThemeTokens.RADIUS_MD,
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                bgcolor=ThemeTokens.bg_surface(is_dark),
            )
            return

        cw = self.preview_data["canvas_width"]
        ch = self.preview_data["canvas_height"]
        scale = self.preview_data["scale"]

        stack_controls: list[ft.Control] = [
            ft.Image(
                src=self.preview_data["png_bytes"],
                width=cw,
                height=ch,
                fit=ft.BoxFit.FILL,
            )
        ]

        # Highlight matched regex regions on the current page (Amber)
        for match in self.pattern_matches:
            if not match.selected or match.page_index != self.current_page_index:
                continue
            for r in match.rects:
                rx0, ry0, rx1, ry1 = r
                stack_controls.append(
                    ft.Container(
                        left=rx0 * scale,
                        top=ry0 * scale,
                        width=max((rx1 - rx0) * scale, 4),
                        height=max((ry1 - ry0) * scale, 4),
                        bgcolor="#44F59E0B",
                        border=ft.Border.all(1.5, ThemeTokens.ACCENT_WARNING),
                        border_radius=2,
                        tooltip=f"{match.category_label}: {match.matched_text}",
                    )
                )

        # Highlight manual redaction boxes on the current page (Rose)
        for box in self.manual_boxes:
            if not box.enabled or box.page_index != self.current_page_index:
                continue
            bx0, by0, bx1, by1 = box.rect
            stack_controls.append(
                ft.Container(
                    left=bx0 * scale,
                    top=by0 * scale,
                    width=max((bx1 - bx0) * scale, 6),
                    height=max((by1 - by0) * scale, 6),
                    bgcolor="#55EF4444",
                    border=ft.Border.all(2, ThemeTokens.ACCENT_DANGER),
                    border_radius=2,
                    tooltip=box.label,
                )
            )

        stack_controls.append(self._drag_overlay)

        canvas_stack = ft.Stack(
            controls=stack_controls,
            width=cw,
            height=ch,
        )

        gesture_canvas = ft.GestureDetector(
            content=canvas_stack,
            mouse_cursor=ft.MouseCursor.PRECISE,
            drag_interval=16,
            on_pan_start=self._on_canvas_pan_start,
            on_pan_update=self._on_canvas_pan_update,
            on_pan_end=self._on_canvas_pan_end,
        )

        nav_bar = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    tooltip="Previous Page",
                    disabled=self.current_page_index <= 0,
                    on_click=lambda e: self.change_page(-1),
                ),
                ft.Text(
                    f"Page {self.current_page_index + 1} of {self.total_pages}",
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=ThemeTokens.text_primary(is_dark),
                ),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    tooltip="Next Page",
                    disabled=self.current_page_index >= self.total_pages - 1,
                    on_click=lambda e: self.change_page(1),
                ),
                ft.Container(expand=True),
                make_badge("Drag to Draw Redaction", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_DANGER),
                ft.OutlinedButton(
                    "Clear Page Boxes",
                    icon=ft.Icons.CLEAR_ALL,
                    on_click=lambda e: self.clear_manual_boxes(current_page_only=True),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
        )

        self._canvas_container.content = ft.Column(
            [
                nav_bar,
                ft.Container(
                    content=gesture_canvas,
                    alignment=ft.Alignment.CENTER,
                    padding=10,
                    border_radius=ThemeTokens.RADIUS_SM,
                    bgcolor=ThemeTokens.bg_app(is_dark),
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                ),
            ],
            spacing=8,
        )

    def _refresh_manual_list(self) -> None:
        is_dark = self._is_dark()
        if not self.manual_boxes:
            self._manual_list_container.content = ft.Text(
                "No manual bounding boxes drawn yet. Drag over the page preview above to select regions.",
                size=11,
                color=ThemeTokens.text_muted(is_dark),
            )
            return

        rows: list[ft.Control] = []
        for box in self.manual_boxes:
            x0, y0, x1, y1 = box.rect
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            make_badge(f"P.{box.page_index + 1}", ThemeTokens.bg_surface(is_dark), ThemeTokens.ACCENT_DANGER),
                            ft.Text(
                                f"{box.label} ({int(x0)}, {int(y0)}, {int(x1)}, {int(y1)} pt)",
                                size=11,
                                color=ThemeTokens.text_primary(is_dark),
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=16,
                                icon_color=ThemeTokens.ACCENT_DANGER,
                                tooltip="Remove Region",
                                on_click=lambda e, bid=box.id: self.remove_manual_box(bid),
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=padding_symmetric(horizontal=10, vertical=4),
                    border_radius=ThemeTokens.RADIUS_XS,
                    bgcolor=ThemeTokens.bg_surface(is_dark),
                    border=ft.Border.all(1, ThemeTokens.border(is_dark)),
                )
            )
        self._manual_list_container.content = ft.Column(rows, spacing=4)

    # -------------------------------------------------------------------------
    # Pattern Auto-Redaction Detector & Preview List
    # -------------------------------------------------------------------------

    def _get_selected_categories(self) -> list[str]:
        cats: list[str] = []
        if self._cat_email.value:
            cats.append("email")
        if self._cat_phone.value:
            cats.append("phone")
        if self._cat_ssn.value:
            cats.append("ssn")
        if self._cat_card.value:
            cats.append("credit_card")
        return cats

    def _on_scan_patterns_clicked(self, e) -> None:
        src = self._validate_source()
        if not src:
            return

        cats = self._get_selected_categories()
        custom = (self._custom_regex_field.value or "").strip()
        if not cats and not custom:
            show_snackbar(self.page, "Select at least one pattern preset or enter a custom regex", "warning")
            return

        try:
            self.pattern_matches = scan_pdf_patterns(
                source=src,
                categories=cats,
                custom_regex=custom or None,
                case_sensitive=bool(self._case_sensitive_switch.value),
            )
            self._refresh_active_doc_card()
            self._refresh_canvas_panel()
            self._refresh_matches_list()
            self._safe_page_update()

            if self.pattern_matches:
                show_snackbar(
                    self.page,
                    f"Detected {len(self.pattern_matches)} confidential pattern match(es)",
                    "info",
                )
            else:
                show_snackbar(self.page, "No matching sensitive patterns found in document", "success")
        except Exception as err:
            show_snackbar(self.page, f"Pattern scan failed: {err}", "error")

    def _toggle_pattern_match(self, match_id: str, selected: bool) -> None:
        for m in self.pattern_matches:
            if m.id == match_id:
                m.selected = selected
                break
        self._refresh_active_doc_card()
        self._refresh_canvas_panel()
        self._safe_page_update()

    def _select_all_matches(self, selected: bool) -> None:
        for m in self.pattern_matches:
            m.selected = selected
        self._refresh_active_doc_card()
        self._refresh_canvas_panel()
        self._refresh_matches_list()
        self._safe_page_update()

    def _refresh_matches_list(self) -> None:
        is_dark = self._is_dark()
        if not self.pattern_matches:
            self._matches_list_container.content = ft.Text(
                "Click 'Scan Document for Patterns' to preview matched emails, phones, SSNs, or cards.",
                size=11,
                color=ThemeTokens.text_muted(is_dark),
            )
            return

        selected_count = sum(1 for m in self.pattern_matches if m.selected)
        header_row = ft.Row(
            [
                make_badge(
                    f"{selected_count}/{len(self.pattern_matches)} Selected",
                    ThemeTokens.bg_surface(is_dark),
                    ThemeTokens.ACCENT_WARNING,
                ),
                ft.Container(expand=True),
                ft.TextButton("Select All", on_click=lambda e: self._select_all_matches(True)),
                ft.TextButton("Deselect All", on_click=lambda e: self._select_all_matches(False)),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        item_rows: list[ft.Control] = []
        for match in self.pattern_matches:
            item_rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Checkbox(
                                value=match.selected,
                                on_change=lambda e, mid=match.id: self._toggle_pattern_match(mid, bool(e.control.value)),
                            ),
                            make_badge(
                                f"P.{match.page_index + 1}",
                                ThemeTokens.bg_surface(is_dark),
                                ThemeTokens.ACCENT_PRIMARY,
                            ),
                            make_badge(
                                match.category_label,
                                ThemeTokens.bg_surface(is_dark),
                                ThemeTokens.ACCENT_WARNING,
                            ),
                            ft.Text(
                                match.matched_text,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                                expand=True,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{len(match.rects)} hit(s)",
                                size=10,
                                color=ThemeTokens.text_muted(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=padding_symmetric(horizontal=8, vertical=4),
                    border_radius=ThemeTokens.RADIUS_XS,
                    bgcolor=ThemeTokens.bg_surface(is_dark),
                    border=ft.Border.all(1, ThemeTokens.border(is_dark)),
                )
            )

        self._matches_list_container.content = ft.Column(
            [header_row, ft.Column(item_rows, spacing=4, scroll=ft.ScrollMode.AUTO, max_height=220)],
            spacing=6,
        )

    # -------------------------------------------------------------------------
    # Metadata Inspector & Sanitizer Report
    # -------------------------------------------------------------------------

    def _refresh_metadata_panel(self) -> None:
        is_dark = self._is_dark()
        if not self.metadata_info:
            self._metadata_panel_container.content = ft.Text(
                "Load a PDF to audit tracking metadata, XMP XML packets, embedded thumbnails, and color profiles.",
                size=11,
                color=ThemeTokens.text_muted(is_dark),
            )
            return

        info_fields = self.metadata_info.get("info_fields", {})
        has_xmp = self.metadata_info.get("has_xmp", False)
        xmp_bytes = self.metadata_info.get("xmp_bytes", 0)
        thumb_pages = self.metadata_info.get("thumbnail_pages", [])
        has_oi = self.metadata_info.get("has_output_intents", False)
        icc_count = self.metadata_info.get("icc_profile_count", 0)
        emb_files = self.metadata_info.get("embedded_files", [])
        total = self.metadata_info.get("total_findings", 0)

        summary_badges = ft.Row(
            [
                make_badge(
                    f"{len(info_fields)} Info Fields",
                    ThemeTokens.bg_surface(is_dark),
                    ThemeTokens.ACCENT_WARNING if info_fields else ThemeTokens.ACCENT_SUCCESS,
                ),
                make_badge(
                    f"XMP: {xmp_bytes} B" if has_xmp else "XMP: Clean",
                    ThemeTokens.bg_surface(is_dark),
                    ThemeTokens.ACCENT_WARNING if has_xmp else ThemeTokens.ACCENT_SUCCESS,
                ),
                make_badge(
                    f"Thumbnails: {len(thumb_pages)}",
                    ThemeTokens.bg_surface(is_dark),
                    ThemeTokens.ACCENT_WARNING if thumb_pages else ThemeTokens.ACCENT_SUCCESS,
                ),
                make_badge(
                    f"Color Profiles: {icc_count + (1 if has_oi else 0)}",
                    ThemeTokens.bg_surface(is_dark),
                    ThemeTokens.ACCENT_WARNING if (icc_count or has_oi) else ThemeTokens.ACCENT_SUCCESS,
                ),
                make_badge(
                    f"Embedded Files: {len(emb_files)}",
                    ThemeTokens.bg_surface(is_dark),
                    ThemeTokens.ACCENT_WARNING if emb_files else ThemeTokens.ACCENT_SUCCESS,
                ),
            ],
            spacing=6,
            wrap=True,
        )

        field_lines: list[ft.Control] = [summary_badges]
        if total == 0:
            field_lines.append(
                ft.Text(
                    "No hidden tracking metadata detected in this document.",
                    size=11,
                    color=ThemeTokens.ACCENT_SUCCESS,
                )
            )
        else:
            for k, v in info_fields.items():
                field_lines.append(
                    ft.Text(
                        f"• {k}: {v}",
                        size=11,
                        color=ThemeTokens.text_secondary(is_dark),
                        overflow=ft.TextOverflow.ELLIPSIS,
                    )
                )

        self._metadata_panel_container.content = ft.Column(field_lines, spacing=4)

    def _refresh_sanitization_report(self) -> None:
        is_dark = self._is_dark()
        report = self.last_sanitization_report
        if not report:
            self._sanitization_report_container.visible = False
            self._sanitization_report_container.content = None
            return

        deleted = report.get("deleted_items", [])
        rows = [
            ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=16, color=ThemeTokens.ACCENT_SUCCESS),
                    ft.Text(
                        "Metadata Sanitization Report",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=ThemeTokens.text_primary(is_dark),
                    ),
                    make_badge(f"{len(deleted)} Purged", ThemeTokens.bg_surface(is_dark), ThemeTokens.ACCENT_SUCCESS),
                ],
                spacing=8,
            )
        ]

        if deleted:
            for item in deleted:
                rows.append(
                    ft.Text(f"✓ Deleted {item}", size=11, color=ThemeTokens.text_secondary(is_dark))
                )
        else:
            rows.append(
                ft.Text(
                    "✓ Document already had zero metadata fields; XMP & hidden streams scrubbed cleanly.",
                    size=11,
                    color=ThemeTokens.text_secondary(is_dark),
                )
            )

        self._sanitization_report_container.content = ft.Container(
            content=ft.Column(rows, spacing=4),
            padding=12,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_surface(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_SUCCESS),
        )
        self._sanitization_report_container.visible = True

    def _refresh_leakage_report(self) -> None:
        is_dark = self._is_dark()
        report = self.last_leakage_report
        if not report:
            self._leakage_report_container.visible = False
            self._leakage_report_container.content = None
            return

        verified = bool(report.get("verified", False))
        checked = int(report.get("checked_count", 0))
        leaked = report.get("leaked_strings", [])
        accent = ThemeTokens.ACCENT_SUCCESS if verified else ThemeTokens.ACCENT_DANGER

        title = (
            f"Zero Leakage Verified ({checked} string pattern(s) checked)"
            if verified
            else f"Leakage Warning: {len(leaked)} string(s) still detectable"
        )
        detail = (
            "Redacted text and streams cannot be copied, searched, or extracted."
            if verified
            else f"Remaining strings: {', '.join(leaked)}"
        )

        self._leakage_report_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.VERIFIED_USER if verified else ft.Icons.WARNING_AMBER,
                        size=18,
                        color=accent,
                    ),
                    ft.Column(
                        [
                            ft.Text(title, size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Text(detail, size=11, color=ThemeTokens.text_secondary(is_dark)),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                ],
                spacing=10,
            ),
            padding=12,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_surface(is_dark),
            border=ft.Border.all(1, accent),
        )
        self._leakage_report_container.visible = True

    # -------------------------------------------------------------------------
    # Execution Handlers
    # -------------------------------------------------------------------------

    def _validate_source(self) -> str | None:
        file_path = self.app_state.current_file or self.current_file
        if not file_path or not os.path.exists(file_path):
            show_snackbar(self.page, "Please select a PDF document first", "warning")
            return None
        if not file_path.lower().endswith(".pdf"):
            show_snackbar(self.page, "Redaction & sanitization only supports PDF files", "warning")
            return None
        return file_path

    def _collect_all_redaction_boxes(self) -> tuple[list[RedactionBox], list[str]]:
        boxes: list[RedactionBox] = [b for b in self.manual_boxes if b.enabled]
        forbidden_strings: list[str] = []

        for match in self.pattern_matches:
            if not match.selected:
                continue
            if match.matched_text:
                forbidden_strings.append(match.matched_text)
            for idx, r in enumerate(match.rects):
                boxes.append(
                    RedactionBox(
                        id=f"{match.id}_{idx}",
                        page_index=match.page_index,
                        rect=r,
                        label=f"{match.category_label}: {match.matched_text}",
                        category=match.category,
                        matched_text=match.matched_text,
                        enabled=True,
                    )
                )
        return boxes, forbidden_strings

    def _on_sanitize_only_clicked(self, e) -> None:
        src = self._validate_source()
        if not src or self.is_processing:
            return

        out_name = generate_output_filename(src, "sanitized", ".pdf")
        out_path = os.path.join(self.output_dir, out_name)

        self.is_processing = True
        self._show_feedback("Purging hidden document metadata...", "info")

        def worker():
            try:
                if self.progress_bar and self.progress_text:
                    update_progress(self.progress_bar, self.progress_text, 0.4, "Sanitizing metadata & XMP...")
                report = sanitize_pdf_metadata(source=src, output_path=out_path)
                self.last_sanitization_report = report
                self.last_output_path = report["output_path"]
                self.last_leakage_report = None
                self._refresh_sanitization_report()
                self._refresh_leakage_report()
                self._show_success_banner(
                    f"Metadata sanitized cleanly ({len(report['deleted_items'])} item(s) purged)",
                    report["output_path"],
                )
                show_snackbar(self.page, f"Sanitized PDF saved: {os.path.basename(report['output_path'])}", "success")
            except Exception as err:
                self._show_feedback(f"Metadata sanitization failed: {err}", "error")
                show_snackbar(self.page, f"Sanitization failed: {err}", "error")
            finally:
                self.is_processing = False
                if self.progress_bar and self.progress_text:
                    reset_progress(self.progress_bar, self.progress_text)
                self._safe_page_update()

        run_background(self.page, worker)

    def _on_apply_redactions_clicked(self, e) -> None:
        src = self._validate_source()
        if not src or self.is_processing:
            return

        boxes, forbidden_strings = self._collect_all_redaction_boxes()
        sanitize_meta = bool(self._sanitize_meta_switch.value)

        if not boxes and not sanitize_meta:
            show_snackbar(
                self.page,
                "Draw manual boxes, select pattern matches, or enable Metadata Sanitization first",
                "warning",
            )
            return

        color_key = self._fill_color_dropdown.value or "black"
        _, fill_rgb = _FILL_COLOR_OPTIONS.get(color_key, _FILL_COLOR_OPTIONS["black"])
        redact_images = bool(self._redact_images_switch.value)

        out_name = generate_output_filename(src, "redacted", ".pdf")
        out_path = os.path.join(self.output_dir, out_name)

        self.is_processing = True
        self._show_feedback("Applying permanent stream-level redactions...", "info")

        def worker():
            t_start = time.perf_counter()
            try:
                def progress(cur, tot, msg):
                    if self.progress_bar and self.progress_text:
                        update_progress(self.progress_bar, self.progress_text, cur / max(tot, 1), msg)

                result = apply_pdf_redactions(
                    source=src,
                    output_path=out_path,
                    redactions=boxes,
                    fill_color=fill_rgb,
                    redact_images=redact_images,
                    sanitize_metadata=sanitize_meta,
                    progress_callback=progress,
                )
                self.last_output_path = result["output_path"]
                self.last_sanitization_report = result.get("metadata_report")
                self.last_leakage_report = (
                    verify_zero_leakage(result["output_path"], forbidden_strings)
                    if forbidden_strings
                    else {"verified": True, "leaked_strings": [], "checked_count": 0}
                )
                self._refresh_sanitization_report()
                self._refresh_leakage_report()

                elapsed = time.perf_counter() - t_start
                self._show_success_banner(
                    f"Redacted {result['regions_applied']} region(s) across {result['pages_redacted']} page(s) in {elapsed:.1f}s!",
                    result["output_path"],
                )
                show_snackbar(
                    self.page,
                    f"Permanent redaction complete: {os.path.basename(result['output_path'])}",
                    "success",
                )
            except Exception as err:
                self._show_feedback(f"Redaction failed: {err}", "error")
                show_snackbar(self.page, f"Redaction failed: {err}", "error")
            finally:
                self.is_processing = False
                if self.progress_bar and self.progress_text:
                    reset_progress(self.progress_bar, self.progress_text)
                self._safe_page_update()

        run_background(self.page, worker)

    # -------------------------------------------------------------------------
    # Feedback Banners & Build UI
    # -------------------------------------------------------------------------

    def _show_feedback(self, message: str, status_type: str = "info") -> None:
        is_dark = self._is_dark()
        color = ThemeTokens.ACCENT_PRIMARY if status_type == "info" else ThemeTokens.ACCENT_DANGER
        self._feedback_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=color),
                    ft.Text(message, size=12, color=ThemeTokens.text_primary(is_dark), expand=True),
                ],
                spacing=8,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_hover(is_dark),
            border=ft.Border.all(1, color),
        )
        self._feedback_container.visible = True
        self._safe_page_update()

    def _show_success_banner(self, title: str, output_path: str) -> None:
        is_dark = self._is_dark()
        self._feedback_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=20, color=ThemeTokens.ACCENT_SUCCESS),
                    ft.Column(
                        [
                            ft.Text(title, size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Text(f"Saved: {os.path.basename(output_path)}", size=11, color=ThemeTokens.text_secondary(is_dark)),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.OutlinedButton(
                        "Open Folder",
                        icon=ft.Icons.FOLDER_OPEN,
                        on_click=lambda e: open_folder(os.path.dirname(output_path)),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=12,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_card(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_SUCCESS),
        )
        self._feedback_container.visible = True
        self._safe_page_update()

    def build_ui(self) -> ft.Control:
        """Construct the complete Phase 6 Operate workspace."""
        is_dark = self._is_dark()
        self._refresh_all_panels()

        self._custom_regex_field.bgcolor = ThemeTokens.bg_surface(is_dark)
        self._custom_regex_field.border_color = ThemeTokens.border_muted(is_dark)
        self._custom_regex_field.color = ThemeTokens.text_primary(is_dark)

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    "🛡️ Permanent Redaction & Metadata Sanitizer",
                                    size=16,
                                    weight=ft.FontWeight.W_700,
                                    color=ThemeTokens.text_primary(is_dark),
                                ),
                                make_badge("Phase 6", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_DANGER),
                                make_badge("Zero Leakage", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_SUCCESS),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            "Permanently scrub sensitive text, graphics & tracking metadata from PDF streams",
                            size=12,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Card 1: Pattern Auto-Redaction Detector
        pattern_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.FIND_IN_PAGE, size=18, color=ThemeTokens.ACCENT_WARNING),
                            ft.Text(
                                "Pattern Auto-Redaction Scanner",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [self._cat_email, self._cat_phone, self._cat_ssn, self._cat_card],
                        spacing=12,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            self._custom_regex_field,
                            self._case_sensitive_switch,
                            ft.FilledButton(
                                "Scan Document for Patterns",
                                icon=ft.Icons.SEARCH,
                                on_click=self._on_scan_patterns_clicked,
                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    self._matches_list_container,
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        # Card 2: Interactive Manual Redaction Canvas
        manual_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DRAW, size=18, color=ThemeTokens.ACCENT_DANGER),
                            ft.Text(
                                "Manual Bounding-Box Redaction",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    self._canvas_container,
                    self._manual_list_container,
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        # Card 3: Metadata Sanitizer & Export Bar
        sanitizer_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.CLEANING_SERVICES, size=18, color=ThemeTokens.ACCENT_SUCCESS),
                            ft.Text(
                                "Metadata Sanitizer & Export",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    self._metadata_panel_container,
                    ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                    ft.Row(
                        [
                            self._fill_color_dropdown,
                            self._redact_images_switch,
                            self._sanitize_meta_switch,
                        ],
                        spacing=16,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.FilledButton(
                                "Apply Permanent Redactions",
                                icon=ft.Icons.SHIELD,
                                on_click=self._on_apply_redactions_clicked,
                                style=ft.ButtonStyle(
                                    bgcolor=ThemeTokens.ACCENT_DANGER,
                                    color=ft.Colors.WHITE,
                                    shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM),
                                ),
                            ),
                            ft.OutlinedButton(
                                "Sanitize Metadata Only (1-Click)",
                                icon=ft.Icons.DELETE_SWEEP,
                                on_click=self._on_sanitize_only_clicked,
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    self._sanitization_report_container,
                    self._leakage_report_container,
                ],
                spacing=12,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        return ft.Column(
            [
                header,
                ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                self._active_doc_container,
                self._feedback_container,
                pattern_card,
                manual_card,
                sanitizer_card,
            ],
            spacing=14,
            expand=True,
        )
