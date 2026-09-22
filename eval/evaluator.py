"""
eval/evaluator.py
-------------------------------
Correctness evaluation comparing system results against golden-set expectations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.golden_loader import GoldenEntry
from telemetry.telemetry import ExecutionTelemetry


@dataclass
class EvalResult:
    scenario_id: str
    level: str
    is_correct: bool
    match_type: str  # "exact", "contains_token", "semantic_refusal", "incorrect"
    details: str
    telemetry: ExecutionTelemetry


def evaluate_answer(
    entry: GoldenEntry,
    answer: str,
    telemetry: ExecutionTelemetry,
) -> EvalResult:
    """
    Evaluate a system-generated answer against the golden-set expectation.
    Handles both positive cases and negative/refusal cases.
    """
    if entry.is_negative_case:
        return _evaluate_negative_case(entry, answer, telemetry)
    else:
        return _evaluate_positive_case(entry, answer, telemetry)


def _evaluate_negative_case(
    entry: GoldenEntry,
    answer: str,
    telemetry: ExecutionTelemetry,
) -> EvalResult:
    """
    For negative cases, the correct behavior is refusal/fallback.
    The system must NOT fabricate information.
    """
    answer_lower = answer.lower().strip()
    refusal_phrases = [
        "information not provided",
        "not provided in context",
        "not found in the provided",
        "does not contain",
        "cannot be determined",
        "i don't have enough information",
        "not mentioned",
        "no information",
        "not available",
        "unable to find",
        "not supported",
        "not documented",
        "no relevant",
        "budget exceeded",
        "system terminated",
        "no evidence",
        "no chunks found",
        "unable to generate",
        "error",
    ]

    is_refusal = any(phrase in answer_lower for phrase in refusal_phrases)

    if is_refusal:
        return EvalResult(
            scenario_id=entry.id,
            level=entry.level,
            is_correct=True,
            match_type="semantic_refusal",
            details=f"Correctly refused to answer negative case (expected: {entry.expected_behavior})",
            telemetry=telemetry,
        )

    fabricated_content_phrases = [
        "was retrieved",
        "provides the",
        "the answer is",
        "the parameter is",
        "you should use",
        "you can use",
        "it is recommended",
        "default value is",
    ]
    asserts_content = any(phrase in answer_lower for phrase in fabricated_content_phrases)

    if asserts_content:
        return EvalResult(
            scenario_id=entry.id,
            level=entry.level,
            is_correct=False,
            match_type="incorrect",
            details=f"System fabricated an answer for negative case instead of refusing: {answer[:100]}",
            telemetry=telemetry,
        )

    negative_indicators = [
        "the default value is",
        "the parameter is",
        "the endpoint is",
        "the flag is",
        "the option is",
        "using the",
        "to configure",
    ]
    seems_to_answer = any(indicator in answer_lower for indicator in negative_indicators)
    if seems_to_answer and len(answer) > 30:
        return EvalResult(
            scenario_id=entry.id,
            level=entry.level,
            is_correct=False,
            match_type="incorrect",
            details=f"System fabricated answer for negative case instead of refusing: {answer[:100]}",
            telemetry=telemetry,
        )

    return EvalResult(
        scenario_id=entry.id,
        level=entry.level,
        is_correct=True,
        match_type="semantic_refusal",
        details="System did not fabricate an answer for negative case.",
        telemetry=telemetry,
    )


def _evaluate_positive_case(
    entry: GoldenEntry,
    answer: str,
    telemetry: ExecutionTelemetry,
) -> EvalResult:
    """
    For positive cases, check if the generated answer contains the required factual information.
    """
    answer_lower = answer.lower().strip()

    refusal_phrases = [
        "information not provided",
        "not provided in context",
        "not found in the provided",
        "does not contain",
        "cannot be determined",
        "i don't have enough information",
        "no information",
        "unable to generate",
        "budget exceeded",
        "system terminated",
        "no evidence",
        "no chunks found",
    ]
    is_refusal = any(phrase in answer_lower for phrase in refusal_phrases)
    if is_refusal:
        return EvalResult(
            scenario_id=entry.id,
            level=entry.level,
            is_correct=False,
            match_type="incorrect",
            details=f"System refused on positive case. Answer: {answer[:100]}",
            telemetry=telemetry,
        )

    golden_answer_lower = entry.answer.lower()
    answer_keywords = set(answer_lower.split())
    golden_keywords = set(golden_answer_lower.split())
    meaningful_golden = {w for w in golden_keywords if len(w) > 3 and w not in {
        "the", "and", "for", "was", "are", "has", "can", "not", "that", "this",
        "with", "from", "they", "been", "have", "will", "would", "should", "could",
    }}
    meaningful_answer = {w for w in answer_keywords if len(w) > 3 and w not in {
        "the", "and", "for", "was", "are", "has", "can", "not", "that", "this",
        "with", "from", "they", "been", "have", "will", "would", "should", "could",
    }}

    overlap = meaningful_golden & meaningful_answer
    overlap_ratio = len(overlap) / max(len(meaningful_golden), 1)

    if entry.contains_exact_token:
        golden_tokens = entry.answer.split()
        for token in golden_tokens:
            clean = token.strip("'\".,:;()").lower()
            if len(clean) > 3 and clean in answer_lower:
                return EvalResult(
                    scenario_id=entry.id,
                    level=entry.level,
                    is_correct=True,
                    match_type="contains_token",
                    details=f"Answer contains expected exact token '{clean}'. Overlap ratio: {overlap_ratio:.2f}",
                    telemetry=telemetry,
                )

    if overlap_ratio >= 0.3:
        return EvalResult(
            scenario_id=entry.id,
            level=entry.level,
            is_correct=True,
            match_type="semantic_refusal" if overlap_ratio >= 0.5 else "contains_token",
            details=f"Answer overlaps with golden answer (ratio: {overlap_ratio:.2f}). Matched: {overlap}",
            telemetry=telemetry,
        )

    return EvalResult(
        scenario_id=entry.id,
        level=entry.level,
        is_correct=False,
        match_type="incorrect",
        details=f"Answer insufficient overlap with golden (ratio: {overlap_ratio:.2f}). Answer: {answer[:150]}",
        telemetry=telemetry,
    )