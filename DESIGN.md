# Design System

<!-- impeccable:design-schema 1 -->

## Visual Architecture & Tone

**PDF-Ops** is built on the **Impeccable** design framework in **Operate Mode**:
- **Tone**: Focused, technical, dependable, high-craft local utility. The tool disappears into the task.
- **Surface Mode**: Operate. Every pixel serves the workflow. Generous hit targets, intuitive shortcuts, high information density without visual noise.

---

## Palette Tokens

### Slate Dark Mode (Default)
- **Canvas / App Background**: `#0B0F17` (Deep Slate)
- **Elevated Surfaces / Navigation Rail / Inspector**: `#111827` (Slate 900)
- **Card / Dropzone / Input Background**: `#1E293B` (Slate 800)
- **Hover Background**: `#334155` (Slate 700)
- **Neutral Border**: `#1E293B` / `#334155`
- **Text Primary**: `#F8FAFC` (Slate 50)
- **Text Secondary**: `#94A3B8` (Slate 400)
- **Text Muted**: `#64748B` (Slate 500)

### Crisp Paper Light Mode
- **Canvas / App Background**: `#F8FAFC` (Slate 50)
- **Elevated Surfaces**: `#FFFFFF` (Pure White)
- **Card / Input Background**: `#F1F5F9` (Slate 100)
- **Hover Background**: `#E2E8F0` (Slate 200)
- **Neutral Border**: `#E2E8F0` / `#CBD5E1`
- **Text Primary**: `#0F172A` (Slate 900)
- **Text Secondary**: `#475569` (Slate 600)
- **Text Muted**: `#94A3B8` (Slate 400)

### Functional Semantic Accents
- **Primary / Actions**: `#3B82F6` (Electric Blue / Indigo)
- **Success / Verified Safe**: `#10B981` (Emerald)
- **Warning / Review**: `#F59E0B` (Amber)
- **Destructive / Password Lock**: `#EF4444` (Rose)
- **Automation / Scanning**: `#06B6D4` (Cyan)

---

## Typography

- **System Font Stack**: Inter, Roboto, -apple-system, Segoe UI, sans-serif.
- **Type Roles**:
  - `Display / App Title`: 18px, Weight 800 (Extra Bold)
  - `Section / Tool Heading`: 14px–16px, Weight 700 (Bold)
  - `Body / Button Text`: 12px–13px, Weight 500 / 600
  - `Captions & Metrics`: 10px–11px, Weight 500
- **Tabular Figures**: File sizes (`MB`, `KB`), page counts (`P.1`, `P.2`), percentages, and coordinate dimensions use tabular numerals for clean alignment.

---

## Geometry & Elevation

- **Radii**:
  - Badge / Tag: `RADIUS_XS = 4px`
  - Button / Control: `RADIUS_SM = 8px`
  - Container / Card: `RADIUS_MD = 12px`
  - Modal / Sheet: `RADIUS_LG = 16px`
- **Tonal Elevation**: In dark mode, depth is conveyed through subtle surface tone step-ups (`#0B0F17` $\rightarrow$ `#111827` $\rightarrow$ `#1E293B`) paired with 1px hairline neutral borders. No fuzzy drop-shadow halos.

---

## Layout & Responsive Breakpoints

1. **Desktop 3-Pane Adaptive Rail ($\ge 780\text{px}$)**:
   - **Left Rail (220px)**: Branding, version pill, navigation destinations (Quick Actions, Convert, Edit, Merge & Split, Security, Page Manager, OCR), output directory indicator, and offline guarantee status.
   - **Center Workspace (Flex)**: Tool-first wizard stage (Step 1 Dropzone with active document card $\rightarrow$ Step 2 Tool configuration parameters $\rightarrow$ Step 3 Execution bar with progress indicators).
   - **Right Contextual Inspector (300px)**: Document metadata summary (name, size, pages, dimensions, encryption status) + in-memory rendered interactive thumbnail reel.
2. **Mobile / Android Responsive Mode ($< 780\text{px}$)**:
   - Collapses rail into a standard Material 3 Bottom Navigation Bar with 48dp minimum touch targets.
   - Stacked single-column primary workspace with collapsible panels.

---

## Keyboard Accelerators

- `Ctrl + O` / `Cmd + O`: Open file browser dialog.
- `Ctrl + D` / `Cmd + D`: Toggle between Slate Dark and Crisp Paper Light themes.
- `Escape`: Clear active document selection or dismiss open dialogs.
