# Evaluation spec — Connected Frontiers

Written before building. Changes after Phase 1 go in DECISIONS.md with a reason.

## Objective (copied from PROBLEM.md, [PROPOSED])
At 500 fetches from 3 seeds, the Constructor finds at least 1.5× BFS's gold-entity recall, with
at least 85% edge precision. The Reasoner grounded on the KG beats no-graph by at least 15 points
in accuracy, with at least 90% citation faithfulness.

## Metrics

| Component | Metric | Why it reflects the objective | Pass threshold [PROPOSED] |
|---|---|---|---|
| Crawl policy (primary) | gold-entity recall @ {100, 250, 500} fetches; area under the recall–fetch curve | finds what matters per unit cost | at least 1.5× BFS @500 |
| Crawl policy | harvest rate = new valid edges per fetch | efficiency | above BFS |
| Crawl policy | boundary precision = share of expanded entities inside the AI core | stops at the right edge | at least 80% |
| Extraction | triple precision / recall / F1 (type + relation + both ends) on labelled pages | KG quality | P ≥ 0.85 |
| Resolution | pairwise merge precision / recall | no false merges | P ≥ 0.95 |
| Graph (inference) | temporal link prediction hits@10 / AUC (freeze at T, edges after T) | does structure predict? | above preferential attachment |
| Reasoner (primary) | answer accuracy (rubric, blinded judge + owner spot-check) | usefulness | at least +15 points over R0 |
| Reasoner | citation faithfulness = cited quote supports the claim | trust | at least 90% |
| Reasoner | abstention correctness ("not in graph" when true) | honesty | at least 80% |
| Evidence: verifier | entailment accuracy; **false-support rate** on about 200 (quote, triple) pairs | bad citations must not pass | false-support ≤ 5% |
| Evidence: grader | status agreement with owner-graded edges (Cohen's κ) | the ladder matches human judgment | κ ≥ 0.7 |
| Evidence: stress test | planted false or inflated claims that stay ≤ CLAIMED; share the Reasoner states as fact | marketing can't become "truth" | ≥ 95% stay ≤ CLAIMED; 0% stated as fact |
| Reasoner: epistemic faithfulness | wording matches edge status (EVIDENCE.md §5) | the user can tell claim from fact | ≥ 95% |
| Coverage (north star) | capture–recapture estimate of ecosystem size N̂ and coverage, stratified by layer (docs/DESIGN.md §3.2) | makes "entire ecosystem" checkable | reported with interval; no threshold in v1 |
| Understanding | orientation quiz: accuracy and time, graph views vs web search, about 5–8 readers | do people actually understand better? | better accuracy at equal or lower time |
| Resource | $ per crawl run, fetches, wall-clock; $ per answer | budget | ≤ $20 per run |

## Test sets (all frozen before building; nothing tunes on them)
1. **Gold entities.** The owner hand-browses from 3 seeds (proposed: Applied Compute, one frontier
   lab, one infra company) and lists the entities within about 3 hops they would *want* found,
   about 40–60 per seed, each with type. Frozen with a date. *Built by the owner: it encodes the
   owner's judgment of relevance.*
2. **Labelled pages.** About 80 pages, split 50 train (for improvement loops) and 30 held-out.
   Triples labelled by hand.
3. **Resolution pairs.** About 200 mention pairs, labelled same or different.
4. **Questions.** About 40, across the five families in DESIGN.md §5, with reference answers and
   source URLs. **Leakage control:** at least half must depend on facts published after the
   models' training cutoff, or on niche pages. Report scores split by post-cutoff vs pre-cutoff.
5. **Temporal split.** Edges with `published_at` ≤ T train the graph; edges after T are targets.

## Baselines

| Component | Baseline | Score |
|---|---|---|
| Crawl | BFS over entities (same sources, same extractor) | |
| Crawl | degree-priority; global PageRank recomputed every m steps | |
| Extraction | GLiNER + rule relations | |
| Resolution | normalized name + domain string match | |
| Link prediction | preferential attachment; common neighbours | |
| Reasoner | R0 LLM, no graph; R1 vector RAG over raw pages | |

Controlled comparison rule: when comparing crawl policies, the extractor, resolver, sources and
budget are held fixed. Only the policy changes. Run at least 3 seeds per configuration and report
the spread.

## Harness
Command: `cf eval --suite {crawl,extract,resolve,linkpred,reason,all} --config configs/eval.yaml`
Output: `eval/results/<date>_<suite>_<git-sha>.jsonl` plus a summary table appended to the
Results log below.

## Failure analysis plan
Slices: entity type (Benchmark and Method are likely hardest); page type (case study vs careers
vs blog); JS-rendered vs static; claimed vs corroborated edges; pre- vs post-cutoff questions.
What errors cost the user: a false edge presented as fact (worst, which is why precision is
favoured), a missed key player (bad), a stale edge (moderate).

## Results log
| Date | System | Primary | Guardrails | Resources | Notes |
|------|--------|---------|------------|-----------|-------|
| 2026-11-21 | Build, 48 seeds + HF adapter | 245 pages, 50 publishers, 3,433 entities, ~3.7k edges (225 verified) | verifier rejects 12.2%; fake-quote drops 3.7% | $0.0017 per verified edge | reports/2026-11-21-1552-build.md |
| 2026-11-21 | Silver v1 (4-judge ensemble: Qwen3.5-35B, Inkling-2-small, Nemotron-3.5, Mistral-Small-2603) | verify: 170/200 labelled, κ=0.40 · ER: 96/120, κ=0.43 | 54 disputes → eval/gold/owner_review_v1.md | $0.09 | silver ≠ gold; owner review pending |
| 2026-11-21 | Production verifier vs silver | acc 0.847 → **0.888** with escalation | false support 0.43 → **0.14**; false reject 0.099 → 0.106 | $0.003 | eval/gold/rescore_v1.json |
| 2026-11-21 | ER vs silver | acc 0.677 → **0.854** with strict-key rule | false merges 0.48 → **0.17** | $0.004 | rule path caused 15/22 bad merges |
| 2026-11-21 | Benchmark v0 (20 use-case tasks × 4 models × 3 conditions) | KG tools mean: Mistral-Small 0.67 · Inkling-2-mini 0.64 · Qwen3.5 0.52 · Nemotron 0.22; closed-book 0.11–0.17; oracle 0.49–0.78 | citations valid 0.78–0.99 | $0.01–0.05/task | reports/*-bench-v0.md; tasks not yet owner-reviewed |
