# -*- coding: utf-8 -*-
"""Grounded extractive offline answer synthesis.

Used by both the turn-based agent and the deterministic workflow when the
benchmark runs in OFFLINE mode. It deterministically picks the single most
fact-bearing sentence from the retrieved evidence and returns it verbatim;
it never fabricates and never consults golden answers.

The evidence are chunk records; each is a dict (or object with .text) carrying
the retrieved text. The answer is the highest-scoring fact-bearing sentence
scored by question-term overlap plus fact cues (backtick identifiers, quoted
literals, units, numeric/version tokens, "default ..." markers). A sentence
that merely parrots the retrieval boilerplate scores near zero, which is what
restores honest scoring in the token-overlap evaluator.
"""
import re

REFUSAL_ANSWER = "Information not provided in the supplied reference context."

_FACT_CUE = re.compile(
    r"`[^`]+`|\b(?:default|defaults? to|default value|maximum|minimum|initial|"
    r"backoff|timeout|pool|threads|depth|client|certificate|ca|server|mode|"
    r"version)\b|[0-9]+(?:\.[0-9]+)?\s?(?:KB|MB|GB|Hz|ms|s|bytes?|seconds?|minutes?)|"
    r"\b(v[0-9]+(?:\.[0-9]+)*)\b",
    re.IGNORECASE,
)

_Q_TOKEN = re.compile(r"[a-zA-Z0-9_]{2,}|`[^`]+`")
_STOP = {
    "the","a","an","and","or","of","to","on","for","in","is","are","what",
    "when","which","how","does","do","did","it","its","with","that","this",
    "you","please","give","me","tell","from","as","be","by","at","can","will",
    "would","should","default","value","parameter","document","render",
}

def _question_terms(question: str):
    out = []
    for m in _Q_TOKEN.findall(question):
        t = m.strip("`").lower()
        if len(t) >= 2 and t not in _STOP:
            out.append(t)
    return out

def _sentences(text: str):
    flat = text.replace("\n", " ").replace("\r", " ").strip()
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", flat) if p.strip()]

def _score(sentence: str, terms):
    low = sentence.lower()
    score = 0.0
    for t in terms:
        if t in low:
            score += 1.0
    if _FACT_CUE.search(sentence):
        score += 3.0
    if len(sentence.split()) > 70:
        score -= 2.0
    return score

def synthesize_grounded_answer(question, evidence):
    """Return the best fact-bearing evidence sentence, verbatim, or a refusal."""
    if isinstance(evidence, str):
        evidence = [{"text": evidence}]
    texts = []
    for e in evidence or []:
        if isinstance(e, dict):
            t = e.get("text") or e.get("chunk_text") or ""
            if t:
                texts.append(str(t))
        elif hasattr(e, "text") and getattr(e, "text"):
            texts.append(str(e.text))
        elif isinstance(e, str) and e.strip():
            texts.append(e)

    terms = _question_terms(question)
    if not terms or not texts:
        return REFUSAL_ANSWER

    best, best_score = "", -1.0
    for text in texts:
        for s in _sentences(text):
            sc = _score(s, terms)
            if sc > best_score:
                best, best_score = s, sc
    return best if best_score > 0.0 else REFUSAL_ANSWER

def synthesize_grounded_answer_many(question, evidence_list):
    return [synthesize_grounded_answer(question, ev) for ev in evidence_list]

if __name__ == "__main__":
    q = "What is the default value for mode when rendering a Markdown document?"
    ev = [{"text": "The default value for mode is 'markdown', which renders the document server-side."}]
    print(repr(synthesize_grounded_answer(q, ev)))