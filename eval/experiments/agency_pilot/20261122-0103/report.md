# Agency experiment `agency_pilot` · 20261122-0103 · KB `v20261122-0022`

4 tasks (2 rejected by the Examiner) · spend $0.2097

## Judge validation (perturbation unit tests)

| Judge | Detected | generic | false claim | infeasible | no baseline | Pass (≥ 80%) |
|---|---|---|---|---|---|---|
| glm-5.3 | 100% | 100% | 100% | 100% | 100% | yes |
| nemotron-3.5-super-vl | 92% | 100% | 67% | 100% | 100% | yes |

## Scores (mean over judges; 95% task-bootstrap interval on the role's mean)

| Model | Condition | usefulness | fit | would_act | persona mean | frontier_relevance | insight | actionability | experiment_rigor | accuracy | expert mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| inkling-2-small | closed_book | 4.75 | 4.88 | 4.75 | 4.79 [4.58–5.00] | 3.88 | 4.12 | 4.88 | 4.62 | 4.38 | 4.38 [4.33–4.40] |
| inkling-2-small | kg_agentic | 4.38 | 4.00 | 4.12 | 4.17 [3.38–4.62] | 4.12 | 3.62 | 3.38 | 3.38 | 3.88 | 3.67 [3.17–4.00] |
| inkling-2-small | kg_tools | 4.62 | 4.62 | 4.38 | 4.54 [3.88–5.00] | 4.25 | 4.00 | 4.38 | 4.12 | 4.12 | 4.17 [3.95–4.45] |

## Pairwise (both orders × judges × roles; 0.5 = no preference)

| Comparison | n | P(x preferred) | rich | thin | position-consistent |
|---|---|---|---|---|---|
| agentic vs memory | 4 | 0.56 [0.12–1.00] | 0.56 (n=4) | – | 88% |
| agentic vs plain tools | 4 | 0.62 [0.44–0.81] | 0.62 (n=4) | – | 50% |

### By persona

| Comparison | Persona | P(x preferred) | n |
|---|---|---|---|
| agentic vs memory | career_switcher | 1.00 | 1 |
| agentic vs memory | forward_deployed | 1.00 | 1 |
| agentic vs memory | senior_research_engineer | 0.25 | 1 |
| agentic vs memory | undergrad_capstone | 0.00 | 1 |
| agentic vs plain tools | career_switcher | 0.75 | 1 |
| agentic vs plain tools | forward_deployed | 0.88 | 1 |
| agentic vs plain tools | senior_research_engineer | 0.50 | 1 |
| agentic vs plain tools | undergrad_capstone | 0.38 | 1 |
