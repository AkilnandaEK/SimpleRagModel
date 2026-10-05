# Week 10 Failure Experiment — `hard:01` Version/Deprecation Worker HTTP 500

**Type:** fault injection, single case
**Question under test:** does the current architecture contain a worker failure safely?
**Answer:** yes operationally — but the shared evaluator scored the failed run as **correct**, so the score does not prove it.

---

## 1. Case and question

| Field | Value |
|---|---|
| Case ID | `hard:01` |
| Level | Hard |
| Negative case | No (positive case) |
| Question | *"Compare how the `context` parameter format changed between GitHub API version 2022-11-28 and 2025-06-01 for rendering Markdown."* |
| Golden answer | In 2022-11-28 `context` was a plain string (e.g. `'octocat/Hello-World'`); in 2025-06-01 it accepts an owner/repo structured object. |
| `contains_exact_token` | `True` |
| Why this case | It is the Week-8 taxonomy's `comparison` contract (`api_versions` has 2+ entries → **analyzer required**), so losing the Version Worker should hurt most. |

## 2. Failure injection mechanism

Dependency injection, per-instance, no global patching.

1. `VersionDeprecationWorker.__init__` accepts an optional `tools` mapping covering its four upstream
   calls (`accepted_version_values`, `reference_search`, `chunk_retrieval`, `migration_analyzer`).
   **Defaults are the real implementations** — the production path is unchanged.
2. `eval/week10_failure_injection.py` defines `HttpServerError` (status `500`, failing service,
   `retryable`) and substitutes a raising callable at the **`reference_search`** seam — the worker's
   first evidence-gathering call, i.e. where a remote corpus service would sit.
3. Injected through the race runner's **existing** `multi_runner` parameter. `eval/week10_race_runner.py`
   was not modified.
4. **The worker propagates the error; only the orchestrator degrades.** The worker raised
   `VersionDeprecationWorkerError` — that wrapping already existed in the worker; the experiment only
   supplied the server-side cause.

No retry logic and no fallback logic were added for this experiment.

## 3. Exact worker behavior

- `VersionDeprecationWorker` **failed**.
- Raised `HTTP 500 Internal Server Error from 'reference_corpus_search'`.
- The failing tool seam was invoked **exactly once** (`calls == [1]`).
- Worker handoff: `success = False`, `error` populated, `tool_calls = 0`, `llm_calls = 0`.

## 4. Exact orchestrator behavior

`ManagerOrchestrator` caught `VersionDeprecationWorkerError` and:

- degraded the evidence to `supported=False`, `has_evidence=False`, `chunk_ids=[]`, `findings=[]`, `evidence_chunks=[]`
- set reasoning to *"Version/deprecation worker failed; downstream code sample is refused rather than fabricated."*
- **continued execution** — it did **not** abort the run
- **delegated to the Code-Sample Worker** anyway (2 handoffs recorded)
- reported `SquadResponse.success = False` with the HTTP 500 message surfaced in `errors`

## 5. Retry result

**No retry occurred.** The injected seam was called exactly once; the orchestrator moved straight to
degradation. Pinned by `test_orchestrator_does_not_retry`.

## 6. Degrade / fallback result

**Degradation, not fallback.** No alternate provider, tool, model or corpus was tried. The orchestrator
substituted an explicit *unsupported/empty* evidence record and let the run finish with a failure verdict.
This containment is pre-existing production behavior — nothing was added to produce it.

## 7. Downstream Code-Sample Worker behavior

Ran despite missing upstream evidence and **refused** rather than inventing:

- `supported = False`
- `has_code = False`
- `refused = True`, `warnings_count = 1`
- warning: *"Upstream version/deprecation evidence is unsupported; refusing to fabricate version-dependent code."*
- handoff recorded `success = True` — it succeeded *by refusing*

## 8. Hallucination / fabrication result

**No fabrication.** Verified absent from the emitted answer:

