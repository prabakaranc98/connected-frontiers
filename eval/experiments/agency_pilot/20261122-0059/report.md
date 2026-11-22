# Agency experiment `agency_pilot` · 20261122-0059 · KB `v20261122-0022`

4 tasks (2 rejected by the Examiner) · spend $0.1615

## Judge validation (perturbation unit tests)

| Judge | Detected | generic | false claim | infeasible | no baseline | Pass (≥ 80%) |
|---|---|---|---|---|---|---|
| glm-5.3 | 83% | 100% | 100% | 100% | 33% | yes |
| nemotron-3.5-super-vl | 75% | 67% | 100% | 100% | 33% | **no** |

## Scores (mean over judges; 95% task-bootstrap interval on the role's mean)

| Model | Condition | usefulness | fit | would_act | persona mean | frontier_relevance | insight | actionability | experiment_rigor | accuracy | expert mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| inkling-2-small | closed_book | 4.50 | 4.88 | 4.88 | 4.75 [4.46–4.96] | 3.62 | 3.50 | 4.00 | 3.75 | 4.12 | 3.80 [3.12–4.28] |
| inkling-2-small | kg_agentic | 3.38 | 3.50 | 3.50 | 3.46 [2.58–4.33] | 3.75 | 3.38 | 3.00 | 2.88 | 3.50 | 3.30 [3.18–3.40] |
| inkling-2-small | kg_tools | 4.50 | 4.75 | 4.75 | 4.67 [4.33–5.00] | 3.88 | 3.38 | 3.00 | 2.62 | 4.00 | 3.38 [2.83–4.00] |

## Pairwise (both orders × judges × roles; 0.5 = no preference)

| Comparison | n | P(x preferred) | rich | thin | position-consistent |
|---|---|---|---|---|---|
| agentic vs memory | 4 | 0.59 [0.22–0.94] | 0.59 (n=4) | – | 81% |
| agentic vs plain tools | 4 | 0.56 [0.34–0.78] | 0.56 (n=4) | – | 38% |

### By persona

| Comparison | Persona | P(x preferred) | n |
|---|---|---|---|
| agentic vs memory | career_switcher | 0.88 | 1 |
| agentic vs memory | forward_deployed | 1.00 | 1 |
| agentic vs memory | senior_research_engineer | 0.50 | 1 |
| agentic vs memory | undergrad_capstone | 0.00 | 1 |
| agentic vs plain tools | career_switcher | 0.62 | 1 |
| agentic vs plain tools | forward_deployed | 0.88 | 1 |
| agentic vs plain tools | senior_research_engineer | 0.50 | 1 |
| agentic vs plain tools | undergrad_capstone | 0.25 | 1 |
