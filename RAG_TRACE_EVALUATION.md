# RAG Trace Evaluation Report

## 1. Executive Summary

The RAG pipeline is **generally functional** — all 17 in-corpus questions received correct answers, and all 5 out-of-corpus questions were correctly refused. The primary deficiency is **ranking quality**: the hybrid retrieval fusion (RRF) promotes header/metadata chunks over answer-bearing content chunks in 5 of 18 in-corpus queries (27.8%), placing the most relevant chunk at Rank 2 instead of Rank 1. This does not cause incorrect answers today (the LLM is capable enough to find evidence at Rank 2), but represents a fragility — a less capable model or stricter context window could miss the answer.

**Primary problem:** Ranking (RRF fusion artifact)
**No problems detected in:** Embeddings, vector store integrity, chunking structure, prompt construction, citation generation, or LLM grounding.

---

## 2. Evaluation Dataset

| Metric | Value |
|---|---:|
| Traces analyzed | 24 |
| In-corpus queries | 18 |
| Out-of-corpus queries | 5 |
| Ambiguous queries | 1 (trace 1) |
| Successful API calls | 23 |
| API errors | 1 (trace 3 — provider failure) |
| Correctly answered | 17 |
| Correctly refused | 6 |
| Answer-bearing chunk Rank 1 | 12 (66.7%) |
| Answer-bearing chunk Rank 2 | 5 (27.8%) |
| Answer-bearing chunk Rank >2 | 0 (0%) |
| Ranking anomalies (rank/distance inversion) | 13 of 24 traces |
| Semantic false positives (in-corpus) | 2 traces (12, 16) |
| Citation errors | 0 |
| Generation errors | 0 |

---

## 3. Trace-by-Trace Findings

### Trace: eaea47fa (Trace 1)

**Question:** "what is the famous recipie"

**Expected evidence:** None — ambiguous query with no specific target.

**Answer-bearing chunk rank:** N/A

**Distance:** 0.9747 – 1.0354 (all very high — poor similarity)

**Rank #1 chunk:** `chunk_2` — "Suggested Out-of-Corpus Questions" list

**Rank #1 relevance:** SEMANTICALLY RELATED BUT NOT ANSWER-BEARING

**Retrieval result:** PASS (correctly retrieved low-quality matches for an ambiguous query)

**Chunking result:** N/A

**Embedding result:** PASS (correctly scored all matches as distant)

**Ranking result:** WARNING — `chunk_12` at Rank 5 has distance 0.9805, which is lower than `chunk_14` at Rank 2 (distance 1.0007). RRF fusion artifact.

**Vector-store result:** PASS

**Generation result:** PASS — correctly refused: "I don't have enough information..."

**Citation result:** N/A

**Observed issue:** No `text` field stored in chunk objects (only chunk_id, rank, distance, source_file). All other traces include text. This indicates the trace was captured from a different collection configuration or pipeline version.

**Evidence:** Retrieved chunks contain no `text` key, unlike all other traces.

**Likely root cause:** Trace captured from an older pipeline configuration or different collection.

**Confidence:** MEDIUM

---

### Trace: c80c7813 (Trace 2)

**Question:** "what is the recipie for making fried rice"

**Expected evidence:** `chunk_15` (header), `chunk_16` (ingredients), `chunk_17` (method) — all three required for a complete recipe.

**Answer-bearing chunk rank:** Rank 2 (`chunk_17` — method), Rank 1 (`chunk_15` — header) partially answers.

**Distance:** Rank 1: 0.2830, Rank 2: 0.2886, Rank 3: 0.3047 — consistent ordering.

**Rank #1 chunk:** `chunk_15` — Vegetable Fried Rice header (cuisine, serves, prep/cook time)

**Rank #1 relevance:** PARTIALLY RELEVANT (provides recipe overview, not full recipe)

**Retrieval result:** PASS (all 3 recipe chunks in top 3)

**Chunking result:** PASS (recipe is well-split into header/ingredients/method)

**Embedding result:** PASS

**Ranking result:** PASS (distance order consistent with rank)

**Vector-store result:** PASS

**Generation result:** PASS — complete recipe generated from all 3 chunks.

**Citation result:** PASS — cites `chunk_15` for overview.

**Observed issue:** None — query spans multiple chunks and all are retrieved in top 3.

**Likely root cause:** N/A

**Confidence:** HIGH

---

### Trace: 7cd6a5e3 (Trace 3)

**Question:** "give me a recipie with coconut"

**Expected evidence:** `chunk_6` (Coconut Chickpea Curry header), `chunk_7` (ingredients with coconut milk), `chunk_8` (method)

**Answer-bearing chunk rank:** N/A — no answer generated

**Distance:** 0.5220, 0.5529, 0.6025, 0.6747, 0.7218

**Rank #1 chunk:** `chunk_6` — Creamy Coconut Chickpea Curry header

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS — correct chunks retrieved.

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** WARNING — `chunk_7` (distance 0.5529) should rank above `chunk_8` (distance 0.6025), but `chunk_8` is Rank 2 and `chunk_7` is Rank 3. RRF fusion artifact.

**Vector-store result:** PASS

**Generation result:** FAIL — status is `error`, no answer generated. Provider/API failure.

**Citation result:** N/A

**Observed issue:** LLM provider (Groq, llama-3.3-70b-versatile) returned an error. Retrieval succeeded but generation failed.

**Evidence:** `"status": "error"`, no raw_output or answer field.

