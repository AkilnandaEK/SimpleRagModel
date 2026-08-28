"""
app/services/chunker.py
-----------------------

Hierarchical structure-aware PDF extraction and chunking.

Pipeline:

    PDF bytes
        ↓
    PDF lines with layout/font information
        ↓
    Detect parent & child headings
        ↓
    Build hierarchical document structure
        ↓
    Parent heading + child heading + content
        ↓
    Semantic chunks (ChunkText objects with attached metadata)
        ↓
    list[ChunkText]

Example document structure:

    5. Vegetable Fried Rice
        Ingredients
            3 cups cold cooked rice
            1 cup diced carrots and beans
            ...

        Method
            1. Heat a wok or large pan until hot.
            2. Scramble the eggs quickly.
            ...

The important property of this implementation is that child sections
always retain their parent context.

Therefore a Method chunk becomes:

    Recipe: 5. Vegetable Fried Rice
    Section: Method

    1. Heat a wok...
    2. Scramble the eggs...
    ...
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import fitz  # PyMuPDF


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150

# Heading font size multiplier relative to body font
HEADING_FONT_RATIO = 1.15

# Maximum character length for a standalone heading title
MAX_HEADING_LENGTH = 150


# Common subsection labels.
KNOWN_SUBSECTIONS = {
    "ingredients",
    "method",
    "methods",
    "directions",
    "instructions",
    "preparation",
    "procedure",
    "steps",
    "cooking method",
    "cooking instructions",
    "preparation method",
}


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

class ChunkText(str):
    """
    String subclass that attaches structured metadata to chunk strings,
    ensuring 100% backwards compatibility with callers expecting list[str].
    """
    metadata: dict

    def __new__(cls, content: str, metadata: dict | None = None):
        obj = super().__new__(cls, content)
        obj.metadata = metadata or {}
        return obj


@dataclass
class PDFLine:
    """
    Represents a single text line extracted from a PDF page with layout details.
    """
    page: int
    text: str
    font_size: float
    is_bold: bool
    bbox: tuple[float, float, float, float]


@dataclass
class PDFBlock:
    """
    Represents a text block (kept for backward compatibility).
    """
    page: int
    text: str
    font_size: float
    is_bold: bool
    bbox: tuple[float, float, float, float]


@dataclass
class DocumentNode:
    """
    Represents a hierarchical section node in the parsed document.
    """
    title: str
    level: int
    page_start: int
    page_end: int
    paragraphs: list[str] = field(default_factory=list)
    parent_title: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Line-level PDF extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_pdf_lines(pdf_bytes: bytes) -> list[PDFLine]:
    """
    Extract text lines from PDF while preserving fine-grained span/font
    information (font size, bold flag, bounding box, page number).
    """
    lines: list[PDFLine] = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_num, page in enumerate(doc, start=1):
            page_data = page.get_text("dict", sort=True)

            for block in page_data.get("blocks", []):
                # Type 0 = text block
                if block.get("type") != 0:
                    continue

                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue

                    line_text = "".join(span.get("text", "") for span in spans).strip()
                    if not line_text:
                        continue

                    font_sizes = [
                        float(span.get("size", 0))
                        for span in spans
                        if span.get("size") is not None
                    ]
                    max_font_size = max(font_sizes) if font_sizes else 9.5

                    # Bold check: PyMuPDF flag 16 or font name containing "bold"
                    is_bold = any(
                        (int(span.get("flags", 0)) & 16)
                        or ("bold" in str(span.get("font", "")).lower())
                        for span in spans
                    )

                    bbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))

                    lines.append(
                        PDFLine(
                            page=page_num,
                            text=line_text,
                            font_size=max_font_size,
                            is_bold=is_bold,
                            bbox=(
                                float(bbox[0]),
                                float(bbox[1]),
                                float(bbox[2]),
                                float(bbox[3]),
                            ),
                        )
                    )

    return lines


def extract_pdf_blocks(pdf_bytes: bytes) -> list[PDFBlock]:
    """
    Backward-compatible helper returning PDFBlock instances.
    """
    lines = extract_pdf_lines(pdf_bytes)
    return [
        PDFBlock(
            page=line.page,
            text=line.text,
            font_size=line.font_size,
            is_bold=line.is_bold,
            bbox=line.bbox,
        )
        for line in lines
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Font analysis
# ─────────────────────────────────────────────────────────────────────────────

def detect_body_font_size(lines: list[PDFLine] | list[PDFBlock]) -> float:
    """
    Detect the most common font size across extracted elements.
    """
    if not lines:
        return 9.5

    font_sizes = [round(item.font_size, 1) for item in lines]
    counts = Counter(font_sizes)
    return float(counts.most_common(1)[0][0])


# ─────────────────────────────────────────────────────────────────────────────
# Heading classification helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_known_subsection(text: str) -> bool:
    return _normalise_heading(text) in KNOWN_SUBSECTIONS


def _is_numbered_title(text: str) -> bool:
    """
    Detect standalone numbered title headings like:
    '5. Vegetable Fried Rice'
    '1. South Indian Vegetable Sambar'
    """
    stripped = text.strip()
    match = re.match(r"^\d+[\.\)]\s+(.+)$", stripped)
    if not match:
        return False
    rest = match.group(1).strip()
    return len(rest.split()) <= 15


def is_heading_candidate(line: PDFLine, body_font_size: float) -> bool:
    text = line.text.strip()
    if not text or len(text) > MAX_HEADING_LENGTH:
        return False

    if _is_known_subsection(text):
        return True

    if line.font_size >= body_font_size * HEADING_FONT_RATIO:
        return True

    if line.is_bold and _is_numbered_title(text):
        return True

    return False


def determine_heading_level(line: PDFLine, body_font_size: float) -> int:
    text = line.text.strip()
    if _is_known_subsection(text):
        return 2

    if line.font_size >= body_font_size * HEADING_FONT_RATIO or _is_numbered_title(text):
        return 1

    return 2


# ─────────────────────────────────────────────────────────────────────────────
# Document hierarchy construction
# ─────────────────────────────────────────────────────────────────────────────

def build_document_hierarchy(lines: list[PDFLine]) -> list[DocumentNode]:
    """
    Build a hierarchical representation of document sections.
    """
    if not lines:
        return []

    body_font_size = detect_body_font_size(lines)
    nodes: list[DocumentNode] = []

    current_parent: DocumentNode | None = None
    current_child: DocumentNode | None = None

    for line in lines:
        text = line.text.strip()
        if not text:
            continue

        # 1. Known subsection label (Level 2 child heading)
        if _is_known_subsection(text):
            parent_title = current_parent.title if current_parent else None
            current_child = DocumentNode(
                title=text,
                level=2,
                page_start=line.page,
                page_end=line.page,
                paragraphs=[],
                parent_title=parent_title,
            )
            nodes.append(current_child)
            continue

        # 2. Parent Heading (Level 1)
        is_parent = False
        if line.font_size >= body_font_size * 1.15:
            is_parent = True
        elif line.is_bold and line.font_size > body_font_size and _is_numbered_title(text):
            is_parent = True
        elif line.is_bold and _is_numbered_title(text) and not (current_child and _is_known_subsection(current_child.title) and not line.is_bold):
            is_parent = True

        if is_parent:
            current_parent = DocumentNode(
                title=text,
                level=1,
                page_start=line.page,
                page_end=line.page,
                paragraphs=[],
                parent_title=None,
            )
            nodes.append(current_parent)
            current_child = None
            continue

        # 3. Content body line (paragraphs or list items under active section)
        target_node = current_child or current_parent
        if target_node is None:
            synthetic = DocumentNode(
                title="Document",
                level=1,
                page_start=line.page,
                page_end=line.page,
                paragraphs=[text],
                parent_title=None,
            )
            nodes.append(synthetic)
            current_parent = synthetic
        else:
            target_node.paragraphs.append(text)
            target_node.page_end = line.page

    return nodes


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchical context formatting
# ─────────────────────────────────────────────────────────────────────────────

def build_node_context(node: DocumentNode) -> str:
    """
    Format parent-child context header for a chunk.
    """
    if node.level == 1:
        if node.title == "Document":
            return "Document"
        if re.match(r"^\d+[\.\)]\s+", node.title):
            return f"Recipe: {node.title}"
        return f"Section: {node.title}"

    if node.level == 2:
        parent_prefix = (
            "Recipe"
            if (node.parent_title and re.match(r"^\d+[\.\)]\s+", node.parent_title))
            else "Section"
        )
        if node.parent_title:
            return f"{parent_prefix}: {node.parent_title}\nSection: {node.title}"
        return f"Section: {node.title}"

    return f"Parent Section: {node.parent_title}\nSection: {node.title}"


# ─────────────────────────────────────────────────────────────────────────────
# Oversized text splitting helper
# ─────────────────────────────────────────────────────────────────────────────

def _split_large_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) > 1:
        return _merge_text_parts(sentences, separator=" ", chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    words = text.split()
    if len(words) > 1:
        return _merge_text_parts(words, separator=" ", chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    step = max(1, chunk_size - chunk_overlap)
    return [text[i : i + chunk_size] for i in range(0, len(text), step)]


def _merge_text_parts(
    parts: list[str],
    separator: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_len = len(part)

        if part_len > chunk_size:
            if current_parts:
                chunks.append(separator.join(current_parts).strip())
                current_parts = []
                current_length = 0
            chunks.extend(_split_large_text(part, chunk_size, chunk_overlap))
            continue

        add_len = part_len if not current_parts else len(separator) + part_len

        if current_parts and current_length + add_len > chunk_size:
            chunks.append(separator.join(current_parts).strip())
            overlap_parts: list[str] = []
            overlap_len = 0

            for prev in reversed(current_parts):
                req_len = len(prev) if not overlap_parts else len(separator) + len(prev)
                if overlap_len + req_len > chunk_overlap:
                    break
                overlap_parts.insert(0, prev)
                overlap_len += req_len

            current_parts = overlap_parts
            current_length = sum(len(p) for p in current_parts) + (
                len(separator) * max(0, len(current_parts) - 1)
            )

        current_parts.append(part)
        current_length = sum(len(p) for p in current_parts) + (
            len(separator) * max(0, len(current_parts) - 1)
        )

    if current_parts:
        chunks.append(separator.join(current_parts).strip())

    return [c for c in chunks if c.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchical chunk generation
# ─────────────────────────────────────────────────────────────────────────────

def create_hierarchical_chunks(
    nodes: list[DocumentNode],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkText]:
    """
    Generate ChunkText instances with hierarchical context headers and metadata.
    """
    chunks: list[ChunkText] = []

    for node in nodes:
        if not node.paragraphs:
            continue

        context_header = build_node_context(node)
        prefix = context_header + "\n\n"

        meta = {
            "parent_section": node.parent_title or node.title,
            "child_section": node.title if node.level > 1 else "",
            "recipe": node.parent_title or (node.title if node.level == 1 else ""),
            "section": node.title,
            "page": node.page_start,
            "page_start": node.page_start,
            "page_end": node.page_end,
        }

        full_content = "\n".join(node.paragraphs).strip()
        full_text = prefix + full_content

        if len(full_text) <= chunk_size:
            chunks.append(ChunkText(full_text, meta))
        else:
            # Section/paragraph splitting respecting safety limits
            current_paras: list[str] = []
            curr_len = len(prefix)

            for p in node.paragraphs:
                p = p.strip()
                if not p:
                    continue
                p_len = len(p)
                add_len = p_len if not current_paras else 1 + p_len

                if current_paras and curr_len + add_len > chunk_size:
                    chunk_str = prefix + "\n".join(current_paras)
                    chunks.append(ChunkText(chunk_str, meta))
                    current_paras = []
                    curr_len = len(prefix)

                if p_len + len(prefix) > chunk_size:
                    if current_paras:
                        chunk_str = prefix + "\n".join(current_paras)
                        chunks.append(ChunkText(chunk_str, meta))
                        current_paras = []
                        curr_len = len(prefix)

                    oversized_parts = _split_large_text(
                        p,
                        chunk_size=max(1, chunk_size - len(prefix)),
                        chunk_overlap=chunk_overlap,
                    )
                    for part in oversized_parts:
                        chunks.append(ChunkText(prefix + part, meta))
                    continue

                current_paras.append(p)
                curr_len += add_len

            if current_paras:
                chunk_str = prefix + "\n".join(current_paras)
                chunks.append(ChunkText(chunk_str, meta))

    return [c for c in chunks if str(c).strip()]


# ─────────────────────────────────────────────────────────────────────────────
# End-to-End PDF to Chunks Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def pdf_to_chunks(
    pdf_bytes: bytes,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkText]:
    """
    Convert raw PDF bytes to structured, hierarchical ChunkText objects.
    """
    lines = extract_pdf_lines(pdf_bytes)
    if not lines:
        return []

    nodes = build_document_hierarchy(lines)
    if not nodes:
        return []

    return create_hierarchical_chunks(
        nodes,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )