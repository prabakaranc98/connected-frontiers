# Use-case testbed `usecases_objects` · 20261122-1439 · KB `v20261122-0143` · spend $2.6234

11 generated tasks (2 rejected by the Examiner or the leak check) · 187/187 runs answered.

## Tasks

| Task | Use case | Anchor | Stratum | Hops | Gold |
|---|---|---|---|---|---|
| U-method_ecosystem-rich-1 | method_ecosystem | LoRA | rich | 2 | 39 |
| U-method_ecosystem-thin-1 | method_ecosystem | human evaluations | thin | 2 | 6 |
| U-model_card-rich-1 | model_card | DeepSeek-V3 | rich | 1 | 19 |
| U-model_card-thin-1 | model_card | Qwen3.6-35B-A3B | thin | 1 | 11 |
| U-benchmark_models-rich-1 | benchmark_models | FrontierCode 2.0 | rich | 2 | 22 |
| U-benchmark_models-thin-1 | benchmark_models | FrontierCode | thin | 2 | 10 |
| U-lab_output-rich-1 | lab_output | Surge AI | rich | 1 | 46 |
| U-lab_output-thin-1 | lab_output | Carnegie Mellon University | thin | 1 | 10 |
| U-framework_stack-rich-1 | framework_stack | Android | rich | 2 | 20 |
| U-framework_stack-thin-1 | framework_stack | CoreWeave Forge | thin | 2 | 9 |
| U-dataset_lineage-thin-1 | dataset_lineage | hh-rlhf | thin | 2 | 7 |

## Retrieval → grounding → use (mean over tasks; ± = spread across trials of the per-trial mean)

| Model | Condition | retrieved | grounded | used | utilisation | precision | doubt | tool calls | $ / answer |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-35b-a3b | closed_book | 0.00 | – | 0.03 | – | – | 0.00 | 0.0 | 0.003 |
| qwen3.5-35b-a3b | kg_agentic | 0.89 | 0.48 | 0.16 | 0.17 | 0.19 | 0.18 | 32.9 | 0.028 |
| qwen3.5-35b-a3b | kg_enrich | 0.90 | 0.38 | 0.19 | 0.21 | 0.10 | 0.09 | 46.5 | 0.029 |
| qwen3.5-35b-a3b | kg_rag | 0.44 | – | 0.12 | 0.26 | 0.25 | 0.09 | 1.0 | 0.003 |
| qwen3.5-397b-a17b | closed_book | 0.00 | – | 0.01 | – | – | 0.09 | 0.0 | 0.010 |
| inkling-2-small | closed_book | 0.00 | – | 0.04 ± 0.01 | – | – | 0.33 | 0.0 | 0.003 |
| inkling-2-small | kg_agentic | 0.88 | 0.70 | 0.31 ± 0.04 | 0.36 | 0.19 | 0.15 | 15.1 | 0.021 |
| inkling-2-small | kg_enrich | 0.82 | 0.68 | 0.27 ± 0.02 | 0.38 | 0.35 | 0.42 | 9.3 | 0.016 |
| inkling-2-small | kg_rag | 0.44 | – | 0.17 ± 0.04 | 0.37 | 0.25 | 0.09 | 1.0 | 0.003 |

## Outcome: answer names ≥ min(3, gold) gold entities (pass@k = any trial · pass^k = every trial)

Memory-answerable tasks (closed book already passes): 1 of 11; shown separately (a task memory can answer does not test the graph).

| Model | Condition | pass (trial 0) | pass@k | pass^k | pass on graph-needed tasks |
|---|---|---|---|---|---|
| qwen3.5-35b-a3b | closed_book | 0.09 | 0.09 | 0.09 | 0.00 (n=10) |
| qwen3.5-35b-a3b | kg_agentic | 0.45 | 0.45 | 0.45 | 0.40 (n=10) |
| qwen3.5-35b-a3b | kg_enrich | 0.45 | 0.45 | 0.45 | 0.40 (n=10) |
| qwen3.5-35b-a3b | kg_rag | 0.18 | 0.18 | 0.18 | 0.10 (n=10) |
| qwen3.5-397b-a17b | closed_book | 0.00 | 0.00 | 0.00 | 0.00 (n=10) |
| inkling-2-small | closed_book | 0.00 | 0.00 | 0.00 | 0.00 (n=10) |
| inkling-2-small | kg_agentic | 0.64 | 0.91 | 0.55 | 0.60 (n=10) |
| inkling-2-small | kg_enrich | 0.64 | 0.82 | 0.45 | 0.60 (n=10) |
| inkling-2-small | kg_rag | 0.09 | 0.64 | 0.00 | 0.10 (n=10) |

## By object type (main model, all trials): retrieved / used, share of gold objects of that type