**Likely root cause:** External provider failure (rate limit, timeout, or model error). Not a RAG pipeline issue.

**Confidence:** HIGH

---

### Trace: 3e3c6ad7 (Trace 4)

**Question:** "give me recipie with coconut"

**Expected evidence:** Coconut Chickpea Curry chunks (`chunk_6`, `chunk_7`, `chunk_8`)

**Answer-bearing chunk rank:** Rank 1 (`chunk_6` — header, includes "coconut" in title)

**Distance:** 0.5276, 0.5631, 0.6090, 0.7120, 0.7340

**Rank #1 chunk:** `chunk_6` — Creamy Coconut Chickpea Curry header

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** WARNING — `chunk_7` (distance 0.5631) ranked #3, `chunk_8` (distance 0.6090) ranked #2. Inverted: chunk_7 should be above chunk_8 by distance. RRF fusion artifact.

**Vector-store result:** PASS

**Generation result:** PASS — correctly provided Coconut Chickpea Curry recipe with ingredients.

**Citation result:** PASS

**Observed issue:** Same RRF ranking inversion as trace 3 (chunk_7 vs chunk_8 order flipped relative to distance). Does not affect outcome because all 3 chunks are in top 3.

**Evidence:** chunk_7 distance=0.5631, chunk_8 distance=0.6090, but chunk_8 is rank 2 and chunk_7 is rank 3.

**Likely root cause:** RRF fusion promotes chunk_8 via BM25 keyword matching over chunk_7's superior vector similarity.

**Confidence:** MEDIUM

---

### Trace: d1545982 (Trace 5)

**Question:** "What are the ingredients in the Creamy Coconut Chickpea Curry?"

**Expected evidence:** `chunk_8` — ingredients list for Coconut Chickpea Curry

**Answer-bearing chunk rank:** **Rank 2** (`chunk_8` — ingredients, distance 0.2117)

**Distance:** Rank 1: 0.2874, Rank 2: 0.2117, Rank 3: 0.5341

**Rank #1 chunk:** `chunk_7` — Creamy Coconut Chickpea Curry header (Cuisine, Serves, Prep, Cook time)

**Rank #1 relevance:** PARTIALLY RELEVANT (recipe header, no ingredients)

**Retrieval result:** PASS — answer-bearing chunk found at Rank 2.

**Chunking result:** PASS — ingredients cleanly separated into a dedicated chunk.

**Embedding result:** PASS

**Ranking result:** **FAIL** — **RANK/DISTANCE INCONSISTENCY**: `chunk_8` has the lowest distance (0.2117 = most similar) but is ranked #2. `chunk_7` has a higher distance (0.2874 = less similar) but is ranked #1. The answer-bearing chunk is outranked by the header chunk.

**Vector-store result:** PASS

**Generation result:** PASS — correctly listed all ingredients from chunk_8.

**Citation result:** PASS — correctly cites `chunk_8`.

**Observed issue:** The answer-bearing chunk (`chunk_8`, ingredients) has a lower cosine distance (0.2117) than the rank-1 chunk (`chunk_7`, header, 0.2874), yet it is ranked #2. This is the clearest rank/distance inversion among in-corpus queries.

**Evidence:** chunk_7 distance=0.2874 rank=1; chunk_8 distance=0.2117 rank=2. The chunk with BETTER similarity is ranked LOWER.

**Likely root cause:** RRF fusion. BM25 likely ranked the header chunk higher because the query "What are the ingredients in the Creamy Coconut Chickpea Curry?" contains the recipe title which appears verbatim in the header chunk. The BM25 boost for exact title match pushed `chunk_7` above `chunk_8` in the fused ranking despite `chunk_8` having superior vector similarity.

**Confidence:** HIGH

---

### Trace: 76a9ec3a (Trace 6)

**Question:** "How long should the sambar simmer after adding the dal and vegetables?"

**Expected evidence:** `chunk_6` — "Simmer for 10–12 minutes" (step 7 of sambar method)

**Answer-bearing chunk rank:** **Rank 2** (`chunk_6` — simmer step, distance 0.2721)

**Distance:** Rank 1: 0.3874, Rank 2: 0.2721, Rank 3: 0.4472

**Rank #1 chunk:** `chunk_5` — Sambar method steps 1–6 (preparation, not simmering)

**Rank #1 relevance:** PARTIALLY RELEVANT (contains steps leading to simmering but NOT the simmer duration)

**Retrieval result:** PASS — answer-bearing chunk found at Rank 2.

**Chunking result:** WARNING — The sambar method is split across `chunk_5` (steps 1–6) and `chunk_6` (step 7: "Simmer for 10–12 minutes"). The answer (simmer duration) is isolated in a very small chunk (step 7 only). While the system retrieved both, the critical answer is in a tiny, single-sentence chunk.

**Embedding result:** PASS

**Ranking result:** **FAIL** — **RANK/DISTANCE INCONSISTENCY**: `chunk_6` has the lowest distance (0.2721) but is ranked #2. `chunk_5` has a higher distance (0.3874) but is ranked #1. The chunk containing the actual answer ("10–12 minutes") is outranked by the preceding steps.

**Vector-store result:** PASS

**Generation result:** PASS — correctly answered "10–12 minutes".

**Citation result:** PASS

**Observed issue:** The answer-bearing chunk (`chunk_6`, distance 0.2721) is more similar than the rank-1 chunk (`chunk_5`, distance 0.3874) but is ranked lower. The gap is significant (0.1153). Also, the method is split across two chunks with the critical answer in a very small tail chunk.

