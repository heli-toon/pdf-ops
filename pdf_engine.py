"""Testable local PDF operations used by the Flet controllers.

The functions in this module do not depend on Flet. They intentionally keep
all files on the local machine and raise useful exceptions for the UI to show.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from collections.abc import Callable

import cv2
import numpy as np
from PIL import Image
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


