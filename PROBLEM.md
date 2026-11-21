# Connected Frontiers — Problem definition

Phase: 0 Scout → moving to 1 Define
Archetype: D dataset/benchmark (the graph + its evals) with E agentic (agents are a studied part,
not glue — see DESIGN.md §0)
Sector: IT / AI ecosystem intelligence
Last updated: 2026-11-21

> Items tagged **[PROPOSED]** are Claude's drafts. The user owns them and must confirm or change
> them before the Phase 1 gate.

## North star and v1 scope

**North star (owner's aim, 2026-11-21):** get the *entire* frontier-AI research and industry
ecosystem into one knowledge graph, built the PageRank way (rank-guided, recursive, reinforced by
several paths), and help people *understand* it: how research, methods, models, infra,
companies, customers and talent connect, and where things are moving.

"Entire" is a direction, not something we can assert. So it is made measurable:

| North-star claim | How it becomes checkable |
|---|---|
| "covers the ecosystem" | **Estimated coverage**: capture–recapture across independent crawls from different seed layers (DESIGN.md §3.2), reported with an interval |
| "built the PageRank way" | rank-guided crawl beats BFS on gold recall per fetch (EVAL.md) |
| "helps people understand" | readers answer orientation questions better and faster with the graph views than with web search (EVAL.md, Understanding) |

**v1 slice:** 3 seeds from different layers, a 500-fetch budget, gold sets frozen. Grow seeds
and budget only after v1 numbers exist.

## 1. User
**[PROPOSED]** Primary: someone who needs to *understand* the frontier-AI ecosystem well enough
to act: an AI researcher or engineer choosing what to work on (first user: the project owner),
or a newcomer (student, engineer moving into AI) getting oriented.

Moment of use: "I want to work on X (e.g. RL for legal agents). Who is already solving it, with
which methods, measured on which benchmarks, on what infra, and hiring for which skills? Where
is the gap?" Or: "How does this ecosystem fit together, layer by layer, and what changed this
month?"

Secondary users, out of scope for v1: job seekers mapping skills to roles, and early founders
looking for white space.

## 2. Problem
The frontier AI ecosystem changes weekly. Frontier labs, neolabs, AI-native startups, infra
providers and their customers are connected by customers, problems, methods, benchmarks, models,
infra, papers and people. That information is spread over company pages, case studies, research
blogs, papers, leaderboards and job posts. Today, finding it means hours of manual browsing per
question, and the result is a mental picture that goes stale and can't be checked.

Example of the structure, from one page (applied compute `/training`, read 2026-11-21, marketing
claims unverified): Applied Compute → serves Harvey, Mercor, Cognition, DoorDash → their
problems (legal agents, corporate law, bug detection, menu onboarding) → their benchmarks
(Harvey Legal Agent Benchmark, APEX-Agents) → methods (async RL, SFT, self-distillation,
quantization) → infra (Blackwell) → comparators (GPT-5.5, Opus 4.8). That is about 25 typed
edges from one page.

- Evidence that the cost is real: **weak, and this is the main Phase 0 gap.** Today it is the
  owner's own first-hand pain. Before the Phase 1 gate, add at least one outside source (a survey,
  a market report on AI-ecosystem intelligence tools, or usage data from tools like those listed
  under Prior solutions). Status: unverified.

## 3. Task
Two roles, one graph (DESIGN.md has the detail):

**Constructor ("training time")**
`build(seeds: list[Entity], budget: Fetches, policy) → KG(entities, typed edges with provenance)`

Worked example: seeds = [Applied Compute] with a budget of 50 fetches → the KG contains
`Harvey —measured_on→ Harvey Legal Agent Benchmark` with evidence quote, URL, date and
status=`claimed`, plus `Harvey` resolved as one entity across "Harvey", "Harvey AI" and harvey.ai.

**Reasoner ("inference time")**
`answer(question: str, KG) → (answer, cited evidence subgraph)`

Worked example: "Who trains models for legal-agent customers, and how is it measured?" →
"Applied Compute (for Harvey and Mercor), measured on Harvey LAB and APEX-Agents [url1, url2];
the method per customer is not stated on the training page."

Primary task types: extraction/structuring (pages → typed records) and ranking/retrieval (crawl
priority, evidence retrieval).

## 4. Data
Sources (full details in DATA_CARD.md, to be registered in `_commons/catalog/datasets.md` before use):
- Company sites: home, case studies, customers, research blog, careers.
- Papers: arXiv and OpenAlex (authors, affiliations, citations).
- Benchmark leaderboards and benchmark papers.
- Job posts (roles → skills): public careers pages only.
- Funding and acquisition news: company press pages first; aggregators only if their terms allow.

