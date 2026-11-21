# Build report

Generated 2026-11-21T18:19:49+00:00 · extractor `llm-v0:thinkingmachines/inkling-2-mini` · verifier `verify-v1:deepseek/deepseek-v4.1-flash:rauto+esc:google/gemma-3-27b-it`

## Headline

| Area | Metric | Value |
|---|---|---|
| Crawl | pages in graph / URLs attempted | 1134 / 2271 (207 publishers, 48 seeds) |
| Extraction | triples kept (per page) | 13319 (11.7) |
| Extraction | unquoted (hallucinated-quote) drop rate | 4.0% |
| Verification | citations entailed / rejected / unchecked | 84.0% / 15.9% / 0.1% |
| Trust | edges with >1 publisher · entities with >1 publisher | 161 · 808 |
| Trust | mean edge strength | 0.42 |
| ER | entities before → after (−%) | 10705 → 10219 (−4.5%) |
| ER | auto · LLM same · LLM hierarchy · LLM different | 4 · 509 · 1073 · 1631 |
| Structure | components · largest component · isolated | 2274 · 74.2% · 2132 |
| Structure | avg degree · segments | 1.8 · 117 |
| Cost | $/page · $/verified edge · this build | $0.00178 · $0.00021 · $0.08571 |
| Cost | projected 300 orgs × 12 pages | $6.4 |
| Time | build total (extract+verify) | 663.4s (0.3s) |

## Verifier reject rate by relation

| Relation | Reject % |
|---|---|
| offers | 6.4% |
| publishes | 2.3% |
| serves | 20.0% |
| uses_tech | 27.4% |
| works_on | 33.4% |
| partners_with | 23.2% |
| measured_on | 32.3% |
| uses_method | 25.4% |
| hires_for | 7.6% |
| compares_against | 23.7% |
| invests_in | 37.9% |
| part_of | 32.1% |
| builds_on | 11.4% |
| trained_on | 7.9% |
| cites | 17.5% |
| acquired | 28.9% |
| subtype_of | 33.3% |
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
| claimed | 8788 |
| unsupported | 1793 |
| confirmed | 264 |
| corroborated | 118 |
| verified | 233 |

## Top by PPR from seeds

1. Scale AI (0.0167)
2. NVIDIA (0.0145)
3. Applied Compute (0.0127)
4. Surge AI (0.0119)
5. vLLM (0.0116)
6. OpenAI (0.0114)
7. Safe Superintelligence (0.0112)
8. AI21 Labs (0.0112)
9. SWE-bench (0.0112)
10. Anthropic (0.0111)

## Top by global PageRank (non-seed)

1. Google (0.016)
2. Graphite (0.0066)
3. GitHub (0.0064)
4. Figma (0.0048)
5. impact.com (0.0045)
6. NBCUniversal (0.0038)
7. TechCrunch (0.0034)
8. Stripe (0.0031)
9. Heidi (0.003)
10. Motif (0.0029)

## Crawl failures

- http_403: 87
- http_429: 4
- robots_disallow: 19
- http_404: 34
- error: 469
- http_200: 10
- http_400: 1
- http_406: 1
- http_525: 1
- http_402: 1

## LLM calls by type · model

| Call · model | n | mean $ | mean out tokens |
|---|---|---|---|
| kg_extract · nvidia/nemotron-3.5-lightning | 12 | 0.00194 | 9756 |
| kg_verify · thinkingmachines/inkling-2-mini | 1 | 0.00102 | 2447 |
| kg_extract · thinkingmachines/inkling-2-mini | 1450 | 0.0015 | 3395 |
| kg_extract · nvidia/nemotron-3-super-120b-a12b | 2 | 0.00567 | 10557 |
| kg_verify · nvidia/nemotron-3.5-lightning | 247 | 0.00028 | 1289 |
| kg_verify · deepseek/deepseek-v4.1-flash | 1577 | 0.00028 | 272 |
| kg_verify · openai/gpt-oss-120b | 2 | 0.00031 | 523 |
| kg_verify · qwen/qwen3-30b-a3b-instruct-2507 | 2 | 0.00024 | 426 |
| kg_verify · mistralai/mistral-small-3.2-24b-instruct | 2 | 0.0002 | 404 |
| er_adjudicate · deepseek/deepseek-v4.1-flash | 303 | 0.00062 | 531 |
| segment_names · deepseek/deepseek-v4.1-flash | 11 | 0.00122 | 832 |
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
| kg_verify · google/gemma-3-27b-it | 1087 | 9e-05 | 128 |
| kg_extract · qwen/qwen3.5-35b-a3b | 7 | 0.01011 | 12502 |
