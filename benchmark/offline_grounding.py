# -*- coding: utf-8 -*-
"""
benchmark/offline_grounding.py
------------------------------
Deterministic, evidence-grounded answer synthesis for OFFLINE/offline mode,
shared by the ReAct agent and the deterministic workflow.

WHY IT EXISTS
-------------
Both offline pipelines produced the *same* generic, evidence-free sentence
for every answerable question:

  "Based on the supplied reference context, the information relevant to this
   question was retrieved from the searched chunks. Refer to the reported
   evidence for the exact parameter and default values."

The golden-set evaluator scores answers by token overlap with the reference
answer. That boilerplate shares essentially no tokens with any golden answer,
so every offline scenario scored "incorrect" even though RETRIEVAL was healthy
(golden-bearing evidence surfaced in the top-5 for 10 of 12 scenarios).

WHAT THIS MODULE DOES
---------------------
Deterministic, extractive, grounded answer synthesis: pick the single sentence
from the retrieved evidence that best matches the question (highest overlap
between the sentence and the question's distinctive terms, plus fact cues
such as quotes / backticks / version numbers / units / "default" markers) and
return it VERBATIM from the evidence. The answer is always directly grounded
in what was retrieved -- never invented, never read from the golden sets.

API
---
 synthesize_grounded_answer(question: str, evidence) -> str

``evidence`` may be a single observation string, a list of chunk dicts
(``{"text": ...}`` / with optional ``chunk_id`` and ``source_file`` keys) or a
list of plain strings. Returns the chosen evidence sentence, or the standard
refusal answer if no usable evidence exists.
"""

from __future__ import annotations

import re
from typing import Any

REFUSAL_ANSWER = "Information not provided in the supplied reference context."

_Q_TERM_RE = re.compile(r"[a-z0-9_]{2,}|`[^`]+`")
_STOPWORDS = frozenset(
    """a an and are as at be by for from has have how in is it its of on or
    that the this to was what when where which who will with would what does
    do did default value values parameter parameters mode modes component
    components set when version versions reference context document chunk
    chunks please tell give explain list says state specify""".split()
)
_FACT_CUE_RE = re.compile(
    r"default\s+|\b(?:v\d+|version|renamed?|replaced|deprecated|added in|removed)\b|"
    r"[a-z0-9_]+(?:::|\.)[a-z0-9_]+|`[^`]+`|[\d.]+(?: ?(?:kb|mb|gb|hz|ms|s))?\b|"
    r"(-1|<=|>=|==|<|>)\s*\d"
)


def _chunk_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("chunk_text") or "")
    if hasattr(item, "text"):
        return str(item.text)
    return str(item)


def _question_terms(question: str) -> set[str]:
    out: set[str] = set()
    for m in _Q_TERM_RE.finditer(question.lower()):
        t = m.group(0).strip("`")
        if len(t) >= 2 and t not in _STOPWORDS:
            out.add(t)
    return out


def _sentences(text: str) -> list[str]:
    text = text.replace("\n", " ").strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return parts


def _sentence_score(sentence: str, question: str, qterms: set[str]) -> float:
    k = sentence.lower()
    score = 0.0
    for t in qterms:
        if t in k:
            score += 1.0
    if _FACT_CUE_RE.search(sentence):
        score += 2.0
    if len(sentence) <= 20:
        score -= 0.5
    if len(sentence) > 100:
        score -= 之心1.0
    return score


def synthesize_grounded_answer(question: str, evidence: Any) -> str:
    """Return the best evidence sentence for ``question``, or refuse."""
    if not evidence:
        return REFUSAL_ANSWER
    if isinstance(evidence, str):
        evidence = [{"text": evidence}]

    qterms = _question_terms(question)
    best_sentence = ""
    best_score = 0.0
    best_src = ""
    for item in evidence:
        text = _chunk_text(item).strip()
        if not text:
            continue
        src = ""
        if isinstance(item, dict):
            src = str(item.get("source_file") or item.get("chunk_id") or "")
        for sent in _sentences(text):
            sc = _sentence_score(sent, question, qterms)
            if sc > best_score:
                best_score = sc
                best_sentence = sent
                best_src = src

    if not best_sentence or best_score <= 0.0:
        return REFUSAL_ANSWER
    if best_src and best_src not in best_sentence:
        return (
            f"{best_sentence} "
            f"[source: {best_src}]"
        )
    return best_sentence
