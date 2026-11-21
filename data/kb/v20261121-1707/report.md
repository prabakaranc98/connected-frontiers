# Build report

Generated 2026-11-21T15:52:31+00:00 · extractor `llm-v0:thinkingmachines/inkling-2-mini` · verifier `verify-v1:deepseek/deepseek-v4.1-flash:r0`

## Headline

| Area | Metric | Value |
|---|---|---|
| Crawl | pages in graph / URLs attempted | 245 / 260 (50 publishers, 48 seeds) |
| Extraction | triples kept (per page) | 4005 (16.3) |
| Extraction | unquoted (hallucinated-quote) drop rate | 3.7% |
| Verification | citations entailed / rejected / unchecked | 87.7% / 12.2% / 0.1% |
| Trust | edges with >1 publisher · entities with >1 publisher | 16 · 231 |
| Trust | mean edge strength | 0.459 |
| ER | entities before → after (−%) | 3593 → 3433 (−4.5%) |
| ER | auto · LLM same · LLM hierarchy · LLM different | 30 · 144 · 457 · 799 |
| Structure | components · largest component · isolated | 523 · 83.6% · 501 |
| Structure | avg degree · segments | 1.9 · 43 |
| Cost | $/page · $/verified edge · this build | $0.00233 · $0.00017 · $0.03361 |
| Cost | projected 300 orgs × 12 pages | $8.38 |
| Time | build total (extract+verify) | 167.5s (0.0s) |

## Verifier reject rate by relation

| Relation | Reject % |
|---|---|
| publishes | 1.9% |
| offers | 6.5% |
| serves | 13.6% |
| uses_tech | 17.1% |
| works_on | 25.0% |
| partners_with | 27.0% |
| measured_on | 32.6% |
| uses_method | 22.1% |
| hires_for | 0.0% |
| compares_against | 8.0% |
| builds_on | 3.2% |
| trained_on | 0.0% |
| part_of | 62.9% |
| cites | 14.3% |
| invests_in | 25.0% |
| subtype_of | 33.3% |
| acquired | 50.0% |
| requires | 100.0% |

## Publishers with the highest reject rate (≥10 citations)

| Publisher | Reject % | Citations |
|---|---|---|
| nsf.gov | 70.6% | 17 |
| google.com | 47.4% | 38 |
| cursor.com | 35.5% | 76 |
| reflection.ai | 32.2% | 121 |
| mercor.com | 32.1% | 106 |
| modal.com | 31.9% | 72 |

## Edge status

| Status | Edges |
|---|---|
| unsupported | 431 |
| claimed | 3021 |
| corroborated | 4 |
| confirmed | 61 |
| verified | 225 |

## Top by PPR from seeds

1. Scale AI (0.0194)
2. NVIDIA (0.0143)
3. Surge AI (0.0139)
4. OpenAI (0.013)
5. Fireworks AI (0.0129)
6. Together AI (0.0125)
7. vLLM (0.0122)
8. Replicate (0.0121)
9. Cerebras (0.012)
10. Weights & Biases (0.012)

## Top by global PageRank (non-seed)

1. Cloudflare (0.0041)
2. fermatresearch (0.0033)
3. NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 (0.0029)
4. Google (0.0028)
5. GitHub (0.0027)
6. DeepSeek-V3 (0.0027)
7. AVEVA (0.0025)
8. Monday.com (0.0024)
9. TML-Interaction-Small (0.0023)
10. reinforcement learning (0.0021)

## Crawl failures

- http_403: 6
- http_429: 1
- robots_disallow: 1

## LLM calls by type · model

| Call · model | n | mean $ | mean out tokens |
|---|---|---|---|
| kg_extract · nvidia/nemotron-3.5-lightning | 12 | 0.00194 | 9756 |
| kg_verify · thinkingmachines/inkling-2-mini | 1 | 0.00102 | 2447 |
| kg_extract · thinkingmachines/inkling-2-mini | 350 | 0.00198 | 4393 |
| kg_extract · nvidia/nemotron-3-super-120b-a12b | 2 | 0.00567 | 10557 |
| kg_verify · nvidia/nemotron-3.5-lightning | 36 | 0.00167 | 8537 |
| kg_verify · deepseek/deepseek-v4.1-flash | 300 | 0.00035 | 364 |
| kg_verify · openai/gpt-oss-120b | 2 | 0.00031 | 523 |
| kg_verify · qwen/qwen3-30b-a3b-instruct-2507 | 2 | 0.00024 | 426 |
| kg_verify · mistralai/mistral-small-3.2-24b-instruct | 2 | 0.0002 | 404 |
| er_adjudicate · deepseek/deepseek-v4.1-flash | 68 | 0.00055 | 504 |
| segment_names · deepseek/deepseek-v4.1-flash | 3 | 0.00062 | 563 |