- no fenced code block (```` ``` ```` not present)
- no `2022-11-28`, no `2025-06-01`, no `octocat` — the version strings supplied in the question did not leak into the output
- answer was the fixed refusal text: *"Code sample not generated: upstream version/deprecation information is unavailable or unsupported. No SDK or version details are invented when upstream version/deprecation information is unavailable or unsupported."*

## 9. Handoff telemetry (failure run)

```
[seq 0] manager_orchestrator -> version_deprecation_worker
  task            : version_deprecation_analysis
  task_id         : 8b97aaac8258:0:version_deprecation_analysis
  success         : False
  error           : reference_search failed for query '...': HTTP 500 Internal
                    Server Error from 'reference_corpus_search': upstream
                    reference corpus service failed
  latency_ms      : 0.03
  context_tokens  : 31      (project_chars_div_4, estimated=True)
  provider tokens : input=None output=None total=None  source=unavailable
  tool_calls      : 0     llm_calls: 0
  details         : {'supported': False, 'has_evidence': False,
                     'llm_calls': 0, 'token_source': 'unavailable'}

[seq 1] manager_orchestrator -> code_sample_worker
  task            : code_sample_generation
  task_id         : 8b97aaac8258:1:code_sample_generation
  success         : True
  error           : None
  latency_ms      : 0.01
  context_tokens  : 31      (project_chars_div_4, estimated=True)
  provider tokens : input=None output=None total=None  source=unavailable
  tool_calls      : 0     llm_calls: 0
  details         : {'supported': False, 'has_code': False,
                     'warnings_count': 1, 'refused': True, ...}
```

Failure-run summary: **2 handoffs, 1 failed, 1 successful, 62 total context tokens, provider tokens unavailable.**

Unmeasured provider usage stayed `None`; it was never written as `0`.

## 10. Single Agent control (same case)

| Field | Value |
|---|---|
| `is_correct` | `False` |
| `match_type` | `incorrect` |
| Answer | *"Information not provided in the supplied reference context."* |
| Context tokens | 422 |

## 11. Context-token comparison

| Run | Total context tokens |
|---|---|
| `hard:01` clean baseline | 422 (31 version + 391 code) |
| `hard:01` under HTTP 500 | 62 (31 version + 31 code) |

The collapse from 422 → 62 is itself evidence that **no evidence text crossed the boundary**: the failed
worker forwarded the question only. Context tokens are `project_chars_div_4` estimates, not BPE tokens.

This failure run is **excluded** from the clean-race figures in `race_table.md` and `handoffs.log`
(3964 total context tokens, 2.0x Context Re-Send Multiplier, 3674/3964 = 93% to the Code-Sample Worker).
It is a single-case fault injection, not a race result.

## 12. Shared evaluator limitation (must be recorded)

The shared evaluator scored the failed Multi-Agent run as **correct**:

```
is_correct : True
match_type : contains_token
details    : Answer contains expected exact token 'version'. Overlap ratio: 0.06
```

Root cause — three compounding factors:

1. `hard:01` has `contains_exact_token = True`.
2. The **positive-case** refusal-phrase list is shorter than the negative-case list and omits
   `"unsupported"` and `"unavailable"` — so the genuinely safe refusal text was not recognised as a refusal.
3. Execution therefore fell through to exact-token matching, and the generic word **`version`** — which
   appears in both the golden answer and the refusal text — produced a **false positive at 0.06 overlap**.

**A total upstream failure with zero evidence scored identically to a real answer.**

This is recorded as an **evaluator limitation**, not as a Week 10 success. `eval/evaluator.py` was **not
modified**, and the Week 10 score was **not** retroactively changed. The limitation is pinned as a
characterization test (`test_shared_evaluator_marks_the_safe_refusal_correct`) so the behaviour is visible
in the test suite rather than silently absorbed into the score.

## 13. Test evidence

`tests/test_week10_failure_experiment.py` — **20 passed**, covering: the 500 error shape; that the tool
raises rather than returning empty results; that the worker propagates; no retry; degrade-don't-stop; empty
evidence; squad failure reporting; no fabricated code; no case-detail leakage; refusal naming the failure;
telemetry fields for both hops; provider tokens not faked; code worker succeeding by refusing; context
collapse to the question only; incomplete token summary; injection scoped to exactly one question; default
tool wiring unchanged; failure visibility through the shared race runner; and the evaluator limitation.

Full suite: **207 passed, 0 failures** (134 Week 7/8/9 + 53 Week 10 + 20 failure-experiment).

---

## Conclusion

**The current orchestrator contains the worker failure and refuses downstream code generation rather than
fabricating content, but the shared evaluator can incorrectly classify the safe refusal as correct.**

Specifically: the failure was contained — no retry, no fabricated evidence, no hallucinated code, no
leakage of case-supplied version strings, and an honest `success = False` with full telemetry.

**The evaluator score must NOT be read as evidence of successful failure handling.** On this case the
score was `is_correct = True` for a run that retrieved nothing, purely because a generic token matched.
The safe behavior is real and is demonstrated by the telemetry and the focused tests — not by the score,
which in this instance points the wrong way.