Sample in hand? Partly: one page (applied compute /training) read and structured.
Known gaps: marketing claims are unverified; many pages are JS-rendered; customer lists are
partial; dates are often missing; people data needs care (see Risks).

## 5. Environment
Runs on: a laptop (Python 3.11+), with no GPU required.
Models: OpenRouter API. A cheap model for extraction, a stronger model for adjudication and
reasoning. Choices are made on measured precision per dollar (EVAL.md), not by name.
Compute and cost budget: **[PROPOSED]** at most $20 in LLM spend and 2,000 fetches per full
crawl experiment.
Latency and freshness: batch crawl; a refresh crawl weekly at most.
Integrates with: local SQLite and Parquet; a static HTML explorer.
Operated by: the owner.

## 6. Objective
**[PROPOSED]** At a fixed budget of 500 fetches from 3 seeds, the Constructor finds **at least
1.5× the gold entities that BFS finds**, with **at least 85% edge precision** on an audited sample.
Over a frozen question set, the Reasoner grounded on that KG beats the same model without the
graph by **at least 15 points in answer accuracy**, with **at least 90% citation faithfulness**.

## 7. Evaluation (full details in EVAL.md)
Metrics: gold-entity recall at N fetches (crawl curve); edge precision; entity-resolution
precision; temporal link-prediction hits@k; reasoner accuracy and citation faithfulness.
Test set: a gold entity set, a labelled page set and a question set, all frozen before building.
Baselines: BFS crawl; degree-priority crawl; GLiNER/rule extraction; domain-string entity
resolution; preferential attachment; LLM with no graph; vector RAG over raw pages.
Pass threshold: as in §6.

## 8. Deliverable
Form: a Python library and CLI (`cf crawl | rank | ask | viz | eval | release`), plus a
versioned KG snapshot and benchmark on Hugging Face (docs/DATASET.md), plus a static interactive
explorer with "understanding views" (docs/DESIGN.md §6).
"Done" means: a fresh clone runs `cf eval` end to end; the snapshot is published with a data
card; the explorer shows PPR-from-seed, filters by type, edge provenance and crawl replay.

## Prior solutions
All entries are unverified as to current coverage.
- **Commercial company graphs** (Crunchbase, CB Insights, PitchBook): funding and firmographics,
  but weak on methods, benchmarks, infra and research links; closed and paid.
- **Epoch AI datasets** (notable models, compute): models and compute, not customers or problems.
- **Paper graphs** (OpenAlex, Semantic Scholar): papers, authors and citations, but not
  customers, problems or infra.
- **LLM knowledge-graph builders** (Microsoft GraphRAG, LightRAG, HippoRAG): build graphs from a
  given corpus. They don't decide what to crawl next.
- **Focused crawling** (Chakrabarti et al. 1999), **OPIC** (Abiteboul et al. 2003) and **PPR
  push** (Andersen, Chung & Lang 2006): the algorithmic base. Established work.

Why build anyway: none of these combine (a) budgeted, rank-guided crawling over *entities* with
(b) typed, provenance-carrying edges across customers, problems, methods, benchmarks, infra and
roles, (c) with a reasoner evaluated against a no-graph baseline. Field vs ours: most of the
pieces are known. The unknown is mostly ours: how well the combination works on this ecosystem.
Say so in any write-up.

## Risks
- **Claims as facts:** marketing numbers stored or reported as truth, and steering the crawl.
  Mitigation (docs/EVIDENCE.md):
  - every edge is graded by who backs it and how independent the sources are, with stricter
    rules for quantitative claims;
  - a separate Verifier checks that each quote really entails the claim;
  - strength sets ranking weight;
  - the Reasoner's wording must match the status;
  - a planted-claims stress test checks all of this.
- **Scraping terms:** respect robots.txt and terms of service; rate-limit; cache raw pages;
  no logins.
- **People data / PII:** store public authorship and role only; no personal contact data; no
  profiles of private individuals. Person nodes are optional in v1.
- **Model leakage in the reasoner eval:** LLMs already know famous companies. Questions must lean
  on post-cutoff or niche facts (EVAL.md §Reasoner).
- **Scope explosion:** e.g. DoorDash links to everything. Mitigation: type caps and the
  relevance boundary (DESIGN.md §3).
- **Method looking for a problem:** if no user question needs it, kill it at the gate.

## Phase 1 gate
- [ ] All eight objects pass their "defined when…" test (FRAMEWORK.md §1). User and objective
      must be confirmed by the owner.
- [ ] Real data sample pulled (about 50 pages, labelled)
- [ ] Test sets frozen (gold entities, labelled pages, questions); baselines named
- [ ] Prior-solution check done (read at least GraphRAG/HippoRAG and one commercial graph)
- [ ] Outside evidence for the problem added (§2)
