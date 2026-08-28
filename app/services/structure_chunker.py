"""
app/services/structure_chunker.py
----------------------------------

Context-Aware Markdown Chunker.

Key Design Principles:
1. Parse document structure (YAML frontmatter, Headings, Subheadings, Tables, Fenced Code Blocks, Paragraphs).
2. CRITICAL RULE - Tables: Parameter table rows are NEVER separated from their table headers/sections.
3. CRITICAL RULE - Code Blocks: Fenced code blocks (```python ... ```) are NEVER split across chunks.
4. Metadata Preservation: Every chunk carries source_file, page_id, sdk_version, page_type, section, and anchor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from app.services.chunker import ChunkText, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP


@dataclass
class SectionBlock:
    heading: str
    level: int
    anchor: str
    content_blocks: list[str] = field(default_factory=list)


def _slugify(text: str) -> str:
    """Generate Markdown header anchor slug e.g. 'Client.send() Method Reference' -> '#client-send-method-reference'"""
    cleaned = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return "#" + re.sub(r"[-\s]+", "-", cleaned)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter metadata if present."""
    metadata = {
        "source_file": "",
        "page_id": "",
        "sdk_version": "v3",
        "page_type": "reference",
    }
    body = content

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if match:
        yaml_text = match.group(1)
        body = content[match.end() :]
        for line in yaml_text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                metadata[k.strip()] = v.strip()

    return metadata, body


def markdown_to_structure_chunks(
    content: str,
    default_metadata: dict | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkText]:
    """
    Parse a Markdown document into context-aware chunks.
    Preserves tables and code blocks as atomic semantic units.
    """
    front_meta, body = parse_frontmatter(content)

    base_meta = dict(default_metadata or {})
    base_meta.update(front_meta)
    if not base_meta.get("source_file"):
        base_meta["source_file"] = base_meta.get("filename", "document.md")
    if not base_meta.get("page_id"):
        base_meta["page_id"] = base_meta["source_file"].rsplit(".", 1)[0]
    if not base_meta.get("sdk_version"):
        base_meta["sdk_version"] = "v3"

    # Step 1: Split body into structural blocks (Headings, Tables, Code Blocks, Paragraphs)
    raw_lines = body.splitlines()
    sections: list[SectionBlock] = []
    
    current_heading = base_meta.get("page_id", "Document")
    current_level = 1
    current_anchor = _slugify(current_heading)
    current_section = SectionBlock(
        heading=current_heading,
        level=current_level,
        anchor=current_anchor,
        content_blocks=[],
    )
    sections.append(current_section)

    in_code_block = False
    code_block_lines: list[str] = []

    in_table = False
    table_lines: list[str] = []

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]

        # Check code fence state
        if line.strip().startswith("```"):
            if in_code_block:
                # End of code block
                code_block_lines.append(line)
                current_section.content_blocks.append("\n".join(code_block_lines))
                code_block_lines = []
                in_code_block = False
            else:
                # Start of code block
                if in_table:
                    current_section.content_blocks.append("\n".join(table_lines))
                    table_lines = []
                    in_table = False
                in_code_block = True
                code_block_lines.append(line)
            i += 1
            continue

        if in_code_block:
            code_block_lines.append(line)
            i += 1
            continue

        # Check table state (line starting with '|')
        if line.strip().startswith("|"):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
            i += 1
            continue
        else:
            if in_table:
                current_section.content_blocks.append("\n".join(table_lines))
                table_lines = []
                in_table = False

        # Check heading state
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            anchor = _slugify(heading_text)

            current_section = SectionBlock(
                heading=heading_text,
                level=level,
                anchor=anchor,
                content_blocks=[],
            )
            sections.append(current_section)
            i += 1
            continue

        # Normal paragraph line
        if line.strip():
            current_section.content_blocks.append(line.strip())

        i += 1

    # Flush remaining table or code blocks
    if in_code_block and code_block_lines:
        current_section.content_blocks.append("\n".join(code_block_lines))
    if in_table and table_lines:
        current_section.content_blocks.append("\n".join(table_lines))

    # Step 2: Combine section blocks into ChunkText instances with metadata
    chunks: list[ChunkText] = []

    parent_heading = sections[0].heading if sections else base_meta["page_id"]

    for sec in sections:
        if not sec.content_blocks:
            continue

        if sec.level == 1:
            parent_heading = sec.heading

        context_prefix = f"## {sec.heading}\n\n" if sec.level > 1 else f"# {sec.heading}\n\n"
        
        meta = dict(base_meta)
        meta["section"] = sec.heading
        meta["parent_section"] = parent_heading
        meta["anchor"] = sec.anchor
        meta["page"] = base_meta.get("page_id", "1")

        full_content = "\n\n".join(sec.content_blocks).strip()
        full_text = context_prefix + full_content

        if len(full_text) <= chunk_size:
            chunks.append(ChunkText(full_text, meta))
        else:
            # Split section blocks while keeping tables and code blocks atomic
            curr_blocks: list[str] = []
            curr_len = len(context_prefix)

            for blk in sec.content_blocks:
                blk_len = len(blk)
                add_len = blk_len if not curr_blocks else 2 + blk_len

                if curr_blocks and curr_len + add_len > chunk_size:
                    chunk_str = context_prefix + "\n\n".join(curr_blocks)
                    chunks.append(ChunkText(chunk_str, meta))
                    curr_blocks = []
                    curr_len = len(context_prefix)

                curr_blocks.append(blk)
                curr_len += add_len

            if curr_blocks:
                chunk_str = context_prefix + "\n\n".join(curr_blocks)
                chunks.append(ChunkText(chunk_str, meta))

    return [c for c in chunks if str(c).strip()]
