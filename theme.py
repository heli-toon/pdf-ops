"""PDF-Ops Impeccable Design System & Neutral Slate Theme Tokens.

Surface Mode: Operate (task efficiency, high scanability, native affordances,
clear semantic hierarchy, zero decorative clutter).
"""

import flet as ft


class ThemeTokens:
    """Design tokens following the Slate architecture and Material 3 principles."""

    # Dark Slate Palette
    DARK_BG_APP = "#0B0F17"          # Deep canvas
    DARK_BG_SURFACE = "#111827"      # Elevated container/rails
    DARK_BG_CARD = "#1E293B"         # Cards, inputs, dropzone
    DARK_BG_HOVER = "#334155"        # Interactive hover
    DARK_BORDER = "#1E293B"          # Hairline separator
    DARK_BORDER_MUTED = "#334155"    # Card outlines
    DARK_TEXT_PRIMARY = "#F8FAFC"    # Crisp white-slate
    DARK_TEXT_SECONDARY = "#94A3B8"  # Slate 400
    DARK_TEXT_MUTED = "#64748B"      # Slate 500

    # Light Paper Palette
    LIGHT_BG_APP = "#F8FAFC"         # Crisp slate 50
    LIGHT_BG_SURFACE = "#FFFFFF"     # Clean white
    LIGHT_BG_CARD = "#F1F5F9"        # Soft slate 100
    LIGHT_BG_HOVER = "#E2E8F0"       # Slate 200
    LIGHT_BORDER = "#E2E8F0"         # Slate 200
    LIGHT_BORDER_MUTED = "#CBD5E1"   # Slate 300
    LIGHT_TEXT_PRIMARY = "#0F172A"   # Deep slate 900
    LIGHT_TEXT_SECONDARY = "#475569" # Slate 600
    LIGHT_TEXT_MUTED = "#94A3B8"     # Slate 400

    # Semantic Accents (Operate Mode Functional Tokens)
    ACCENT_PRIMARY = "#3B82F6"       # Electric Blue / Indigo (actions)
    ACCENT_PRIMARY_HOVER = "#2563EB"
    ACCENT_PRIMARY_BG_DARK = "#1E3A8A"
    ACCENT_PRIMARY_BG_LIGHT = "#EFF6FF"

    ACCENT_SUCCESS = "#10B981"       # Emerald (safe, completed, verified)
    ACCENT_SUCCESS_BG_DARK = "#064E3B"
    ACCENT_SUCCESS_BG_LIGHT = "#ECFDF5"

    ACCENT_WARNING = "#F59E0B"       # Amber (review, non-destructive caution)
    ACCENT_WARNING_BG_DARK = "#78350F"
    ACCENT_WARNING_BG_LIGHT = "#FFFBEB"

    ACCENT_DANGER = "#EF4444"        # Rose (destructive, password lock)
    ACCENT_DANGER_BG_DARK = "#7F1D1D"
    ACCENT_DANGER_BG_LIGHT = "#FEF2F2"

    ACCENT_CYAN = "#06B6D4"          # Cyan (OCR / batch automation)

    # Geometry & Spacing
    RADIUS_XS = 4
    RADIUS_SM = 8
    RADIUS_MD = 12
    RADIUS_LG = 16

    @classmethod
    def bg_app(cls, is_dark: bool) -> str:
        return cls.DARK_BG_APP if is_dark else cls.LIGHT_BG_APP

    @classmethod
    def bg_surface(cls, is_dark: bool) -> str:
        return cls.DARK_BG_SURFACE if is_dark else cls.LIGHT_BG_SURFACE

    @classmethod
    def bg_card(cls, is_dark: bool) -> str:
        return cls.DARK_BG_CARD if is_dark else cls.LIGHT_BG_CARD

    @classmethod
    def bg_hover(cls, is_dark: bool) -> str:
        return cls.DARK_BG_HOVER if is_dark else cls.LIGHT_BG_HOVER

    @classmethod
    def border(cls, is_dark: bool) -> str:
        return cls.DARK_BORDER if is_dark else cls.LIGHT_BORDER

    @classmethod
    def border_muted(cls, is_dark: bool) -> str:
        return cls.DARK_BORDER_MUTED if is_dark else cls.LIGHT_BORDER_MUTED

    @classmethod
    def text_primary(cls, is_dark: bool) -> str:
        return cls.DARK_TEXT_PRIMARY if is_dark else cls.LIGHT_TEXT_PRIMARY

    @classmethod
    def text_secondary(cls, is_dark: bool) -> str:
        return cls.DARK_TEXT_SECONDARY if is_dark else cls.LIGHT_TEXT_SECONDARY

    @classmethod
    def text_muted(cls, is_dark: bool) -> str:
        return cls.DARK_TEXT_MUTED if is_dark else cls.LIGHT_TEXT_MUTED


def padding_symmetric(horizontal: float = 0, vertical: float = 0) -> ft.Padding:
    """Create symmetric padding."""
    return ft.Padding(left=horizontal, right=horizontal, top=vertical, bottom=vertical)


def padding_only(left: float = 0, top: float = 0, right: float = 0, bottom: float = 0) -> ft.Padding:
    """Create directional padding."""
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def make_badge(text: str, bg_color: str, text_color: str, icon: str | None = None) -> ft.Container:
    """Create a compact, high-scanability semantic status badge."""
    controls = []
    if icon:
        controls.append(ft.Icon(icon, size=12, color=text_color))
    controls.append(
        ft.Text(
            text,
            size=11,
            weight=ft.FontWeight.W_600,
            color=text_color,
        )
    )
    return ft.Container(
        content=ft.Row(controls, spacing=4, alignment=ft.MainAxisAlignment.CENTER, tight=True),
        bgcolor=bg_color,
        border_radius=ThemeTokens.RADIUS_XS,
        padding=padding_symmetric(horizontal=8, vertical=3),
    )
