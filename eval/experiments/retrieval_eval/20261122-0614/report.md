# Retrieval → grounding → use · 20261122-0614 · KB `v20261122-0143` · inkling-2-small · spend $0.2017

Gold = the graph facts that answer each question (question-aware; see `cf/bench/retrieval.py`). Means over 6 questions.

| Condition | retrieved | grounded (findings) | used (answer) | utilisation | precision | doubt phrases | tool calls | $ |
|---|---|---|---|---|---|---|---|---|
| memory (no retrieval) | 0.00 | – | 0.03 | – | – | 0.00 | 0.00 | 0.00 |
| typical RAG (one pass, packed context) | 0.17 | – | 0.09 | 0.53 | 0.21 | 0.00 | 1.00 | 0.00 |
| plain tool loop | 0.65 | – | 0.11 | 0.17 | 0.34 | 0.00 | 9.83 | 0.01 |
| agentic, before | 0.61 | 0.33 | 0.12 | 0.25 | 0.18 | 0.50 | 24.00 | 0.02 |
| agentic v3 (fixed) | 0.63 | 0.44 | 0.21 | 0.35 | 0.24 | 0.00 | 15.00 | 0.01 |
| memory-first, before | 0.60 | 0.45 | 0.17 | 0.23 | 0.47 | 0.83 | 13.83 | 0.01 |
| memory-first v2 (fixed) | 0.60 | 0.50 | 0.29 | 0.54 | 0.28 | 0.50 | 9.67 | 0.01 |

## Per question (retrieved / used)

| Question | memory (no retrieval) | typical RAG (one pass, packed context) | plain tool loop | agentic, before | agentic v3 (fixed) | memory-first, before | memory-first v2 (fixed) |
|---|---|---|---|---|---|---|---|
| S-fde-harvey (gold 30) | 0.00 / 0.00 | 0.27 / 0.23 | 0.93 / 0.20 | 0.97 / 0.20 | 1.00 / 0.47 | 0.87 / 0.17 | 0.90 / 0.07 |
| S-startup-rl-post-training (gold 33) | 0.00 / 0.03 | 0.03 / 0.03 | 0.67 / 0.18 | 0.48 / 0.15 | 0.36 / 0.09 | 0.67 / 0.18 | 0.46 / 0.30 |
| S-switcher-fde-jobs (gold 39) | 0.00 / 0.00 | 0.08 / 0.08 | 0.46 / 0.08 | 0.23 / 0.10 | 0.26 / 0.13 | 0.87 / 0.13 | 0.18 / 0.08 |
| S-junior-finetune-base (gold 5) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 1.00 / 0.20 | 0.00 / 0.20 | 1.00 / 1.00 |
| S-senior-agentic-rl (gold 32) | 0.00 / 0.03 | 0.09 / 0.12 | 0.91 / 0.06 | 0.97 / 0.06 | 0.19 / 0.09 | 0.28 / 0.16 | 0.06 / 0.19 |
| S-control-lora-basics (gold 22) | 0.00 / 0.09 | 0.55 / 0.09 | 0.95 / 0.14 | 1.00 / 0.23 | 1.00 / 0.27 | 0.91 / 0.18 | 1.00 / 0.09 |
