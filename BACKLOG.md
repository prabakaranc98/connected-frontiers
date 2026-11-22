# Backlog — Connected Frontiers

Ideas and deferred work. Move an item into DECISIONS.md when it's picked up.

## People in the graph (deferred, owner request 2026-11-21)
- What: `person` nodes for researchers, founders and authors; `authored`, `works_at`, `founded`,
  and `moved_from → to` (talent flow between labs).
- Sources: OpenAlex authors and affiliations (primary), paper bylines, company team and research
  pages, research-post bylines (e.g. the author names on Applied Compute's posts).
- Rules before enabling (type cap is 0 today):
  - public professional facts only (authorship, affiliation, role); no contact details, no
    private individuals;
  - person resolution is hard (same names): key on OpenAlex/ORCID IDs where possible;
  - check the data-release licence and ethics section (docs/DATASET.md §5) before any person
    data ships.
- Use cases: "who works on X", talent flow between labs, author → method → org paths.

## Retrieval for agents (next after the scout)
- Hybrid retrieval: graph (PPR from question entities, paths) + vector search over evidence
  quotes and entity cards.
- Agent tool API (DESIGN.md §5) served as a Python library first, MCP server later.
- Eval: evidence recall@k on gold questions; R0–R3 comparison; tool calls per answer.

## Trust layer on top of PageRank (designed, not built)
- TrustRank-style trust score, spread from verified and corroborated edges.
- Rank stability: Monte Carlo PPR over edges sampled by strength → rank intervals.
- Source diversity per node (independent publishers).
- Importance × trust map → targets for the corroboration seeker.

## Source adapters (DESIGN.md §1.3)
- OpenAlex, HF Hub, leaderboards, GitHub, careers pages.

## Verifier
- Customer-voice testimonials (named customer person) as a separate source kind.
- Tiered verification (NLI first, LLM only when unsure) for scale (docs/SCALING.md §3).

## Open items, 2026-11-21 (after the v0.1 evaluation round)

**Blocked on a working OpenRouter key** (the shared $60 key is exhausted; project spend $7.55 of $10).
Prefer a separate key for this project with its own cap.

| # | Item | Why | Est. cost |
|---|---|---|---|
| 1 | Re-run the meta-loop held-out confirmation for h0 vs h2 (truncation notice + empty-query hints) and h3 (schema card + neighbor limit 50) | train gains +0.25 each; held-out run invalidated by the key limit (ledger has the correction) | ~$1.2 |
| 2 | Resume the crawl (`--resume`; checkpoint at 1,921 extracted pages) | coverage | ~$0.0018 / page |
| 3 | Final build → new KB → `cf eval` scorecard → `cf site` + `scripts/deploy_pages.sh` | the public explorer shows the interim KB | ~$0.2 (pages already extracted) |
| 4 | HF structured-vs-extracted ablation (drop vs keep adapter edges on the same KB: connectivity, verified share, lineage coverage, Reasoner scores on lineage/benchmark templates) | does registry data fix "broad but thin"? | free + one session run |
| 5 | Persona discovery run (`cf discover`, 15 tasks × 2 models × KB vs closed book) + blind review sheet | discovery beyond QA, claims checked on the graph | ~$0.6 |
| 6 | Hidden-link recovery (D2 proxy) vs Adamic–Adar / common neighbours / PPR | must beat graph heuristics to claim discovery | ~$0.3 |
| 7 | Verifier second opinion on rejected edges (L1 loop) | silver: 50% of rejected edges are supported | ~$0.3 |

**Owner actions**
- HF account for the private collection push (`cf release --push --repo …`).
- 20-session answer-key audit (keys come from the KB; only a human can measure how often they are wrong).
- `configs/must_have.yaml`: ~50 orgs / models / benchmarks any map should contain (coverage recall).
- Review the 6 silver disputes and the HF org-mapping ambiguities (`data/processed/hf_org_map.json`).

**Engineering**
- Examiner: more anchors for landscape (ran out); target 40 distinct sessions; frozen held-out set.
- `published_at` extraction → time-based discovery tests (D1 forecast, D3 gap closure).
- Graph query: model writes single-hop queries 98% of the time; test a worked multi-hop example in the tool description.
- PraCha Labs site: a short project page linking to the explorer (optional).

## Experiment: Connected Frontiers vs web search (owner idea, 2026-11-22)

Does a curated, evidence-graded graph beat open web search as the agent's source, or do they complement each other?

| Condition | Agent's tools |
|---|---|
| `kg_agentic` | the graph only (current) |
| `web_agentic` | web search + page fetch only, same harness (plan → research → read → notes → advise) |
| `kg_web_agentic` | both; findings record which source each came from |

Fairness: same harness, prompts, models, step budget and output caps; judges blind to the source (citations stripped,
URLs normalised); the symmetric fact sheet stays KB-based, so add a web-sourced fact card per named entity to avoid
favouring the graph. Expected trade-offs to measure, not assume: the web is fresher and broader; the graph gives typed
connections, evidence status and lower cost. Report: persona and expert judge preference, accuracy (false-claim rate),
salient coverage, cost per answer, latency. Tool: a search API (e.g. Firecrawl or a provider web plugin); cost
budgeted per query.

## Hugging Face objects only partly attached (found 2026-11-22) · fixed in `v20261122-0143`

The final build mapped 169 orgs to their Hub accounts (1,131 models listed) but captured 488 adapter rows: the Hub
rate-limited the build's burst and the adapter read 429 as "no models". Fixed: requests back off and retry; the Hub data
is being pre-fetched into the cache. Next: rebuild (~$0.2, HF phase then runs from cache) and the structured-vs-extracted
ablation on that KB.

**Done (2026-11-22):** rebuilt as `v20261122-0143`: 2,411 Hub rows, 2,371 new edges, verified edges 468 → 2,363.
Still open: the structured-vs-extracted ablation, and re-running the agency tasks on the new KB.