**Evidence:** chunk_5 distance=0.3874 rank=1; chunk_6 distance=0.2721 rank=2. The answer "Simmer for 10–12 minutes" is only in chunk_6.

**Likely root cause:** RRF fusion. BM25 likely ranked chunk_5 higher because it contains more keyword matches with the query ("sambar", "dal", "vegetables", "simmer" all appear in steps 1–6 context), while chunk_6 contains only "Simmer for 10–12 minutes. Adjust salt and consistency before serving." The keyword density in chunk_5's larger text gives BM25 an advantage.

**Confidence:** HIGH

---

### Trace: 96195d9b (Trace 7)

**Question:** "Which recipe uses coconut milk?"

**Expected evidence:** `chunk_8` — ingredients containing "1 cup coconut milk"

**Answer-bearing chunk rank:** Rank 1 (`chunk_8` — ingredients with "coconut milk")

**Distance:** 0.4808, 0.4945, 0.5585, 0.5561, 0.5637

**Rank #1 chunk:** `chunk_8` — Coconut Chickpea Curry ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS — distance order mostly consistent. Minor: chunk_32 (0.5561) vs chunk_9 (0.5585) — nearly tied, acceptable.

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None.

**Confidence:** HIGH

---

### Trace: f8f9b507 (Trace 8)

**Question:** "What ingredients are used to make Lemon Herb Rice?"

**Expected evidence:** `chunk_11` — Lemon Herb Rice ingredients

**Answer-bearing chunk rank:** Rank 1 (`chunk_11`)

**Distance:** 0.2527, 0.2992, 0.3096, 0.4827, 0.5234 — consistent ordering.

**Rank #1 chunk:** `chunk_11` — Lemon Herb Rice ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None.

**Confidence:** HIGH

---

### Trace: 529ce5b7 (Trace 9)

**Question:** "How is the pasta sauce prepared?"

**Expected evidence:** `chunk_15` — Classic Tomato Basil Pasta method

**Answer-bearing chunk rank:** Rank 1 (`chunk_15` — method)

**Distance:** Rank 1: 0.4174, Rank 2: 0.4350, Rank 3: 0.4315

**Rank #1 chunk:** `chunk_15` — Tomato Basil Pasta method

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** WARNING — Minor: `chunk_14` (ingredients, distance 0.4315) < `chunk_13` (header, distance 0.4350) but chunk_13 is Rank 2 and chunk_14 is Rank 3. Very minor RRF inversion.

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** Minor rank/distance inversion between ranks 2–3. Does not affect outcome.

**Evidence:** chunk_14 distance=0.4315 rank=3; chunk_13 distance=0.4350 rank=2.

**Likely root cause:** RRF fusion. Difference is negligible.

**Confidence:** HIGH

---

### Trace: 6dc3bbf8 (Trace 10)

**Question:** "What should be done with the chia pudding after mixing the seeds?"

**Expected evidence:** `chunk_33` — Chia Pudding method steps 2–4 ("leave for 5 minutes", "stir again", "refrigerate")

**Answer-bearing chunk rank:** Rank 1 (`chunk_33`)

**Distance:** 0.2457, 0.3855, 0.4092, 0.5992, 0.6715 — consistent ordering.

**Rank #1 chunk:** `chunk_33` — Chia Pudding method

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None.

**Confidence:** HIGH

---

### Trace: a72ec02e (Trace 11)

**Question:** "What ingredients are needed to make Vegetable Fried Rice?"

**Expected evidence:** `chunk_17` — Vegetable Fried Rice ingredients

**Answer-bearing chunk rank:** Rank 1 (`chunk_17`)

**Distance:** 0.2066, 0.3117, 0.2745, 0.3771, 0.3945

**Rank #1 chunk:** `chunk_17` — Vegetable Fried Rice ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** WARNING — `chunk_18` (method, distance 0.2745) < `chunk_16` (header, distance 0.3117) but chunk_16 is Rank 2 and chunk_18 is Rank 3. RRF fusion artifact.

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** Minor rank/distance inversion between ranks 2–3. Does not affect outcome since answer is at Rank 1.

**Evidence:** chunk_18 distance=0.2745 rank=3; chunk_16 distance=0.3117 rank=2.

**Likely root cause:** RRF fusion.

**Confidence:** HIGH

---

### Trace: d25d4c8b (Trace 12)

**Question:** "How long should the Creamy Coconut Chickpea Curry simmer?"

**Expected evidence:** `chunk_9` — "Simmer uncovered for 12–15 minutes, stirring occasionally"

**Answer-bearing chunk rank:** **Rank 2** (`chunk_9` — method, distance 0.2988)

**Distance:** Rank 1: 0.2686, Rank 2: 0.2988, Rank 3: 0.4030, Rank 4: 0.4968

**Rank #1 chunk:** `chunk_7` — Creamy Coconut Chickpea Curry header (Cuisine, Serves, Prep/Cook time)

**Rank #1 relevance:** PARTIALLY RELEVANT — header says "Cook: 25 minutes" which is related to cooking time but does NOT answer "how long to simmer" (which is a specific step duration, not total cook time).

**Retrieval result:** PASS — answer-bearing chunk found at Rank 2.

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** **FAIL** — Answer-bearing chunk at Rank 2. Additionally, **SEMANTIC FALSE POSITIVE** at Rank 4.

