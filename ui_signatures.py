"""Digital Signatures & Stamp Studio workspace (Phase 7).

Operate Mode:
- Signature Studio:
  - Touch/Mouse vector drawing pad with quadratic Bezier smoothing & variable stroke width
  - Type-to-sign with multiple cursive script typography presets
  - Image signature upload (PNG/JPG/WEBP) with automatic white-paper background removal
  - Persistent local Signature Vault for one-click signing and initials
- Stamp Studio:
  - Professional presets (APPROVED, CONFIDENTIAL, DRAFT, FINAL, PAID, REJECTED) + custom text
  - Dynamic variables (Date, Time, Operator Name), customizable colors, borders & rotation
  - Real-time live preview
- Interactive Document Canvas:
  - Click-to-place normalized overlays, drag-to-move, bottom-right corner resize handles
  - Multi-page signing (All Pages, Initial All + Sign Final Page, Final Page, Custom Range)
  - Local SHA-256 document integrity verification
"""

from __future__ import annotations

from collections.abc import Callable
import io
import os
from pathlib import Path
import time
import uuid

import flet as ft
import flet.canvas as cv
from PIL import Image

from app_state import AppState
from pdf_engine import (
    PlacementItem,
    SIGNATURE_INK_COLORS,
    STAMP_BORDER_STYLES,
    STAMP_COLORS,
    STAMP_PRESETS,
    apply_signatures_and_stamps,
    build_multipage_placements,
    compute_quadratic_bezier_segments,
    delete_vault_signature,
    get_available_signature_fonts,
    inspect_pdf,
    list_vault_signatures,
    load_vault_signature_bytes,
    remove_signature_background,
    render_drawn_signature_png,
    render_redaction_page_preview,
    render_stamp_image,
    render_typed_signature_png,
    save_signature_to_vault,
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


_DRAW_PAD_WIDTH = 500.0
_DRAW_PAD_HEIGHT = 165.0


class SignatureStampView:
    """Phase 7 Digital Signatures & Stamp Studio workspace."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        output_dir: str,
        progress_bar: ft.ProgressBar | None = None,
        progress_text: ft.Text | None = None,
        is_dark_supplier: Callable[[], bool] = lambda: True,
        vault_dir: str | Path | None = None,
    ):
        self.page = page
        self.app_state = app_state
        self.output_dir = output_dir
        self.progress_bar = progress_bar
        self.progress_text = progress_text
        self.is_dark_supplier = is_dark_supplier
        self.vault_dir = Path(vault_dir) if vault_dir else None

        # Document & preview state
        self.current_file: str | None = getattr(app_state, "current_file", None)
        self.current_page_index: int = 0
        self.total_pages: int = 0
        self.preview_data: dict | None = None
        self.is_processing: bool = False

        # Studio mode: "draw" | "type" | "upload" | "stamp" | "vault"
        self.studio_tab: str = "draw"

        # Drawing pad state
        self._draw_strokes: list[list[tuple[float, float]]] = []
        self._draw_ink_key: str = "black"
        self._draw_stroke_width: float = 3.5

        # Typed signature state
        self._typed_preview_bytes: bytes | None = None

        # Uploaded image state
        self._uploaded_raw_bytes: bytes | None = None
        self._uploaded_clean_bytes: bytes | None = None
        self._uploaded_filename: str = ""

        # Stamp preview state
        self._stamp_preview_bytes: bytes | None = None

        # Active asset ready to click-to-place on document
        self.active_asset: dict | None = None  # {png_bytes, label, kind, aspect_ratio}
        self.initials_asset: dict | None = None  # optional initials asset for multi-page contracts

        # Placed overlays & selection
        self.placements: list[PlacementItem] = []
        self.selected_placement_id: str | None = None
        self._last_integrity_report: dict | None = None

        # Image FilePicker for uploaded signatures
        self.sig_image_picker = ft.FilePicker()
        try:
            self.page.services.append(self.sig_image_picker)
        except Exception:
            pass

        self._build_controls()
        self._refresh_typed_preview(update_ui=False)
        self._refresh_stamp_preview(update_ui=False)
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
        self.preview_data = None
        self.placements.clear()
        self.selected_placement_id = None
        self._last_integrity_report = None
        self._feedback_container.visible = False

        if file_path and os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
            self._load_document_state(file_path)
        else:
            self._refresh_all_panels()

        self._safe_page_update()

    def _load_document_state(self, file_path: str) -> None:
        try:
            info = inspect_pdf(file_path)
            self.total_pages = int(info.get("page_count", 0))
            if self.total_pages > 0:
                self.current_page_index = max(0, min(self.current_page_index, self.total_pages - 1))
                self.preview_data = render_redaction_page_preview(
                    file_path, page_index=self.current_page_index
                )
        except Exception as err:
            self.preview_data = None
            self._show_feedback(f"Could not inspect PDF: {err}", "error")

        self._refresh_all_panels()

    def change_page(self, delta: int) -> None:
        if not self.current_file or self.total_pages < 1:
            return
        target = max(0, min(self.current_page_index + delta, self.total_pages - 1))
        if target == self.current_page_index:
            return
        self.current_page_index = target
        self.selected_placement_id = None
        try:
            self.preview_data = render_redaction_page_preview(
                self.current_file, page_index=self.current_page_index
            )
        except Exception as err:
            show_snackbar(self.page, f"Could not render page {target + 1}: {err}", "error")
            return
        self._refresh_doc_canvas()
        self._refresh_placement_inspector()
        self._safe_page_update()

    # -------------------------------------------------------------------------
    # Control Construction
    # -------------------------------------------------------------------------

    def _build_controls(self) -> None:
        self._active_doc_container = ft.Container()
        self._feedback_container = ft.Container(visible=False)
        self._studio_tabs_row = ft.Row(spacing=6, wrap=True)
        self._studio_body_container = ft.Container()
        self._active_asset_bar = ft.Container()
        self._doc_canvas_container = ft.Container()
        self._placement_inspector_container = ft.Container()
        self._placements_list_container = ft.Container()
        self._integrity_report_container = ft.Container(visible=False)

        # Draw pad controls
        self._draw_canvas = cv.Canvas(
            shapes=[],
            width=_DRAW_PAD_WIDTH,
            height=_DRAW_PAD_HEIGHT,
        )
        self._draw_ink_dropdown = ft.Dropdown(
            label="Ink Color",
            options=[
                ft.dropdown.Option(key=k, text=label)
                for k, (label, _, _) in SIGNATURE_INK_COLORS.items()
            ],
            value="black",
            width=165,
            on_select=self._on_draw_style_changed,
        )
        self._draw_width_slider = ft.Slider(
            min=1.5,
            max=8.5,
            divisions=14,
            value=self._draw_stroke_width,
            label="{value} px",
            width=160,
            on_change=self._on_draw_width_changed,
        )
        self._vault_name_field = ft.TextField(
            label="Save Label (Optional)",
            hint_text="e.g., Full Signature or Initials",
            text_size=12,
            width=210,
            border_radius=ThemeTokens.RADIUS_SM,
        )

        # Type-to-sign controls
        self._typed_name_field = ft.TextField(
            label="Signer Name / Initials",
            value="Alex Morgan",
            hint_text="Type your full name or initials",
            text_size=13,
            width=240,
            border_radius=ThemeTokens.RADIUS_SM,
            on_change=lambda e: self._refresh_typed_preview(),
        )
        fonts = get_available_signature_fonts()
        self._typed_font_dropdown = ft.Dropdown(
            label="Cursive Typography",
            options=[ft.dropdown.Option(key=f["id"], text=f["label"]) for f in fonts],
            value=fonts[0]["id"] if fonts else "chancery",
            width=195,
            on_select=lambda e: self._refresh_typed_preview(),
        )
        self._typed_ink_dropdown = ft.Dropdown(
            label="Ink Color",
            options=[
                ft.dropdown.Option(key=k, text=label)
                for k, (label, _, _) in SIGNATURE_INK_COLORS.items()
            ],
            value="navy",
            width=155,
            on_select=lambda e: self._refresh_typed_preview(),
        )
        self._typed_preview_holder = ft.Container()

        # Upload image controls
        self._upload_bg_remove_switch = ft.Switch(
            label="Auto-Remove White Background",
            value=True,
            on_change=lambda e: self._reprocess_uploaded_signature(),
        )
        self._upload_threshold_slider = ft.Slider(
            min=160,
            max=250,
            divisions=18,
            value=220,
            label="Threshold {value}",
            width=180,
            on_change=lambda e: self._reprocess_uploaded_signature(),
        )
        self._upload_preview_holder = ft.Container()

        # Stamp studio controls
        self._stamp_preset_dropdown = ft.Dropdown(
            label="Stamp Preset",
            options=[ft.dropdown.Option(key=p, text=p) for p in STAMP_PRESETS],
            value="APPROVED",
            width=175,
            on_select=self._on_stamp_preset_selected,
        )
        self._stamp_text_field = ft.TextField(
            label="Custom Stamp Text",
            value="APPROVED",
            text_size=12,
            width=185,
            border_radius=ThemeTokens.RADIUS_SM,
            on_change=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_color_dropdown = ft.Dropdown(
            label="Stamp Color",
            options=[
                ft.dropdown.Option(key=k, text=label)
                for k, (label, _, _) in STAMP_COLORS.items()
            ],
            value="red",
            width=155,
            on_select=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_border_dropdown = ft.Dropdown(
            label="Border Style",
            options=[
                ft.dropdown.Option(key=k, text=label)
                for k, label in STAMP_BORDER_STYLES.items()
            ],
            value="double",
            width=155,
            on_select=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_rotation_dropdown = ft.Dropdown(
            label="Angle",
            options=[
                ft.dropdown.Option(key="0", text="0° Straight"),
                ft.dropdown.Option(key="-12", text="-12° Classic"),
                ft.dropdown.Option(key="-25", text="-25° Steep"),
                ft.dropdown.Option(key="15", text="+15° Tilt"),
            ],
            value="-12",
            width=145,
            on_select=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_opacity_slider = ft.Slider(
            min=0.35,
            max=1.0,
            divisions=13,
            value=0.92,
            label="Opacity {value}",
            width=165,
            on_change=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_include_date = ft.Checkbox(
            label="Date",
            value=True,
            on_change=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_include_time = ft.Checkbox(
            label="Time",
            value=False,
            on_change=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_operator_field = ft.TextField(
            label="Operator Name",
            hint_text="e.g., J. DOE",
            text_size=12,
            width=160,
            border_radius=ThemeTokens.RADIUS_SM,
            on_change=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_subtext_field = ft.TextField(
            label="Subtext (Optional)",
            hint_text="e.g., DEPT. VERIFIED",
            text_size=12,
            width=185,
            border_radius=ThemeTokens.RADIUS_SM,
            on_change=lambda e: self._refresh_stamp_preview(),
        )
        self._stamp_preview_holder = ft.Container()

        # Multi-page range input
        self._multipage_range_field = ft.TextField(
            label="Page Range",
            hint_text="e.g., 1-3, 5",
            text_size=12,
            width=145,
            border_radius=ThemeTokens.RADIUS_SM,
        )

    def _refresh_all_panels(self) -> None:
        self._refresh_active_doc_card()
        self._refresh_studio_panel()
        self._refresh_active_asset_bar()
        self._refresh_doc_canvas()
        self._refresh_placement_inspector()
        self._refresh_placements_list()
        self._refresh_integrity_report()

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
                            "Select a PDF document above to sign, stamp, and verify integrity",
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
        count = len(self.placements)
        badge_text = f"{count} Placed" if count else "Ready"
        badge_color = ThemeTokens.ACCENT_PRIMARY if count else ThemeTokens.ACCENT_SUCCESS

        self._active_doc_container.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.DRAW, size=20, color=ThemeTokens.ACCENT_PRIMARY),
                    ft.Column(
                        [
                            ft.Text(name, size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                            ft.Text(
                                f"Signature & Stamp Studio • {size_mb:.2f} MB{page_label}",
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

    # -------------------------------------------------------------------------
    # Studio Tab Navigation & Builders
    # -------------------------------------------------------------------------

    def switch_studio_tab(self, tab_id: str) -> None:
        self.studio_tab = tab_id
        self._refresh_studio_panel()
        self._safe_page_update()

    def _refresh_studio_panel(self) -> None:
        is_dark = self._is_dark()
        tabs = [
            ("draw", "Draw Pad", ft.Icons.GESTURE),
            ("type", "Type-to-Sign", ft.Icons.TEXT_FIELDS),
            ("upload", "Upload Image", ft.Icons.UPLOAD_FILE),
            ("stamp", "Stamp Studio", ft.Icons.APPROVAL),
            ("vault", "Signature Vault", ft.Icons.BOOKMARKS_OUTLINED),
        ]

        tab_controls: list[ft.Control] = []
        for tid, label, icon in tabs:
            active = self.studio_tab == tid
            bg = ThemeTokens.ACCENT_PRIMARY if active else ThemeTokens.bg_surface(is_dark)
            fg = ft.Colors.WHITE if active else ThemeTokens.text_primary(is_dark)
            tab_controls.append(
                ft.Container(
                    content=ft.Row(
                        [ft.Icon(icon, size=15, color=fg), ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=fg)],
                        spacing=6,
                        tight=True,
                    ),
                    padding=padding_symmetric(horizontal=12, vertical=8),
                    border_radius=ThemeTokens.RADIUS_SM,
                    bgcolor=bg,
                    border=ft.Border.all(1, ThemeTokens.ACCENT_PRIMARY if active else ThemeTokens.border_muted(is_dark)),
                    on_click=lambda e, target=tid: self.switch_studio_tab(target),
                )
            )
        self._studio_tabs_row.controls = tab_controls

        if self.studio_tab == "draw":
            self._studio_body_container.content = self._build_draw_panel(is_dark)
        elif self.studio_tab == "type":
            self._studio_body_container.content = self._build_type_panel(is_dark)
        elif self.studio_tab == "upload":
            self._studio_body_container.content = self._build_upload_panel(is_dark)
        elif self.studio_tab == "stamp":
            self._studio_body_container.content = self._build_stamp_panel(is_dark)
        else:
            self._studio_body_container.content = self._build_vault_panel(is_dark)

    # -------------------------------------------------------------------------
    # Tab 1: Vector Drawing Pad (Quadratic Bezier)
    # -------------------------------------------------------------------------

    def _rebuild_draw_canvas_shapes(self) -> None:
        _, hex_col, _ = SIGNATURE_INK_COLORS.get(self._draw_ink_key, SIGNATURE_INK_COLORS["black"])
        paint = ft.Paint(
            color=hex_col,
            stroke_width=self._draw_stroke_width,
            style=ft.PaintingStyle.STROKE,
            stroke_cap=ft.StrokeCap.ROUND,
            stroke_join=ft.StrokeJoin.ROUND,
        )
        dot_paint = ft.Paint(
            color=hex_col,
            style=ft.PaintingStyle.FILL,
        )

        shapes: list[cv.Shape] = []
        for stroke in self._draw_strokes:
            start, segs = compute_quadratic_bezier_segments(stroke)
            if start is None:
                continue
            if not segs:
                shapes.append(cv.Circle(x=start[0], y=start[1], radius=max(1.5, self._draw_stroke_width / 2.0), paint=dot_paint))
                continue
            elements: list[cv.Path.PathElement] = [cv.Path.MoveTo(x=start[0], y=start[1])]
            for cpx, cpy, ex, ey in segs:
                elements.append(cv.Path.QuadraticTo(cp1x=cpx, cp1y=cpy, x=ex, y=ey))
            shapes.append(cv.Path(elements=elements, paint=paint))

        self._draw_canvas.shapes = shapes

    def _on_draw_pan_start(self, e: ft.DragStartEvent) -> None:
        x = max(0.0, min(float(e.local_position.x), _DRAW_PAD_WIDTH))
        y = max(0.0, min(float(e.local_position.y), _DRAW_PAD_HEIGHT))
        self._draw_strokes.append([(x, y)])
        self._rebuild_draw_canvas_shapes()
        try:
            self._draw_canvas.update()
        except Exception:
            pass

    def _on_draw_pan_update(self, e: ft.DragUpdateEvent) -> None:
        if not self._draw_strokes:
            return
        x = max(0.0, min(float(e.local_position.x), _DRAW_PAD_WIDTH))
        y = max(0.0, min(float(e.local_position.y), _DRAW_PAD_HEIGHT))
        last = self._draw_strokes[-1][-1]
        if abs(x - last[0]) + abs(y - last[1]) >= 1.5:
            self._draw_strokes[-1].append((x, y))
            self._rebuild_draw_canvas_shapes()
            try:
                self._draw_canvas.update()
            except Exception:
                pass

    def _on_draw_pan_end(self, e: ft.DragEndEvent) -> None:
        self._rebuild_draw_canvas_shapes()
        try:
            self._draw_canvas.update()
        except Exception:
            pass

    def _on_draw_style_changed(self, e) -> None:
        self._draw_ink_key = self._draw_ink_dropdown.value or "black"
        self._rebuild_draw_canvas_shapes()
        self._safe_page_update()

    def _on_draw_width_changed(self, e) -> None:
        self._draw_stroke_width = float(self._draw_width_slider.value or 3.5)
        self._rebuild_draw_canvas_shapes()
        self._safe_page_update()

    def undo_drawing_stroke(self) -> None:
        if self._draw_strokes:
            self._draw_strokes.pop()
            self._rebuild_draw_canvas_shapes()
            self._safe_page_update()

    def clear_drawing_pad(self) -> None:
        self._draw_strokes.clear()
        self._rebuild_draw_canvas_shapes()
        self._safe_page_update()

    def render_current_drawing(self) -> bytes:
        return render_drawn_signature_png(
            strokes=self._draw_strokes,
            canvas_width=_DRAW_PAD_WIDTH,
            canvas_height=_DRAW_PAD_HEIGHT,
            stroke_width=self._draw_stroke_width,
            ink_color=self._draw_ink_key,
        )

    def activate_drawn_signature(self) -> None:
        try:
            png_bytes = self.render_current_drawing()
        except Exception as err:
            show_snackbar(self.page, str(err), "warning")
            return
        self._set_active_asset(png_bytes, label="Drawn Signature", kind="signature")
        show_snackbar(self.page, "Drawn signature ready — click on the PDF page to place", "info")

    def save_drawn_to_vault(self, label: str | None = None) -> dict | None:
        try:
            png_bytes = self.render_current_drawing()
            sig_name = (label if label is not None else self._vault_name_field.value or "").strip() or "Drawn Signature"
            entry = save_signature_to_vault(png_bytes, name=sig_name, kind="drawn", vault_dir=self.vault_dir)
            self._set_active_asset(png_bytes, label=entry["name"], kind="signature")
            show_snackbar(self.page, f"Saved '{entry['name']}' to local Signature Vault", "success")
            self._safe_page_update()
            return entry
        except Exception as err:
            show_snackbar(self.page, f"Could not save signature: {err}", "error")
            return None

    def _build_draw_panel(self, is_dark: bool) -> ft.Control:
        self._rebuild_draw_canvas_shapes()
        pad_surface = ft.Container(
            content=ft.Stack(
                [
                    # Paper baseline guide
                    ft.Container(
                        left=24,
                        right=24,
                        bottom=36,
                        height=1,
                        bgcolor="#CBD5E1",
                    ),
                    ft.Container(
                        content=ft.Text("Sign above", size=10, color="#94A3B8"),
                        left=24,
                        bottom=18,
                    ),
                    ft.GestureDetector(
                        content=self._draw_canvas,
                        mouse_cursor=ft.MouseCursor.PRECISE,
                        drag_interval=12,
                        on_pan_start=self._on_draw_pan_start,
                        on_pan_update=self._on_draw_pan_update,
                        on_pan_end=self._on_draw_pan_end,
                    ),
                ],
                width=_DRAW_PAD_WIDTH,
                height=_DRAW_PAD_HEIGHT,
            ),
            width=_DRAW_PAD_WIDTH,
            height=_DRAW_PAD_HEIGHT,
            bgcolor="#FFFFFF",
            border_radius=ThemeTokens.RADIUS_SM,
            border=ft.Border.all(1.5, ThemeTokens.border_muted(is_dark)),
        )

        return ft.Column(
            [
                ft.Row(
                    [
                        self._draw_ink_dropdown,
                        ft.Column(
                            [
                                ft.Text("Stroke Width", size=11, color=ThemeTokens.text_secondary(is_dark)),
                                self._draw_width_slider,
                            ],
                            spacing=0,
                        ),
                        self._vault_name_field,
                    ],
                    spacing=12,
                    wrap=True,
                ),
                pad_surface,
                ft.Row(
                    [
                        ft.FilledButton(
                            "Use Drawn Signature",
                            icon=ft.Icons.CHECK,
                            on_click=lambda e: self.activate_drawn_signature(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                        ),
                        ft.OutlinedButton(
                            "Save to Vault",
                            icon=ft.Icons.BOOKMARK_ADD_OUTLINED,
                            on_click=lambda e: self.save_drawn_to_vault(),
                        ),
                        ft.OutlinedButton(
                            "Undo",
                            icon=ft.Icons.UNDO,
                            on_click=lambda e: self.undo_drawing_stroke(),
                        ),
                        ft.OutlinedButton(
                            "Clear Pad",
                            icon=ft.Icons.CLEAR,
                            on_click=lambda e: self.clear_drawing_pad(),
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
            ],
            spacing=10,
        )

    # -------------------------------------------------------------------------
    # Tab 2: Type-to-Sign Cursive Typography
    # -------------------------------------------------------------------------

    def _refresh_typed_preview(self, update_ui: bool = True) -> None:
        text = (self._typed_name_field.value or "").strip()
        if not text:
            self._typed_preview_bytes = None
            self._typed_preview_holder.content = ft.Text(
                "Type your name to preview cursive signature",
                size=11,
                color=ThemeTokens.text_muted(self._is_dark()),
            )
        else:
            try:
                self._typed_preview_bytes = render_typed_signature_png(
                    text=text,
                    font_style=self._typed_font_dropdown.value or "chancery",
                    ink_color=self._typed_ink_dropdown.value or "navy",
                )
                self._typed_preview_holder.content = ft.Image(
                    src=self._typed_preview_bytes,
                    height=78,
                    fit=ft.BoxFit.CONTAIN,
                )
            except Exception as err:
                self._typed_preview_bytes = None
                self._typed_preview_holder.content = ft.Text(f"Preview error: {err}", size=11, color=ThemeTokens.ACCENT_DANGER)

        if update_ui:
            self._safe_page_update()

    def activate_typed_signature(self) -> None:
        self._refresh_typed_preview(update_ui=False)
        if not self._typed_preview_bytes:
            show_snackbar(self.page, "Enter a name to generate a typed signature", "warning")
            return
        name = (self._typed_name_field.value or "").strip()
        self._set_active_asset(self._typed_preview_bytes, label=f"Typed: {name}", kind="signature")
        show_snackbar(self.page, "Typed signature active — click on the PDF page to place", "info")

    def save_typed_to_vault(self) -> dict | None:
        self._refresh_typed_preview(update_ui=False)
        if not self._typed_preview_bytes:
            show_snackbar(self.page, "Enter a name before saving to vault", "warning")
            return None
        name = (self._typed_name_field.value or "").strip() or "Typed Signature"
        entry = save_signature_to_vault(
            self._typed_preview_bytes,
            name=name,
            kind="typed",
            vault_dir=self.vault_dir,
        )
        self._set_active_asset(self._typed_preview_bytes, label=entry["name"], kind="signature")
        show_snackbar(self.page, f"Saved '{entry['name']}' to local Signature Vault", "success")
        self._safe_page_update()
        return entry

    def _build_type_panel(self, is_dark: bool) -> ft.Control:
        return ft.Column(
            [
                ft.Row(
                    [
                        self._typed_name_field,
                        self._typed_font_dropdown,
                        self._typed_ink_dropdown,
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Container(
                    content=self._typed_preview_holder,
                    height=105,
                    width=500,
                    alignment=ft.Alignment.CENTER,
                    bgcolor="#FFFFFF",
                    border_radius=ThemeTokens.RADIUS_SM,
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                    padding=10,
                ),
                ft.Row(
                    [
                        ft.FilledButton(
                            "Use Typed Signature",
                            icon=ft.Icons.CHECK,
                            on_click=lambda e: self.activate_typed_signature(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                        ),
                        ft.OutlinedButton(
                            "Save to Vault",
                            icon=ft.Icons.BOOKMARK_ADD_OUTLINED,
                            on_click=lambda e: self.save_typed_to_vault(),
                        ),
                    ],
                    spacing=8,
                ),
            ],
            spacing=10,
        )

    # -------------------------------------------------------------------------
    # Tab 3: Image Upload & Background Removal
    # -------------------------------------------------------------------------

    def _browse_signature_image(self) -> None:
        async def _pick():
            try:
                files = await self.sig_image_picker.pick_files(
                    dialog_title="Select Signature Image — PDF-Ops",
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["png", "jpg", "jpeg", "webp"],
                    allow_multiple=False,
                )
                if files and files[0].path:
                    self.load_uploaded_signature_image(files[0].path)
            except Exception as err:
                show_snackbar(self.page, f"Could not load image: {err}", "error")

        self.page.run_task(_pick)

    def load_uploaded_signature_image(self, image_path: str | Path) -> bytes:
        path = Path(image_path)
        self._uploaded_raw_bytes = path.read_bytes()
        self._uploaded_filename = path.name
        self._reprocess_uploaded_signature()
        if self._uploaded_clean_bytes is None:
            raise ValueError("Uploaded image could not be processed.")
        return self._uploaded_clean_bytes

    def _reprocess_uploaded_signature(self) -> None:
        if not self._uploaded_raw_bytes:
            return
        try:
            if self._upload_bg_remove_switch.value:
                threshold = int(self._upload_threshold_slider.value or 220)
                self._uploaded_clean_bytes = remove_signature_background(
                    self._uploaded_raw_bytes,
                    threshold=threshold,
                )
            else:
                with Image.open(io.BytesIO(self._uploaded_raw_bytes)) as im:
                    buf = io.BytesIO()
                    im.convert("RGBA").save(buf, format="PNG")
                    self._uploaded_clean_bytes = buf.getvalue()

            self._upload_preview_holder.content = ft.Image(
                src=self._uploaded_clean_bytes,
                height=85,
                fit=ft.BoxFit.CONTAIN,
            )
        except Exception as err:
            self._uploaded_clean_bytes = None
            self._upload_preview_holder.content = ft.Text(f"Error: {err}", size=11, color=ThemeTokens.ACCENT_DANGER)
        self._safe_page_update()

    def activate_uploaded_signature(self) -> None:
        if not self._uploaded_clean_bytes:
            show_snackbar(self.page, "Upload a signature image first", "warning")
            return
        label = self._uploaded_filename or "Uploaded Signature"
        self._set_active_asset(self._uploaded_clean_bytes, label=label, kind="signature")
        show_snackbar(self.page, "Uploaded signature ready — click on the PDF page to place", "info")

    def save_uploaded_to_vault(self) -> dict | None:
        if not self._uploaded_clean_bytes:
            show_snackbar(self.page, "Upload a signature image first", "warning")
            return None
        name = os.path.splitext(self._uploaded_filename)[0] or "Uploaded Signature"
        entry = save_signature_to_vault(
            self._uploaded_clean_bytes,
            name=name,
            kind="uploaded",
            vault_dir=self.vault_dir,
        )
        self._set_active_asset(self._uploaded_clean_bytes, label=entry["name"], kind="signature")
        show_snackbar(self.page, f"Saved '{entry['name']}' to local Signature Vault", "success")
        self._safe_page_update()
        return entry

    def _build_upload_panel(self, is_dark: bool) -> ft.Control:
        if self._uploaded_clean_bytes is None:
            self._upload_preview_holder.content = ft.Text(
                "Upload a PNG/JPG photo of your signature on paper — white backgrounds are removed automatically",
                size=11,
                color=ThemeTokens.text_muted(is_dark),
                text_align=ft.TextAlign.CENTER,
            )

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.FilledButton(
                            "Browse Signature Image",
                            icon=ft.Icons.IMAGE_SEARCH,
                            on_click=lambda e: self._browse_signature_image(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                        ),
                        self._upload_bg_remove_switch,
                        ft.Column(
                            [
                                ft.Text("Paper Eraser Sensitivity", size=10, color=ThemeTokens.text_secondary(is_dark)),
                                self._upload_threshold_slider,
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                ft.Container(
                    content=self._upload_preview_holder,
                    height=110,
                    width=500,
                    alignment=ft.Alignment.CENTER,
                    bgcolor=ThemeTokens.bg_surface(is_dark),
                    border_radius=ThemeTokens.RADIUS_SM,
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                    padding=10,
                ),
                ft.Row(
                    [
                        ft.FilledButton(
                            "Use Uploaded Signature",
                            icon=ft.Icons.CHECK,
                            on_click=lambda e: self.activate_uploaded_signature(),
                        ),
                        ft.OutlinedButton(
                            "Save to Vault",
                            icon=ft.Icons.BOOKMARK_ADD_OUTLINED,
                            on_click=lambda e: self.save_uploaded_to_vault(),
                        ),
                    ],
                    spacing=8,
                ),
            ],
            spacing=10,
        )

    # -------------------------------------------------------------------------
    # Tab 4: Stamp Generator & Presets
    # -------------------------------------------------------------------------

    def _on_stamp_preset_selected(self, e) -> None:
        preset = self._stamp_preset_dropdown.value or "APPROVED"
        self._stamp_text_field.value = preset
        # Sensible color defaults per preset
        if preset in ("CONFIDENTIAL", "REJECTED"):
            self._stamp_color_dropdown.value = "red"
        elif preset in ("APPROVED", "PAID"):
            self._stamp_color_dropdown.value = "green"
        else:
            self._stamp_color_dropdown.value = "navy"
        self._refresh_stamp_preview()

    def _refresh_stamp_preview(self, update_ui: bool = True) -> None:
        text = (self._stamp_text_field.value or "").strip()
        if not text:
            self._stamp_preview_bytes = None
            self._stamp_preview_holder.content = ft.Text(
                "Enter stamp text to generate a live preview",
                size=11,
                color=ThemeTokens.text_muted(self._is_dark()),
            )
        else:
            try:
                self._stamp_preview_bytes = render_stamp_image(
                    text=text,
                    color_key=self._stamp_color_dropdown.value or "red",
                    border_style=self._stamp_border_dropdown.value or "double",
                    include_date=bool(self._stamp_include_date.value),
                    include_time=bool(self._stamp_include_time.value),
                    operator_name=self._stamp_operator_field.value or "",
                    custom_subtext=self._stamp_subtext_field.value or "",
                    rotation=float(self._stamp_rotation_dropdown.value or -12.0),
                    opacity=float(self._stamp_opacity_slider.value or 0.92),
                )
                self._stamp_preview_holder.content = ft.Image(
                    src=self._stamp_preview_bytes,
                    height=105,
                    fit=ft.BoxFit.CONTAIN,
                )
            except Exception as err:
                self._stamp_preview_bytes = None
                self._stamp_preview_holder.content = ft.Text(f"Preview error: {err}", size=11, color=ThemeTokens.ACCENT_DANGER)

        if update_ui:
            self._safe_page_update()

    def activate_stamp(self) -> None:
        self._refresh_stamp_preview(update_ui=False)
        if not self._stamp_preview_bytes:
            show_snackbar(self.page, "Enter valid stamp text first", "warning")
            return
        label = f"Stamp: {(self._stamp_text_field.value or 'STAMP').strip().upper()}"
        self._set_active_asset(self._stamp_preview_bytes, label=label, kind="stamp")
        show_snackbar(self.page, f"{label} ready — click on the PDF page to stamp", "info")

    def _build_stamp_panel(self, is_dark: bool) -> ft.Control:
        preset_chips = ft.Row(
            [
                ft.OutlinedButton(
                    preset,
                    on_click=lambda e, p=preset: self._select_stamp_chip(p),
                )
                for preset in STAMP_PRESETS
            ],
            spacing=6,
            wrap=True,
        )

        return ft.Column(
            [
                preset_chips,
                ft.Row(
                    [
                        self._stamp_text_field,
                        self._stamp_color_dropdown,
                        self._stamp_border_dropdown,
                        self._stamp_rotation_dropdown,
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    [
                        self._stamp_operator_field,
                        self._stamp_subtext_field,
                        self._stamp_include_date,
                        self._stamp_include_time,
                        ft.Column(
                            [
                                ft.Text("Opacity", size=10, color=ThemeTokens.text_secondary(is_dark)),
                                self._stamp_opacity_slider,
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Container(
                    content=self._stamp_preview_holder,
                    height=130,
                    width=500,
                    alignment=ft.Alignment.CENTER,
                    bgcolor="#FFFFFF",
                    border_radius=ThemeTokens.RADIUS_SM,
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                    padding=10,
                ),
                ft.Row(
                    [
                        ft.FilledButton(
                            "Use This Stamp",
                            icon=ft.Icons.APPROVAL,
                            on_click=lambda e: self.activate_stamp(),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM)),
                        ),
                    ],
                    spacing=8,
                ),
            ],
            spacing=10,
        )

    def _select_stamp_chip(self, preset: str) -> None:
        self._stamp_preset_dropdown.value = preset
        self._on_stamp_preset_selected(None)

    # -------------------------------------------------------------------------
    # Tab 5: Saved Signature Vault
    # -------------------------------------------------------------------------

    def activate_vault_signature(self, sig_id: str, as_initials: bool = False) -> None:
        try:
            entries = list_vault_signatures(self.vault_dir)
            meta = next((e for e in entries if e["id"] == sig_id), None)
            png_bytes = load_vault_signature_bytes(sig_id, vault_dir=self.vault_dir)
            label = meta["name"] if meta else "Saved Signature"
            if as_initials:
                self._set_initials_asset(png_bytes, label=label)
                show_snackbar(self.page, f"Set '{label}' as Initials asset for multi-page contracts", "info")
            else:
                self._set_active_asset(png_bytes, label=label, kind="signature")
                show_snackbar(self.page, f"Loaded '{label}' — click on PDF page to place", "info")
        except Exception as err:
            show_snackbar(self.page, f"Vault error: {err}", "error")

    def delete_from_vault(self, sig_id: str) -> None:
        if delete_vault_signature(sig_id, vault_dir=self.vault_dir):
            show_snackbar(self.page, "Removed signature from vault", "info")
            self._refresh_studio_panel()
            self._safe_page_update()

    def _build_vault_panel(self, is_dark: bool) -> ft.Control:
        entries = list_vault_signatures(self.vault_dir)
        if not entries:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.BOOKMARKS_OUTLINED, size=32, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text(
                            "Signature Vault is Empty",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                        ft.Text(
                            "Draw, type, or upload a signature and click 'Save to Vault' for instant 1-click reuse across future sessions.",
                            size=11,
                            color=ThemeTokens.text_muted(is_dark),
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                ),
                padding=24,
                alignment=ft.Alignment.CENTER,
                border_radius=ThemeTokens.RADIUS_SM,
                bgcolor=ThemeTokens.bg_surface(is_dark),
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            )

        cards: list[ft.Control] = []
        for entry in entries:
            try:
                png_bytes = Path(entry["png_path"]).read_bytes()
            except Exception:
                continue
            cards.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Image(src=png_bytes, width=110, height=44, fit=ft.BoxFit.CONTAIN),
                                bgcolor="#FFFFFF",
                                border_radius=ThemeTokens.RADIUS_XS,
                                padding=4,
                            ),
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(entry["name"], size=12, weight=ft.FontWeight.W_600, color=ThemeTokens.text_primary(is_dark)),
                                            make_badge(entry.get("kind", "saved").upper(), ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                                        ],
                                        spacing=6,
                                    ),
                                    ft.Text(f"Saved {entry.get('created_at', '')}", size=10, color=ThemeTokens.text_muted(is_dark)),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.FilledButton(
                                "Use",
                                icon=ft.Icons.CHECK,
                                on_click=lambda e, sid=entry["id"]: self.activate_vault_signature(sid, as_initials=False),
                            ),
                            ft.OutlinedButton(
                                "Set Initials",
                                on_click=lambda e, sid=entry["id"]: self.activate_vault_signature(sid, as_initials=True),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=18,
                                icon_color=ThemeTokens.ACCENT_DANGER,
                                tooltip="Delete from Vault",
                                on_click=lambda e, sid=entry["id"]: self.delete_from_vault(sid),
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    padding=10,
                    border_radius=ThemeTokens.RADIUS_SM,
                    bgcolor=ThemeTokens.bg_surface(is_dark),
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                )
            )

        return ft.Column(cards, spacing=8)

    # -------------------------------------------------------------------------
    # Active Placement Asset & Interactive Document Canvas
    # -------------------------------------------------------------------------

    def _compute_aspect_ratio(self, png_bytes: bytes) -> float:
        with Image.open(io.BytesIO(png_bytes)) as img:
            return max(0.2, min(6.0, img.width / max(img.height, 1)))

    def _set_active_asset(self, png_bytes: bytes, label: str, kind: str) -> None:
        self.active_asset = {
            "png_bytes": png_bytes,
            "label": label,
            "kind": kind,
            "aspect_ratio": self._compute_aspect_ratio(png_bytes),
        }
        self._refresh_active_asset_bar()
        self._safe_page_update()

    def _set_initials_asset(self, png_bytes: bytes, label: str) -> None:
        self.initials_asset = {
            "png_bytes": png_bytes,
            "label": label,
            "kind": "initials",
            "aspect_ratio": self._compute_aspect_ratio(png_bytes),
        }
        self._refresh_active_asset_bar()
        self._safe_page_update()

    def _refresh_active_asset_bar(self) -> None:
        is_dark = self._is_dark()
        if not self.active_asset:
            self._active_asset_bar.content = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.TOUCH_APP_OUTLINED, size=18, color=ThemeTokens.ACCENT_WARNING),
                        ft.Text(
                            "No active signature or stamp selected yet — create or pick one in the Studio above, then click the page to place.",
                            size=11,
                            color=ThemeTokens.text_secondary(is_dark),
                            expand=True,
                        ),
                    ],
                    spacing=8,
                ),
                padding=10,
                border_radius=ThemeTokens.RADIUS_SM,
                bgcolor=ThemeTokens.bg_surface(is_dark),
                border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            )
            return

        initials_badge = (
            make_badge(
                f"Initials: {self.initials_asset['label']}",
                ThemeTokens.bg_hover(is_dark),
                ThemeTokens.ACCENT_CYAN,
            )
            if self.initials_asset
            else ft.Container()
        )

        self._active_asset_bar.content = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Image(src=self.active_asset["png_bytes"], width=86, height=34, fit=ft.BoxFit.CONTAIN),
                        bgcolor="#FFFFFF",
                        border_radius=ThemeTokens.RADIUS_XS,
                        padding=3,
                    ),
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        f"Active Asset: {self.active_asset['label']}",
                                        size=12,
                                        weight=ft.FontWeight.W_600,
                                        color=ThemeTokens.text_primary(is_dark),
                                    ),
                                    make_badge("Click Page to Place", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                                    initials_badge,
                                ],
                                spacing=6,
                                wrap=True,
                            ),
                            ft.Text(
                                "Click anywhere on the page preview to drop, drag to reposition, or drag bottom-right corner to resize.",
                                size=10,
                                color=ThemeTokens.text_muted(is_dark),
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                ],
                spacing=10,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_surface(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_PRIMARY),
        )

    def place_active_asset_at(
        self,
        page_index: int,
        nx_center: float,
        ny_center: float,
        nw: float = 0.24,
    ) -> PlacementItem:
        """Place the active signature/stamp at normalized page coordinates centered on (nx_center, ny_center)."""
        if not self.active_asset:
            raise ValueError("Select or draw a signature or stamp in the Studio first.")

        aspect = float(self.active_asset.get("aspect_ratio", 2.5))
        page_ratio = 1.414
        if self.preview_data and self.preview_data["page_width"] > 0:
            page_ratio = self.preview_data["page_height"] / self.preview_data["page_width"]

        nw_clamped = max(0.06, min(0.8, float(nw)))
        nh_clamped = max(0.03, min(0.5, nw_clamped / max(aspect * page_ratio, 0.2)))

        nx = max(0.0, min(1.0 - nw_clamped, float(nx_center) - nw_clamped / 2.0))
        ny = max(0.0, min(1.0 - nh_clamped, float(ny_center) - nh_clamped / 2.0))

        item = PlacementItem(
            id=str(uuid.uuid4())[:8],
            page_index=page_index,
            nx=nx,
            ny=ny,
            nw=nw_clamped,
            nh=nh_clamped,
            png_bytes=self.active_asset["png_bytes"],
            label=self.active_asset["label"],
            kind=self.active_asset["kind"],
            opacity=1.0,
        )
        self.placements.append(item)
        self.selected_placement_id = item.id
        self._refresh_active_doc_card()
        self._refresh_doc_canvas()
        self._refresh_placement_inspector()
        self._refresh_placements_list()
        self._safe_page_update()
        return item

    def select_placement(self, placement_id: str) -> None:
        self.selected_placement_id = placement_id
        self._refresh_doc_canvas()
        self._refresh_placement_inspector()
        self._safe_page_update()

    def remove_placement(self, placement_id: str) -> None:
        self.placements = [p for p in self.placements if p.id != placement_id]
        if self.selected_placement_id == placement_id:
            self.selected_placement_id = None
        self._refresh_active_doc_card()
        self._refresh_doc_canvas()
        self._refresh_placement_inspector()
        self._refresh_placements_list()
        self._safe_page_update()

    def clear_placements(self, current_page_only: bool = False) -> None:
        if current_page_only:
            self.placements = [p for p in self.placements if p.page_index != self.current_page_index]
        else:
            self.placements.clear()
        self.selected_placement_id = None
        self._refresh_active_doc_card()
        self._refresh_doc_canvas()
        self._refresh_placement_inspector()
        self._refresh_placements_list()
        self._safe_page_update()

    def move_placement_by_delta(self, placement_id: str, dx_px: float, dy_px: float) -> None:
        if not self.preview_data:
            return
        cw = max(self.preview_data["canvas_width"], 1.0)
        ch = max(self.preview_data["canvas_height"], 1.0)
        item = next((p for p in self.placements if p.id == placement_id), None)
        if not item:
            return
        item.nx = max(0.0, min(1.0 - item.nw, item.nx + dx_px / cw))
        item.ny = max(0.0, min(1.0 - item.nh, item.ny + dy_px / ch))

    def resize_placement_by_delta(self, placement_id: str, dw_px: float, dh_px: float) -> None:
        if not self.preview_data:
            return
        cw = max(self.preview_data["canvas_width"], 1.0)
        ch = max(self.preview_data["canvas_height"], 1.0)
        item = next((p for p in self.placements if p.id == placement_id), None)
        if not item:
            return
        item.nw = max(0.05, min(1.0 - item.nx, item.nw + dw_px / cw))
        item.nh = max(0.03, min(1.0 - item.ny, item.nh + dh_px / ch))

    def _on_canvas_tap_down(self, e: ft.TapEvent) -> None:
        if not self.preview_data:
            return
        if not self.active_asset:
            show_snackbar(self.page, "Create or select a signature/stamp in the Studio first", "warning")
            return
        cw = max(self.preview_data["canvas_width"], 1.0)
        ch = max(self.preview_data["canvas_height"], 1.0)
        pos = getattr(e, "local_position", None)
        if pos is None:
            return
        nx = max(0.0, min(1.0, float(pos.x) / cw))
        ny = max(0.0, min(1.0, float(pos.y) / ch))
        self.place_active_asset_at(self.current_page_index, nx, ny)

    def _on_overlay_drag_update(self, placement_id: str, e: ft.DragUpdateEvent) -> None:
        delta = getattr(e, "local_delta", None) or getattr(e, "global_delta", None)
        if delta is None:
            return
        self.selected_placement_id = placement_id
        self.move_placement_by_delta(placement_id, float(delta.x), float(delta.y))
        self._refresh_doc_canvas()
        self._safe_page_update()

    def _on_overlay_drag_end(self, e: ft.DragEndEvent) -> None:
        self._refresh_placement_inspector()
        self._refresh_placements_list()
        self._safe_page_update()

    def _on_resize_drag_update(self, placement_id: str, e: ft.DragUpdateEvent) -> None:
        delta = getattr(e, "local_delta", None) or getattr(e, "global_delta", None)
        if delta is None:
            return
        self.selected_placement_id = placement_id
        self.resize_placement_by_delta(placement_id, float(delta.x), float(delta.y))
        self._refresh_doc_canvas()
        self._safe_page_update()

    def _on_resize_drag_end(self, e: ft.DragEndEvent) -> None:
        self._refresh_placement_inspector()
        self._refresh_placements_list()
        self._safe_page_update()

    def _refresh_doc_canvas(self) -> None:
        is_dark = self._is_dark()
        if not self.current_file or not self.preview_data:
            self._doc_canvas_container.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.HISTORY_EDU, size=36, color=ThemeTokens.text_muted(is_dark)),
                        ft.Text(
                            "Interactive Signing & Stamping Canvas",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                        ft.Text(
                            "Load a PDF to click-to-place signatures and stamps, move them, and resize with handles.",
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

        page_click_surface = ft.GestureDetector(
            content=ft.Image(
                src=self.preview_data["png_bytes"],
                width=cw,
                height=ch,
                fit=ft.BoxFit.FILL,
            ),
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap_down=self._on_canvas_tap_down,
        )

        stack_controls: list[ft.Control] = [page_click_surface]

        for item in self.placements:
            if item.page_index != self.current_page_index:
                continue
            is_sel = item.id == self.selected_placement_id
            ox = item.nx * cw
            oy = item.ny * ch
            ow = max(20.0, item.nw * cw)
            oh = max(14.0, item.nh * ch)

            border_color = ThemeTokens.ACCENT_PRIMARY if is_sel else "#64748B"
            overlay_body = ft.GestureDetector(
                content=ft.Container(
                    content=ft.Image(
                        src=item.png_bytes,
                        width=ow,
                        height=oh,
                        fit=ft.BoxFit.CONTAIN,
                        opacity=item.opacity,
                    ),
                    width=ow,
                    height=oh,
                    border=ft.Border.all(2 if is_sel else 1, border_color),
                    bgcolor="#183B82F6" if is_sel else "transparent",
                    border_radius=3,
                    tooltip=f"{item.label} (drag to move)",
                ),
                mouse_cursor=ft.MouseCursor.MOVE,
                drag_interval=16,
                on_tap_down=lambda e, pid=item.id: self.select_placement(pid),
                on_pan_update=lambda e, pid=item.id: self._on_overlay_drag_update(pid, e),
                on_pan_end=self._on_overlay_drag_end,
            )

            overlay_children: list[ft.Control] = [overlay_body]
            if is_sel:
                resize_handle = ft.GestureDetector(
                    content=ft.Container(
                        width=14,
                        height=14,
                        bgcolor=ThemeTokens.ACCENT_PRIMARY,
                        border=ft.Border.all(1.5, ft.Colors.WHITE),
                        border_radius=3,
                        tooltip="Drag to resize",
                    ),
                    mouse_cursor=ft.MouseCursor.RESIZE_DOWN_RIGHT,
                    drag_interval=16,
                    on_pan_update=lambda e, pid=item.id: self._on_resize_drag_update(pid, e),
                    on_pan_end=self._on_resize_drag_end,
                )
                overlay_children.append(
                    ft.Container(
                        content=resize_handle,
                        right=0,
                        bottom=0,
                    )
                )

            stack_controls.append(
                ft.Container(
                    content=ft.Stack(overlay_children, width=ow, height=oh),
                    left=ox,
                    top=oy,
                    width=ow,
                    height=oh,
                )
            )

        canvas_stack = ft.Stack(controls=stack_controls, width=cw, height=ch)

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
                ft.OutlinedButton(
                    "Clear Page",
                    icon=ft.Icons.LAYERS_CLEAR,
                    on_click=lambda e: self.clear_placements(current_page_only=True),
                ),
                ft.OutlinedButton(
                    "Clear All",
                    icon=ft.Icons.DELETE_SWEEP,
                    on_click=lambda e: self.clear_placements(current_page_only=False),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
        )

        self._doc_canvas_container.content = ft.Column(
            [
                nav_bar,
                ft.Container(
                    content=canvas_stack,
                    alignment=ft.Alignment.CENTER,
                    padding=10,
                    border_radius=ThemeTokens.RADIUS_SM,
                    bgcolor=ThemeTokens.bg_app(is_dark),
                    border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
                ),
            ],
            spacing=8,
        )

    # -------------------------------------------------------------------------
    # Selected Overlay Tuning & Multi-Page Signing
    # -------------------------------------------------------------------------

    def _on_selected_scale_changed(self, value: float) -> None:
        item = next((p for p in self.placements if p.id == self.selected_placement_id), None)
        if not item:
            return
        ratio = item.nh / max(item.nw, 0.01)
        new_nw = max(0.05, min(0.85, float(value)))
        item.nw = new_nw
        item.nh = max(0.03, min(0.7, new_nw * ratio))
        item.nx = min(item.nx, 1.0 - item.nw)
        item.ny = min(item.ny, 1.0 - item.nh)
        self._refresh_doc_canvas()
        self._safe_page_update()

    def _on_selected_opacity_changed(self, value: float) -> None:
        item = next((p for p in self.placements if p.id == self.selected_placement_id), None)
        if not item:
            return
        item.opacity = max(0.15, min(1.0, float(value)))
        self._refresh_doc_canvas()
        self._safe_page_update()

    def apply_multipage_preset(self, mode: str) -> list[PlacementItem]:
        if not self.current_file or self.total_pages < 1:
            show_snackbar(self.page, "Load a PDF document first", "warning")
            return []
        if not self.active_asset:
            show_snackbar(self.page, "Create or select a signature/stamp in the Studio first", "warning")
            return []

        try:
            page_range = self._multipage_range_field.value or ""
            secondary_png = self.initials_asset["png_bytes"] if self.initials_asset else None
            secondary_label = self.initials_asset["label"] if self.initials_asset else f"{self.active_asset['label']} (Initials)"

            new_items = build_multipage_placements(
                page_count=self.total_pages,
                mode=mode,
                primary_png=self.active_asset["png_bytes"],
                secondary_png=secondary_png,
                primary_label=self.active_asset["label"],
                secondary_label=secondary_label,
                kind=self.active_asset["kind"],
                page_range=page_range,
            )
            self.placements.extend(new_items)
            if new_items:
                self.selected_placement_id = new_items[-1].id
            self._refresh_active_doc_card()
            self._refresh_doc_canvas()
            self._refresh_placement_inspector()
            self._refresh_placements_list()
            self._safe_page_update()
            show_snackbar(self.page, f"Added {len(new_items)} placement(s) across document", "info")
            return new_items
        except Exception as err:
            show_snackbar(self.page, f"Multi-page error: {err}", "error")
            return []

    def _refresh_placement_inspector(self) -> None:
        is_dark = self._is_dark()
        selected = next((p for p in self.placements if p.id == self.selected_placement_id), None)

        if selected is None:
            self._placement_inspector_container.content = ft.Text(
                "Tip: Click any placed signature or stamp on the page to resize, adjust opacity, or remove it.",
                size=11,
                color=ThemeTokens.text_muted(is_dark),
            )
            return

        self._placement_inspector_container.content = ft.Container(
            content=ft.Row(
                [
                    make_badge(f"Selected: P.{selected.page_index + 1} • {selected.label}", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                    ft.Column(
                        [
                            ft.Text("Width (%)", size=10, color=ThemeTokens.text_secondary(is_dark)),
                            ft.Slider(
                                min=0.06,
                                max=0.75,
                                divisions=23,
                                value=max(0.06, min(0.75, selected.nw)),
                                width=165,
                                on_change=lambda e: self._on_selected_scale_changed(float(e.control.value)),
                            ),
                        ],
                        spacing=0,
                    ),
                    ft.Column(
                        [
                            ft.Text("Opacity", size=10, color=ThemeTokens.text_secondary(is_dark)),
                            ft.Slider(
                                min=0.2,
                                max=1.0,
                                divisions=16,
                                value=max(0.2, min(1.0, selected.opacity)),
                                width=140,
                                on_change=lambda e: self._on_selected_opacity_changed(float(e.control.value)),
                            ),
                        ],
                        spacing=0,
                    ),
                    ft.OutlinedButton(
                        "Remove Selected",
                        icon=ft.Icons.DELETE_OUTLINE,
                        on_click=lambda e, pid=selected.id: self.remove_placement(pid),
                    ),
                ],
                spacing=10,
                wrap=True,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_surface(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_PRIMARY),
        )

    def _refresh_placements_list(self) -> None:
        is_dark = self._is_dark()
        if not self.placements:
            self._placements_list_container.content = ft.Text(
                "No signatures or stamps placed yet.",
                size=11,
                color=ThemeTokens.text_muted(is_dark),
            )
            return

        rows: list[ft.Control] = []
        for item in self.placements:
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            make_badge(f"P.{item.page_index + 1}", ThemeTokens.bg_surface(is_dark), ThemeTokens.ACCENT_PRIMARY),
                            ft.Text(
                                f"{item.label} ({int(item.nx * 100)}%, {int(item.ny * 100)}% • {int(item.nw * 100)}% w)",
                                size=11,
                                color=ThemeTokens.text_primary(is_dark),
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=16,
                                icon_color=ThemeTokens.ACCENT_DANGER,
                                tooltip="Remove Overlay",
                                on_click=lambda e, pid=item.id: self.remove_placement(pid),
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=padding_symmetric(horizontal=10, vertical=4),
                    border_radius=ThemeTokens.RADIUS_XS,
                    bgcolor=ThemeTokens.bg_surface(is_dark),
                    border=ft.Border.all(1, ThemeTokens.border(is_dark)),
                )
            )
        self._placements_list_container.content = ft.Column(rows, spacing=4)

    # -------------------------------------------------------------------------
    # Export Signed PDF & Integrity Verification
    # -------------------------------------------------------------------------

    def apply_and_save_signed_pdf(self, e=None) -> None:
        if not self.current_file or not os.path.exists(self.current_file):
            show_snackbar(self.page, "Please select a PDF document first", "error")
            return
        if not self.placements:
            show_snackbar(self.page, "Place at least one signature or stamp before saving", "warning")
            return
        if self.is_processing:
            return

        self.is_processing = True
        out_name = generate_output_filename(self.current_file, "signed", ".pdf")
        out_path = os.path.join(self.output_dir, out_name)

        def worker():
            t_start = time.perf_counter()
            try:
                def on_progress(step: int, total: int, msg: str) -> None:
                    if self.progress_bar and self.progress_text:
                        update_progress(self.progress_bar, self.progress_text, step / max(total, 1), msg)

                result = apply_signatures_and_stamps(
                    source=self.current_file,
                    output_path=out_path,
                    placements=list(self.placements),
                    progress_callback=on_progress,
                )
                self._last_integrity_report = result
                self._refresh_integrity_report()
                elapsed = time.perf_counter() - t_start
                self._show_success_banner(
                    f"Embedded {result['placements_applied']} signature/stamp(s) across {result['pages_signed']} page(s) in {elapsed:.1f}s",
                    result["output_path"],
                )
                show_snackbar(self.page, f"Signed PDF saved: {os.path.basename(result['output_path'])}", "success")
            except Exception as err:
                self._show_feedback(f"Signing failed: {err}", "error")
                show_snackbar(self.page, f"Signing failed: {err}", "error")
            finally:
                self.is_processing = False
                if self.progress_bar and self.progress_text:
                    reset_progress(self.progress_bar, self.progress_text)
                self._safe_page_update()

        run_background(self.page, worker)

    def _refresh_integrity_report(self) -> None:
        is_dark = self._is_dark()
        if not self._last_integrity_report:
            self._integrity_report_container.visible = False
            self._integrity_report_container.content = None
            return

        rep = self._last_integrity_report
        self._integrity_report_container.visible = True
        self._integrity_report_container.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.VERIFIED, size=18, color=ThemeTokens.ACCENT_SUCCESS),
                            ft.Text(
                                "Local Integrity Digest (SHA-256)",
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                            make_badge(f"{rep['placements_applied']} Baked", ThemeTokens.bg_surface(is_dark), ThemeTokens.ACCENT_SUCCESS),
                        ],
                        spacing=8,
                    ),
                    ft.Text(f"Original SHA-256: {rep['sha256_before']}", size=10, color=ThemeTokens.text_secondary(is_dark), selectable=True),
                    ft.Text(f"Signed   SHA-256: {rep['sha256_after']}", size=10, color=ThemeTokens.text_secondary(is_dark), selectable=True),
                ],
                spacing=3,
            ),
            padding=10,
            border_radius=ThemeTokens.RADIUS_SM,
            bgcolor=ThemeTokens.bg_surface(is_dark),
            border=ft.Border.all(1, ThemeTokens.ACCENT_SUCCESS),
        )

    # -------------------------------------------------------------------------
    # Feedback Banners & Master UI Layout
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
        """Construct the complete Phase 7 Digital Signatures & Stamp Studio workspace."""
        is_dark = self._is_dark()
        self._refresh_all_panels()

        for tf in (
            self._vault_name_field,
            self._typed_name_field,
            self._stamp_text_field,
            self._stamp_operator_field,
            self._stamp_subtext_field,
            self._multipage_range_field,
        ):
            tf.bgcolor = ThemeTokens.bg_surface(is_dark)
            tf.border_color = ThemeTokens.border_muted(is_dark)
            tf.color = ThemeTokens.text_primary(is_dark)

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    "✍️ Digital Signatures & Stamp Studio",
                                    size=16,
                                    weight=ft.FontWeight.W_700,
                                    color=ThemeTokens.text_primary(is_dark),
                                ),
                                make_badge("Phase 7", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_PRIMARY),
                                make_badge("Local Vault", ThemeTokens.bg_hover(is_dark), ThemeTokens.ACCENT_SUCCESS),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            "Draw, type, or upload signatures, generate dynamic rubber stamps, and sign multi-page PDFs locally",
                            size=12,
                            color=ThemeTokens.text_secondary(is_dark),
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Card 1: Signature & Stamp Creation Studio
        studio_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DESIGN_SERVICES, size=18, color=ThemeTokens.ACCENT_PRIMARY),
                            ft.Text(
                                "Signature & Stamp Creator",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    self._studio_tabs_row,
                    self._studio_body_container,
                    self._active_asset_bar,
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        # Card 2: Interactive Document Canvas & Multi-Page Signing
        canvas_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TOUCH_APP, size=18, color=ThemeTokens.ACCENT_CYAN),
                            ft.Text(
                                "Interactive Placement Canvas & Multi-Page Signing",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=ThemeTokens.text_primary(is_dark),
                            ),
                        ],
                        spacing=8,
                    ),
                    self._doc_canvas_container,
                    self._placement_inspector_container,
                    ft.Divider(height=1, color=ThemeTokens.border(is_dark)),
                    ft.Text(
                        "Multi-Page Signing Workflows",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=ThemeTokens.text_primary(is_dark),
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "Initial All + Sign Final Page",
                                icon=ft.Icons.AUTO_STORIES,
                                on_click=lambda e: self.apply_multipage_preset("initial_all_sign_last"),
                            ),
                            ft.OutlinedButton(
                                "Apply to All Pages",
                                icon=ft.Icons.COPY_ALL,
                                on_click=lambda e: self.apply_multipage_preset("all_pages"),
                            ),
                            ft.OutlinedButton(
                                "Sign Final Page",
                                icon=ft.Icons.LAST_PAGE,
                                on_click=lambda e: self.apply_multipage_preset("final_page"),
                            ),
                            self._multipage_range_field,
                            ft.OutlinedButton(
                                "Apply to Range",
                                icon=ft.Icons.FILTER_LIST,
                                on_click=lambda e: self.apply_multipage_preset("custom_range"),
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    self._placements_list_container,
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=ThemeTokens.RADIUS_MD,
            border=ft.Border.all(1, ThemeTokens.border_muted(is_dark)),
            bgcolor=ThemeTokens.bg_card(is_dark),
        )

        # Card 3: Export & Verification Bar
        export_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.FilledButton(
                                "Save Signed & Stamped PDF",
                                icon=ft.Icons.VERIFIED,
                                on_click=self.apply_and_save_signed_pdf,
                                style=ft.ButtonStyle(
                                    bgcolor=ThemeTokens.ACCENT_PRIMARY,
                                    color=ft.Colors.WHITE,
                                    shape=ft.RoundedRectangleBorder(radius=ThemeTokens.RADIUS_SM),
                                ),
                            ),
                        ],
                        spacing=10,
                    ),
                    self._integrity_report_container,
                ],
                spacing=10,
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
                studio_card,
                canvas_card,
                export_card,
            ],
            spacing=14,
            expand=True,
        )
