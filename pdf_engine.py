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

