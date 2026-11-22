# Agency experiment `agency_fit_dev` · 20261122-0106 · KB `v20261122-0022`

4 tasks (2 rejected by the Examiner) · spend $0.3252

## Judge validation (perturbation unit tests)

| Judge | Detected | generic | false claim | infeasible | no baseline | Pass (≥ 80%) |
|---|---|---|---|---|---|---|
| glm-5.3 | 100% | 100% | 100% | 100% | 100% | yes |

## Scores (mean over judges; 95% task-bootstrap interval on the role's mean)

| Model | Condition | usefulness | fit | would_act | persona mean | frontier_relevance | insight | actionability | experiment_rigor | accuracy | expert mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| inkling-2-small | closed_book | 4.75 | 4.75 | 4.50 | 4.67 [4.25–5.00] | 4.25 | 3.75 | 4.75 | 4.00 | 4.25 | 4.20 [3.95–4.40] |
| inkling-2-small | kg_agentic | 4.75 | 4.25 | 4.50 | 4.50 [4.00–5.00] | 4.75 | 4.25 | 4.25 | 4.25 | 4.25 | 4.35 [4.05–4.80] |
| inkling-2-small | kg_agentic+fit | 3.75 | 4.00 | 4.00 | 3.92 [3.00–4.83] | 4.00 | 3.75 | 4.50 | 4.50 | 4.25 | 4.20 [3.55–4.60] |

## Pairwise (both orders × judges × roles; 0.5 = no preference)

| Comparison | n | P(x preferred) | rich | thin | position-consistent |
|---|---|---|---|---|---|
| fit-first vs agentic | 4 | 0.69 [0.50–0.88] | 0.69 (n=4) | – | 38% |
| fit-first vs memory | 4 | 0.38 [0.00–0.75] | 0.38 (n=4) | – | 100% |
| agentic vs memory | 4 | 0.44 [0.00–0.88] | 0.44 (n=4) | – | 88% |

### By persona

| Comparison | Persona | P(x preferred) | n |
|---|---|---|---|
| agentic vs memory | career_switcher | 0.75 | 1 |
| agentic vs memory | forward_deployed | 1.00 | 1 |
| agentic vs memory | senior_research_engineer | 0.00 | 1 |
| agentic vs memory | undergrad_capstone | 0.00 | 1 |
| fit-first vs agentic | career_switcher | 0.50 | 1 |
| fit-first vs agentic | forward_deployed | 1.00 | 1 |
| fit-first vs agentic | senior_research_engineer | 0.50 | 1 |
| fit-first vs agentic | undergrad_capstone | 0.75 | 1 |
| fit-first vs memory | career_switcher | 0.50 | 1 |
| fit-first vs memory | forward_deployed | 1.00 | 1 |
| fit-first vs memory | senior_research_engineer | 0.00 | 1 |
| fit-first vs memory | undergrad_capstone | 0.00 | 1 |
