# Use-case testbed `usecases_v1` · 20261122-1323 · KB `v20261122-0143` · spend $2.5159

11 generated tasks (49 rejected by the Examiner or the leak check) · 187/187 runs answered.

## Tasks

| Task | Use case | Anchor | Stratum | Hops | Gold |
|---|---|---|---|---|---|
| U-customer_stack-rich-1 | customer_stack | OpenAI | rich | 1 | 30 |
| U-customer_stack-thin-1 | customer_stack | NBCUniversal | thin | 1 | 9 |
| U-hiring_targets-rich-1 | hiring_targets | Software Engineer (Agent Platform) | rich | 2 | 48 |
| U-method_adoption-rich-1 | method_adoption | speculative decoding | rich | 2 | 33 |
| U-method_adoption-thin-1 | method_adoption | Mixture-of-Experts | thin | 2 | 5 |
| U-vendor_choice-rich-1 | vendor_choice | vLLM | rich | 2 | 41 |
| U-vendor_choice-thin-1 | vendor_choice | Ai2 ScholarQA | thin | 2 | 4 |
| U-base_model-rich-1 | base_model | DeepSeek-V3 | rich | 1 | 20 |
| U-benchmark_landscape-thin-1 | benchmark_landscape | ARC-AGI | thin | 2 | 7 |
| U-learn_method-rich-1 | learn_method | Retrieval-Augmented Generation | rich | 1 | 14 |
| U-learn_method-thin-1 | learn_method | quantization | thin | 1 | 5 |

## Retrieval → grounding → use (mean over tasks; ± = spread across trials of the per-trial mean)

| Model | Condition | retrieved | grounded | used | utilisation | precision | doubt | tool calls | $ / answer |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-35b-a3b | closed_book | 0.00 | – | 0.05 | – | – | 0.00 | 0.0 | 0.003 |
| qwen3.5-35b-a3b | kg_agentic | 0.93 | 0.48 | 0.24 | 0.26 | 0.14 | 0.00 | 29.1 | 0.032 |
| qwen3.5-35b-a3b | kg_enrich | 0.49 | 0.22 | 0.14 | 0.20 | 0.07 | 0.09 | 32.1 | 0.023 |
| qwen3.5-35b-a3b | kg_rag | 0.60 | – | 0.17 | 0.29 | 0.20 | 0.00 | 1.0 | 0.003 |
| qwen3.5-397b-a17b | closed_book | 0.00 | – | 0.06 | – | – | 0.00 | 0.0 | 0.010 |
| inkling-2-small | closed_book | 0.00 | – | 0.05 ± 0.00 | – | – | 0.00 | 0.0 | 0.002 |
| inkling-2-small | kg_agentic | 0.90 | 0.69 | 0.37 ± 0.03 | 0.40 | 0.16 | 0.00 | 14.6 | 0.017 |
| inkling-2-small | kg_enrich | 0.85 | 0.71 | 0.30 ± 0.02 | 0.34 | 0.27 | 0.30 | 9.3 | 0.012 |
| inkling-2-small | kg_rag | 0.60 | – | 0.14 ± 0.01 | 0.23 | 0.20 | 0.00 | 1.0 | 0.002 |

## Outcome: answer names ≥ min(3, gold) gold entities (pass@k = any trial · pass^k = every trial)

Memory-answerable tasks (closed book already passes): 2 of 11; shown separately (a task memory can answer does not test the graph).

| Model | Condition | pass (trial 0) | pass@k | pass^k | pass on graph-needed tasks |
|---|---|---|---|---|---|
| qwen3.5-35b-a3b | closed_book | 0.18 | 0.18 | 0.18 | 0.00 (n=9) |
| qwen3.5-35b-a3b | kg_agentic | 0.55 | 0.55 | 0.55 | 0.44 (n=9) |
| qwen3.5-35b-a3b | kg_enrich | 0.27 | 0.27 | 0.27 | 0.11 (n=9) |
| qwen3.5-35b-a3b | kg_rag | 0.27 | 0.27 | 0.27 | 0.11 (n=9) |
| qwen3.5-397b-a17b | closed_book | 0.18 | 0.18 | 0.18 | 0.00 (n=9) |
| inkling-2-small | closed_book | 0.18 | 0.27 | 0.18 | 0.00 (n=9) |
| inkling-2-small | kg_agentic | 0.73 | 0.91 | 0.45 | 0.67 (n=9) |
| inkling-2-small | kg_enrich | 0.55 | 0.73 | 0.45 | 0.44 (n=9) |
| inkling-2-small | kg_rag | 0.45 | 0.45 | 0.36 | 0.33 (n=9) |

