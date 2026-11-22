# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users

Primary users are privacy-conscious professionals and individuals (legal, financial, healthcare, government, and administrative operators) who handle sensitive, confidential, or proprietary PDF documents and require reliable document operations on desktop (Windows, Linux) and mobile (Android) without risking data leakage or cloud storage exposure.

## Product Purpose

PDF-Ops provides a local-first, privacy-guaranteed desktop and mobile utility suite for converting, editing, organizing, encrypting, and manipulating PDF documents. Success means tasks (such as conversion, password removal, watermark application, and page splitting/merging) complete swiftly and reliably on-device with zero network requests, complete offline autonomy, and predictable, deterministic results.

## Positioning

Unlike cloud-based PDF web services (Smallpdf, iLovePDF, Adobe Acrobat Cloud) that require uploading confidential files to remote servers, and unlike bloated legacy desktop software packed with dark patterns and upsells, PDF-Ops runs 100% locally with a decoupled, high-performance Python/PyMuPDF core engine. It never makes external network calls for core document operations.

## Operating Context

- **Workspaces & Platforms**: Desktop environments (Windows 10/11, Linux distributions via native deb/AppImage) and Android mobile devices (via Flet / Flutter APK).
- **Primary Interaction Model**: Tool-first action wizard: Users pick a dedicated tool action (e.g., Convert to Word, Watermark, Split Pages, Encrypt), select the target file(s), configure focused parameters, and execute the run with real-time progress and immediate file reveal.
- **File System**: Direct local filesystem integration, saving processed documents to a user-configured or dedicated local directory (`~/Documents/PDF-OPS/` or platform equivalent) without intermediate cloud caching.

## Capabilities and Constraints

- **Confirmed Core Capabilities**:
  - Convert: PDF to Word (`pdf2docx`), PDF to Images/DPI presets, Images to PDF, PDF to Excel tables (`pymupdf.find_tables()` to `.xlsx`), and Office document detection.
  - Edit & Geometry: Text/image stamp overlay, opacity & angled watermark engine, 90°/180°/270° rotation, and page cropping margin updates.
  - Merge & Split: Multi-file merge queue, custom range splitting (`1-3, 5, 8-end`), bookmark chapter splitting, and stream compression/deflate.
  - Security: Standard AES-256 encryption, granular permissions (print, copy, edit, comment, forms), and password removal / validation.
- **Technical Constraints**:
  - Python 3.12 + Flet 1.1+ UI framework.
  - PyMuPDF (`pymupdf`), `pypdf`, `pdf2docx`, `openpyxl`, `Pillow`.
  - Zero cloud dependencies / strictly local execution.
  - No code pushes to remote repositories during current stages (`Don't push any code....`).
- **Phase 3 UI Scope**:
  - Ground-up overhaul using Impeccable framework in **Operate Mode** (high information density, clear hierarchy, high scanability, keyboard shortcuts, clean feedback).
  - Adaptive layout: 3-pane rail architecture on desktop that folds gracefully into single-column responsive cards and bottom navigation on Android.

## Brand Commitments

- **Name**: PDF-Ops
- **Voice**: Crisp, professional, technical, dependable, transparent utility. No promotional hype or patronizing prose.
- **Visual Identity**: Modern slate palette (deep slate dark mode, crisp paper light mode), semantic status accents (Emerald success, Amber warning, Rose destructive, Indigo primary), clean system sans-serif hierarchy with tabular figures for file sizes and page metrics.
- **Assets**: Embedded SVG / Material Symbols via Flet, local `icon.ico` and brand assets in `images/`.

## Evidence on Hand

- Fully realized and decoupled backend engine in [`pdf_engine.py`](file:///home/muhaimin/Documents/pdf-ops/pdf_engine.py) passing 100% of test suites (14 unit tests in [`tests/`](file:///home/muhaimin/Documents/pdf-ops/tests/)).
- Reactive application state store in [`app_state.py`](file:///home/muhaimin/Documents/pdf-ops/app_state.py).
- Comprehensive phased architecture roadmap in [`WAY Forward.md`](file:///home/muhaimin/Documents/pdf-ops/WAY%20Forward.md).
- Packaging automation specifications for Inno Setup ([`PDF-Ops Build Inno Script.iss`](file:///home/muhaimin/Documents/pdf-ops/PDF-Ops%20Build%20Inno%20Script.iss)) and PyInstaller ([`main.spec`](file:///home/muhaimin/Documents/pdf-ops/main.spec)).

## Product Principles

1. **Zero Leakage, Absolute Privacy**: Every byte of document data remains on the user's physical machine. No telemetry, no background network calls, and no cloud dependencies.
2. **Operate Mode Precision**: The user has work to get done. Optimize for rapid scanning, obvious primary actions, instant feedback, and zero decorative fluff.
3. **Tool-First Simplicity**: Clear progression: select tool -> provide document -> set parameters -> execute -> access output. Avoid nested multi-screen mazes.
4. **Adaptive Ergonomics**: Desktop provides an expansive, dense 3-pane workspace with keyboard accelerators; Android provides thumb-friendly touch targets, bottom sheets, and single-column clarity without sacrificing power.
5. **Deterministic Fidelity**: Document geometry, fonts, formatting, and permissions must be preserved with exact mathematical coordinates and robust error recovery.
