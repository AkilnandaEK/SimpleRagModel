"""
tools/migration_analyzer.py
-----------------------------------
Tool 3: Analyze retrieved information and compare versions/configurations.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


# ── Input Schema ─────────────────────────────────────────────────────────────

class MigrationAnalyzerInput(BaseModel):
    question: str = Field(..., min_length=1, description="The migration or comparison question to analyze.")
    evidence_chunks: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="List of evidence chunks retrieved from the reference corpus. Each must have 'chunk_id' and 'text'.",
    )
    version_from: str | None = Field(default=None, description="Source version for migration (e.g., '2022-11-28').")
    version_to: str | None = Field(default=None, description="Target version for migration (e.g., '2025-06-01').")


# ── Output Schema ────────────────────────────────────────────────────────────

class MigrationFinding(BaseModel):
    topic: str
    old_behavior: str | None = None
    new_behavior: str | None = None
    evidence_text: str
    source_chunk_id: str


class MigrationAnalysisOutput(BaseModel):
    is_answerable: bool
    migration_changes: list[MigrationFinding] = []
    evidence: str
    source_references: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    refusal_reason: str | None = None


# ── Tool Implementation ──────────────────────────────────────────────────────

def migration_analyzer(input_data: MigrationAnalyzerInput) -> MigrationAnalysisOutput:
    """
    Analyze retrieved evidence chunks to extract migration/comparison findings.

    Answerability requires the evidence to speak to the question: it must share a
    meaningful share of distinctive terms with the question (lexical overlap) and
    contain fact-bearing text (defaults / version wording / quoted values).
    """
    if not input_data.evidence_chunks:
        return MigrationAnalysisOutput(
            is_answerable=False,
            migration_changes=[],
            evidence="",
            source_references=[],
            confidence=0.0,
            refusal_reason="No evidence chunks provided for analysis.",
        )

    evidence_texts = []
    source_refs = []
    findings = []

    question_terms = _distinctive_terms(input_data.question)
    fact_pattern = re.compile(
        r"(default|deprecated|replaced|renamed|added|removed|changed|new in|version|'[^']*'|\"[^\"]*\"|\d{4}[-/]\d{2}|\d\.\d|\btrue\b|\bfalse\b)",
        re.IGNORECASE,
    )

    best_overlap = 0.0
    best_containment = 0.0
    relevant_chunks = []

    for chunk in input_data.evidence_chunks:
        chunk_id = chunk.get("chunk_id", "unknown")
        text = chunk.get("text", "")
        evidence_texts.append(text)
        source_refs.append(chunk_id)

        chunk_terms = _distinctive_terms(text)
        if question_terms:
            matching_question_terms = len(question_terms & chunk_terms)
            overlap = matching_question_terms / max(len(question_terms), 1)
        else:
            matching_question_terms = 0
            overlap = 0.0
        best_overlap = max(best_overlap, overlap)

        if matching_question_terms >= 2 and overlap >= 0.5:
            best_containment = max(best_containment, overlap)
            fact_bearing = bool(fact_pattern.search(text))
            if fact_bearing:
                relevant_chunks.append((chunk_id, text, overlap))

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines:
            lower = line.lower()
            if any(kw in lower for kw in ("default", "deprecated", "replaced", "changed", "new in", "added", "removed", "version")):
                findings.append(MigrationFinding(
                    topic=_extract_topic(line, input_data.question),
                    old_behavior=line if _is_old_behavior(line) else None,
                    new_behavior=line if _is_new_behavior(line) else None,
                    evidence_text=line,
                    source_chunk_id=chunk_id,
                ))

    combined_evidence = "\n\n".join(evidence_texts)

    if input_data.version_from or input_data.version_to:
        version_filtered = []
        for text in evidence_texts:
            lower = text.lower()
            if input_data.version_from and input_data.version_from.lower() in lower:
                version_filtered.append(text)
            if input_data.version_to and input_data.version_to.lower() in lower:
                version_filtered.append(text)
        if not version_filtered and evidence_texts:
            version_filtered = evidence_texts

    is_answerable = any(overlap >= 0.5 and len(chunk_text) > 40 for _, chunk_text, overlap in relevant_chunks)

    if is_answerable:
        has_substantive = any(
            len(f.evidence_text) > 20 for f in findings
        ) or len(combined_evidence) > 100
        confidence = min(0.9, 0.5 + best_overlap) if has_substantive else 0.4
    else:
        confidence = 0.0

    return MigrationAnalysisOutput(
        is_answerable=is_answerable,
        migration_changes=findings[:10],
        evidence=combined_evidence[:2000],
        source_references=source_refs,
        confidence=round(confidence, 2),
        refusal_reason=None if is_answerable else (
            "Insufficient evidence in retrieved chunks to answer the question. "
            "The retrieved text does not substantively address the question."
        ),
    )


_STOPWORDS = {
    "what", "which", "how", "does", "the", "and", "for", "was", "are", "has",
    "can", "not", "that", "this", "with", "from", "they", "been", "have",
    "will", "would", "should", "could", "when", "where", "is", "in", "of", "it",
    "to", "a", "an", "do", "did", "so", "as", "on", "at", "by", "or", "if",
    "parameter", "parameters", "value", "values", "using", "used", "use",
    "between", "version", "versions", "api", "github", "swagger", "codegen",
}


def _distinctive_terms(text: str) -> set[str]:
    """Extract distinctive (non-stopword) terms from text."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_.\-]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _extract_topic(line: str, question: str) -> str:
    """Extract a concise topic label from an evidence line."""
    words = line.split()[:8]
    return " ".join(words) if words else line[:50]


def _is_old_behavior(line: str) -> bool:
    lower = line.lower()
    return any(kw in lower for kw in ("was", "used to", "previous", "before", "2022", "v2", "2.x"))


def _is_new_behavior(line: str) -> bool:
    lower = line.lower()
    return any(kw in lower for kw in ("is now", "changed to", "new", "added", "2025", "v3", "3.x", "replaced"))