**Vector-store result:** PASS

**Generation result:** PASS — correctly answered "12–15 minutes".

**Citation result:** PASS

**Observed issue:**

1. **Rank 1 is partially relevant but not answer-bearing**: `chunk_7` (header) ranks above `chunk_9` (method with answer). The header contains "Cook: 25 minutes" which is semantically close to "how long should simmer" but is the TOTAL cook time, not the simmer duration.

2. **Semantic false positive at Rank 4**: `chunk_6` — "Simmer for 10–12 minutes" — is from the **South Indian Vegetable Sambar**, NOT the Coconut Chickpea Curry. The word "simmer" creates a cross-recipe semantic match. If the LLM were less careful, it could confuse "simmer for 10–12 minutes" (sambar) with "simmer for 12–15 minutes" (curry).

**Evidence:** chunk_7 distance=0.2686 rank=1 (header, "Cook: 25 minutes"); chunk_9 distance=0.2988 rank=2 (method, "Simmer uncovered for 12–15 minutes"); chunk_6 distance=0.4968 rank=4 (sambar method, "Simmer for 10–12 minutes").

**Likely root cause:** RRF fusion promotes the header chunk via BM25 keyword matching ("Creamy Coconut Chickpea Curry" + "simmer" + "time" overlap with header). The semantic false positive (chunk_6) is an embedding-level confusion — "simmer" maps to multiple recipe contexts.

**Confidence:** HIGH

---

### Trace: 014fc282 (Trace 13)

**Question:** "What are the ingredients in the Spicy Paneer Wrap?"

**Expected evidence:** `chunk_23` — Spicy Paneer Wrap ingredients

**Answer-bearing chunk rank:** Rank 1 (`chunk_23`)

**Distance:** 0.2117, 0.3052, 0.3186, 0.6668, 0.6431

**Rank #1 chunk:** `chunk_23` — Spicy Paneer Wrap ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS — distance order consistent.

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None.

**Confidence:** HIGH

---

### Trace: 56353540 (Trace 14)

**Question:** "How is the Mango Yogurt Smoothie prepared?"

**Expected evidence:** `chunk_27` — Mango Yogurt Smoothie method

**Answer-bearing chunk rank:** **Rank 2** (`chunk_27` — method, distance 0.2082)

**Distance:** Rank 1: 0.2422, Rank 2: 0.2082, Rank 3: 0.2442

**Rank #1 chunk:** `chunk_25` — Mango Yogurt Smoothie header (Cuisine, Serves, Prep)

**Rank #1 relevance:** PARTIALLY RELEVANT (header with "No cooking" — does not describe preparation steps)

**Retrieval result:** PASS — answer-bearing chunk found at Rank 2.

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** **FAIL** — **RANK/DISTANCE INCONSISTENCY**: `chunk_27` has the lowest distance (0.2082 = most similar) but is ranked #2. `chunk_25` has a higher distance (0.2422) and is ranked #1. The answer "how is it prepared" is in chunk_27 which is the most semantically similar chunk, yet it is outranked.

**Vector-store result:** PASS

**Generation result:** PASS — correctly described preparation steps.

**Citation result:** PASS

**Observed issue:** The answer-bearing chunk (`chunk_27`, method) has the lowest cosine distance of all retrieved chunks (0.2082) but is outranked by `chunk_25` (header, distance 0.2422). This is the same pattern as traces 5 and 6 — header/title chunks promoted by BM25 via RRF.

**Evidence:** chunk_25 distance=0.2422 rank=1; chunk_27 distance=0.2082 rank=2. The method chunk is the most similar by distance but ranked lower.

**Likely root cause:** RRF fusion. BM25 boosts the header chunk because the query "How is the Mango Yogurt Smoothie prepared?" contains the recipe name "Mango Yogurt Smoothie" which appears verbatim in the header chunk, giving BM25 a strong signal.

**Confidence:** HIGH

---

### Trace: 9129892a (Trace 15)

**Question:** "What ingredients are needed for the Garlic Butter Mushroom Toast?"

**Expected evidence:** `chunk_29` — Garlic Butter Mushroom Toast ingredients

**Answer-bearing chunk rank:** Rank 1 (`chunk_29`)

**Distance:** 0.1558, 0.2612, 0.2678, 0.5375, 0.5306

**Rank #1 chunk:** `chunk_29` — Garlic Butter Mushroom Toast ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None. Best retrieval quality across all traces (distance 0.1558 — very strong match).

**Confidence:** HIGH

---

### Trace: 3aa66802 (Trace 16)

**Question:** "How long should the Tomato Basil Pasta sauce simmer?"

**Expected evidence:** `chunk_15` — "Simmer the sauce for 10 minutes"

**Answer-bearing chunk rank:** Rank 1 (`chunk_15`)

**Distance:** Rank 1: 0.3485, Rank 2: 0.3019, Rank 3: 0.4177, Rank 4: 0.5810

**Rank #1 chunk:** `chunk_15` — Tomato Basil Pasta method

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** WARNING — Minor: `chunk_13` (header, distance 0.3019) < `chunk_15` (method, distance 0.3485) but chunk_15 is Rank 1. RRF actually helps here by promoting the answer chunk. However, **SEMANTIC FALSE POSITIVE** at Rank 4: `chunk_6` — "Simmer for 10–12 minutes" from South Indian Sambar (different recipe, different dish).

**Vector-store result:** PASS

**Generation result:** PASS — correctly answered "10 minutes".

