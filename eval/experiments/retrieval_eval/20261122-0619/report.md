# Retrieval → grounding → use · 20261122-0619 · KB `v20261122-0143` · inkling-2-small · spend $0.1874

Gold = the graph facts that answer each question (question-aware; see `cf/bench/retrieval.py`). Means over 6 questions.

| Condition | retrieved | grounded (findings) | used (answer) | utilisation | precision | doubt phrases | tool calls | $ |
|---|---|---|---|---|---|---|---|---|
| memory (no retrieval) | 0.00 | – | 0.03 | – | – | 0.00 | 0.00 | 0.00 |
| typical RAG (one pass, packed context) | 0.18 | – | 0.09 | 0.53 | 0.18 | 0.00 | 1.00 | 0.00 |
| plain tool loop | 0.65 | – | 0.12 | 0.18 | 0.29 | 0.00 | 9.83 | 0.01 |
| agentic v2 (start) | 0.61 | 0.33 | 0.14 | 0.28 | 0.16 | 0.50 | 24.00 | 0.02 |
| agentic v3 (+top, link, facts) | 0.63 | 0.44 | 0.21 | 0.36 | 0.21 | 0.00 | 15.00 | 0.01 |
| agentic v4 (+broader, twins) | 0.76 | 0.44 | 0.21 | 0.28 | 0.20 | 0.00 | 15.67 | 0.02 |
| memory-first v1 (start) | 0.60 | 0.45 | 0.18 | 0.25 | 0.41 | 0.67 | 13.83 | 0.01 |
| memory-first v2 (+explore, facts) | 0.60 | 0.50 | 0.29 | 0.54 | 0.24 | 0.00 | 9.67 | 0.01 |
| memory-first v3 (+broader, twins) | 0.68 | 0.46 | 0.25 | 0.38 | 0.28 | 0.17 | 8.83 | 0.01 |

## Per question (retrieved / used)

| Question | memory (no retrieval) | typical RAG (one pass, packed context) | plain tool loop | agentic v2 (start) | agentic v3 (+top, link, facts) | agentic v4 (+broader, twins) | memory-first v1 (start) | memory-first v2 (+explore, facts) | memory-first v3 (+broader, twins) |
|---|---|---|---|---|---|---|---|---|---|
| S-fde-harvey (gold 30) | 0.00 / 0.00 | 0.27 / 0.23 | 0.93 / 0.23 | 0.97 / 0.23 | 1.00 / 0.47 | 0.97 / 0.23 | 0.87 / 0.17 | 0.90 / 0.07 | 0.87 / 0.23 |
| S-startup-rl-post-training (gold 33) | 0.00 / 0.03 | 0.03 / 0.03 | 0.67 / 0.18 | 0.48 / 0.18 | 0.36 / 0.12 | 0.30 / 0.15 | 0.67 / 0.21 | 0.46 / 0.30 | 0.48 / 0.27 |
| S-switcher-fde-jobs (gold 39) | 0.00 / 0.00 | 0.08 / 0.08 | 0.46 / 0.08 | 0.23 / 0.10 | 0.26 / 0.13 | 0.31 / 0.08 | 0.87 / 0.15 | 0.18 / 0.08 | 0.18 / 0.08 |
| S-junior-finetune-base (gold 5) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 1.00 / 0.20 | 1.00 / 0.40 | 0.00 / 0.20 | 1.00 / 1.00 | 1.00 / 0.60 |
| S-senior-agentic-rl (gold 32) | 0.00 / 0.03 | 0.09 / 0.12 | 0.91 / 0.06 | 0.97 / 0.09 | 0.19 / 0.09 | 1.00 / 0.19 | 0.28 / 0.16 | 0.06 / 0.19 | 0.56 / 0.16 |
| S-control-lora-basics (gold 22) | 0.00 / 0.09 | 0.59 / 0.09 | 0.95 / 0.14 | 1.00 / 0.23 | 1.00 / 0.27 | 1.00 / 0.23 | 0.91 / 0.18 | 1.00 / 0.09 | 1.00 / 0.18 |
