# Showcase questions · 20261122-0559 · KB `v20261122-0143` · inkling-2-small · spend $0.1797

| Question | Expect | Condition | named | in graph | key entities found | findings | changes | evidence reads | jev | $ |
|---|---|---|---|---|---|---|---|---|---|---|
| S-fde-harvey | grounding helps | closed_book | 30 | 8 | 0.0 | – | – | – | 0.68 | 0.003 |
| S-fde-harvey | grounding helps | kg_agentic | 30 | 19 | 0.0 | 8 | – | 4 | 0.67 | 0.011 |
| S-fde-harvey | grounding helps | kg_enrich | 37 | 17 | 0.167 | 8 | 9 | 7 | 0.67 | 0.012 |
| S-startup-rl-post-training | grounding helps | closed_book | 34 | 20 | 0.0 | – | – | – | 0.62 | 0.002 |
| S-startup-rl-post-training | grounding helps | kg_agentic | 40 | 23 | 0.083 | 8 | – | 3 | 0.65 | 0.019 |
| S-startup-rl-post-training | grounding helps | kg_enrich | 45 | 31 | 0.0 | 8 | 9 | 8 | 0.66 | 0.009 |
| S-switcher-fde-jobs | grounding helps | closed_book | 46 | 30 | 0.0 | – | – | – | 0.72 | 0.003 |
| S-switcher-fde-jobs | grounding helps | kg_agentic | 36 | 18 | 1.0 | 8 | – | 3 | 0.70 | 0.016 |
| S-switcher-fde-jobs | grounding helps | kg_enrich | 52 | 35 | 1.0 | 8 | 10 | 3 | 0.68 | 0.014 |
| S-junior-finetune-base | grounding helps | closed_book | 42 | 21 | 0.083 | – | – | – | 0.67 | 0.002 |
| S-junior-finetune-base | grounding helps | kg_agentic | 34 | 17 | 0.083 | 7 | – | 5 | 0.64 | 0.014 |
| S-junior-finetune-base | grounding helps | kg_enrich | 41 | 22 | 0.083 | 8 | 7 | 3 | 0.66 | 0.009 |
| S-senior-agentic-rl | grounding helps | closed_book | 34 | 25 | 0.0 | – | – | – | 0.65 | 0.003 |
| S-senior-agentic-rl | grounding helps | kg_agentic | 36 | 19 | 0.0 | 8 | – | 3 | 0.64 | 0.029 |
| S-senior-agentic-rl | grounding helps | kg_enrich | 44 | 35 | 1.0 | 8 | 8 | 3 | 0.63 | 0.019 |
| S-control-lora-basics | control | closed_book | 24 | 15 | 0.083 | – | – | – | 0.71 | 0.002 |
| S-control-lora-basics | control | kg_agentic | 44 | 30 | 0.333 | 8 | – | 2 | 0.63 | 0.014 |
| S-control-lora-basics | control | kg_enrich | 34 | 25 | 0.25 | 8 | 7 | 2 | 0.73 | 0.012 |

## Checklist (typed yes/no items; P(yes), abstentions excluded)

| Model | Condition | code | jev |
|---|---|---|---|
| inkling-2-small | closed_book | 0.93 | 0.67 |
| inkling-2-small | kg_agentic | 1.00 | 0.65 |
| inkling-2-small | kg_enrich | 0.97 | 0.67 |

### Per item (mean over models and conditions)

| Item | Dimension | code | jev |
|---|---|---|---|
| fit_compute | fit | abstains | 0.39 |
| fit_skills | fit | abstains | 0.46 |
| first_step_day | actionability | abstains | 0.54 |
| stack_named | actionability | 1.00 | 0.87 |
| baseline | rigor | 1.00 | 0.89 |
| one_change | rigor | abstains | 0.54 |
| measure | rigor | 1.00 | 0.78 |
| specific_names | relevance | 1.00 | 0.99 |
| current | relevance | abstains | 0.56 |
| no_invented | accuracy | abstains | 0.30 |
| no_dated | accuracy | abstains | 0.52 |
| flags_uncertainty | honesty | 0.83 | 0.89 |
| gap_or_connection | insight | abstains | 0.81 |
| meets_success | usefulness | abstains | 0.78 |

### Scorer agreement per item (agreement at 0.5 · Cohen's κ · n)

| Item | code vs jev |
|---|---|
| fit_compute | – |
| fit_skills | – |
| first_step_day | – |
| stack_named | 100% · – · 18 |
| baseline | 100% · – · 18 |
| one_change | – |
| measure | 100% · – · 18 |
| specific_names | 100% · – · 18 |
| current | – |
| no_invented | – |
| no_dated | – |
| flags_uncertainty | 78% · -0.091 · 18 |
| gap_or_connection | – |
| meets_success | – |
