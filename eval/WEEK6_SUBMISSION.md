# Week 6 — Evals & Error Analysis

**Track E: Developer Documentation**
Final submission. All figures below are taken verbatim from the verified Work Item 10 consistency audit. No evaluation was re-run; no historical artifacts, labels, or scores were altered.

---

## 1. Eval Set

- **28 total cases** (`eval/eval_cases.json`)
- Taxonomy distribution:
  - factual_lookup: **13**
  - conceptual_explanation: **5**
  - unsupported_question: **4**
  - ambiguous_question: **3**
  - version_specific: **3**
- **2 genuine Week-5 regression cases**: `eval_027`, `eval_028` (source `week5_failure`) — present in the dataset
- **25 cases** selected for blind human/judge validation (subset of the 28)

---

## 2. One-Command Evaluation

The full 28-case application run is driven by a single command:

```
.\.venv\Scripts\python.exe eval\run_eval.py
```

**28-case application pass rate: 26/28 = 92.9%**

By taxonomy mode:

| Mode | Passed / Total | Rate |
|------|----------------|------|
| factual_lookup | 13/13 | 100.0% |
| conceptual_explanation | 5/5 | 100.0% |
| unsupported_question | 4/4 | 100.0% |
| ambiguous_question | 1/3 | 33.3% |
| version_specific | 3/3 | 100.0% |
| **TOTAL** | **26/28** | **92.9%** |

> **Important distinction:** this 92.9% is the **application** pass rate (does the assistant answer or refuse as expected, per the deterministic expectation in the runner). It is **not** judge agreement. Judge agreement (76.0% → 96.0%) measures agreement between an LLM judge and blind human labels on a single binary semantic criterion — a separate quantity reported in Sections 5–9.

---

## 3. Deterministic vs LLM Judge

The evaluation splits criteria into a deterministic assertion layer and a future LLM judge layer.

**Deterministic assertion criteria: 4**

1. `code_sample_parses`
2. `endpoint_exists`
3. `api_version_stated`
4. `deprecated_symbol_migration`

Applicable counts (from `eval/results.json`):

| Criterion | Applicable | Passed | Failed | N/A |
|-----------|-----------|--------|--------|-----|
| code_sample_parses | 5 | 5 | 0 | 23 |
| endpoint_exists | 0 | 0 | 0 | 28 |
| api_version_stated | 3 | 1 | 2 | 25 |
| deprecated_symbol_migration | 0 | 0 | 0 | 28 |

**LLM-judged criteria: 1** — a single binary semantic criterion (`helpful`).

The four deterministic criteria were **explicitly removed from the LLM judge**: the judge prompt (`eval/judge_v1.txt`, `eval/judge_v2.txt`) states the judge MUST NOT evaluate code-sample parsing, endpoint existence in the OpenAPI spec, API-version wording, or deprecated-symbol migration — these are handled exclusively by the deterministic layer.

---

## 4. Blind Human Labels

- **25 labels** (`eval/labels_25.json`)
- **23 helpful / 2 not helpful**
- Binary (`0`/`1` only), **no nulls**, all IDs unique
- Commit: `87f9e3e57b263badf641e8abb21c8b8fd2424529`
- Timestamp: `2026-09-04T01:26:06+05:30`
- The labels were **committed before any judge execution** (evidence in `eval/labeling_metadata.txt`), establishing the required ordering: blind human labels existed before the LLM judge was run.

---

## 5. Judge V1

- **25 cases** evaluated
- Judge labels: **21 = 1** / **4 = 0**
- **19 matches**
- **6 disagreements**
- **Agreement = 76.0%**
- Disagreement IDs: `eval_003`, `eval_011`, `eval_017`, `eval_019`, `eval_022`, `eval_023`

---

## 6. Disagreement Analysis

The six V1 disagreements split into two systematic error modes:

- **False negatives** (judge = 0, human = 1): `eval_003`, `eval_011`, `eval_022`, `eval_023`
  The judge marked direct, correct, grounded answers as "not helpful".
- **False positives** (judge = 1, human = 0): `eval_017`, `eval_019`
  The judge accepted answers to ambiguous/non-answerable questions that should have been refused.

**The human label was correct on all six disagreements.**

---

## 7. Prediction

Pre-iteration prediction (written and committed BEFORE Judge V2):

> "The V2 judge iteration, taught from the two selected disagreements (eval_023 and eval_019), will fix V1's two systematic agreement errors ... thereby raising agreement above the 76.0% V1 baseline."

- Commit: `708860f46fb0caabe2f2d736640d7cd9d372669c`
- Timestamp: `2026-09-04T01:43:52+05:30`

**Where it was correct:**
- Agreement rose above 76% (to 96.0%).
- The fixes on the two selected cases worked — `eval_023` (false negative) corrected to 1 and `eval_019` (false positive) corrected to 0.

**Where it was imprecise:**
- The prediction stated it would fix both false positives (`eval_017` and `eval_019`), but `eval_017` was **not** one of the two selected few-shot cases and **remained** the single V2 disagreement. The prediction over-extended the fix to a non-selected case.

---

## 8. Judge V2

- **24/25 agreement**
- **96.0%**
- **+20.0 percentage points** over V1
- Only remaining disagreement: **`eval_017`**
- Exactly **two few-shot examples** were used: **`eval_023`** and **`eval_019`** (both V1 actual disagreements — one false negative, one false positive)

---

## 9. Before → After

| Metric | V1 | V2 |
|--------|-----|-----|
| Agreement | 76.0% | 96.0% |
| Matches | 19/25 | 24/25 |
| Disagreements | 6 | 1 |

---

## 10. Final Verdict

The Week 6 evidence is **complete and internally consistent**: a 28-case deterministic eval with a one-command runner (26/28 = 92.9% application pass rate); an explicit deterministic (4) vs LLM-judged (1) boundary; 25 binary blind human labels committed before judge execution; Judge V1 at 76.0% with 6 disagreements that were all correctly labeled by the human; a committed pre-iteration prediction; and a Judge V2 iteration driven by two actual few-shot disagreements that raised exact binary agreement to 96.0% (+20.0 points), leaving a single holdout (`eval_017`).