## Used in the answer, by use case (main model; mean over trials)

| Use case | closed_book | kg_agentic | kg_enrich | kg_rag |
|---|---|---|---|---|
| base_model | 0.00 | 0.12 | 0.08 | 0.03 |
| benchmark_landscape | 0.00 | 0.05 | 0.14 | 0.00 |
| customer_stack | 0.01 | 0.24 | 0.17 | 0.09 |
| hiring_targets | 0.06 | 0.17 | 0.17 | 0.06 |
| learn_method | 0.00 | 0.42 | 0.41 | 0.00 |
| method_adoption | 0.08 | 0.58 | 0.30 | 0.12 |
| vendor_choice | 0.17 | 0.64 | 0.60 | 0.54 |

## Checklist (typed yes/no items; P(yes), abstentions excluded)

| Model | Condition | code | jev |
|---|---|---|---|
| qwen3.5-35b-a3b | closed_book | 0.89 | 0.64 |
| qwen3.5-35b-a3b | kg_agentic | 0.73 | 0.50 |
| qwen3.5-35b-a3b | kg_enrich | 0.89 | 0.65 |
| qwen3.5-35b-a3b | kg_rag | 0.94 | 0.64 |
| qwen3.5-397b-a17b | closed_book | 0.84 | 0.63 |
| inkling-2-small | closed_book | 0.91 | 0.66 |
| inkling-2-small | kg_agentic | 0.96 | 0.69 |
| inkling-2-small | kg_enrich | 0.98 | 0.65 |
| inkling-2-small | kg_rag | 0.85 | 0.68 |

### Per item (mean over models and conditions)

| Item | Dimension | code | jev |
|---|---|---|---|
| fit_compute | fit | 0.00 | 0.40 |
| fit_skills | fit | abstains | 0.44 |
| first_step_day | actionability | abstains | 0.58 |
| stack_named | actionability | 0.88 | 0.86 |
| baseline | rigor | 0.98 | 0.84 |
| one_change | rigor | abstains | 0.48 |
| measure | rigor | 0.98 | 0.75 |
| specific_names | relevance | 0.98 | 0.96 |
| current | relevance | abstains | 0.50 |
| no_invented | accuracy | abstains | 0.40 |
| no_dated | accuracy | abstains | 0.59 |
| flags_uncertainty | honesty | 0.65 | 0.76 |
| gap_or_connection | insight | abstains | 0.70 |
| meets_success | usefulness | abstains | 0.64 |

### Scorer agreement per item (agreement at 0.5 · Cohen's κ · n)

| Item | code vs jev |
|---|---|
| fit_compute | 100% · – · 2 |
| fit_skills | – |
| first_step_day | – |
| stack_named | 86% · 0.154 · 99 |
| baseline | 97% · 0.559 · 99 |
| one_change | – |
| measure | 97% · 0.559 · 99 |
| specific_names | 100% · 1.0 · 99 |
| current | – |
| no_invented | – |
| no_dated | – |
| flags_uncertainty | 70% · 0.227 · 99 |
| gap_or_connection | – |
| meets_success | – |


## Pairwise judges (persona and expert, both orders; P(x preferred), 0.5 = no preference)

| Comparison | n | P(x) [95% CI] | rich | thin | order-consistent |
|---|---|---|---|---|---|
| agentic vs memory | 11 | 0.50 [0.27–0.73] | 0.46 | 0.55 | 73% |
| memory-first vs memory | 11 | 0.91 [0.75–1.00] | 0.88 | 0.95 | 91% |
| memory-first vs agentic | 11 | 0.86 [0.77–0.95] | 0.92 | 0.80 | 73% |
| agentic vs typical RAG | 11 | 0.48 [0.25–0.70] | 0.46 | 0.50 | 77% |
| small memory-first vs large memory | 11 | 0.98 [0.93–1.00] | 1.00 | 0.95 | 95% |

### By use case