| Condition | benchmark | dataset | method | model | org | paper | technology |
|---|---|---|---|---|---|---|---|
| closed_book | 0.00 / 0.06 (n=51) | 0.00 / 0.00 (n=24) | 0.00 / 0.07 (n=57) | 0.00 / 0.01 (n=129) | 0.00 / 0.08 (n=96) | 0.00 / 0.00 (n=90) | 0.00 / 0.03 (n=150) |
| kg_agentic | 1.00 / 0.41 (n=51) | 1.00 / 0.29 (n=24) | 1.00 / 0.30 (n=57) | 1.00 / 0.36 (n=129) | 0.97 / 0.42 (n=96) | 1.00 / 0.00 (n=90) | 0.52 / 0.21 (n=150) |
| kg_enrich | 0.94 / 0.25 (n=51) | 1.00 / 0.12 (n=24) | 1.00 / 0.16 (n=57) | 0.95 / 0.26 (n=129) | 0.91 / 0.56 (n=96) | 0.93 / 0.00 (n=90) | 0.51 / 0.12 (n=150) |
| kg_rag | 0.41 / 0.14 (n=51) | 0.88 / 0.04 (n=24) | 0.16 / 0.16 (n=57) | 0.81 / 0.18 (n=129) | 0.38 / 0.21 (n=96) | 0.07 / 0.00 (n=90) | 0.14 / 0.09 (n=150) |

## Used in the answer, by use case (main model; mean over trials)

| Use case | closed_book | kg_agentic | kg_enrich | kg_rag |
|---|---|---|---|---|
| benchmark_models | 0.01 | 0.34 | 0.39 | 0.18 |
| dataset_lineage | 0.14 | 0.48 | 0.33 | 0.43 |
| framework_stack | 0.07 | 0.39 | 0.38 | 0.13 |
| lab_output | 0.00 | 0.13 | 0.12 | 0.10 |
| method_ecosystem | 0.02 | 0.24 | 0.17 | 0.11 |
| model_card | 0.05 | 0.38 | 0.23 | 0.19 |

## Checklist (typed yes/no items; P(yes), abstentions excluded)

| Model | Condition | code | jev |
|---|---|---|---|
| qwen3.5-35b-a3b | closed_book | 0.91 | 0.66 |
| qwen3.5-35b-a3b | kg_agentic | 0.78 | 0.51 |
| qwen3.5-35b-a3b | kg_enrich | 0.93 | 0.64 |
| qwen3.5-35b-a3b | kg_rag | 0.86 | 0.63 |
| qwen3.5-397b-a17b | closed_book | 0.93 | 0.65 |
| inkling-2-small | closed_book | 0.96 | 0.69 |
| inkling-2-small | kg_agentic | 1.00 | 0.65 |
| inkling-2-small | kg_enrich | 0.96 | 0.67 |
| inkling-2-small | kg_rag | 0.93 | 0.66 |

### Per item (mean over models and conditions)

| Item | Dimension | code | jev |
|---|---|---|---|
| fit_compute | fit | 0.00 | 0.47 |
| fit_skills | fit | abstains | 0.49 |
| first_step_day | actionability | abstains | 0.59 |
| stack_named | actionability | 0.90 | 0.89 |
| baseline | rigor | 0.98 | 0.86 |
| one_change | rigor | abstains | 0.50 |
| measure | rigor | 0.99 | 0.71 |
| specific_names | relevance | 0.99 | 0.97 |
| current | relevance | abstains | 0.48 |
| no_invented | accuracy | abstains | 0.30 |
| no_dated | accuracy | abstains | 0.54 |
| flags_uncertainty | honesty | 0.77 | 0.87 |
| gap_or_connection | insight | abstains | 0.74 |
| meets_success | usefulness | abstains | 0.52 |

### Scorer agreement per item (agreement at 0.5 · Cohen's κ · n)

| Item | code vs jev |
|---|---|
| fit_compute | 100% · – · 4 |
| fit_skills | – |
| first_step_day | – |
| stack_named | 90% · 0.138 · 99 |
| baseline | 98% · 0.49 · 99 |
| one_change | – |
| measure | 93% · 0.208 · 99 |
| specific_names | 100% · 1.0 · 99 |
| current | – |
| no_invented | – |
| no_dated | – |
| flags_uncertainty | 78% · 0.065 · 99 |
| gap_or_connection | – |
| meets_success | – |


## Pairwise judges (persona and expert, both orders; P(x preferred), 0.5 = no preference)

| Comparison | n | P(x) [95% CI] | rich | thin | order-consistent |
|---|---|---|---|---|---|
| agentic vs memory | 11 | 0.55 [0.27–0.82] | 0.40 | 0.67 | 100% |
| memory-first vs memory | 11 | 0.86 [0.70–0.98] | 0.75 | 0.96 | 91% |
| memory-first vs agentic | 11 | 0.93 [0.84–1.00] | 1.00 | 0.88 | 95% |
| small memory-first vs large memory | 11 | 1.00 [1.00–1.00] | 1.00 | 1.00 | 100% |

### By use case

| Comparison | benchmark_models | dataset_lineage | framework_stack | lab_output | method_ecosystem | model_card |
|---|---|---|---|---|---|---|
| agentic vs memory | 1.00 | 1.00 | 0.50 | 1.00 | 0.00 | 0.00 |
| memory-first vs memory | 1.00 | 1.00 | 0.62 | 1.00 | 0.62 | 1.00 |
| memory-first vs agentic | 1.00 | 1.00 | 0.88 | 0.75 | 1.00 | 1.00 |
| small memory-first vs large memory | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Rejected (2)

- benchmark_models · benchmark:apex-accounting (thin): curator: The term 'APEX-Accounting' follows the naming convention of specialized domain-specific benchmarks (like GSM8K for math or HumanEval for cod
- benchmark_models · benchmark:gdp.pdf (thin): curator: The term 'GDP.pdf' is a filename, not a standardized benchmark name. In the context of LLM evaluation, benchmarks are typically identified b