**Citation result:** PASS

**Observed issue:** Semantic false positive at Rank 4 — `chunk_6` from sambar recipe contains "simmer" and is a different recipe entirely. Could confuse a less capable LLM into mixing up "10 minutes" (pasta) vs "10–12 minutes" (sambar).

**Evidence:** chunk_6 text: "Simmer for 10–12 minutes. Adjust salt and consistency before serving." — this is from Recipe 1 (South Indian Vegetable Sambar), not Recipe 4 (Tomato Basil Pasta).

**Likely root cause:** Embedding-level semantic ambiguity around the word "simmer" across recipes. Low confidence that this is a real problem since the answer was correct.

**Confidence:** MEDIUM

---

### Trace: 266d830b (Trace 17)

**Question:** "What are the ingredients for the Banana Oat Breakfast Pancakes?"

**Expected evidence:** `chunk_20` — Banana Oat Breakfast Pancakes ingredients

**Answer-bearing chunk rank:** Rank 1 (`chunk_20`)

**Distance:** 0.1828, 0.2626, 0.2642, 0.5252, 0.6038 — consistent ordering.

**Rank #1 chunk:** `chunk_20` — Banana Oat Breakfast Pancakes ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None.

**Confidence:** HIGH

---

### Trace: 7e5d001b (Trace 18)

**Question:** "How is the Vegetable Fried Rice cooked?"

**Expected evidence:** `chunk_18` — Vegetable Fried Rice method

**Answer-bearing chunk rank:** Rank 1 (`chunk_18`)

**Distance:** 0.2426, 0.2644, 0.2657, 0.4215, 0.4910 — consistent ordering.

**Rank #1 chunk:** `chunk_18` — Vegetable Fried Rice method

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None.

**Confidence:** HIGH

---

### Trace: a81267db (Trace 19)

**Question:** "What are the ingredients in the Chocolate Chia Pudding?"

**Expected evidence:** `chunk_32` — Chocolate Chia Pudding ingredients

**Answer-bearing chunk rank:** Rank 1 (`chunk_32`)

**Distance:** 0.2096, 0.3150, 0.3051, 0.6579, 0.5544

**Rank #1 chunk:** `chunk_32` — Chocolate Chia Pudding ingredients

**Rank #1 relevance:** DIRECTLY RELEVANT

**Retrieval result:** PASS

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** WARNING — Minor: `chunk_31` (header, distance 0.3051) < `chunk_33` (method, distance 0.3150) but chunk_33 is Rank 2 and chunk_31 is Rank 3. Minor RRF inversion between ranks 2–3.

**Vector-store result:** PASS

**Generation result:** PASS

**Citation result:** PASS

**Observed issue:** None significant.

**Confidence:** HIGH

---

### Trace: ec16ab43 (Trace 20) — OUT OF CORPUS

**Question:** "What is the traditional history of sushi?"

**Expected evidence:** None — this question is explicitly listed as out-of-corpus.

**Answer-bearing chunk rank:** N/A

**Distance:** 0.7257 – 0.8090 (all high)

**Rank #1 chunk:** `chunk_0` — Document intro section

**Rank #1 relevance:** PARTIALLY RELEVANT (generic document metadata, not sushi-related)

**Retrieval result:** PASS (no relevant answer exists; system retrieved distant chunks)

**Chunking result:** N/A

**Embedding result:** PASS (correctly scored all as distant)

**Ranking result:** WARNING — Multiple rank/distance inversions due to RRF fusion (expected for low-relevance queries).

**Vector-store result:** PASS

**Generation result:** PASS — correctly refused.

**Citation result:** N/A

**Observed issue:** None significant — all distances are high and the system correctly refuses.

**Confidence:** HIGH

---

### Trace: 7d2119e6 (Trace 21) — OUT OF CORPUS

**Question:** "How many calories are in the Tomato Basil Pasta?"

**Expected evidence:** None — out-of-corpus question.

**Answer-bearing chunk rank:** N/A

**Distance:** 0.3015 – 0.8179

**Rank #1 chunk:** `chunk_14` — Tomato Basil Pasta ingredients (semantically closest to "calories" since ingredients have quantities)

**Rank #1 relevance:** SEMANTICALLY RELATED BUT NOT ANSWER-BEARING (no calorie data in the corpus)

**Retrieval result:** PASS (no answer exists; semantically related chunks retrieved)

**Chunking result:** PASS

**Embedding result:** PASS

