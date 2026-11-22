# Build report

Generated 2026-11-22T00:16:59+00:00 · extractor `llm-v0:thinkingmachines/inkling-2-mini` · verifier `verify-v1:deepseek/deepseek-v4.1-flash:rauto+esc:google/gemma-3-27b-it`

## Headline

| Area | Metric | Value |
|---|---|---|
| Crawl | pages in graph / URLs attempted | 1921 / 3923 (254 publishers, 48 seeds) |
| Extraction | triples kept (per page) | 22035 (11.5) |
| Extraction | unquoted (hallucinated-quote) drop rate | 3.7% |
| Verification | citations entailed / rejected / unchecked | 83.6% / 16.3% / 0.1% |
| Trust | edges with >1 publisher · entities with >1 publisher | 382 · 1427 |
| Trust | mean edge strength | 0.423 |
| ER | entities before → after (−%) | 16385 → 15544 (−5.1%) |
| ER | auto · LLM same · LLM hierarchy · LLM different | 11 · 877 · 1869 · 3253 |
| Structure | components · largest component · isolated | 3432 · 75.0% · 3257 |
| Structure | avg degree · segments | 1.87 · 133 |
| Cost | $/page · $/verified edge · this build | $0.00168 · $0.00022 · $0.1732 |
| Cost | projected 300 orgs × 12 pages | $6.04 |
| Time | build total (extract+verify) | 3322.6s (0.6s) |

## Verifier reject rate by relation

| Relation | Reject % |
|---|---|
| offers | 6.0% |
| publishes | 2.1% |
| uses_tech | 26.3% |
| serves | 18.7% |
| works_on | 32.8% |
| partners_with | 25.1% |
| measured_on | 38.0% |
| uses_method | 24.7% |
| compares_against | 22.4% |
| hires_for | 7.5% |
| invests_in | 35.9% |
| part_of | 27.4% |
| builds_on | 11.8% |
| trained_on | 12.7% |
| cites | 14.4% |
| acquired | 29.0% |
| subtype_of | 54.3% |
| requires | 70.6% |

## Publishers with the highest reject rate (≥10 citations)

| Publisher | Reject % | Citations |
|---|---|---|
| al-jammaz.com | 93.3% | 45 |
| lens.google | 91.7% | 12 |
| arxiv.org | 85.7% | 21 |
| alphaxiv.org | 70.6% | 17 |
| beam.google | 65.0% | 20 |
| nsf.gov | 64.7% | 17 |

## Edge status

| Status | Edges |
|---|---|
| corroborated | 310 |
| claimed | 13591 |
| unsupported | 3023 |
| confirmed | 538 |
| verified | 468 |

## Top by PPR from seeds

1. NVIDIA (0.0127)
2. Anthropic (0.0115)
3. Epoch AI (0.0113)
4. Safe Superintelligence (0.0111)
5. SWE-bench (0.0111)
6. vLLM (0.0108)
7. Surge AI (0.0106)
8. Fireworks AI (0.0105)
9. AI21 Labs (0.0104)
10. Cohere (0.0104)

## Top by global PageRank (non-seed)

1. Google (0.0107)
2. Graphite (0.0047)
3. Microsoft (0.0042)
4. GitHub (0.0041)
5. Flutter (0.0035)
6. Alibaba Cloud (0.0034)
7. Figma (0.0031)
8. impact.com (0.003)
9. MIT Technology Review (0.003)
10. Ideogram (0.0028)

## Crawl failures

- http_403: 143
- http_429: 10
- robots_disallow: 40
- http_404: 38
- error: 1119
- http_200: 12
- http_400: 1
- http_406: 1
- http_525: 1
- http_402: 1
- http_500: 1
- http_530: 2
- http_522: 1
- http_202: 2

## LLM calls by type · model