| Comparison | base_model | benchmark_landscape | customer_stack | hiring_targets | learn_method | method_adoption | vendor_choice |
|---|---|---|---|---|---|---|---|
| agentic vs memory | 0.25 | 0.50 | 0.50 | 1.00 | 0.38 | 0.12 | 0.88 |
| memory-first vs memory | 1.00 | 0.75 | 0.62 | 1.00 | 1.00 | 1.00 | 1.00 |
| memory-first vs agentic | 1.00 | 1.00 | 0.88 | 1.00 | 1.00 | 0.75 | 0.62 |
| agentic vs typical RAG | 0.50 | 0.75 | 0.38 | 1.00 | 0.25 | 0.00 | 0.88 |
| small memory-first vs large memory | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.88 | 1.00 |

## Rejected (49)

- hiring_targets · role:research-scientists (rich): curator: The role of 'Research Scientist' at major AI companies (OpenAI, Google DeepMind, Anthropic, etc.) typically requires a PhD in a quantitative
- hiring_targets · role:account-executive-enterprise (rich): curator: The role of 'Account Executive, Enterprise' is a pure sales position. It focuses on relationship management, contract negotiation, and meeti
- vendor_choice · technology:scientist (thin): curator: The term 'co-scientist' is highly ambiguous in a professional engineering context. It could refer to a specific AI research tool (like a sci
- vendor_choice · technology:peacock (thin): curator: The term 'Peacock' is highly ambiguous in a technical context. While it could potentially refer to a niche internal tool, a specific obscure
- vendor_choice · technology:coreweave-forge (thin): writer: subject dropped or leaked ['CoreWeave']
- vendor_choice · technology:dell-ai-data-platform (thin): curator: The 'Dell AI Data Platform' is an enterprise-grade infrastructure solution designed for managing large-scale datasets, model training, and d
- vendor_choice · technology:nexus (thin): curator: The term 'Nexus' is highly ambiguous and lacks sufficient context to determine its relevance to an Applied ML Engineer. In the current tech 
- base_model · model:nvidia-nemotron-3.5-super-vl (rich): curator: I have searched for 'NVIDIA Nemotron 3.5 Super VL' across official NVIDIA technical reports, model repositories (Hugging Face), and research
- base_model · model:beam (rich): curator: I have evaluated the term 'Beam' against current machine learning architectures, model repositories (Hugging Face, GitHub), and industry-sta
- base_model · model:qwen3.8-27b (rich): curator: I am evaluating whether 'Qwen3.8-27B' refers to a real, specific model available in the current machine learning ecosystem. As of my current
- base_model · model:smolvla-odin-bimanual-handover-450-eps (rich): curator: The string 'smolvla_odin_bimanual_handover_450_eps' follows a naming convention typical of internal experiment tracking (e.g., Weights & Bia
- base_model · model:smolvlm2-2.2b-instruct (rich): curator: The model name 'SmolVLM2-2.2B-Instruct' follows the naming convention of the 'SmolVLM' series released by Hugging Face (part of their 'SmolL
- base_model · model:inkling-2-small (rich): curator: I have searched for 'Inkling 2 Small' across major model repositories (Hugging Face, GitHub, OpenAI, Meta, Google, Mistral, etc.) and techni
- base_model · model:smolvlm2-500m-video-instruct (rich): curator: The model name 'SmolVLM2-500M-Video-Instruct' appears to be a synthetic or speculative name rather than a verified, released model in the cu
- base_model · model:nvidia-nemotron-3-nano-30b-a3b-bf16 (rich): curator: The model name provided follows a specific naming convention used by NVIDIA for their Nemotron family, but it contains internal inconsistenc
- base_model · model:deepseek-v4.1-flash (thin): curator: I have checked the current landscape of released models from DeepSeek and major AI providers. As of my current knowledge cutoff, there is no
- base_model · model:smoke-tests-public-gated (thin): curator: The term 'smoke-tests-public-gated' does not correspond to any known public foundation model (such as Llama, Mistral, GPT, or BERT), nor is 
- base_model · model:daisyrose-27b (thin): curator: I have searched for 'DaisyRose-27B' across major model repositories (Hugging Face, GitHub, and academic databases) and common model naming c
- base_model · model:qwen3.6-35b-a3b (thin): curator: The model name 'Qwen3.6-35B-A3B' does not correspond to any real, publicly released model in the Qwen series by Alibaba Cloud. As of my curr
- base_model · model:inkling-2-mini (thin): curator: I have searched for 'Inkling 2 Mini' across major model repositories (Hugging Face, GitHub), research papers, and official releases from maj
