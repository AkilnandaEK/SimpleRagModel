"""
app/services/chunker.py
-----------------------
Handles PDF text extraction and recursive character-based text splitting.

Pipeline:
  PDF bytes → raw text (per page) → chunks (list[str])

The RecursiveCharacterSplitter mimics LangChain's approach without the
LangChain dependency:
  1. Try to split on paragraph breaks  (\n\n)
  2. Fall back to line breaks          (\n)
  3. Fall back to spaces               ( )
  4. Fall back to characters           ("")
"""

from __future__ import annotations

import re
from typing import Generator

import fitz  # PyMuPDF


# ─────────────────────────────────────────────────────────────────────────────
# PDF Extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract all text from a PDF given its raw bytes.
    Returns a single string with pages separated by form-feed characters.
    """
    text_parts: list[str] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text("text")
            if page_text.strip():
                text_parts.append(f"[Page {page_num}]\n{page_text.strip()}")
    return "\n\n".join(text_parts)


# ─────────────────────────────────────────────────────────────────────────────
# Recursive Character Text Splitter
# ─────────────────────────────────────────────────────────────────────────────

_SEPARATORS = ["\n\n", "\n", " ", ""]


def _split_by_separator(text: str, separator: str) -> list[str]:
    """Split text by a separator, keeping non-empty parts."""
    if separator:
        parts = text.split(separator)
    else:
        parts = list(text)
    return [p for p in parts if p.strip()]


def _merge_splits(splits: list[str], separator: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Merge small splits into chunks of up to `chunk_size` characters,
    with `chunk_overlap` characters carried over between consecutive chunks.
    """
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for split in splits:
        split_len = len(split)

        # If this single split already exceeds chunk_size, add it as-is
        if split_len > chunk_size:
            if current_parts:
                chunks.append(separator.join(current_parts))
                current_parts = []
                current_len = 0
            chunks.append(split)
            continue

        # Would adding this split exceed the limit?
        would_be_len = current_len + len(separator) * bool(current_parts) + split_len
        if would_be_len > chunk_size and current_parts:
            chunks.append(separator.join(current_parts))

            # Keep overlap: remove parts from the front until we're within overlap budget
            while current_parts and current_len > chunk_overlap:
                removed = current_parts.pop(0)
                current_len -= len(removed) + len(separator)
                current_len = max(current_len, 0)

        current_parts.append(split)
        current_len = sum(len(p) for p in current_parts) + len(separator) * (len(current_parts) - 1)

    if current_parts:
        chunks.append(separator.join(current_parts))

    return [c.strip() for c in chunks if c.strip()]


def recursive_character_splitter(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    separators: list[str] | None = None,
) -> list[str]:
    """
    Recursively split text using a hierarchy of separators.

    Args:
        text:          Raw text to split.
        chunk_size:    Maximum number of *characters* per chunk.
        chunk_overlap: Number of characters of overlap between consecutive chunks.
        separators:    Ordered list of separators to try. Defaults to
                       [\"\\n\\n\", \"\\n\", \" \", \"\"].

    Returns:
        List of text chunk strings.
    """
    if separators is None:
        separators = _SEPARATORS

    def _split(text: str, seps: list[str]) -> list[str]:
        separator = seps[0]
        remaining_seps = seps[1:]

        if len(text) <= chunk_size:
            return [text.strip()] if text.strip() else []

        splits = _split_by_separator(text, separator)

        good_splits: list[str] = []
        final_chunks: list[str] = []

        for split in splits:
            if len(split) <= chunk_size:
                good_splits.append(split)
            else:
                # Flush good splits first
                if good_splits:
                    merged = _merge_splits(good_splits, separator, chunk_size, chunk_overlap)
                    final_chunks.extend(merged)
                    good_splits = []

                # Recurse with next separator
                if remaining_seps:
                    sub_chunks = _split(split, remaining_seps)
                    final_chunks.extend(sub_chunks)
                else:
                    final_chunks.append(split)

        if good_splits:
            merged = _merge_splits(good_splits, separator, chunk_size, chunk_overlap)
            final_chunks.extend(merged)

        return final_chunks

    return _split(text, separators)


# ─────────────────────────────────────────────────────────────────────────────
# Combined pipeline helper
# ─────────────────────────────────────────────────────────────────────────────

def pdf_to_chunks(
    pdf_bytes: bytes,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[str]:
    """
    End-to-end helper: PDF bytes → list of text chunks.
    """
    raw_text = extract_text_from_pdf(pdf_bytes)
    return recursive_character_splitter(raw_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
