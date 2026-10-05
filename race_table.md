# Week 10 Race Table — Single Agent vs Multi-Agent Squad

**Source of truth:** `sdk-v3-strategy-b` corpus · shared evaluator `eval.evaluator.evaluate_answer`
**Race type:** clean baseline, `failure_injection_enabled = false`
**Context-token convention:** `project_chars_div_4` (`len(text) // 4`)

---

## Benchmark case set (exactly 10, sanctioned Week 7 golden-set cases)

```
easy:01  easy:04  easy:13
medium:02  medium:05  medium:14
hard:01  hard:04  hard:09  hard:13
```

Composition: **7 positive / 3 negative** (`easy:13`, `medium:14`, `hard:13`).
This is **not** the historical Week 6 28-case evaluation.

---

## Head-to-head comparison

| Metric | Single Agent | Multi-Agent Squad |
|---|---|---|
| **Pass Rate** | 30.0% (3/10) | 30.0% (3/10) |
| **p50 Latency** | 19.58 ms | 21.40 ms |
| **p99 Latency** | 35.97 ms | 26.83 ms |
| **Total Provider Tokens** | 2024 | **unavailable (not applicable)** |
| **Cost Per Question** | $0.000055 | $0.000000 |
| **Total Cost** | $0.000546 | $0.000000 |
| **Handoffs** | 0 (not an agent-to-agent architecture) | 20 (20 success / 0 failed) |
| **Handoff Context Tokens** | n/a | 3964 (estimated, char/4) |
| **Context Re-Send Multiplier** | 1.0x (baseline) | **2.0x** |
| **Errors** | 0 | 0 |

### Provider tokens — read this before comparing token rows

The Multi-Agent provider-token figure is **unavailable / not applicable**, *not zero*.

The Week 10 workers perform **no LLM calls at all** — retrieval, embeddings and analysis are entirely local
(ChromaDB + `all-MiniLM-L6-v2` + the migration analyzer). There is therefore no provider token usage to report.
The schema records this as `input_tokens = None` / `output_tokens = None` with
`token_source = "unavailable"`, and **never** coerces it to `0`.

Consequently:

- Multi-Agent **provider cost is genuinely $0.00** — a real cost of zero, not a missing measurement.
- Provider tokens and handoff context tokens are **two different quantities and are never summed**.
- The Context Re-Send Multiplier deliberately compares *handoff context re-send* (numerator)
  against *Single Agent provider tokens* (denominator), and is flagged as an estimate.

### Context Re-Send Multiplier

```
3964 handoff context tokens / 2024 Single Agent provider tokens = 1.9585  ->  reported as 2.0x
```

**This 2.0x is NOT model-native token overhead.** It is derived from the project's
`project_chars_div_4` (`len(text) // 4`) character heuristic, recorded with
`context_token_method = "project_chars_div_4"` and `context_tokens_estimated = true`.
It is not BPE tokenization and must not be compared against a provider's native token counts.

### Handoff context-token distribution

| Destination worker | Handoffs | Context tokens | Share |
|---|---|---|---|
| `version_deprecation_worker` | 10 | 290 | 7.3% |
| `code_sample_worker` | 10 | 3674 | **92.7% (~93%)** |
| **Total** | **20** | **3964** | 100% |

The Code-Sample Worker is the dominant context bottleneck, consuming 3674 of 3964 tokens.

---

## Per-case results

| Case | Level | Type | Single | Multi | Agree | Single latency | Single provider tokens | Multi latency | Multi context tokens |
|---|---|---|---|---|---|---|---|---|---|
| easy:01 | Easy | positive | FAIL | FAIL | yes | 35.97 ms | 202 | 26.83 ms | 418 |
| easy:04 | Easy | positive | FAIL | FAIL | yes | 18.59 ms | 194 | 20.97 ms | 386 |
| easy:13 | Easy | **negative** | PASS | PASS | yes | 21.36 ms | 192 | 21.01 ms | 402 |
| medium:02 | Medium | positive | FAIL | FAIL | yes | 20.57 ms | 190 | 24.37 ms | 413 |
| medium:05 | Medium | positive | FAIL | FAIL | yes | 18.06 ms | 202 | 20.38 ms | 376 |
| medium:14 | Medium | **negative** | PASS | PASS | yes | 21.73 ms | 224 | 21.66 ms | 465 |
| hard:01 | Hard | positive | FAIL | FAIL | yes | 25.73 ms | 206 | 20.56 ms | 422 |
| hard:04 | Hard | positive | FAIL | FAIL | yes | 18.15 ms | 204 | 23.63 ms | 226 |
| hard:09 | Hard | positive | FAIL | FAIL | yes | 16.25 ms | 196 | 21.14 ms | 432 |
| hard:13 | Hard | **negative** | PASS | PASS | yes | 18.01 ms | 214 | 21.77 ms | 424 |

**Case-outcome agreement: 10/10.** Both arms produced the same pass/fail verdict on every case.

### Pass composition — the decisive caveat

All 3 passes are the **negative** cases (`easy:13`, `medium:14`, `hard:13`), scored `semantic_refusal`.
All **7 positive cases failed on both arms** at ~0.00 keyword overlap.

So the headline "30% vs 30%" decomposes as:

- **3/3 negative cases pass on both arms** — negative cases pass largely by default in the shared evaluator.
- **0/7 positive cases pass on either arm** — measured retrieval correctness is **0% for both**.

The aggregate 30% therefore does **not** demonstrate equivalent retrieval capability, and it does not
discriminate between the two architectures.

### Why the Code-Sample Worker cannot be scored on this set

The 10 sanctioned cases reward a scalar fact, a limit, a flag name, a prose version comparison, or a
refusal — never a code sample. Of the 47 corpus chunks covering the golden subjects
(`github_combined_reference.pdf`, `swagger_v2_reference.pdf`, `swagger_v3_reference.pdf`),
**0 contain a fenced code block**. All fenced code in the collection belongs to `v3_sdk_corpus`, which is
unrelated to these questions. The worker therefore emitted no code on any case and its correctness is
**unmeasured** — it neither passed nor failed.