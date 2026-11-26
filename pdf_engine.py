"""Testable local PDF operations used by the Flet controllers.

The functions in this module do not depend on Flet. They intentionally keep
all files on the local machine and raise useful exceptions for the UI to show.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pymupdf as fitz


def find_office_converter() -> str | None:
    """Return a LibreOffice command available on PATH, if there is one."""
    for command in ("soffice", "libreoffice"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def convert_office_to_pdf(source: str | Path, output_dir: str | Path) -> Path:
    """Convert a local Office document through LibreOffice's headless mode."""
    converter = find_office_converter()
    if not converter:
        raise RuntimeError(
            "LibreOffice was not found. Install LibreOffice and make soffice available on PATH."
        )
    source_path = Path(source)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [converter, "--headless", "--convert-to", "pdf", "--outdir", str(destination), str(source_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = destination / f"{source_path.stem}.pdf"
    if result.returncode or not output.exists():
        detail = (result.stderr or result.stdout).strip() or "LibreOffice did not create a PDF."
        raise RuntimeError(detail)
    return output


def export_pdf_images(
    source: str | Path,
    output_dir: str | Path,
    dpi: int = 150,
    image_format: str = "png",
) -> list[Path]:
    """Render each PDF page locally at a predictable DPI and image format (PNG, JPEG, WEBP)."""
    if dpi not in (72, 150, 300):
        raise ValueError("DPI must be one of 72, 150, or 300")
    fmt = image_format.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in {"png", "jpeg", "webp"}:
        raise ValueError("Image format must be PNG, JPEG, or WEBP")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    extension = "jpg" if fmt == "jpeg" else fmt
    outputs: list[Path] = []
    with fitz.open(source) as document:
        for index, page in enumerate(document, start=1):
            output = destination / f"page_{index}.{extension}"
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            if fmt == "webp":
                img = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                img.save(output, format="WEBP")
            else:
                pixmap.save(output, output=fmt)
            outputs.append(output)
    return outputs


def convert_images_to_pdf(image_paths: list[str | Path], output_path: str | Path) -> Path:
    """Convert a sequence of images into a single PDF document without temporary files."""
    if not image_paths:
        raise ValueError("No images provided for conversion")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        for img_path in sorted(image_paths, key=lambda p: str(p)):
            with fitz.open(str(img_path)) as img_doc:
                pdf_bytes = img_doc.convert_to_pdf()
            with fitz.open("pdf", pdf_bytes) as img_pdf:
                document.insert_pdf(img_pdf)
        document.save(out)
    return out


def export_pdf_tables_to_excel(source: str | Path, output_path: str | Path) -> int:
    """Extract detected PDF tables into individual Excel worksheets."""
    import openpyxl

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    table_count = 0
    with fitz.open(source) as document:
        for page_number, page in enumerate(document, start=1):
            tables = page.find_tables().tables
            for table_number, table in enumerate(tables, start=1):
                worksheet = workbook.create_sheet(f"Page {page_number} Table {table_number}")
                for row in table.extract():
                    worksheet.append([cell or "" for cell in row])
                table_count += 1
    if not table_count:
        raise ValueError("No extractable tables were found in this PDF")
    workbook.save(out)
    return table_count


def parse_page_ranges(expression: str, page_count: int) -> list[int]:
    """Parse 1-based page syntax such as ``1-3, 5, 8-end`` preserving order."""
    if page_count < 1:
        raise ValueError("The document has no pages")
    if not expression or not expression.strip():
        raise ValueError("Page range expression cannot be empty")
    pages: list[int] = []
    for raw_part in expression.split(","):
        part = raw_part.strip().lower()
        if not part:
            raise ValueError("Page ranges cannot contain empty entries")
        if "-" in part:
            start_text, end_text = (item.strip() for item in part.split("-", 1))
            start = int(start_text)
            end = page_count if end_text == "end" else int(end_text)
            if start < 1 or end < start or end > page_count:
                raise ValueError(f"Invalid page range: {raw_part}")
            pages.extend(range(start, end + 1))
        else:
            page = page_count if part == "end" else int(part)
            if page < 1 or page > page_count:
                raise ValueError(f"Page {raw_part} is outside this document")
            pages.append(page)
    return pages


def compress_pdf(source: str | Path, output: str | Path) -> None:
    """Losslessly clean and deflate PDF streams without simulated work."""
    with fitz.open(source) as document:
        document.save(
            output,
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
        )


def rotate_pdf_pages(
    source: str | Path,
    output_path: str | Path,
    angle: int,
    page_numbers: list[int] | None = None,
) -> Path:
    """Rotate specified pages (1-based) by cumulative angle (e.g. 90, 180, 270)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as document:
        targets = set(page_numbers) if page_numbers is not None else set(range(1, document.page_count + 1))
        for index, page in enumerate(document, start=1):
            if index in targets:
                page.set_rotation((page.rotation + angle) % 360)
        document.save(out)
    return out


def crop_pdf_pages(
    source: str | Path,
    output_path: str | Path,
    margins: tuple[float, float, float, float],  # (left, top, right, bottom) as 0.0-1.0
    page_numbers: list[int] | None = None,
) -> Path:
    """Crop margins on specified pages (1-based) keeping MediaBox & CropBox in sync."""
    left, top, right, bottom = margins
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as document:
        targets = set(page_numbers) if page_numbers is not None else set(range(1, document.page_count + 1))
        for index, page in enumerate(document, start=1):
            if index in targets:
                rect = page.rect
                new_rect = fitz.Rect(
                    rect.x0 + rect.width * left,
                    rect.y0 + rect.height * top,
                    rect.x1 - rect.width * right,
                    rect.y1 - rect.height * bottom,
                )
                page.set_cropbox(new_rect)
                page.set_mediabox(new_rect)
        document.save(out)
    return out


def add_watermark_to_pdf(
    source: str | Path,
    output_path: str | Path,
    text: str,
    font_size: int = 48,
    color: tuple[float, float, float] = (0.8, 0.8, 0.8),
    opacity: float = 0.3,
    angle: int = 45,
    overlay: bool = True,
) -> Path:
    """Add a watermark with controllable opacity, arbitrary angle, and layer placement."""
    if not text:
        raise ValueError("Watermark text cannot be empty")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as document:
        for page in document:
            rect = page.rect
            center = fitz.Point(rect.width / 2, rect.height / 2)
            rot = angle if angle in (0, 90, 180, 270) else 0
            morph = (center, fitz.Matrix(angle)) if angle not in (0, 90, 180, 270) else None
            page.insert_text(
                center,
                text,
                fontsize=font_size,
                color=color,
                fill_opacity=opacity,
                stroke_opacity=opacity,
                rotate=rot,
                morph=morph,
                overlay=overlay,
            )
        document.save(out)
    return out


def encrypt_pdf(
    source: str | Path,
    output_path: str | Path,
    user_password: str,
    owner_password: str | None = None,
    allow_printing: bool = True,
    allow_copying: bool = True,
    allow_editing: bool = False,
    allow_annotations: bool = True,
    allow_forms: bool = True,
) -> Path:
    """Encrypt a PDF with AES-256 and granular permission flags."""
    if not user_password and not owner_password:
        raise ValueError("At least one password must be specified")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    perms = 0
    if allow_printing:
        perms |= fitz.PDF_PERM_PRINT
    if allow_copying:
        perms |= fitz.PDF_PERM_COPY
    if allow_editing:
        perms |= fitz.PDF_PERM_MODIFY
    if allow_annotations:
        perms |= fitz.PDF_PERM_ANNOTATE
    if allow_forms:
        perms |= fitz.PDF_PERM_FORM

    with fitz.open(source) as document:
        if document.is_encrypted:
            raise ValueError("Document is already encrypted")
        owner_pw = owner_password if owner_password else user_password
        user_pw = user_password if user_password else ""
        document.save(
            out,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=owner_pw,
            user_pw=user_pw,
            permissions=perms,
        )
    return out


def decrypt_pdf(
    source: str | Path,
    output_path: str | Path,
    password: str,
) -> Path:
    """Decrypt an encrypted PDF document in-memory."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as document:
        if document.needs_pass or document.is_encrypted:
            auth = document.authenticate(password)
            if auth == 0:
                raise ValueError("Incorrect password")
        elif not password:
            pass
        else:
            auth = document.authenticate(password)
            if auth == 0:
                raise ValueError("Incorrect password")
        document.save(out)
    return out


def inspect_pdf(source: str | Path) -> dict:
    """Return metadata, page count, and encryption status for a PDF."""
    path = Path(source)
    with fitz.open(source) as document:
        return {
            "page_count": document.page_count,
            "is_encrypted": document.is_encrypted,
            "file_size": path.stat().st_size if path.exists() else 0,
            "metadata": document.metadata or {},
        }


@dataclass
class PageDescriptor:
    """Reactive descriptor of a single PDF page for interactive organization."""

    id: str
    source_path: str
    page_index: int  # 0-based index in source_path
    rotation: int = 0  # 0, 90, 180, 270 degrees relative rotation
    is_deleted: bool = False


def render_page_thumbnail(
    source: str | Path,
    page_index: int,
    rotation: int = 0,
    max_dim: int = 180,
) -> bytes:
    """Render a high-fidelity in-memory PNG thumbnail of a PDF page with cumulative rotation."""
    with fitz.open(str(source)) as doc:
        if page_index < 0 or page_index >= doc.page_count:
            raise IndexError(f"Page index {page_index} out of bounds (document has {doc.page_count} pages)")
        page = doc[page_index]
        orig_rect = page.rect
        scale = max_dim / max(orig_rect.width, orig_rect.height, 1)
        matrix = fitz.Matrix(scale, scale).prerotate(rotation)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")


def load_document_descriptors(source: str | Path) -> list[PageDescriptor]:
    """Inspect a PDF and generate initial PageDescriptor items for each page."""
    source_path = str(Path(source).resolve())
    descriptors: list[PageDescriptor] = []
    with fitz.open(source_path) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{Path(source).name}' is password protected. Decrypt it before organizing.")
        for idx in range(doc.page_count):
            descriptors.append(
                PageDescriptor(
                    id=str(uuid.uuid4())[:8],
                    source_path=source_path,
                    page_index=idx,
                    rotation=0,
                    is_deleted=False,
                )
            )
    return descriptors


def save_organized_pdf(pages: list[PageDescriptor], output_path: str | Path) -> Path:
    """Export rearranged, rotated, and filtered pages into a bit-perfect PDF without quality loss."""
    active_pages = [p for p in pages if not p.is_deleted]
    if not active_pages:
        raise ValueError("Cannot save an empty PDF. At least one active page is required.")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    source_cache: dict[str, fitz.Document] = {}
    try:
        target_doc = fitz.open()
        for desc in active_pages:
            src_str = str(desc.source_path)
            if src_str not in source_cache:
                source_cache[src_str] = fitz.open(src_str)
            src_doc = source_cache[src_str]
            target_doc.insert_pdf(src_doc, from_page=desc.page_index, to_page=desc.page_index)
            if desc.rotation % 360 != 0:
                target_page = target_doc[-1]
                target_page.set_rotation((target_page.rotation + desc.rotation) % 360)

        target_doc.save(out, deflate=True, garbage=3)
        return out
    finally:
        for d in source_cache.values():
            d.close()


def extract_organized_pages(
    pages: list[PageDescriptor],
    output_path: str | Path,
    selected_ids: set[str] | list[str] | None = None,
) -> Path:
    """Extract specified or selected pages into a new standalone PDF."""
    if selected_ids is not None:
        target_ids = set(selected_ids)
        target_pages = [p for p in pages if p.id in target_ids and not p.is_deleted]
    else:
        target_pages = [p for p in pages if not p.is_deleted]

    if not target_pages:
        raise ValueError("No pages were selected for extraction.")

    return save_organized_pdf(target_pages, output_path)


def insert_document_descriptors(
    current_pages: list[PageDescriptor],
    insert_at_index: int,
    new_source: str | Path,
) -> list[PageDescriptor]:
    """Insert pages from another PDF at a specified index in the descriptor list."""
    new_descriptors = load_document_descriptors(new_source)
    result = list(current_pages)
    idx = max(0, min(insert_at_index, len(result)))
    result[idx:idx] = new_descriptors
    return result


def get_tessdata_path(custom_path: str | Path | None = None) -> str:
    """Return the absolute path to the Tesseract language models directory."""
    if custom_path is not None:
        cp = Path(custom_path)
        if cp.is_dir():
            return str(cp.resolve())
        raise FileNotFoundError(f"Specified tessdata directory '{custom_path}' does not exist.")

    env_prefix = os.getenv("TESSDATA_PREFIX")
    if env_prefix and Path(env_prefix).is_dir():
        return str(Path(env_prefix).resolve())

    # Check local project tessdata directory
    local_dir = Path(__file__).resolve().parent / "tessdata"
    if local_dir.is_dir() and any(local_dir.glob("*.traineddata")):
        return str(local_dir)

    # Standard Linux system paths
    for candidate in [
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tessdata"),
        Path("/usr/local/share/tessdata"),
    ]:
        if candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return str(candidate)

    # If local directory exists even if empty, return it
    if local_dir.is_dir():
        return str(local_dir)

    raise FileNotFoundError(
        "Tessdata directory containing *.traineddata models was not found. "
        "Place language models in 'tessdata/' or set TESSDATA_PREFIX."
    )


def get_available_ocr_languages(tessdata_dir: str | Path | None = None) -> list[tuple[str, str]]:
    """Return list of (language_code, display_name) available in the tessdata directory."""
    try:
        tess_path = Path(get_tessdata_path(tessdata_dir))
    except FileNotFoundError:
        return [("eng", "English (eng)")]

    lang_names = {
        "eng": "English (eng)",
        "fra": "French (fra)",
        "deu": "German (deu)",
        "spa": "Spanish (spa)",
        "ita": "Italian (ita)",
        "por": "Portuguese (por)",
        "rus": "Russian (rus)",
        "chi_sim": "Chinese Simplified (chi_sim)",
        "chi_tra": "Chinese Traditional (chi_tra)",
        "jpn": "Japanese (jpn)",
    }

    found: list[tuple[str, str]] = []
    traineddata_files = list(tess_path.glob("*.traineddata"))
    for file in sorted(traineddata_files, key=lambda f: f.name):
        code = file.stem
        if code == "osd":
            continue
        display_name = lang_names.get(code, f"{code.capitalize()} ({code})")
        found.append((code, display_name))

    if not found:
        return [("eng", "English (eng)")]

    # If multiple languages are available, add an Auto multi-language entry
    if len(found) > 1:
        combo_code = "+".join(c for c, _ in found)
        found.append((combo_code, "Multi-Language Auto (All Installed)"))

    return found


def preprocess_image_for_ocr(
    image: fitz.Pixmap | Image.Image | np.ndarray,
    deskew: bool = True,
    binarize: bool = False,
) -> tuple[fitz.Pixmap, float]:
    """Preprocess image with deskewing and contrast thresholding prior to OCR.

    Returns:
        (processed_pixmap, detected_skew_angle_degrees)
    """
    if isinstance(image, fitz.Pixmap):
        if image.alpha:
            clean_pix = fitz.Pixmap(image, 0)
        else:
            clean_pix = image
        img_np = np.frombuffer(clean_pix.samples, dtype=np.uint8).reshape(
            (clean_pix.height, clean_pix.width, clean_pix.n)
        )
        if clean_pix.n == 1:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
        elif clean_pix.n == 3:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        else:
            img_bgr = img_np
    elif isinstance(image, Image.Image):
        img_rgb = np.array(image.convert("RGB"))
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    elif isinstance(image, np.ndarray):
        img_bgr = image.copy()
        if len(img_bgr.shape) == 2:
            img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        raise TypeError(f"Unsupported image type: {type(image)}")

    detected_angle = 0.0

    # 1. Deskewing
    if deskew:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) >= 50:
            rect = cv2.minAreaRect(coords)
            raw_angle = rect[-1]
            if raw_angle < -45:
                angle = -(90 + raw_angle)
            elif raw_angle > 45:
                angle = 90 - raw_angle
            else:
                angle = -raw_angle

            if 0.5 <= abs(angle) <= 45.0:
                detected_angle = float(angle)
                (h, w) = img_bgr.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, detected_angle, 1.0)
                img_bgr = cv2.warpAffine(
                    img_bgr,
                    M,
                    (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )

    # 2. Contrast Binarization
    if binarize:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        img_bgr = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)

    _, png_buf = cv2.imencode(".png", img_bgr)
    processed_pix = fitz.Pixmap(png_buf.tobytes())
    return processed_pix, detected_angle


