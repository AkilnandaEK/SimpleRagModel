# Trace Observations — Recipe RAG

**File:** `traces/traces.jsonl` (25 traces, 2026-08-26 to 2026-08-27)

## What was observed
- Mixed providers/models in logs: `gemini-3.5-flash` (v1, no provider), `groq/llama-3.3-70b-versatile`, and `groq/openai/gpt-oss-20b`.
- Two collection names used (`recipe_rag_test_corpus`, `trace-test`) for overlapping questions — inconsistent labeling.
- Traces log **retrieval only** (retrieved chunks + distances); no LLM answer or grounded fallback response is recorded.
- In-corpus questions retrieve well (distances ~0.15–0.5, top chunk matches the target recipe).
- Out-of-corpus questions (sushi history, pizza inventor, best restaurant in Bangalore, chicken shelf life, pasta calories) pull off-topic chunks with high distances (~0.6–0.9) — retrieval has no notion of "not in corpus."

## Issues found
1. **Schema inconsistency** — `provider` field missing on some traces (gemini ones); `model_parameters` always empty; collection names inconsistent.
2. **Out-of-corpus leakage** — vague/off-topic queries return recipe chunks as plausible answers; no reliable "I don't know" signal in the trace data to verify grounded fallback works.
3. **No answer captured** — can't evaluate answer quality, citation behavior, or fallback correctness from traces alone.
4. **Query noise** — misspellings ("recipie"), informal phrasing ("give me recipie with coconut") handled fine, but suggest query normalization could help.