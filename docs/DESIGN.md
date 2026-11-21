# Connected Frontiers: Design

Last updated: 2026-11-21 · Status: draft for review

**Contents**

0. [Overview: one system, three roles](#0-overview-one-system-three-roles)
1. [Data model and ecosystem layers](#1-data-model-and-ecosystem-layers)
2. [Components](#2-components)
3. [The crawl algorithm, and estimating coverage](#3-the-crawl-algorithm-and-estimating-coverage)
4. [How the Constructor improves over time](#4-how-the-constructor-improves-over-time)
5. [Reasoner and Examiner](#5-reasoner-and-examiner)
6. [Understanding layer: helping people make sense of it](#6-understanding-layer-helping-people-make-sense-of-it)
7. [Build order](#7-build-order)
8. [Repo layout](#8-repo-layout)

---

## 0. Overview: one system, three roles

![Architecture](architecture.svg)

*Regenerate the figure with `python scripts/make_architecture_svg.py docs/architecture.svg`.*

```mermaid
flowchart LR
    S([Seeds]) --> F

    subgraph C["CONSTRUCTOR · curation"]
        direction LR
        F["Frontier<br/>PPR priority"] --> FE["Fetch + noise gates"] --> EX["Extract"] --> VE["Verify"]
        VE --> GR["Grade"] --> ER["Resolve"] --> RK["Rank<br/>PPR"]
        RK -- "new priorities" --> F
    end

    ER --> KB[("KB vN<br/>graph + GraphRAG index<br/>versioned")]

    subgraph X["EXAMINER · task builder"]
        direction TB
        GE["Generate keys<br/>graph algorithms"] --> WR["Write turns<br/>LLM"] --> CK["Check<br/>deterministic"] --> SG["Solver gate"]
    end

    subgraph R["REASONER · inference"]
        direction TB
        Q["Question / turn"] --> M["Retrieval mode<br/>closed · graph_rag · kg_tools ·<br/>graph_query · oracle"] --> A["Cited answer"]
    end

    KB --> GE
    KB --> M
    SG -- "sessions" --> Q
    A -- "trajectories → per-turn scores" --> X
    A -. "request_crawl (planned)" .-> F
    KB --> U["Explorer<br/>Map › Segment › Entity"]
    KB & SG & A --> HF["Hugging Face<br/>kg · bench · runs · labels"]
```

### Layered architecture (as built, 2026-11-21)

```mermaid
flowchart TB
    subgraph L1["1 · ACQUIRE"]
        SE[Seed registry<br/>48 orgs · all categories] --> FR[Frontier crawler<br/>PPR priority · co-citation ·<br/>site resolution · caps]
        FR --> NG[Noise gates<br/>URL · domain · thin ·<br/>near-dup · media · metric nodes]
        NG --> FC[(Fetch cache<br/>raw HTML by sha)]
        AD[Structured adapters<br/>HF Hub lineage] --> KGS
    end
    subgraph L2["2 · EXTRACT & VERIFY"]
        FC --> EX[Typed extraction<br/>Pydantic · verbatim quotes]
        EX --> VE[Verifier + escalation<br/>second family on risky claims]
        EX -.- C1[(extract cache)]
        VE -.- C2[(verify cache)]
        MP[Model profiles · fallback chains<br/>configs/models.yaml] -.-> EX & VE
    end
    subgraph L3["3 · CURATE"]
        VE --> GR[Evidence grading<br/>claimed→verified · strength]
        GR --> ER[Entity resolution<br/>strict key · 3-way judge ·<br/>hierarchy links]
        ER --> KGS
    end
    subgraph L4["4 · REPRESENT (versioned KB)"]
        KGS[(KG snapshot<br/>data/kb/&lt;version&gt;)] --> RK[PageRank · PPR ·<br/>segments + names]
        KGS --> DI[GraphRAG index<br/>documents → passages ·<br/>edge↔passage · entity↔passage]
    end
    subgraph L5["5 · USE"]
        RK & DI --> EXP[Explorer<br/>Map › Segment › Entity ·<br/>relation lens · paths]
        RK & DI --> LK[cf lookup<br/>KG or live fetch]
        RK & DI --> AG[Reasoner<br/>closed · graph_rag · kg_tools ·<br/>graph_query planned · oracle]
        AG --> UC[Use cases<br/>opportunity discovery ·<br/>education · analysis]
    end
    subgraph L6["6 · EVALUATE & OBSERVE"]
        SV[Silver labels<br/>4-judge ensemble] --> RS[Rescore components]
        TK[Examiner<br/>keys by graph algorithms ·<br/>LLM writes · checks · solver gate] --> BN[Benchmark<br/>single-turn tasks +<br/>multi-turn sessions]
        TR[(Traces<br/>LLM · pages · agent steps)] --> MON[Live monitor · reports]
    end
    subgraph L7["7 · RELEASE"]
        HF[HF collection<br/>kg · bench tasks + sessions ·<br/>runs trajectories · labels]
    end
    AG --> BN
    KGS --> TK & SV
    BN & SV & KGS --> HF
```

Each layer has its own cache or checkpoint, so any failure resumes from the last good state:
fetch cache → extract cache → verify cache → crawl checkpoint → KB version.

### The pipeline, stage by stage

```mermaid
flowchart LR
    C1[crawl] --> C2[clean<br/>HTML → text,<br/>alt texts] --> C3[extract<br/>typed triples<br/>+ quotes] --> C4[resolve<br/>mentions → entities] --> C5[verify<br/>per citation:<br/>does the quote say it?]
    C5 --> C6[grade<br/>per edge:<br/>status · strength] --> C7[index<br/>graph + text/vector] --> C8[represent<br/>PPR · layers ·<br/>entity cards] --> C9[retrieve<br/>agent tools] --> C10[evaluate<br/>agents grounded<br/>on the KG]
    C10 -. gaps .-> C1
```

| Stage | What can go wrong | Measured by |
|---|---|---|
| crawl | wrong pages, missed pages | gold recall per fetch |
| clean | content dropped (e.g. customer cards) | chars kept vs visible text |
| extract | missed or invented triples | triple P/R/F1; unquoted-drop rate |
| resolve | false or missed merges | pairwise merge P/R |
| verify | false support or false reject | false-support rate; agreement with labels |
| grade | status not matching human judgment | κ vs owner grades; calibration |
| index / retrieve | right evidence not retrieved | evidence recall@k for gold questions |
| evaluate | agent reasons badly over good evidence | answer accuracy; citation faithfulness; wording matches status |

| Role | Job | Output |
|---|---|---|
| **Constructor** (curation) | discover, read, verify, connect, rank | a versioned KB: graph + GraphRAG index |
| **Examiner** (task builder) | build tasks from a KB release; keys by graph algorithms; test them (checks + solver gate) | gated multi-turn sessions pinned to the KB version |
| **Reasoner** (inference) | answer and explain from the KB, citing evidence, in one retrieval mode | cited answers, trajectories, and (planned) crawl requests for gaps |

The Examiner and the Reasoner are deliberately different: the Examiner knows the answer (it computed
it on the graph); the Reasoner has to find it. Their gap, per retrieval mode and per turn type, is the
release's scorecard: what a user of this KB can see proven.

**Rule for agents vs algorithms.** Algorithms own *control*: what to crawl, when to stop, how to
rank. Those are what we compare. Models own *judgment*: finding sources, extracting, deciding
merges, reasoning over evidence. Every model step has a non-LLM baseline it must beat.

---

## 1. Data model and ecosystem layers

### 1.1 Layers (how readers orient themselves)

Every entity gets a `layer`, so the graph can be read as a stack.

```mermaid
flowchart TB
    AD["ADOPTER · customers, sectors"]
    AP["APPLICATION · AI-native products"]
    TO["TOOLING · evals, data, observability, agent frameworks"]
    PL["PLATFORM · training, post-training, serving, neolabs"]
    MO["MODELS · frontier labs, open-weight builders"]
    CL["CLOUD · GPU clouds, data centres"]
    CO["COMPUTE · chips, hardware"]
    CO --> CL --> MO --> PL --> TO --> AP --> AD

    RE["RESEARCH · papers, methods, benchmarks"]:::x
    TA["TALENT · roles, skills"]:::x
    CA["CAPITAL · investors, funding"]:::x
    RE -.-> MO & PL & AP
    TA -.-> MO & PL & AP
    CA -.-> MO & PL & AP
    classDef x fill:#f3f0ff,stroke:#7c5cd6
```

Example: Applied Compute sits in **PLATFORM**. Harvey and Cognition are in **APPLICATION**.
DoorDash is an **ADOPTER**. Blackwell is **COMPUTE**. Async RL and APEX-Agents are in
**RESEARCH**.

### 1.2 Entities and relations

**Entity types:** `org` (kind: frontier_lab · neolab · startup · infra · customer · investor ·
academic), `problem`, `method`, `benchmark`, `model`, `technology`, `paper`, `role`, `skill`,
`person` (off in v1). The code contract is in [`src/cf/graph/schema.py`](../src/cf/graph/schema.py).

| Relation | From → To | Example |
|---|---|---|
| `serves` | org → org | Applied Compute → Harvey |
| `works_on` | org → problem | Harvey → legal agents |
| `uses_method` | org / paper → method | Applied Compute → async RL |
| `measured_on` | org / model / paper → benchmark | Mercor → APEX-Agents |
| `builds_on` | org / model → model | → Kimi K3 (from a URL slug only, so `claimed`) |
| `uses_tech` | org → technology | Applied Compute → Blackwell |
| `compares_against` | org / model → model | Harvey case → GPT-5.5 |
| `publishes`, `cites` | org → paper, paper → paper | |
| `hires_for`, `requires` | org → role, role → skill | → "forward deployed researcher" |
| `invests_in`, `acquired`, `partners_with` | org → org | Applied Compute → Delegate (acquired) |

**Every edge is a claim with graded evidence.** Each citation carries `source_url · publisher ·
quote · dates · source_kind (self | counterparty | independent_primary | press | aggregator) ·
stance · entailed`. A fixed rule grades the edge to `unsupported → claimed → confirmed →
corroborated → verified`, with `contested` and `stale` flags, a `strength` score and readable
reasons. **Full spec: [EVIDENCE.md](EVIDENCE.md).**

### 1.3 Sources per category (adapters)

The graph covers **every category** (labs, research labs, academia, businesses, industries, papers,
methods, benchmarks, models, systems, infra, roles and skills) in one typed graph, and ranks all of
them together. Each category has a *native* source. Structured sources give **primary,
high-trust edges with no LLM**; LLM extraction is reserved for unstructured pages.

```mermaid
flowchart LR
    OA["OpenAlex / arXiv /<br/>Semantic Scholar"] -->|publishes · cites · affiliation| KG
    HF["Hugging Face Hub"] -->|builds_on · measured_on · datasets| KG
    LB["Leaderboards"] -->|measured_on + scores| KG
    GH["GitHub"] -->|uses_tech · builds_on| KG
    WEB["Company / lab sites<br/>(LLM extraction)"] -->|serves · partners · works_on · uses_method| KG
    JOB["Careers pages"] -->|hires_for · requires| KG
    KG[("one typed graph<br/>one PageRank")]
```

| Adapter | Edge status by default |
|---|---|
| OpenAlex / arXiv, HF Hub metadata, leaderboards, GitHub manifests | `verified` (primary record) |
| Company and lab pages | graded per EVIDENCE.md (usually `claimed`) |

Seeds for PPR can be **any** node type: a method, a benchmark, a lab or a skill.

### 1.4 The object layer: models, methods, benchmarks, datasets (owner direction, 2026-11-21)

The graph goes **all the way down to the technical objects** and back up to the organisations that
build, use and sell them, and the problems they solve.

```mermaid
flowchart LR
    subgraph Objects["Object layer (what)"]
        MO[model] -- "fine_tuned_from · distilled_from<br/>quantized_from · merged_from" --> MO
        MO -- trained_on --> DS[dataset]
        MO -- measured_on --> BM[benchmark]
        PA[paper / tech report] -- introduces --> ME[method] & BM & DS & MO
        ME -- subtype_of --> ME
        MO -- uses_method --> ME
    end
    subgraph Orgs["Organisation layer (who)"]
        OR[org] -- offers --> MO
        OR -- publishes --> PA
        OR -- serves --> CU[customer org]
    end
    subgraph Problems["Problem layer (why)"]
        CU -- works_on --> PR[problem]
        MO -- "applied_to" --> PR
    end
```

| New in the schema | Meaning | Best source |
|---|---|---|
| `dataset` entity type | training and eval datasets | HF dataset cards, papers |
| `builds_on` + `derivation` ∈ {fine_tune, distill, quantize, merge, continued_pretrain} | model lineage | HF model card `base_model` (primary), release posts |
| `trained_on` | model → dataset | model cards, tech reports |
| `introduces` | paper/post → method, benchmark, dataset, model | papers (arXiv/OpenAlex), release posts |
| `measured_on` + score attribute | model → benchmark with a number | leaderboards, tech reports |
| `applied_to` | model/method → problem | case studies, papers |

**Sources for objects:** model release pages (web), **technical reports as PDFs** (text via a PDF
parser, or arXiv's HTML versions), HF model and dataset cards (structured), benchmark leaderboards.

**Crawling objects:** seeds and frontier nodes can be *any* type. Each type has its own source
finder: model → card + release post + tech report; method → introducing paper; benchmark → paper
+ leaderboard; dataset → dataset card. PPR runs over the mixed graph, so a model reached from
three labs and two benchmarks rises the same way an org does.

### 1.5 Storage

SQLite tables (`entities`, `aliases`, `sources`, `edges`, `evidence`, `crawl_log`,
`frontier`). Raw HTML is kept unchanged under `data/raw/<sha256>`. Graph views come from networkx;
releases are Parquet. Neo4j only if it is ever actually needed.

---

## 2. Components

Python package `cf` under `src/cf/`. Each component implements an interface in
[`src/cf/interfaces.py`](../src/cf/interfaces.py), so variants can be swapped and compared.

| Module | Job | v0 baseline | v1+ variant (must beat v0) |
|---|---|---|---|
| `cf.crawl` | entity → URLs → raw page → text | rule sources; httpx + protego + cache; trafilatura | LLM source finder; bandit over page types; Playwright for JS pages |
| `cf.extract` | text → typed triples | GLiNER + rules | cheap LLM + Pydantic schema; prompts improved over rounds |
| `cf.resolve` | mention → entity | normalized name + domain key | + rapidfuzz + embeddings + LLM adjudication |
| `cf.graph` | store, corroborate, snapshot | SQLite + networkx | — |
| `cf.rank` | scores and frontier policy | BFS · degree · PageRank | PPR push; typed, confidence and time-decayed PPR; HITS |
| `cf.reason` | question → cited answer | R0 no-graph · R1 page RAG | R2 PPR subgraph · R3 agent + graph tools |
| `cf.viz` | KG → understanding views | static Cytoscape.js page | stack map, entity cards, tours, diffs (§6) |
| `cf.eval` | score everything | `cf eval` → `eval/results/*.jsonl` | — |
| `cf.llm` | model access | OpenRouter, cost logged per call, budget guard | routing by measured precision per dollar |

Orchestration is a plain Python loop. Move to LangGraph only if checkpointing or
human-in-the-loop review becomes real friction (log the reason in DECISIONS.md).

---

## 3. The crawl algorithm, and estimating coverage

### 3.1 Entity-level focused crawl with incremental personalized PageRank

Each entity holds two numbers:

- `p(v)`: settled importance.
- `r(v)`: *residual*, importance that has arrived at v but hasn't yet been passed on.

Expanding an entity settles part of its residual and pushes the rest to its neighbours
(Andersen, Chung & Lang 2006, "push").

```
init:  r[s] = 1/|S| for each seed s;  frontier = S
loop until budget spent  or  max over frontier of r(v)/deg(v) < ε:
    v      = argmax over frontier of priority(v)
    pages  = sources(v)[:k]
    triples= extract(fetch(p)) for p in pages
    graph.add(resolve(triples))                     # corroborate if already seen
    p[v]  += α · r[v]                               # settle
    for u in neighbours(v):                         # push
        r[u] += (1-α) · r[v] · w(v→u) / Σw
    r[v]   = 0
    frontier ∪= new neighbours inside the boundary

priority(v) = r(v)/deg(v) × novelty(v) × type_cap(v) − λ·cost(v)
w(v→u)      = β[relation] × strength(v→u)        # evidence strength, see EVIDENCE.md §4
```

```mermaid
sequenceDiagram
    participant AC as Applied Compute (seed)
    participant H as Harvey
    participant B as Harvey Legal Agent Benchmark
    participant M as Mercor
    AC->>H: push residual (serves)
    AC->>M: push residual (serves)
    H->>B: push residual (measured_on)
    Note over B: B gains residual from H
    B-->>H: push back (other orgs measured on B)
    Note over H: Harvey reached by 2 paths, so residual adds up and priority rises
```

What this gives:

- **Reinforcement through several paths** comes for free, because residual accumulates.
- **A principled stopping rule:** stop when no frontier node holds residual above ε.
- **Incremental updates:** no full recompute after each page.

**Relevance boundary.** Non-AI `customer` orgs are added as nodes but expanded only if their
residual is at least τ *and* they have at least 2 edges into the AI core. Each type has a cap.
This stops DoorDash from pulling in all of food delivery.

**Policies compared** (everything else held fixed): `bfs` · `degree` · `pagerank` · `ppr_push` ·
`ppr_push_typed` · `ppr_push_bandit`.

### 3.2 How much of the "entire" ecosystem do we have? Capture–recapture

There is no complete list of the ecosystem to score against, so we **estimate** its size the way
ecologists count fish. Run two crawls from **independent seed sets in different layers** (e.g.
seeds in MODELS vs seeds in APPLICATION):

- n₁ entities found by crawl A, n₂ by crawl B, m found by both
- Estimated population (Chapman): **N̂ = (n₁+1)(n₂+1)/(m+1) − 1**
- Estimated coverage of the union: **(n₁ + n₂ − m) / N̂**

Caveat: the method assumes every entity is equally likely to be found, which is false here
(large orgs are easier to find). That biases N̂ *down*, i.e. coverage is overstated. Mitigations:
stratify by layer and type, use more than 2 crawls (log-linear models), and report the bias
openly. Status: standard method (Lincoln–Petersen / Chapman); applying it to crawls is our
choice, not yet checked against literature on estimating web-crawl coverage.

---

## 4. How the Constructor improves over time

Each loop must show a learning curve on **held-out** data. Nothing tunes on frozen test sets.

| Loop | Signal | What changes | Shown by |
|---|---|---|---|
| Extraction | errors on labelled *train* pages | prompts and few-shot examples (GEPA/DSPy-style reflective edits) | held-out F1 across rounds |
| Source policy | new-edge yield per page type | Thompson-sampling weights | new edges per fetch vs fixed rules |
| Entity resolution | adjudicated merges | alias table and rules | merge P/R across rounds |
| Schema | agent-proposed relations | owner accepts or rejects | share of "other" triples falls |
| Refresh | change rate per source | recrawl schedule | stale-edge rate |
| Reasoner → Constructor | `request_crawl` gaps | targeted crawls | share of "not in graph" answers falls |

---

## 5. Reasoner and Examiner

### 5.1 Reasoner: retrieval modes

**Answer contract:** every claim cites an `edge_id`, which resolves to a URL and quote. **The
wording must match the edge's status**: "X claims …" for CLAIMED, "both parties say …" for
CONFIRMED, plain statements only for VERIFIED ([EVIDENCE.md §5](EVIDENCE.md#5-how-the-reasoner-must-speak-language-contract)).
"Not in the graph" is a valid answer.

Who does the retrieval is the variable; the model stays the same.

| Mode | Who retrieves | How | Expected strength |
|---|---|---|---|
| `closed_book` | nobody | the model's own memory | baseline |
| `graph_rag` | fixed code, once | question n-grams → seed entities → personalized PageRank over the KG → chunks scored by 0.6 · PPR mass of the entities they mention + 0.4 · BM25 → top passages + the edges whose quotes sit in them | cheap; "what is around X" |
| `kg_tools` | the model, step by step | `find_entity` → `neighbors(id, relation)` → `evidence(edge_id)` / `passage(chunk_id)`; `segment`, `ppr`, `paths`, `search_text` | multi-hop and relation-aware, but many steps |
| `graph_query` *(planned)* | the model, in one call | writes a typed path pattern (start, relation path with directions, status filter); executed deterministically; returns the subgraph and its passages | multi-hop in about one call |
| `oracle` | given | the gold subgraph (and computed facts) pasted in | upper bound for retrieval |

**Why `graph_rag` is graph-aware.** The PPR step spreads relevance along edges, so a passage can rank
high without sharing a word with the question when it mentions entities close to the seeds. That
needs the KB-time joins: edge → chunk (the evidence quote's offset; 96.5% linked) and entity → chunks
(mentions). Its limit: PPR ignores relation types, and it makes one retrieval decision. "Which orgs
*use* X" and "which orgs *offer* X" pull the same neighbourhood, and "those orgs → their methods →
benchmarks" is not followed. `kg_tools` and `graph_query` exist for that.

Prior art these follow (unverified until read): HippoRAG (PPR over a KG), Microsoft GraphRAG
(community summaries), Think-on-Graph (LLM-steered graph search), Text2Cypher (model-written queries).

### 5.2 Examiner: building tested tasks from a release

```mermaid
flowchart LR
    KB[(KB vN)] --> G["Generate<br/>graph algorithm picks an anchor,<br/>computes each turn's key"]
    G --> W["Write<br/>LLM turns intents into<br/>natural follow-ups"]
    W --> C{"Check<br/>ids exist · no leak ·<br/>non-empty keys"}
    C -- fail --> RJ[rejected + reason]
    C --> S{"Solver gate<br/>different-family model,<br/>oracle context ≥ 0.6"}
    S -- fail --> RJ
    S --> OK[(sessions_vN.jsonl)]
```

| Template | Turns (each with a computed key) | Use case |
|---|---|---|
| opportunity | who works on problem P → their methods/tech → their benchmarks (or none) → which of those no other org in the KB uses | opportunity discovery |
| landscape | top orgs of a segment → which use/offer method M → evidence status of each claim → recommend one | analysis, trust |
| learn | what M is a kind of / its variants → who uses it → which models use it | education |
| lineage | base model → derivation → who offers the base → siblings on the same base (HF-verified) | education, provenance |

Keys are never written by an LLM. The writer (Inkling-2-mini) only phrases questions; the gate solver
(Nemotron-3.5-lightning) is from a different family. "Under-explored" means *in this KB*, not in the
world. Scoring per turn: set F1 for lists, exact status ladder for evidence labels, letters-match for
derivation, correct abstention for empty keys. Session pass = every turn ≥ 0.5.

**Per-release scorecard ("what this KB can prove"):** lift over closed-book · status-wording accuracy ·
multi-hop accuracy per turn · best retrieval mode per turn type · abstention when the KB has no answer.

## 6. Understanding layer: helping people make sense of it

The graph is only useful if people can *read* it. Each view answers one orientation question.

**Explorer: overview first, details on demand** (Map › Segment › Entity, with breadcrumbs, URL
hash routing and browser back; Esc goes up one level).

| Level | Shows | Why |
|---|---|---|
| Map | one bubble per segment (≥ 8 members, top 30), links aggregated across segments and labelled by their most common relation; own layout with overlap removal | 9k nodes at once is a hairball |
| Segment | that segment's top 40 members by PageRank; a card with main players, problems, methods, models, benchmarks, connected segments | the education overview |
| Entity | relation lens (sectors by relation, top 12 per sector, "+N more"); a card with connections grouped by relation, status chips, evidence, and the source pages | details and provenance |
| All entities | the full force layout or layer swimlanes; path finder | for power users |

| View | Orientation question | Built from |
|---|---|---|
| **Stack map** | "How does the ecosystem fit together?" | layers as lanes; edges that cross layers |
| **Entity card** | "What is X, and what is it connected to?" | top-k PPR neighbours by relation, evidence quotes, cited summary |
| **Guided tour** | "Walk me from X outward" | ordered walk by PPR from a seed, one sentence per step, each cited |
| **Method diffusion** | "How fast does research reach industry?" | paper date of a method → first org `uses_method` date |
| **Benchmark ↔ customer** | "Which evals matter to buyers?" | benchmarks reached from customer-facing claims |
| **Segments** | "What are the clusters?" | community detection (Leiden/Louvain), labelled by a model with citations |
| **What changed** | "What's new since last month?" | diff between snapshots |

**Key aspects** the views should make visible (seed list; owner to refine):

1. Where value and dependence sit across layers (e.g. how many applications build on how few
   models).
2. How fast research methods move into production (the diffusion lag).
3. Which benchmarks are cited to customers, and which only in papers.
4. What skills and roles the frontier is hiring for.
5. Open-weight vs closed-model dependence.

*Caveat:* PageRank measures link centrality, not merit or quality. The UI says "most connected
from this seed", never "best".

---

## 7. Build order

```mermaid
flowchart LR
    M0["M0<br/>gold sets frozen"] --> M1["M1<br/>skeleton + BFS<br/>cf eval runs"]
    M1 --> M2["M2<br/>LLM extraction<br/>vs GLiNER"]
    M2 --> M3["M3<br/>PPR push vs BFS<br/><b>core result</b>"]
    M3 --> M4["M4<br/>typed weights, boundary,<br/>bandit, capture–recapture"]
    M4 --> M5["M5<br/>Reasoner R0–R3"]
    M5 --> M6["M6<br/>understanding views,<br/>HF release"]
```

Each milestone ends with numbers in the EVAL.md results log.

---

## 8. Repo layout

```
connected-frontiers/
├── README.md · PROBLEM.md · EVAL.md · DECISIONS.md   # framework docs (root by convention)
├── pyproject.toml · Makefile · .env.example
├── docs/          DESIGN.md · DATASET.md · architecture.svg
├── configs/       seeds.yaml · crawl.yaml · eval.yaml
├── src/cf/        cli.py · config.py · interfaces.py
│   ├── crawl/  extract/  resolve/  graph/  rank/
│   └── reason/ viz/  eval/  llm/
├── tests/
├── notebooks/     one per milestone experiment
├── data/          raw/ interim/ processed/ (gitignored) · samples/
└── eval/          gold/ (frozen, committed) · results/ (gitignored)
```