| Call · model | n | mean $ | mean out tokens |
|---|---|---|---|
| kg_extract · nvidia/nemotron-3.5-lightning | 12 | 0.00194 | 9756 |
| kg_verify · thinkingmachines/inkling-2-mini | 1 | 0.00102 | 2447 |
| kg_extract · thinkingmachines/inkling-2-mini | 2109 | 0.0014 | 3283 |
| kg_extract · nvidia/nemotron-3-super-120b-a12b | 2 | 0.00567 | 10557 |
| kg_verify · nvidia/nemotron-3.5-lightning | 344 | 0.00021 | 937 |
| kg_verify · deepseek/deepseek-v4.1-flash | 2196 | 0.00028 | 268 |
| kg_verify · openai/gpt-oss-120b | 2 | 0.00031 | 523 |
| kg_verify · qwen/qwen3-30b-a3b-instruct-2507 | 2 | 0.00024 | 426 |
| kg_verify · mistralai/mistral-small-3.2-24b-instruct | 2 | 0.0002 | 404 |
| er_adjudicate · deepseek/deepseek-v4.1-flash | 545 | 0.00066 | 546 |
| segment_names · deepseek/deepseek-v4.1-flash | 15 | 0.00113 | 735 |
| bench_kg_tools · thinkingmachines/inkling-2-mini | 148 | 0.0002 | 175 |
| kg_verify · qwen/qwen3.5-35b-a3b | 308 | 0.00013 | 65 |
| bench_closed_book · qwen/qwen3.5-35b-a3b | 40 | 0.00127 | 1278 |
| kg_verify · thinkingmachines/inkling-2-small | 308 | 0.00042 | 380 |
| bench_kg_tools · qwen/qwen3.5-35b-a3b | 329 | 0.00091 | 269 |
| kg_verify · mistralai/mistral-small-2603 | 308 | 6e-05 | 40 |
| er_adjudicate · nvidia/nemotron-3.5-lightning | 15 | 0.00019 | 485 |
| er_adjudicate · mistralai/mistral-small-2603 | 15 | 0.00056 | 462 |
| er_adjudicate · qwen/qwen3.5-35b-a3b | 15 | 0.00068 | 511 |
| bench_oracle · qwen/qwen3.5-35b-a3b | 40 | 0.00185 | 1913 |
| bench_closed_book · thinkingmachines/inkling-2-mini | 20 | 0.00035 | 866 |
| er_adjudicate · thinkingmachines/inkling-2-small | 9 | 0.0021 | 1587 |
| bench_oracle · thinkingmachines/inkling-2-mini | 20 | 0.00075 | 1491 |
| bench_closed_book · nvidia/nemotron-3.5-lightning | 20 | 0.00013 | 604 |
| bench_kg_tools · nvidia/nemotron-3.5-lightning | 191 | 0.00014 | 85 |
| bench_oracle · nvidia/nemotron-3.5-lightning | 20 | 0.00024 | 719 |
| bench_closed_book · mistralai/mistral-small-2603 | 20 | 0.00048 | 711 |
| bench_kg_tools · mistralai/mistral-small-2603 | 142 | 0.00042 | 189 |
| bench_oracle · mistralai/mistral-small-2603 | 20 | 0.00061 | 577 |
| kg_verify · google/gemma-3-27b-it | 1591 | 9e-05 | 130 |
| kg_extract · qwen/qwen3.5-35b-a3b | 11 | 0.00868 | 10654 |
| task_write · thinkingmachines/inkling-2-mini | 200 | 0.00015 | 434 |
| session_oracle · nvidia/nemotron-3.5-lightning | 736 | 9e-05 | 207 |
| session_oracle · mistralai/mistral-small-2603 | 312 | 0.00019 | 164 |
| session_closed_book · nvidia/nemotron-3.5-lightning | 80 | 8e-05 | 229 |
| session_graph_rag · nvidia/nemotron-3.5-lightning | 67 | 0.00025 | 209 |
| session_kg_tools · nvidia/nemotron-3.5-lightning | 197 | 0.00021 | 88 |
| session_kg_tools_format · nvidia/nemotron-3.5-lightning | 64 | 0.00028 | 184 |
| session_graph_query · nvidia/nemotron-3.5-lightning | 130 | 9e-05 | 75 |
| session_graph_query_format · nvidia/nemotron-3.5-lightning | 49 | 0.0001 | 104 |
| session_closed_book · thinkingmachines/inkling-2-small | 85 | 0.00036 | 459 |
| session_graph_rag · thinkingmachines/inkling-2-small | 40 | 0.00084 | 565 |
| session_kg_tools · thinkingmachines/inkling-2-small | 1426 | 0.00043 | 197 |
| session_kg_tools_format · thinkingmachines/inkling-2-small | 421 | 0.00082 | 453 |
| session_graph_query · thinkingmachines/inkling-2-small | 1539 | 0.0003 | 185 |
| session_graph_query_format · thinkingmachines/inkling-2-small | 421 | 0.0006 | 366 |
| session_oracle · thinkingmachines/inkling-2-small | 85 | 0.00044 | 462 |
| probe · nvidia/nemotron-3.5-lightning | 3 | 8e-05 | 48 |
| session_closed_book · qwen/qwen3.5-35b-a3b | 81 | 0.00026 | 197 |
| session_graph_rag · qwen/qwen3.5-35b-a3b | 36 | 0.00068 | 211 |
| session_kg_tools · qwen/qwen3.5-35b-a3b | 1220 | 0.00051 | 167 |
| session_kg_tools_format · qwen/qwen3.5-35b-a3b | 351 | 0.00068 | 263 |
| session_graph_query · qwen/qwen3.5-35b-a3b | 1091 | 0.00032 | 133 |
| session_graph_query_format · qwen/qwen3.5-35b-a3b | 323 | 0.00042 | 210 |
| session_oracle · qwen/qwen3.5-35b-a3b | 81 | 0.00038 | 249 |
| session_closed_book · mistralai/mistral-small-2603 | 36 | 0.00015 | 156 |
| session_graph_rag · mistralai/mistral-small-2603 | 36 | 0.00052 | 98 |
| session_kg_tools · mistralai/mistral-small-2603 | 145 | 0.00027 | 92 |
| session_kg_tools_format · mistralai/mistral-small-2603 | 36 | 0.00061 | 171 |
| session_graph_query · mistralai/mistral-small-2603 | 141 | 0.00014 | 71 |
| session_graph_query_format · mistralai/mistral-small-2603 | 36 | 0.00032 | 117 |
| meta_propose · mistralai/mistral-small-2603 | 1 | 0.00038 | 315 |
| guidance_kg_tools · thinkingmachines/inkling-2-small | 6 | 0.00068 | 208 |
| guidance_closed_book · thinkingmachines/inkling-2-small | 1 | 0.00115 | 1121 |
| guidance_closed_book_format · thinkingmachines/inkling-2-small | 1 | 0.00169 | 1342 |
| guidance_kg_tools_format · thinkingmachines/inkling-2-small | 1 | 0.00327 | 1502 |
| guidance_closed_book · qwen/qwen3.5-397b-a17b | 1 | 0.00519 | 2198 |
| guidance_closed_book_format · qwen/qwen3.5-397b-a17b | 1 | 0.00344 | 783 |
| guidance_agentic_plan · thinkingmachines/inkling-2-small | 2 | 0.00047 | 277 |
| guidance_agentic_research · thinkingmachines/inkling-2-small | 31 | 0.00071 | 134 |
| guidance_agentic_notes · thinkingmachines/inkling-2-small | 2 | 0.00745 | 2539 |
| guidance_agentic_advise · thinkingmachines/inkling-2-small | 1 | 0.00705 | 2115 |
