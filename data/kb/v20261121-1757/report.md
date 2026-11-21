# Build report

Generated 2026-11-21T17:56:33+00:00 · extractor `llm-v0:thinkingmachines/inkling-2-mini` · verifier `verify-v1:deepseek/deepseek-v4.1-flash:rauto+esc:google/gemma-3-27b-it`

## Headline

| Area | Metric | Value |
|---|---|---|
| Crawl | pages in graph / URLs attempted | 946 / 1635 (207 publishers, 48 seeds) |
| Extraction | triples kept (per page) | 11360 (12.0) |
| Extraction | unquoted (hallucinated-quote) drop rate | 3.7% |
| Verification | citations entailed / rejected / unchecked | 84.0% / 16.0% / 0.0% |
| Trust | edges with >1 publisher · entities with >1 publisher | 149 · 704 |
| Trust | mean edge strength | 0.423 |
| ER | entities before → after (−%) | 9484 → 9150 (−3.5%) |
| ER | auto · LLM same · LLM hierarchy · LLM different | 4 · 340 · 738 · 1472 |
| Structure | components · largest component · isolated | 2022 · 73.7% · 1892 |
| Structure | avg degree · segments | 1.77 · 120 |
| Cost | $/page · $/verified edge · this build | $0.00188 · $0.00022 · $0.07218 |
| Cost | projected 300 orgs × 12 pages | $6.78 |
| Time | build total (extract+verify) | 482.2s (0.2s) |

## Verifier reject rate by relation

| Relation | Reject % |
|---|---|
| offers | 6.3% |
| publishes | 2.2% |
| serves | 20.4% |
| uses_tech | 28.5% |
| works_on | 32.7% |
| partners_with | 23.8% |
| uses_method | 26.4% |
| measured_on | 37.0% |
| hires_for | 7.3% |
| compares_against | 28.5% |
| invests_in | 38.3% |
| part_of | 34.2% |
| builds_on | 9.7% |
| trained_on | 7.7% |
| cites | 25.0% |
| acquired | 22.2% |
| subtype_of | 31.2% |
| requires | 66.7% |

## Publishers with the highest reject rate (≥10 citations)

| Publisher | Reject % | Citations |
|---|---|---|
| lens.google | 91.7% | 12 |
| arxiv.org | 85.7% | 21 |
| beam.google | 65.0% | 20 |
| nsf.gov | 64.7% | 17 |
| gendo.ai | 63.1% | 65 |
| families.google | 61.5% | 13 |

## Edge status

| Status | Edges |
|---|---|
| claimed | 7670 |
| unsupported | 1563 |
| confirmed | 213 |
| corroborated | 110 |
| verified | 237 |

## Top by PPR from seeds

1. Scale AI (0.017)
2. Applied Compute (0.014)
3. NVIDIA (0.0139)
4. Surge AI (0.0122)
5. OpenAI (0.0116)
6. vLLM (0.0114)
7. Safe Superintelligence (0.0113)
8. AI21 Labs (0.0113)
9. SWE-bench (0.0113)
10. Mistral (0.0113)

## Top by global PageRank (non-seed)

1. Google (0.0179)
2. Graphite (0.0074)
3. GitHub (0.0072)
4. Figma (0.0054)
5. impact.com (0.005)
6. NBCUniversal (0.0042)
7. TechCrunch (0.0037)
8. Stripe (0.0035)
9. Heidi (0.0034)
10. Motif (0.0033)

## Crawl failures

- http_403: 63
- http_429: 4
- robots_disallow: 17
- http_404: 32
- error: 266
- http_200: 3
- http_400: 1
- http_406: 1
- http_525: 1

## LLM calls by type · model

| Call · model | n | mean $ | mean out tokens |
|---|---|---|---|
| kg_extract · nvidia/nemotron-3.5-lightning | 12 | 0.00194 | 9756 |
| kg_verify · thinkingmachines/inkling-2-mini | 1 | 0.00102 | 2447 |
| kg_extract · thinkingmachines/inkling-2-mini | 1152 | 0.00159 | 3505 |
| kg_extract · nvidia/nemotron-3-super-120b-a12b | 2 | 0.00567 | 10557 |
| kg_verify · nvidia/nemotron-3.5-lightning | 247 | 0.00028 | 1289 |
| kg_verify · deepseek/deepseek-v4.1-flash | 1293 | 0.00029 | 285 |
| kg_verify · openai/gpt-oss-120b | 2 | 0.00031 | 523 |
| kg_verify · qwen/qwen3-30b-a3b-instruct-2507 | 2 | 0.00024 | 426 |
| kg_verify · mistralai/mistral-small-3.2-24b-instruct | 2 | 0.0002 | 404 |
| er_adjudicate · deepseek/deepseek-v4.1-flash | 174 | 0.0006 | 523 |
| segment_names · deepseek/deepseek-v4.1-flash | 7 | 0.0016 | 1099 |
| bench_kg_tools · thinkingmachines/inkling-2-mini | 148 | 0.0002 | 175 |
| kg_verify · qwen/qwen3.5-35b-a3b | 211 | 0.00013 | 71 |
| bench_closed_book · qwen/qwen3.5-35b-a3b | 40 | 0.00127 | 1278 |
| kg_verify · thinkingmachines/inkling-2-small | 211 | 0.00046 | 408 |
| bench_kg_tools · qwen/qwen3.5-35b-a3b | 329 | 0.00091 | 269 |
| kg_verify · mistralai/mistral-small-2603 | 211 | 6e-05 | 43 |
| er_adjudicate · nvidia/nemotron-3.5-lightning | 11 | 0.00019 | 480 |
| er_adjudicate · mistralai/mistral-small-2603 | 11 | 0.00057 | 474 |
| er_adjudicate · qwen/qwen3.5-35b-a3b | 11 | 0.00073 | 540 |
| bench_oracle · qwen/qwen3.5-35b-a3b | 40 | 0.00185 | 1913 |
| bench_closed_book · thinkingmachines/inkling-2-mini | 20 | 0.00035 | 866 |
| er_adjudicate · thinkingmachines/inkling-2-small | 5 | 0.00215 | 1596 |
| bench_oracle · thinkingmachines/inkling-2-mini | 20 | 0.00075 | 1491 |
| bench_closed_book · nvidia/nemotron-3.5-lightning | 20 | 0.00013 | 604 |
| bench_kg_tools · nvidia/nemotron-3.5-lightning | 191 | 0.00014 | 85 |
| bench_oracle · nvidia/nemotron-3.5-lightning | 20 | 0.00024 | 719 |
| bench_closed_book · mistralai/mistral-small-2603 | 20 | 0.00048 | 711 |
| bench_kg_tools · mistralai/mistral-small-2603 | 142 | 0.00042 | 189 |
| bench_oracle · mistralai/mistral-small-2603 | 20 | 0.00061 | 577 |
| kg_verify · google/gemma-3-27b-it | 837 | 0.0001 | 135 |
| kg_extract · qwen/qwen3.5-35b-a3b | 7 | 0.01011 | 12502 |