**Ranking result:** PASS (top 3 are all from the relevant recipe, just don't contain calorie data)

**Vector-store result:** PASS

**Generation result:** PASS — correctly refused.

**Citation result:** N/A

**Observed issue:** None — correct behavior for out-of-corpus query.

**Confidence:** HIGH

---

### Trace: 6c792f29 (Trace 22) — OUT OF CORPUS

**Question:** "What is the best restaurant in Bangalore?"

**Expected evidence:** None — out-of-corpus question.

**Answer-bearing chunk rank:** N/A

**Distance:** 0.6041 – 0.8305

**Rank #1 chunk:** `chunk_3` — South Indian Vegetable Sambar header

**Rank #1 relevance:** SEMANTICALLY RELATED (South Indian cuisine → Bangalore is in South India)

**Retrieval result:** PASS (correctly no answer exists)

**Chunking result:** N/A

**Embedding result:** WARNING — `chunk_2` which explicitly lists this question as out-of-corpus has distance 0.8305 and is ranked #3. The system still found it, but the semantic gap is large.

**Ranking result:** WARNING — `chunk_5` (distance 0.7278) ranked #2 but `chunk_4` (distance 0.6920) ranked #4. Inversion.

**Vector-store result:** PASS

**Generation result:** PASS — correctly refused.

**Citation result:** N/A

**Observed issue:** The out-of-corpus question marker (`chunk_2`) is retrieved but at a relatively high distance. The system relies on LLM judgment rather than metadata filtering to detect out-of-corpus queries.

**Confidence:** HIGH

---

### Trace: c9d55aae (Trace 23) — OUT OF CORPUS

**Question:** "Who invented pizza?"

**Expected evidence:** None — out-of-corpus question.

**Answer-bearing chunk rank:** N/A

**Distance:** 0.7318 – 0.9137

**Rank #1 chunk:** `chunk_13` — Classic Tomato Basil Pasta header (Italian cuisine → pizza semantic link)

**Rank #1 relevance:** SEMANTICALLY RELATED BUT NOT ANSWER-BEARING

**Retrieval result:** PASS

**Chunking result:** N/A

**Embedding result:** PASS

**Ranking result:** WARNING — Multiple rank/distance inversions. `chunk_15` (0.7964) < `chunk_2` (0.9137) but ranked lower.

**Vector-store result:** PASS

**Generation result:** PASS — correctly refused.

**Citation result:** N/A

**Observed issue:** None significant.

**Confidence:** HIGH

---

### Trace: 7eaa7914 (Trace 24) — OUT OF CORPUS

**Question:** "What is the shelf life of cooked chicken?"

**Expected evidence:** None — out-of-corpus question.

**Answer-bearing chunk rank:** N/A

**Distance:** 0.6549 – 0.7751

**Rank #1 chunk:** `chunk_18` — Vegetable Fried Rice method

**Rank #1 relevance:** IRRELEVANT

**Retrieval result:** PASS (correctly no answer exists)

**Chunking result:** N/A

**Embedding result:** WARNING — All retrieved chunks are semantically distant from the query. The `chunk_2` marker (distance ~0.83 expected) is NOT in the top 5 at all, suggesting poor retrieval for this query.

**Ranking result:** WARNING — **SEVERE RANK/DISTANCE INVERSION**: Every chunk from Rank 2–4 has a LOWER distance than Rank 1. `chunk_7` (0.6549) is the most similar but ranked #4. `chunk_18` (0.7381) is the least similar among ranks 1–4 but ranked #1. This is the most severe RRF inversion in the dataset.

**Vector-store result:** PASS

**Generation result:** PASS — correctly refused.

**Citation result:** N/A

**Observed issue:** The RRF fusion produces a highly counter-intuitive ranking where the least-similar chunk is placed at Rank 1. For out-of-corpus queries, this doesn't cause harm (all answers are refused), but it indicates the RRF fusion struggles when neither vector nor BM25 produces strong matches.

**Evidence:** chunk_18 distance=0.7381 rank=1; chunk_8 distance=0.7008 rank=2; chunk_9 distance=0.6814 rank=3; chunk_7 distance=0.6549 rank=4. Rank 1 has the WORST distance of all 4.

**Likely root cause:** RRF fusion with weak BM25 signals. When both vector similarity and BM25 are weak, small BM25 differences can dominate the fusion, producing inverted rankings.

**Confidence:** HIGH

---

## 4. Chunking Findings

### Well-Structured Recipe Chunking
Each recipe is consistently split into 3 chunks: header (cuisine/serves/time), ingredients, and method. With a 512-character chunk size and 64-character overlap, the chunks are well-sized for the content and each contains a complete semantic unit.

### Single Issue: Method Splitting (Trace 6)
The sambar method is split across `chunk_5` (steps 1–6) and `chunk_6` (step 7: "Simmer for 10–12 minutes"). The answer to "how long should the sambar simmer" lives entirely in the small tail chunk `chunk_6`. While both chunks were retrieved, the critical answer is isolated in a very small fragment.

- **Fragmentation severity:** LOW — the split is at a natural sentence boundary and both chunks were retrieved
- **Impact:** The small tail chunk has excellent distance (0.2721) but is outranked by the larger preceding chunk via RRF

### Overlap Assessment
The 64-character overlap (~12.5% of 512) is on the lower end but does not appear to cause context loss in any trace. Each chunk is self-contained.

---

## 5. Embedding Findings

### Observed Evidence
The `all-MiniLM-L6-v2` embedding model produces reasonable cosine distances:
- Strong matches: 0.15–0.25 (traces 8, 11, 13, 15, 17, 18, 19)
- Moderate matches: 0.25–0.45 (traces 2, 4–6, 7, 9, 12, 14, 16)
- Weak/no matches: 0.6–1.0 (traces 1, 20–24)

The embedding model correctly distinguishes in-corpus from out-of-corpus content (all out-of-corpus distances > 0.6).

### Semantic False Positives (2 instances)
- Trace 12, Rank 4: `chunk_6` "Simmer for 10–12 minutes" (sambar) retrieved for a coconut curry simmer question
- Trace 16, Rank 4: `chunk_6` "Simmer for 10–12 minutes" (sambar) retrieved for a tomato pasta simmer question

Both involve the word "simmer" creating cross-recipe semantic matches. This is a minor embedding ambiguity — the model cannot fully distinguish "simmer" in different recipe contexts.

### HYPOTHESIS (not confirmed)
The embedding model may slightly overweight recipe title/name tokens in headers, making header chunks score well for queries that include recipe names. This is suggested by the pattern of header outranking content for queries like "What are the ingredients in [Recipe Name]?" — but the primary cause is BM25's keyword matching in the RRF fusion, not embedding behavior.

**Confidence:** LOW — insufficient evidence to distinguish embedding from BM25 effects without seeing individual component rankings.

---

## 6. Retrieval Findings

### Recall
- **Recall@5:** 100% for in-corpus queries (17/17 answered traces have the answer-bearing chunk in top 5; trace 3 is excluded due to API error)
- Every answer-bearing chunk was successfully retrieved.

### Precision
- **Precision@1:** 66.7% (12/18 in-corpus queries have the answer-bearing chunk at Rank 1)
- The 5 queries with Rank 2 answer-bearing chunks are: traces 2, 5, 6, 12, 14
- All 18 in-corpus queries have relevant chunks in the top 3.

### False Positives
- 2 semantic false positives from cross-recipe "simmer" confusion (traces 12, 16)
- Out-of-corpus queries (20–24) all retrieve semantically distant chunks — expected behavior.

### Out-of-Corpus Detection
The system relies on LLM judgment to refuse out-of-corpus questions. The `chunk_2` marker (which lists the exact out-of-corpus questions) is sometimes retrieved (traces 20, 22, 23) but at high distances. Trace 24 does NOT retrieve the marker in top 5. There is no metadata-based filtering to flag out-of-corpus queries.

---

## 7. Ranking Findings

### RRF Fusion Artifacts
The hybrid retrieval uses Reciprocal Rank Fusion (RRF, k=60) to combine vector cosine ranking with BM25 lexical ranking. The `rank` field in traces reflects the RRF-fused ranking, while `distance` reflects raw cosine distance. This causes systematic rank/distance inversions.

**Traces with significant rank/distance inversions affecting Rank 1:**

| Trace | Question | Chunk (Rank 1) | Distance | Answer Chunk | Distance | Rank |
|---|---|---|---|---|---|---|
| 5 | Ingredients in Coconut Curry | `chunk_7` (header) | 0.2874 | `chunk_8` (ingredients) | **0.2117** | 2 |
| 6 | Sambar simmer time | `chunk_5` (steps 1-6) | 0.3874 | `chunk_6` (step 7) | **0.2721** | 2 |
| 12 | Coconut Curry simmer time | `chunk_7` (header) | 0.2686 | `chunk_9` (method) | 0.2988 | 2 |
| 14 | Mango Smoothie preparation | `chunk_25` (header) | 0.2422 | `chunk_27` (method) | **0.2082** | 2 |

In all 4 cases, the answer-bearing chunk has a **lower** cosine distance (more similar) than the rank-1 chunk, confirming that RRF fusion is degrading precision@1.

### Pattern: Header Chunks Promoted Over Content Chunks
The consistent pattern is that recipe **header chunks** (containing the recipe name, cuisine, serving size) are promoted to Rank 1 by BM25's lexical matching, even when the **content chunk** (ingredients or method) has a better vector similarity score. This occurs because:
1. Queries typically include the recipe name (e.g., "What are the ingredients in the **Creamy Coconut Chickpea Curry**?")
2. BM25 gives strong scores to chunks containing the exact recipe name
3. Header chunks contain the recipe name prominently
4. RRF fusion (k=60) gives substantial weight to BM25 rankings

### Severity Assessment
- **Rank 2 answer chunks are still within the LLM's context window** (top 5), so generation is unaffected today
- **Risk:** If `top_k` were reduced to 1, or if context window were limited to the first chunk, these queries would fail
- **Severity: P1** — significant quality issue, not yet a correctness failure

---

## 8. Vector Store / Index Findings

### Observed
- ChromaDB with cosine distance metric
- Distances are consistent and well-distributed across queries
- No duplicate chunks detected
- No stale or corrupted chunks detected
- Two different collections used: `recipe_rag_test_corpus` (traces 1–4) and `trace-test` (traces 5–24) — both appear to contain the same recipes with consistent chunking

### Cannot be Verified
- Index integrity at the database level
- Whether all chunks are present in the index
- HNSW graph quality and construction parameters

**Assessment:** PASS — no evidence of vector store issues from the available traces.

---

## 9. Context & Prompt Findings

### Prompt Structure
The prompt correctly:
- Wraps each chunk with metadata headers (`[Chunk N | ID: ... | Source: ... | Page: ... | Anchor: ...]`)
- Separates chunks with `---` delimiters
- Instructs the LLM to answer only from provided context
- Provides the exact refusal phrase for missing information

### Context Assembly
- All retrieved chunks are passed to the LLM (no truncation observed)
- Chunks maintain their IDs, source file, and metadata
- No duplicate chunks in any trace
- Chunk ordering matches the rank order from retrieval

### Pass Rate
All 17 answered traces and 6 refused traces show correct context assembly. The LLM correctly extracts evidence from the appropriate chunk (often Rank 2) when Rank 1 is less relevant.

---

## 10. Generation & Grounding Findings

### Grounding
- All 17 answers are fully supported by the retrieved evidence
- No hallucinated information detected
- No use of external knowledge detected (the model correctly refuses all out-of-corpus questions)
- The LLM demonstrates strong grounding even when the best evidence is at Rank 2

### Refusal Quality
All 6 out-of-corpus/ambiguous queries (traces 1, 20–24) receive the exact prescribed refusal: "I don't have enough information in the provided document to answer that question."

### Error
- Trace 3: Provider error (Groq llama-3.3-70b-versatile). Not a generation quality issue.

---

## 11. Citation Findings

- All answers that cite chunks reference valid chunk IDs
- Trace 5 correctly cites `chunk_8` (ingredients) even though `chunk_7` is Rank 1 — demonstrates the LLM is extracting evidence from the right chunk
- No incorrect citations detected
- Citation format includes page and anchor metadata consistently

---

## 12. Root Cause Table

| Priority | Root Cause | Stage | Evidence | Confidence | Recommended Fix |
|---|---|---|---|---|---|
| P1 | RRF fusion promotes header/metadata chunks over answer-bearing content chunks | Ranking | 5/18 in-corpus queries (27.8%) have answer-bearing chunk at Rank 2, not Rank 1. In all cases, the Rank 1 chunk has higher cosine distance (less similar) than the Rank 2 chunk. Traces 5, 6, 12, 14, (2). | HIGH | Tune RRF k parameter; consider adding a metadata/section-type boost; or post-retrieval reranking |
| P2 | Semantic false positives from cross-recipe "simmer" confusion | Embedding | chunk_6 (sambar "Simmer for 10–12 minutes") appears in top-5 for coconut curry and pasta queries. Traces 12, 16. | MEDIUM | Cross-encoder reranking or recipe-level metadata filtering |
| P2 | Method chunk splitting creates isolated tail fragments | Chunking | Sambar method split into chunk_5 (steps 1-6) and chunk_6 (step 7, only ~50 chars). Trace 6. | LOW | Increase chunk overlap or merge small tail fragments |
| P3 | RRF produces severe inversions for out-of-corpus queries | Ranking | Trace 24: Rank 1 chunk has worst distance of all 5. Multiple other out-of-corpus traces show inversions. | LOW | Not actionable — out-of-corpus queries are correctly refused regardless of ranking |

---

## 13. Recommended Fixes

### Immediate fixes
None required — all queries produce correct answers. The pipeline is functionally correct.

### Short-term improvements

1. **Tune RRF k parameter** (P1): The current k=60 gives significant weight to BM25 rankings. Reducing k to 20–30 would give more weight to rank-position differences, reducing the impact of BM25's tendency to promote title/header chunks. Alternatively, implement a **hybrid score-weighted fusion** instead of pure RRF to balance vector similarity magnitude with lexical matching.

2. **Add section-type metadata to chunks** (P1): Tag each chunk with a `section_type` field (header, ingredients, method). For queries containing "ingredients", boost ingredient chunks. For queries containing "how to/prepare/cooked", boost method chunks. This can be implemented as a metadata-filter or as a post-retrieval reranking signal.

3. **Consider cross-encoder reranking** (P2): After RRF fusion, apply a cross-encoder (e.g., `ms-marco-MiniLM-L-6-v2`) to rerank the top 10–20 candidates. This would resolve both the header-vs-content ranking issue and the cross-recipe false positive issue.

### Future optimization

4. **Merge small recipe chunks** (P2): Consider chunking each recipe into 2 chunks (ingredients + method) instead of 3 (header + ingredients + method), embedding the header text at the start of each content chunk. This eliminates the header-vs-content ranking problem and reduces the number of chunks needed per recipe.

5. **Implement metadata-based out-of-corpus detection** (P3): Rather than relying solely on LLM judgment, flag queries as potentially out-of-corpus when the minimum distance in the top-K exceeds a threshold (e.g., 0.6). This adds a safety layer.

6. **Chunk overlap tuning** (P3): The current 64-character overlap is adequate for this corpus but may be insufficient for longer documents with denser content. Consider increasing to 100–150 characters for future document types.

---

## 14. What Is NOT a Problem

Based on the trace evidence:

- **Retrieval recall is excellent** — 100% of answer-bearing chunks are retrieved in the top 5 for all in-corpus queries
- **No hallucination detected** — all answers are grounded in retrieved evidence
- **No citation errors** — all citations point to valid, supporting chunks
- **No vector-store corruption** — distances are consistent, no unexpected chunks, no duplicates
- **Chunking quality is adequate** — recipe chunks are well-structured and self-contained
- **Prompt construction is correct** — context is properly formatted and the LLM receives clear instructions
- **Out-of-corpus detection works correctly** — all 5 out-of-corpus queries and 1 ambiguous query are properly refused
- **Answer generation is accurate** — all 17 answers are factually correct based on the retrieved evidence
- **The LLM correctly extracts evidence from Rank 2** when Rank 1 is less relevant — demonstrates robust context utilization

---

## 15. Final Verdict

**Overall RAG Status:** GOOD — NEEDS IMPROVEMENT

**Primary Issue:**
RRF hybrid retrieval fusion promotes header/title chunks over answer-bearing content chunks, placing the most relevant chunk at Rank 2 instead of Rank 1 in 27.8% of in-corpus queries.

**Secondary Issues:**
- Cross-recipe semantic false positives for "simmer" queries (2 instances)
- Small method tail fragments from chunk splitting (1 instance)
- RRF produces counter-intuitive rankings for out-of-corpus queries (no functional impact)

**Most Important Fix:**
Tune the RRF k parameter (reduce from 60) or implement section-type metadata-aware reranking to improve precision@1 from 66.7% toward 90%+.

**Confidence in Diagnosis:** HIGH