def generate_searchable_pdf(
    source: str | Path,
    output_path: str | Path,
    language: str = "eng",
    dpi: int = 300,
    deskew: bool = True,
    binarize: bool = False,
    tessdata_dir: str | Path | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Transform scanned documents or image collections into dual-layer searchable PDFs.

    Creates an output PDF with high-resolution visual scans on top and an invisible,
    selectable text layer underneath that can be searched using Ctrl+F.
    """
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    tess_path = get_tessdata_path(tessdata_dir)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(str(source_path)) as src_doc:
        if src_doc.is_encrypted and src_doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it before performing OCR.")

        total_pages = src_doc.page_count
        if total_pages < 1:
            raise ValueError("The document has no pages to process.")

        target_doc = fitz.open()
        try:
            for idx in range(total_pages):
                current_page_num = idx + 1
                if progress_callback:
                    progress_callback(
                        current_page_num,
                        total_pages,
                        f"Recognizing text on page {current_page_num} of {total_pages}...",
                    )

                page = src_doc[idx]
                pix = page.get_pixmap(dpi=dpi, alpha=False)

                if deskew or binarize:
                    pix, _ = preprocess_image_for_ocr(pix, deskew=deskew, binarize=binarize)

                ocr_bytes = pix.pdfocr_tobytes(language=language, tessdata=tess_path, compress=True)
                with fitz.open("pdf", ocr_bytes) as ocr_page_doc:
                    target_doc.insert_pdf(ocr_page_doc)

            if progress_callback:
                progress_callback(total_pages, total_pages, "Optimizing and writing searchable PDF...")

            target_doc.save(str(out), deflate=True, garbage=3)
            return out
        finally:
            target_doc.close()


def extract_document_ocr_text(
    source: str | Path,
    language: str = "eng",
    dpi: int = 150,
    deskew: bool = False,
    binarize: bool = False,
    format_type: str = "plain",
    tessdata_dir: str | Path | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> str:
    """Perform on-device OCR and return recognized text as plain text or formatted Markdown."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    tess_path = get_tessdata_path(tessdata_dir)

    with fitz.open(str(source_path)) as src_doc:
        if src_doc.is_encrypted and src_doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it before performing OCR.")

        total_pages = src_doc.page_count
        if total_pages < 1:
            raise ValueError("The document has no pages to process.")

        extracted_pages: list[str] = []
        for idx in range(total_pages):
            current_page_num = idx + 1
            if progress_callback:
                progress_callback(
                    current_page_num,
                    total_pages,
                    f"Extracting text from page {current_page_num} of {total_pages}...",
                )

            page = src_doc[idx]

            if not deskew and not binarize:
                tp = page.get_textpage_ocr(tessdata=tess_path, language=language, dpi=dpi, full=True)
                page_text = page.get_text(textpage=tp)
            else:
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                pix, _ = preprocess_image_for_ocr(pix, deskew=deskew, binarize=binarize)
                ocr_bytes = pix.pdfocr_tobytes(language=language, tessdata=tess_path, compress=True)
                with fitz.open("pdf", ocr_bytes) as ocr_doc:
                    page_text = ocr_doc[0].get_text()

            extracted_pages.append(page_text.strip())

    if format_type.lower() == "markdown":
        sections = [f"## Page {i + 1}\n\n{text}" for i, text in enumerate(extracted_pages) if text]
        return "\n\n---\n\n".join(sections)
    else:
        sections = [f"--- Page {i + 1} ---\n{text}" for i, text in enumerate(extracted_pages) if text]
        return "\n\n".join(sections)


def export_ocr_text_file(
    source: str | Path,
    output_path: str | Path,
    language: str = "eng",
    dpi: int = 150,
    deskew: bool = False,
    binarize: bool = False,
    format_type: str = "plain",
    tessdata_dir: str | Path | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Extract recognized document text and save to a local .txt or .md file."""
    text_content = extract_document_ocr_text(
        source=source,
        language=language,
        dpi=dpi,
        deskew=deskew,
        binarize=binarize,
        format_type=format_type,
        tessdata_dir=tessdata_dir,
        progress_callback=progress_callback,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text_content, encoding="utf-8")
    return out


# =============================================================================
# Phase 6: Permanent Redaction & Metadata Sanitizer
# =============================================================================

REDACTION_PATTERNS: dict[str, tuple[str, str]] = {
    "email": (
        "Email Addresses",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ),
    "phone": (
        "Phone Numbers",
        r"(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b",
    ),
    "ssn": (
        "SSN / National IDs",
        r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b",
    ),
    "credit_card": (
        "Credit Card Numbers",
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{4}[-\s]?\d{6}[-\s]?\d{5}\b",
    ),
}

_STANDARD_METADATA_KEYS = (
    "title",
    "author",
    "subject",
    "keywords",
    "creator",
    "producer",
    "creationDate",
    "modDate",
    "trapped",
)


@dataclass
class RedactionBox:
    """Single rectangular redaction region in PDF page point coordinates."""

    id: str
    page_index: int  # 0-based page index
    rect: tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF points
    label: str = "Manual Region"
    category: str = "manual"
    matched_text: str = ""
    enabled: bool = True


@dataclass
class PatternMatch:
    """Sensitive pattern match discovered on a PDF page."""

    id: str
    page_index: int  # 0-based page index
    category: str
    category_label: str
    matched_text: str
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    selected: bool = True


def _normalize_rect(rect: tuple[float, float, float, float] | fitz.Rect) -> tuple[float, float, float, float]:
    r = fitz.Rect(rect)
    r.normalize()
    return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))


def _find_match_rects_on_page(page: fitz.Page, matched_text: str) -> list[tuple[float, float, float, float]]:
    """Locate bounding rectangles for a matched string on a PDF page."""
    rects = page.search_for(matched_text)
    if rects:
        return [_normalize_rect(r) for r in rects]

    # Fallback: normalize whitespace and check word sequences if PDF layout split tokens
    target_norm = re.sub(r"\s+", "", matched_text)
    if not target_norm:
        return []

    words = page.get_text("words")  # (x0, y0, x1, y1, word, block_no, line_no, word_no)
    found: list[tuple[float, float, float, float]] = []
    n = len(words)
    for start in range(n):
        combined = ""
        union_rect: fitz.Rect | None = None
        for end in range(start, min(start + 12, n)):
            w_rect = fitz.Rect(words[end][:4])
            w_text = str(words[end][4])
            combined += w_text
            union_rect = w_rect if union_rect is None else (union_rect | w_rect)
            if combined == target_norm:
                found.append(_normalize_rect(union_rect))
                break
            if not target_norm.startswith(combined):
                break
    return found


def scan_pdf_patterns(
    source: str | Path,
    categories: list[str] | None = None,
    custom_regex: str | None = None,
    case_sensitive: bool = False,
) -> list[PatternMatch]:
    """Scan a PDF document for sensitive regex patterns and locate their page coordinates."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    active_categories = list(REDACTION_PATTERNS.keys()) if categories is None else list(categories)
    compiled_patterns: list[tuple[str, str, re.Pattern[str]]] = []
    flags = 0 if case_sensitive else re.IGNORECASE

    for cat in active_categories:
        if cat in REDACTION_PATTERNS:
            label, expr = REDACTION_PATTERNS[cat]
            compiled_patterns.append((cat, label, re.compile(expr, flags)))

    if custom_regex and custom_regex.strip():
        try:
            compiled_patterns.append(("custom", "Custom Pattern", re.compile(custom_regex.strip(), flags)))
        except re.error as err:
            raise ValueError(f"Invalid custom regex pattern: {err}") from err

    if not compiled_patterns:
        return []

    matches: list[PatternMatch] = []
    with fitz.open(str(source_path)) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it before scanning.")

        for page_index in range(doc.page_count):
            page = doc[page_index]
            page_text = page.get_text("text") or ""
            seen_on_page: set[tuple[str, str]] = set()

            for cat, cat_label, pattern in compiled_patterns:
                for m in pattern.finditer(page_text):
                    matched_str = m.group(0).strip()
                    if not matched_str:
                        continue
                    dedup_key = (cat, matched_str)
                    if dedup_key in seen_on_page:
                        continue
                    seen_on_page.add(dedup_key)

                    rects = _find_match_rects_on_page(page, matched_str)
                    if not rects:
                        continue
                    matches.append(
                        PatternMatch(
                            id=str(uuid.uuid4())[:8],
                            page_index=page_index,
                            category=cat,
                            category_label=cat_label,
                            matched_text=matched_str,
                            rects=rects,
                            selected=True,
                        )
                    )

    return matches


def _count_icc_profiles(doc: fitz.Document) -> list[int]:
    """Return xref numbers of ICCBased color profile streams in the document."""
    icc_xrefs: list[int] = []
    for xref in range(1, doc.xref_length()):
        try:
            obj_str = doc.xref_object(xref, compressed=False)
        except Exception:
            continue
        if "/ICCBased" in obj_str or ("/N " in obj_str and "/Alternate" in obj_str and doc.xref_is_stream(xref)):
            if doc.xref_is_stream(xref):
                n_val = doc.xref_get_key(xref, "N")
                if n_val[0] == "int" and n_val[1] in ("1", "3", "4"):
                    icc_xrefs.append(xref)
    return icc_xrefs


def _has_output_intents(doc: fitz.Document) -> bool:
    """Return True if PDF root catalog contains OutputIntents color profiles."""
    try:
        catalog_xref = doc.pdf_catalog()
        oi = doc.xref_get_key(catalog_xref, "OutputIntents")
        return oi[0] != "null"
    except Exception:
        return False


def _list_thumbnail_pages(doc: fitz.Document) -> list[int]:
    """Return 1-based page numbers that contain embedded /Thumb page thumbnails."""
    thumb_pages: list[int] = []
    for idx in range(doc.page_count):
        try:
            page_xref = doc[idx].xref
            thumb_key = doc.xref_get_key(page_xref, "Thumb")
            if thumb_key[0] != "null":
                thumb_pages.append(idx + 1)
        except Exception:
            continue
    return thumb_pages


def inspect_pdf_metadata(source: str | Path) -> dict:
    """Inspect standard Info dictionary, XMP packets, thumbnails, color profiles, and embedded files."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    with fitz.open(str(source_path)) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it first.")

        raw_meta = doc.metadata or {}
        info_fields = {
            k: str(raw_meta[k])
            for k in _STANDARD_METADATA_KEYS
            if raw_meta.get(k)
        }
        xmp_xml = ""
        try:
            xmp_xml = doc.get_xml_metadata() or ""
        except Exception:
            xmp_xml = ""

        thumb_pages = _list_thumbnail_pages(doc)
        has_output_intents = _has_output_intents(doc)
        icc_xrefs = _count_icc_profiles(doc)
        embedded_names = list(doc.embfile_names()) if hasattr(doc, "embfile_names") else []

        total_findings = (
            len(info_fields)
            + (1 if xmp_xml else 0)
            + len(thumb_pages)
            + (1 if has_output_intents else 0)
            + len(icc_xrefs)
            + len(embedded_names)
        )

        return {
            "info_fields": info_fields,
            "has_xmp": bool(xmp_xml),
            "xmp_bytes": len(xmp_xml.encode("utf-8")) if xmp_xml else 0,
            "thumbnail_pages": thumb_pages,
            "has_output_intents": has_output_intents,
            "icc_profile_count": len(icc_xrefs),
            "embedded_files": embedded_names,
            "total_findings": total_findings,
        }


def _strip_color_profiles(doc: fitz.Document) -> int:
    """Remove OutputIntents from catalog and replace ICCBased color spaces with device equivalents."""
    removed_count = 0
    try:
        catalog_xref = doc.pdf_catalog()
        oi = doc.xref_get_key(catalog_xref, "OutputIntents")
        if oi[0] != "null":
            doc.xref_set_key(catalog_xref, "OutputIntents", "null")
            removed_count += 1
    except Exception:
        pass

    # Map ICCBased streams to safe DeviceGray/DeviceRGB/DeviceCMYK where referenced in ColorSpace dicts
    icc_device_map: dict[int, str] = {}
    for xref in _count_icc_profiles(doc):
        n_val = doc.xref_get_key(xref, "N")
        if n_val[1] == "1":
            icc_device_map[xref] = "/DeviceGray"
        elif n_val[1] == "4":
            icc_device_map[xref] = "/DeviceCMYK"
        else:
            icc_device_map[xref] = "/DeviceRGB"

    if icc_device_map:
        for xref in range(1, doc.xref_length()):
            try:
                cs_key = doc.xref_get_key(xref, "ColorSpace")
            except Exception:
                continue
            if cs_key[0] == "array" and "/ICCBased" in cs_key[1]:
                for icc_xref, dev_space in icc_device_map.items():
                    if f"{icc_xref} 0 R" in cs_key[1]:
                        doc.xref_set_key(xref, "ColorSpace", dev_space)
                        removed_count += 1
                        break

    return removed_count


def _sanitize_open_document(
    doc: fitz.Document,
    remove_info: bool = True,
    remove_xmp: bool = True,
    remove_thumbnails: bool = True,
    remove_color_profiles: bool = True,
    remove_embedded_files: bool = True,
) -> dict:
    """Sanitize metadata in an open PyMuPDF document and return a detailed report of deleted fields."""
    raw_meta = doc.metadata or {}
    removed_info_fields = {
        k: str(raw_meta[k])
        for k in _STANDARD_METADATA_KEYS
        if remove_info and raw_meta.get(k)
    }

    xmp_xml = ""
    try:
        xmp_xml = doc.get_xml_metadata() or ""
    except Exception:
        xmp_xml = ""
    removed_xmp_bytes = len(xmp_xml.encode("utf-8")) if (remove_xmp and xmp_xml) else 0

    thumb_pages = _list_thumbnail_pages(doc) if remove_thumbnails else []
    embedded_names = list(doc.embfile_names()) if (remove_embedded_files and hasattr(doc, "embfile_names")) else []

    deleted_items: list[str] = []

    if remove_info:
        doc.set_metadata({})
        try:
            trailer_info = doc.xref_get_key(-1, "Info")
            if trailer_info[0] != "null":
                doc.xref_set_key(-1, "Info", "null")
        except Exception:
            pass
        for k, v in removed_info_fields.items():
            deleted_items.append(f"Info.{k}: {v}")

    if remove_xmp:
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
        try:
            catalog_xref = doc.pdf_catalog()
            if doc.xref_get_key(catalog_xref, "Metadata")[0] != "null":
                doc.xref_set_key(catalog_xref, "Metadata", "null")
        except Exception:
            pass
        if removed_xmp_bytes:
            deleted_items.append(f"XMP XML Metadata Packet ({removed_xmp_bytes} bytes)")

    if remove_thumbnails:
        for page_num in thumb_pages:
            try:
                doc.xref_set_key(doc[page_num - 1].xref, "Thumb", "null")
            except Exception:
                pass
        if thumb_pages:
            deleted_items.append(f"Embedded Page Thumbnails ({len(thumb_pages)} pages)")

    removed_color_profiles_count = 0
    if remove_color_profiles:
        removed_color_profiles_count = _strip_color_profiles(doc)
        if removed_color_profiles_count:
            deleted_items.append(f"Color Profiles / OutputIntents ({removed_color_profiles_count})")

    doc.scrub(
        attached_files=remove_embedded_files,
        clean_pages=False,
        embedded_files=remove_embedded_files,
        hidden_text=False,
        javascript=True,
        metadata=remove_info,
        redactions=False,
        remove_links=False,
        reset_fields=False,
        reset_responses=False,
        thumbnails=remove_thumbnails,
        xml_metadata=remove_xmp,
    )

    if embedded_names:
        deleted_items.append(f"Embedded Files ({len(embedded_names)}: {', '.join(embedded_names)})")

    return {
        "removed_info_fields": removed_info_fields,
        "removed_xmp": bool(removed_xmp_bytes),
        "removed_xmp_bytes": removed_xmp_bytes,
        "removed_thumbnails_count": len(thumb_pages),
        "removed_color_profiles_count": removed_color_profiles_count,
        "removed_embedded_files_count": len(embedded_names),
        "deleted_items": deleted_items,
    }


def sanitize_pdf_metadata(
    source: str | Path,
    output_path: str | Path,
    remove_info: bool = True,
    remove_xmp: bool = True,
    remove_thumbnails: bool = True,
    remove_color_profiles: bool = True,
    remove_embedded_files: bool = True,
) -> dict:
    """Purge document metadata, timestamps, XMP XML, embedded thumbnails, and color profiles."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(str(source_path)) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it before sanitizing.")

        report = _sanitize_open_document(
            doc,
            remove_info=remove_info,
            remove_xmp=remove_xmp,
            remove_thumbnails=remove_thumbnails,
            remove_color_profiles=remove_color_profiles,
            remove_embedded_files=remove_embedded_files,
        )
        doc.save(str(out), garbage=4, clean=True, deflate=True)

    report["output_path"] = str(out)
    return report


def apply_pdf_redactions(
    source: str | Path,
    output_path: str | Path,
    redactions: list[RedactionBox | dict],
    fill_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    redact_images: bool = True,
    sanitize_metadata: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Permanently redact specified regions from PDF streams and optionally sanitize metadata."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    active_boxes: list[RedactionBox] = []
    for item in redactions:
        if isinstance(item, RedactionBox):
            if item.enabled:
                active_boxes.append(item)
        elif isinstance(item, dict):
            if item.get("enabled", True):
                active_boxes.append(
                    RedactionBox(
                        id=str(item.get("id", str(uuid.uuid4())[:8])),
                        page_index=int(item["page_index"]),
                        rect=tuple(item["rect"]),  # type: ignore[arg-type]
                        label=str(item.get("label", "Redaction")),
                        category=str(item.get("category", "manual")),
                        matched_text=str(item.get("matched_text", "")),
                        enabled=True,
                    )
                )

    if not active_boxes and not sanitize_metadata:
        raise ValueError("No redaction regions or metadata sanitization options were selected.")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    by_page: dict[int, list[RedactionBox]] = {}
    for box in active_boxes:
        by_page.setdefault(box.page_index, []).append(box)

    with fitz.open(str(source_path)) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it before redacting.")

        total_pages = max(len(by_page), 1)
        pages_redacted = 0
        regions_applied = 0

        image_mode = fitz.PDF_REDACT_IMAGE_PIXELS if redact_images else fitz.PDF_REDACT_IMAGE_NONE

        for step, (page_idx, boxes) in enumerate(sorted(by_page.items()), start=1):
            if page_idx < 0 or page_idx >= doc.page_count:
                raise IndexError(f"Page index {page_idx} out of range (0..{doc.page_count - 1})")

            if progress_callback:
                progress_callback(step, total_pages, f"Applying permanent redactions to page {page_idx + 1}...")

            page = doc[page_idx]
            for box in boxes:
                r = fitz.Rect(box.rect)
                r.normalize()
                if r.width <= 0 or r.height <= 0:
                    continue
                page.add_redact_annot(r, fill=fill_color)
                regions_applied += 1

            page.apply_redactions(
                images=image_mode,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )
            pages_redacted += 1

        metadata_report = None
        if sanitize_metadata:
            if progress_callback:
                progress_callback(total_pages, total_pages, "Sanitizing document metadata & XMP streams...")
            metadata_report = _sanitize_open_document(doc)

        doc.save(str(out), garbage=4, clean=True, deflate=True)

    return {
        "output_path": str(out),
        "pages_redacted": pages_redacted,
        "regions_applied": regions_applied,
        "metadata_report": metadata_report,
    }


def verify_zero_leakage(
    redacted_pdf: str | Path,
    forbidden_strings: list[str],
) -> dict:
    """Verify that redacted strings cannot be extracted, searched, or found in PDF streams."""
    pdf_path = Path(redacted_pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Redacted PDF '{redacted_pdf}' not found.")

    clean_targets = [s for s in dict.fromkeys(forbidden_strings) if s and s.strip()]
    leaked: list[str] = []

    with fitz.open(str(pdf_path)) as doc:
        all_text_parts: list[str] = []
        for page in doc:
            all_text_parts.append(page.get_text("text") or "")
            word_tuples = page.get_text("words") or []
            all_text_parts.append(" ".join(str(w[4]) for w in word_tuples))
            for target in clean_targets:
                if page.search_for(target):
                    if target not in leaked:
                        leaked.append(target)

        joined_text = "\n".join(all_text_parts)
        for target in clean_targets:
            if target in joined_text and target not in leaked:
                leaked.append(target)

        # Also inspect uncompressed content streams for residual literal text
        for page in doc:
            for xref in page.get_contents():
                try:
                    stream_bytes = doc.xref_stream(xref) or b""
                except Exception:
                    continue
                for target in clean_targets:
                    if target.encode("utf-8", errors="ignore") in stream_bytes:
                        if target not in leaked:
                            leaked.append(target)

    return {
        "verified": len(leaked) == 0,
        "leaked_strings": leaked,
        "checked_count": len(clean_targets),
    }


def render_redaction_page_preview(
    source: str | Path,
    page_index: int = 0,
    max_width: int = 540,
    max_height: int = 620,
) -> dict:
    """Render a PDF page to PNG bytes alongside its canvas dimensions and PDF-point scale factor."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    with fitz.open(str(source_path)) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it first.")
        if page_index < 0 or page_index >= doc.page_count:
            raise IndexError(f"Page index {page_index} out of bounds (document has {doc.page_count} pages)")

        page = doc[page_index]
        rect = page.rect
        scale = min(max_width / max(rect.width, 1.0), max_height / max(rect.height, 1.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return {
            "png_bytes": pix.tobytes("png"),
            "canvas_width": float(pix.width),
            "canvas_height": float(pix.height),
            "page_width": float(rect.width),
            "page_height": float(rect.height),
            "scale": float(scale),
            "page_count": doc.page_count,
        }


# =============================================================================
# Phase 7: Digital Signatures & Stamp Studio Engine
# =============================================================================

STAMP_PRESETS: tuple[str, ...] = (
    "APPROVED",
    "CONFIDENTIAL",
    "DRAFT",
    "FINAL",
    "PAID",
    "REJECTED",
)

STAMP_COLORS: dict[str, tuple[str, str, tuple[int, int, int]]] = {
    "red": ("Classic Red", "#DC2626", (220, 38, 38)),
    "navy": ("Navy Blue", "#1E3A8A", (30, 58, 138)),
    "green": ("Forest Green", "#15803D", (21, 128, 61)),
    "slate": ("Charcoal Slate", "#334155", (51, 65, 85)),
}

STAMP_BORDER_STYLES: dict[str, str] = {
    "double": "Double Box",
    "solid": "Solid Frame",
    "rounded": "Rounded Badge",
    "dashed": "Dashed Seal",
}

SIGNATURE_INK_COLORS: dict[str, tuple[str, str, tuple[int, int, int]]] = {
    "black": ("Midnight Black", "#0F172A", (15, 23, 42)),
    "blue": ("Classic Blue", "#1D4ED8", (29, 78, 216)),
    "navy": ("Deep Navy", "#1E3A8A", (30, 58, 138)),
    "crimson": ("Crimson Ink", "#B91C1C", (185, 28, 28)),
}

_SIGNATURE_FONT_DEFINITIONS: list[dict] = [
    {
        "id": "chancery",
        "label": "Chancery Script",
        "description": "Flowing calligraphic chancery script",
        "fitz_fallback": "tiit",
        "candidates": [
            "/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf",
            "/usr/share/fonts/truetype/urw-base35/Z003-MediumItalic.ttf",
            "C:/Windows/Fonts/SCRIPTBL.TTF",
            "C:/Windows/Fonts/BRUSHSCI.TTF",
            "/System/Library/Fonts/Supplemental/SnellRoundhand.ttc",
            "/System/Library/Fonts/Supplemental/Zapfino.ttf",
        ],
    },
    {
        "id": "calligraphic",
        "label": "Calligraphic",
        "description": "Formal artistic pen calligraphy",
        "fitz_fallback": "tiit",
        "candidates": [
            "/usr/share/fonts/opentype/mathjax/MathJax_Caligraphic-Regular.otf",
            "/usr/share/fonts/opentype/urw-base35/URWBookman-DemiItalic.otf",
            "C:/Windows/Fonts/LHANDW.TTF",
            "C:/Windows/Fonts/ITCEDSCR.TTF",
            "/System/Library/Fonts/Supplemental/Apple Chancery.ttf",
        ],
    },
    {
        "id": "script",
        "label": "Editorial Script",
        "description": "Clean cursive manuscript lettering",
        "fitz_fallback": "tiit",
        "candidates": [
            "/usr/share/fonts/opentype/mathjax/MathJax_Script-Regular.otf",
            "/usr/share/fonts/opentype/urw-base35/C059-Italic.otf",
            "C:/Windows/Fonts/FREESCPT.TTF",
            "C:/Windows/Fonts/KUNSTLER.TTF",
            "/System/Library/Fonts/Supplemental/Brush Script.ttf",
        ],
    },
    {
        "id": "serif_italic",
        "label": "Classic Serif Italic",
        "description": "Executive italic serif signature",
        "fitz_fallback": "tibi",
        "candidates": [
            "/usr/share/fonts/opentype/urw-base35/P052-Italic.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            "C:/Windows/Fonts/georgiai.ttf",
            "C:/Windows/Fonts/timesi.ttf",
            "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
        ],
    },
]

_STAMP_BOLD_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


@dataclass
class PlacementItem:
    """Normalized signature or stamp overlay placed on a specific PDF page."""

    id: str
    page_index: int
    nx: float
    ny: float
    nw: float
    nh: float
    png_bytes: bytes
    label: str = "Signature"
    kind: str = "signature"  # "signature" | "initials" | "stamp"
    opacity: float = 1.0
    rotation: float = 0.0


def _parse_rgb_color(color: str | tuple[int, int, int]) -> tuple[int, int, int]:
    """Normalize a hex color string or RGB tuple into (r, g, b) ints."""
    if isinstance(color, tuple) and len(color) >= 3:
        return (int(color[0]), int(color[1]), int(color[2]))
    if isinstance(color, str):
        key = color.strip().lower()
        if key in SIGNATURE_INK_COLORS:
            return SIGNATURE_INK_COLORS[key][2]
        if key in STAMP_COLORS:
            return STAMP_COLORS[key][2]
        cleaned = key.lstrip("#")
        if len(cleaned) == 6:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16),
            )
    return (15, 23, 42)


def _find_first_existing_font(candidates: tuple[str, ...] | list[str]) -> str | None:
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def compute_quadratic_bezier_segments(
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float] | None, list[tuple[float, float, float, float]]]:
    """Convert raw pointer samples into midpoint quadratic Bezier segments.

    Returns ``(start_point, [(cp_x, cp_y, end_x, end_y), ...])``.
    For a 2-point stroke, the control point is the midpoint so the curve is linear.
    """
    if not points:
        return None, []
    start = (float(points[0][0]), float(points[0][1]))
    if len(points) == 1:
        return start, []
    if len(points) == 2:
        p1 = (float(points[1][0]), float(points[1][1]))
        cx = (start[0] + p1[0]) / 2.0
        cy = (start[1] + p1[1]) / 2.0
        return start, [(cx, cy, p1[0], p1[1])]

    segments: list[tuple[float, float, float, float]] = []
    for idx in range(1, len(points) - 1):
        px, py = float(points[idx][0]), float(points[idx][1])
        nx, ny = float(points[idx + 1][0]), float(points[idx + 1][1])
        mid_x = (px + nx) / 2.0
        mid_y = (py + ny) / 2.0
        segments.append((px, py, mid_x, mid_y))

    last_x, last_y = float(points[-1][0]), float(points[-1][1])
    prev_x, prev_y = float(points[-2][0]), float(points[-2][1])
    segments.append(((prev_x + last_x) / 2.0, (prev_y + last_y) / 2.0, last_x, last_y))
    return start, segments


def _evaluate_quadratic_bezier(
    p0: tuple[float, float],
    cp: tuple[float, float],
    p1: tuple[float, float],
    steps: int = 12,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        inv = 1.0 - t
        x = inv * inv * p0[0] + 2.0 * inv * t * cp[0] + t * t * p1[0]
        y = inv * inv * p0[1] + 2.0 * inv * t * cp[1] + t * t * p1[1]
        pts.append((x, y))
    return pts


def _crop_transparent_png(img: Image.Image, padding: int = 12) -> bytes:
    """Tightly crop an RGBA image to non-transparent bounds with padding and return PNG bytes."""
    rgba = img.convert("RGBA")
    bbox = rgba.getbbox()
    if bbox is None:
        raise ValueError("Rendered graphic contains no visible pixels.")
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(rgba.width, bbox[2] + padding)
    bottom = min(rgba.height, bbox[3] + padding)
    cropped = rgba.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def render_drawn_signature_png(
    strokes: list[list[tuple[float, float]]],
    canvas_width: float = 520.0,
    canvas_height: float = 180.0,
    stroke_width: float = 3.5,
    ink_color: str | tuple[int, int, int] = "#0F172A",
    padding: int = 16,
    scale: int = 2,
) -> bytes:
    """Rasterize smoothed quadratic-Bezier signature strokes into a transparent PNG."""
    valid_strokes = [s for s in strokes if s]
    if not valid_strokes:
        raise ValueError("Signature pad is empty. Draw your signature first.")

    r, g, b = _parse_rgb_color(ink_color)
    rgba_ink = (r, g, b, 255)
    w = max(int(math.ceil(canvas_width * scale)), 32)
    h = max(int(math.ceil(canvas_height * scale)), 32)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scaled_width = max(int(round(stroke_width * scale)), 2)
    radius = scaled_width / 2.0

    for raw_stroke in valid_strokes:
        scaled_pts = [(float(x) * scale, float(y) * scale) for x, y in raw_stroke]
        start, segments = compute_quadratic_bezier_segments(scaled_pts)
        if start is None:
            continue
        if not segments:
            draw.ellipse(
                [start[0] - radius, start[1] - radius, start[0] + radius, start[1] + radius],
                fill=rgba_ink,
            )
            continue

        dense_pts: list[tuple[float, float]] = [start]
        cur = start
        for cpx, cpy, ex, ey in segments:
            seg_pts = _evaluate_quadratic_bezier(cur, (cpx, cpy), (ex, ey), steps=10)
            dense_pts.extend(seg_pts[1:])
            cur = (ex, ey)

        draw.line(dense_pts, fill=rgba_ink, width=scaled_width, joint="curve")
        for pt in (dense_pts[0], dense_pts[-1]):
            draw.ellipse(
                [pt[0] - radius, pt[1] - radius, pt[0] + radius, pt[1] + radius],
                fill=rgba_ink,
            )

    return _crop_transparent_png(img, padding=padding)


def remove_signature_background(
    source: str | Path | bytes,
    threshold: int = 220,
    feather: int = 28,
    ink_tint: tuple[int, int, int] | None = None,
) -> bytes:
    """Remove bright/white paper backgrounds from an uploaded signature image via PIL/NumPy."""
    if isinstance(source, (str, Path)):
        src_path = Path(source)
        if not src_path.exists():
            raise FileNotFoundError(f"Signature image '{source}' not found.")
        img = Image.open(str(src_path)).convert("RGBA")
    elif isinstance(source, (bytes, bytearray)):
        img = Image.open(io.BytesIO(bytes(source))).convert("RGBA")
    else:
        raise TypeError("source must be a file path or image bytes")

    arr = np.array(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    # Perceived luminance + low-chroma check preserves colored ink while erasing paper
    lum = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    chroma = np.max(rgb, axis=2) - np.min(rgb, axis=2)
    is_paper_hue = chroma <= 55.0

    thresh = float(max(100, min(254, threshold)))
    feath = float(max(1, feather))
    low = thresh - feath

    # Fully transparent above threshold; smooth linear ramp in [low, thresh]
    factor = np.ones_like(lum, dtype=np.float32)
    ramp_mask = is_paper_hue & (lum >= low) & (lum < thresh)
    factor[ramp_mask] = (thresh - lum[ramp_mask]) / feath
    factor[is_paper_hue & (lum >= thresh)] = 0.0

    new_alpha = np.clip(alpha * factor, 0.0, 255.0)
    arr[:, :, 3] = new_alpha

    if ink_tint is not None:
        ink_mask = new_alpha > 8.0
        arr[ink_mask, 0] = float(ink_tint[0])
        arr[ink_mask, 1] = float(ink_tint[1])
        arr[ink_mask, 2] = float(ink_tint[2])

    cleaned = Image.fromarray(arr.astype(np.uint8), mode="RGBA")
    return _crop_transparent_png(cleaned, padding=10)


def get_available_signature_fonts() -> list[dict[str, str]]:
    """Return cursive/script typography presets with resolved local font paths when available."""
    results: list[dict[str, str]] = []
    for entry in _SIGNATURE_FONT_DEFINITIONS:
        resolved = _find_first_existing_font(entry["candidates"]) or ""
        results.append(
            {
                "id": entry["id"],
                "label": entry["label"],
                "description": entry["description"],
                "font_path": resolved,
            }
        )
    return results


def render_typed_signature_png(
    text: str,
    font_style: str = "chancery",
    ink_color: str | tuple[int, int, int] = "#0F172A",
    font_size: int = 92,
) -> bytes:
    """Render a typed name into a transparent cursive signature PNG."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Please enter your name to generate a typed signature.")

    r, g, b = _parse_rgb_color(ink_color)
    profile = next((f for f in _SIGNATURE_FONT_DEFINITIONS if f["id"] == font_style), _SIGNATURE_FONT_DEFINITIONS[0])
    font_path = _find_first_existing_font(profile["candidates"])

    if font_path:
        font = ImageFont.truetype(font_path, font_size)
        probe = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        probe_draw = ImageDraw.Draw(probe)
        bbox = probe_draw.textbbox((0, 0), cleaned, font=font)
        tw = max(bbox[2] - bbox[0], 20)
        th = max(bbox[3] - bbox[1], 20)
        pad = 24
        canvas = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((pad - bbox[0], pad - bbox[1]), cleaned, font=font, fill=(r, g, b, 255))
        return _crop_transparent_png(canvas, padding=10)

    # Portable PyMuPDF built-in italic serif fallback if no OS cursive font exists
    with fitz.open() as tmp_doc:
        width_pt = max(len(cleaned) * font_size * 0.72 + 80.0, 240.0)
        height_pt = float(font_size * 2.0)
        page = tmp_doc.new_page(width=width_pt, height=height_pt)
        page.insert_text(
            fitz.Point(28.0, font_size * 1.25),
            cleaned,
            fontname=profile.get("fitz_fallback", "tiit"),
            fontsize=float(font_size),
            color=(r / 255.0, g / 255.0, b / 255.0),
        )
        pix = page.get_pixmap(alpha=True)
        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
        return _crop_transparent_png(img, padding=10)


def _load_stamp_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = _find_first_existing_font(_STAMP_BOLD_FONT_CANDIDATES)
    if font_path:
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()


def render_stamp_image(
    text: str = "APPROVED",
    color_key: str = "red",
    border_style: str = "double",
    include_date: bool = True,
    include_time: bool = False,
    operator_name: str = "",
    custom_subtext: str = "",
    rotation: float = -12.0,
    opacity: float = 0.92,
    timestamp: datetime | None = None,
) -> bytes:
    """Render an official customizable rubber stamp to high-resolution transparent PNG bytes."""
    main_text = (text or "").strip().upper()
    if not main_text:
        raise ValueError("Stamp text cannot be empty.")

    r, g, b = _parse_rgb_color(color_key)
    op = max(0.15, min(1.0, float(opacity)))
    alpha_full = int(round(255 * op))
    ink = (r, g, b, alpha_full)
    tint_bg = (r, g, b, int(round(22 * op)))

    now = timestamp or datetime.now()
    meta_parts: list[str] = []
    if include_date:
        meta_parts.append(now.strftime("%Y-%m-%d"))
    if include_time:
        meta_parts.append(now.strftime("%H:%M"))
    if operator_name.strip():
        meta_parts.append(operator_name.strip().upper())

    sub_lines: list[str] = []
    if custom_subtext.strip():
        sub_lines.append(custom_subtext.strip().upper())
    if meta_parts:
        sub_lines.append(" • ".join(meta_parts))

    main_font = _load_stamp_font(44)
    sub_font = _load_stamp_font(17)

    probe = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(probe)
    main_bbox = pdraw.textbbox((0, 0), main_text, font=main_font)
    main_w = main_bbox[2] - main_bbox[0]
    main_h = main_bbox[3] - main_bbox[1]

    sub_bboxes = [pdraw.textbbox((0, 0), line, font=sub_font) for line in sub_lines]
    sub_widths = [bb[2] - bb[0] for bb in sub_bboxes]
    sub_heights = [bb[3] - bb[1] for bb in sub_bboxes]

    content_w = max([main_w, *sub_widths, 180])
    pad_x = 34
    pad_y = 22
    line_gap = 10
    total_sub_h = sum(sub_heights) + (line_gap * len(sub_lines))
    divider_space = 14 if sub_lines else 0

    box_w = content_w + pad_x * 2
    box_h = main_h + total_sub_h + divider_space + pad_y * 2

    margin = 16
    canvas = Image.new("RGBA", (box_w + margin * 2, box_h + margin * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    x0, y0 = margin, margin
    x1, y1 = margin + box_w, margin + box_h

    style_key = border_style.lower().strip()
    if style_key == "rounded":
        draw.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=tint_bg, outline=ink, width=5)
        draw.rounded_rectangle([x0 + 7, y0 + 7, x1 - 7, y1 - 7], radius=12, outline=ink, width=2)
    elif style_key == "solid":
        draw.rectangle([x0, y0, x1, y1], fill=tint_bg, outline=ink, width=6)
    elif style_key == "dashed":
        draw.rectangle([x0, y0, x1, y1], fill=tint_bg)
        dash = 14
        gap = 8
        for sx in range(x0, x1, dash + gap):
            draw.line([(sx, y0), (min(sx + dash, x1), y0)], fill=ink, width=5)
            draw.line([(sx, y1), (min(sx + dash, x1), y1)], fill=ink, width=5)
        for sy in range(y0, y1, dash + gap):
            draw.line([(x0, sy), (x0, min(sy + dash, y1))], fill=ink, width=5)
            draw.line([(x1, sy), (x1, min(sy + dash, y1))], fill=ink, width=5)
    else:  # "double" default
        draw.rectangle([x0, y0, x1, y1], fill=tint_bg, outline=ink, width=5)
        draw.rectangle([x0 + 8, y0 + 8, x1 - 8, y1 - 8], outline=ink, width=2)

    cur_y = y0 + pad_y
    main_x = x0 + (box_w - main_w) // 2 - main_bbox[0]
    draw.text((main_x, cur_y - main_bbox[1]), main_text, font=main_font, fill=ink)
    cur_y += main_h

    if sub_lines:
        cur_y += 8
        draw.line([(x0 + 20, cur_y), (x1 - 20, cur_y)], fill=ink, width=2)
        cur_y += 6
        for line, bb, lw, lh in zip(sub_lines, sub_bboxes, sub_widths, sub_heights):
            cur_y += line_gap // 2
            lx = x0 + (box_w - lw) // 2 - bb[0]
            draw.text((lx, cur_y - bb[1]), line, font=sub_font, fill=ink)
            cur_y += lh + line_gap // 2

    if abs(float(rotation)) > 0.05:
        canvas = canvas.rotate(-float(rotation), resample=Image.Resampling.BICUBIC, expand=True)

    return _crop_transparent_png(canvas, padding=8)


def get_signature_vault_dir(vault_dir: str | Path | None = None) -> Path:
    """Return and ensure the local directory storing saved signatures."""
    target = Path(vault_dir) if vault_dir else (Path.home() / "Documents" / "PDF-OPS" / ".signature_vault")
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_signature_to_vault(
    png_bytes: bytes,
    name: str,
    kind: str = "drawn",
    vault_dir: str | Path | None = None,
) -> dict:
    """Persist a signature PNG and metadata entry into the local signature vault."""
    if not png_bytes:
        raise ValueError("Cannot save an empty signature to the vault.")
    with Image.open(io.BytesIO(png_bytes)) as verified_img:
        verified_img.verify()

    vdir = get_signature_vault_dir(vault_dir)
    index_path = vdir / "vault_index.json"
    entries: list[dict] = []
    if index_path.exists():
        try:
            entries = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            entries = []

    sig_id = str(uuid.uuid4())[:10]
    png_path = vdir / f"sig_{sig_id}.png"
    png_path.write_bytes(png_bytes)

    entry = {
        "id": sig_id,
        "name": (name or "").strip() or f"Signature {len(entries) + 1}",
        "kind": kind,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": png_path.name,
    }
    entries.insert(0, entry)
    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    return {**entry, "png_path": str(png_path)}


def list_vault_signatures(vault_dir: str | Path | None = None) -> list[dict]:
    """List saved signatures available in the local signature vault."""
    vdir = get_signature_vault_dir(vault_dir)
    index_path = vdir / "vault_index.json"
    if not index_path.exists():
        return []
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    valid_entries: list[dict] = []
    for item in entries:
        png_path = vdir / str(item.get("filename", ""))
        if png_path.exists():
            valid_entries.append({**item, "png_path": str(png_path)})
    return valid_entries


def load_vault_signature_bytes(sig_id: str, vault_dir: str | Path | None = None) -> bytes:
    """Load raw PNG bytes for a signature stored in the local vault."""
    for entry in list_vault_signatures(vault_dir):
        if entry["id"] == sig_id:
            return Path(entry["png_path"]).read_bytes()
    raise FileNotFoundError(f"Vault signature '{sig_id}' was not found.")


def delete_vault_signature(sig_id: str, vault_dir: str | Path | None = None) -> bool:
    """Delete a signature from the local vault index and disk."""
    vdir = get_signature_vault_dir(vault_dir)
    index_path = vdir / "vault_index.json"
    if not index_path.exists():
        return False
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    kept: list[dict] = []
    removed = False
    for item in entries:
        if item.get("id") == sig_id:
            removed = True
            png_path = vdir / str(item.get("filename", ""))
            if png_path.exists():
                png_path.unlink(missing_ok=True)
        else:
            kept.append(item)

    if removed:
        index_path.write_text(json.dumps(kept, indent=2), encoding="utf-8")
    return removed


def build_multipage_placements(
    page_count: int,
    mode: str,
    primary_png: bytes,
    secondary_png: bytes | None = None,
    primary_rect: tuple[float, float, float, float] = (0.68, 0.84, 0.24, 0.09),
    secondary_rect: tuple[float, float, float, float] = (0.78, 0.88, 0.14, 0.06),
    page_range: str = "",
    primary_label: str = "Signature",
    secondary_label: str = "Initials",
    kind: str = "signature",
    opacity: float = 1.0,
) -> list[PlacementItem]:
    """Generate normalized multi-page placements for common contract signing workflows."""
    if page_count < 1:
        raise ValueError("Document has no pages.")
    if not primary_png:
        raise ValueError("Primary signature or stamp image is required.")

    norm_mode = mode.strip().lower()
    items: list[PlacementItem] = []

    def _clamp_box(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        nx = max(0.0, min(0.95, float(rect[0])))
        ny = max(0.0, min(0.95, float(rect[1])))
        nw = max(0.04, min(1.0 - nx, float(rect[2])))
        nh = max(0.03, min(1.0 - ny, float(rect[3])))
        return nx, ny, nw, nh

    pnx, pny, pnw, pnh = _clamp_box(primary_rect)
    snx, sny, snw, snh = _clamp_box(secondary_rect)

    if norm_mode == "all_pages":
        for p_idx in range(page_count):
            items.append(
                PlacementItem(
                    id=str(uuid.uuid4())[:8],
                    page_index=p_idx,
                    nx=pnx,
                    ny=pny,
                    nw=pnw,
                    nh=pnh,
                    png_bytes=primary_png,
                    label=primary_label,
                    kind=kind,
                    opacity=opacity,
                )
            )
    elif norm_mode == "final_page":
        items.append(
            PlacementItem(
                id=str(uuid.uuid4())[:8],
                page_index=page_count - 1,
                nx=pnx,
                ny=pny,
                nw=pnw,
                nh=pnh,
                png_bytes=primary_png,
                label=primary_label,
                kind=kind,
                opacity=opacity,
            )
        )
    elif norm_mode == "initial_all_sign_last":
        init_png = secondary_png or primary_png
        for p_idx in range(page_count - 1):
            items.append(
                PlacementItem(
                    id=str(uuid.uuid4())[:8],
                    page_index=p_idx,
                    nx=snx,
                    ny=sny,
                    nw=snw,
                    nh=snh,
                    png_bytes=init_png,
                    label=secondary_label,
                    kind="initials",
                    opacity=opacity,
                )
            )
        items.append(
            PlacementItem(
                id=str(uuid.uuid4())[:8],
                page_index=page_count - 1,
                nx=pnx,
                ny=pny,
                nw=pnw,
                nh=pnh,
                png_bytes=primary_png,
                label=primary_label,
                kind=kind,
                opacity=opacity,
            )
        )
    elif norm_mode == "custom_range":
        target_pages = [p - 1 for p in dict.fromkeys(parse_page_ranges(page_range, page_count))]
        for p_idx in target_pages:
            items.append(
                PlacementItem(
                    id=str(uuid.uuid4())[:8],
                    page_index=p_idx,
                    nx=pnx,
                    ny=pny,
                    nw=pnw,
                    nh=pnh,
                    png_bytes=primary_png,
                    label=primary_label,
                    kind=kind,
                    opacity=opacity,
                )
            )
    else:
        raise ValueError(f"Unsupported multi-page mode '{mode}'.")

    return items


def _apply_opacity_and_rotation(
    png_bytes: bytes,
    opacity: float = 1.0,
    rotation: float = 0.0,
) -> bytes:
    """Apply overlay opacity and rotation cleanly to an RGBA PNG buffer."""
    op = max(0.05, min(1.0, float(opacity)))
    if op >= 0.999 and abs(float(rotation)) <= 0.05:
        return png_bytes

    with Image.open(io.BytesIO(png_bytes)) as img:
        rgba = img.convert("RGBA")
        if op < 0.999:
            arr = np.array(rgba, dtype=np.float32)
            arr[:, :, 3] = np.clip(arr[:, :, 3] * op, 0.0, 255.0)
            rgba = Image.fromarray(arr.astype(np.uint8), mode="RGBA")
        if abs(float(rotation)) > 0.05:
            rgba = rgba.rotate(-float(rotation), resample=Image.Resampling.BICUBIC, expand=True)
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        return buf.getvalue()


def _compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def verify_signed_pdf_integrity(pdf_path: str | Path) -> dict:
    """Compute a local SHA-256 integrity fingerprint and summarize embedded visual graphics."""
    target = Path(pdf_path)
    if not target.exists():
        raise FileNotFoundError(f"PDF file '{pdf_path}' not found.")

    sha256 = _compute_file_sha256(target)
    with fitz.open(str(target)) as doc:
        image_count = sum(len(page.get_images(full=True)) for page in doc)
        return {
            "path": str(target),
            "sha256": sha256,
            "page_count": doc.page_count,
            "embedded_image_count": image_count,
            "is_encrypted": bool(doc.is_encrypted),
        }


def apply_signatures_and_stamps(
    source: str | Path,
    output_path: str | Path,
    placements: list[PlacementItem | dict],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Embed signature and stamp PNG overlays onto exact normalized PDF coordinates."""
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source}' not found.")

    normalized_items: list[PlacementItem] = []
    for raw in placements:
        if isinstance(raw, PlacementItem):
            normalized_items.append(raw)
        elif isinstance(raw, dict):
            normalized_items.append(
                PlacementItem(
                    id=str(raw.get("id", str(uuid.uuid4())[:8])),
                    page_index=int(raw["page_index"]),
                    nx=float(raw["nx"]),
                    ny=float(raw["ny"]),
                    nw=float(raw["nw"]),
                    nh=float(raw["nh"]),
                    png_bytes=bytes(raw["png_bytes"]),
                    label=str(raw.get("label", "Signature")),
                    kind=str(raw.get("kind", "signature")),
                    opacity=float(raw.get("opacity", 1.0)),
                    rotation=float(raw.get("rotation", 0.0)),
                )
            )

    if not normalized_items:
        raise ValueError("No signature or stamp placements were provided.")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sha_before = _compute_file_sha256(source_path)

    by_page: dict[int, list[PlacementItem]] = {}
    for item in normalized_items:
        by_page.setdefault(item.page_index, []).append(item)

    with fitz.open(str(source_path)) as doc:
        if doc.is_encrypted and doc.needs_pass:
            raise ValueError(f"Document '{source_path.name}' is password protected. Decrypt it before signing.")

        total_pages = max(len(by_page), 1)
        placements_applied = 0

        for step, (page_idx, page_items) in enumerate(sorted(by_page.items()), start=1):
            if page_idx < 0 or page_idx >= doc.page_count:
                raise IndexError(f"Page index {page_idx} out of range (0..{doc.page_count - 1})")

            if progress_callback:
                progress_callback(step, total_pages, f"Embedding signatures & stamps on page {page_idx + 1}...")

            page = doc[page_idx]
            page_rect = page.rect
            pw, ph = float(page_rect.width), float(page_rect.height)

            for item in page_items:
                x0 = max(0.0, min(item.nx, 0.99)) * pw
                y0 = max(0.0, min(item.ny, 0.99)) * ph
                x1 = min(pw, x0 + max(0.02, item.nw) * pw)
                y1 = min(ph, y0 + max(0.02, item.nh) * ph)
                target_rect = fitz.Rect(x0, y0, max(x0 + 4.0, x1), max(y0 + 4.0, y1))

                final_png = _apply_opacity_and_rotation(
                    item.png_bytes,
                    opacity=item.opacity,
                    rotation=item.rotation,
                )
                page.insert_image(
                    target_rect,
                    stream=final_png,
                    keep_proportion=True,
                    overlay=True,
                )
                placements_applied += 1

        doc.save(str(out), garbage=3, deflate=True)

    sha_after = _compute_file_sha256(out)
    return {
        "output_path": str(out),
        "pages_signed": len(by_page),
        "placements_applied": placements_applied,
        "sha256_before": sha_before,
        "sha256_after": sha_after,
    }



