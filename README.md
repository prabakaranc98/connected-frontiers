# Connected Frontiers

> A knowledge graph of the frontier-AI research and industry ecosystem: who serves whom, on which
> problems, with which methods, measured on which benchmarks, on what infra, and hiring for which
> skills. It is **built the PageRank way** by a rank-guided crawler, and **explained** by a reasoner
> that cites its evidence.

**Status (2026-11-21):** v0.1, mid-crawl. Three roles run end to end: the Constructor builds a
versioned KB, the Examiner builds and gates multi-turn tasks from it, the Reasoner answers them in
five retrieval modes, and a per-KB scorecard measures truth, coverage, usefulness and cost.
**The agent harness is not optimised yet** (no prompt or tool tuning, no retries or self-checks):
the numbers below are a first, honest baseline.

| v0.1 at a glance (KB `v20261121-1821`) | |
|---|---|
| Graph | 1,134 pages · 10,219 entities · 11,196 edges · 117 segments (82 named) · crawl still running (1,550+ pages) |
| Truth (silver re-reads the cited page) | verifier-accepted edges supported 93–97% · verifier-rejected 50% (it discards real edges) · ER accuracy 0.86, false merges 0.13 |
| Usefulness (10 gated sessions) | Inkling-2-small: KG tools **0.86** mean F1 vs **0.19** closed book (paired Δ +0.67 [+0.56, +0.76]) · whole-session pass@1 **40%** [10–70%] |
| Cost | $4.6 LLM spend all time · ~$0.003 per multi-turn conversation |

Full scorecard: [reports/scorecard-v20261121-1821.md](reports/scorecard-v20261121-1821.md).

![Architecture](docs/architecture.svg)

---

## Why

The ecosystem changes weekly, and the connections that explain it are spread across company pages,
case studies, research blogs, papers, leaderboards and job posts. One page already holds a lot.
Applied Compute's `/training` page alone gives about 25 typed edges:

```mermaid
flowchart LR
    AC["Applied Compute<br/><i>platform</i>"] -- serves --> H[Harvey] & MR[Mercor] & CG[Cognition] & DD[DoorDash]
    H -- works_on --> LA((legal agents))
    H -- measured_on --> HB[[Harvey Legal Agent Benchmark]]
    MR -- measured_on --> AX[[APEX-Agents]]
    CG -- works_on --> BD((real-time bug detection))
    AC -- uses_method --> RL{{async RL · SFT · self-distillation}}
    AC -- uses_tech --> BW[(Blackwell)]
    AC -- compares_against --> FM["GPT-5.5 · Opus 4.8"]
```

*(These are claims from the page, stored as `claimed` until corroborated.)*

Following these links recursively, ranked so that **things reached by several paths rise**, is
how the graph grows.

## What it's for

Think **Connected Papers, but for the whole ecosystem**: not just papers citing papers, but labs,
neolabs, startups, infra, customers, problems, methods, benchmarks, models, roles and skills, with
every link backed by graded evidence.

| Who | Use |
|---|---|
| Researchers and engineers | see who works on a problem, with which methods, measured how; find gaps; pick projects |
| Newcomers and professionals | build a mental model of the stack, layer by layer; see which skills the frontier hires for |
| Agents | a grounded, cited knowledge source to reason over (the Reasoner), instead of model memory |
| Dataset and eval builders | curated, provenance-carrying data; a 5-task benchmark ([docs/DATASET.md](docs/DATASET.md)) |

It is also a **practice ground for the whole chain**, with each stage measured:

```mermaid
flowchart LR
    A[Crawling<br/>polite, rank-guided] --> B[Curation<br/>extraction, resolution,<br/>evidence grading]
    B --> C[Knowledge representation<br/>typed graph, layers,<br/>provenance]
    C --> D[Reasoning<br/>PPR retrieval,<br/>cited answers]
    D --> E[Agentic systems<br/>constructor ↔ reasoner,<br/>corroboration seeking]
    E -. gaps .-> A
    C --> F[Downstream<br/>datasets · evals ·<br/>understanding views]
```

## How it works

| Part | What it does | Where |
|---|---|---|
| 🕸️ **Constructor** (curation) | rank-guided crawl → noise gates → extract → verify → grade → resolve → versioned KB (graph + GraphRAG index) | `src/cf/crawl`, `extract`, `graph`, `resolve`, `rank`, `docs.py`, `kb.py` |
| 🧪 **Examiner** (task builder) | builds multi-turn tasks from a KB release: keys computed by graph algorithms, LLM-written turns, deterministic checks, a solver gate | `src/cf/bench/sessions.py` |
| 🧠 **Reasoner** (inference) | answers from the KB in one retrieval mode (closed book · GraphRAG · KG tools · graph query · oracle), citing every claim | `src/cf/agent` |
| 🗺️ **Explorer** | the real graph (ForceAtlas2): zoom reveals more entities; click to explore in place and walk a trail; entity card with relations, evidence status and sources; relation lens; path finder | `src/cf/viz` |
| 📏 **Eval + observability** | per-KB scorecard (truth · coverage · structure · usefulness · cost), silver labels (4-judge ensemble), traces, live crawl monitor | `src/cf/eval`, `trace.py`, `serve.py`, [EVAL.md](EVAL.md) |
| 🤗 **Release** | HF collection: `kg` · `bench` (tasks + sessions) · `runs` (trajectories) · `labels` | `release.py`, [docs/DATASET.md](docs/DATASET.md) |

The gap between the Examiner (which knows each answer) and the Reasoner (which must find it), per
retrieval mode and turn, is each release's scorecard. Design: [docs/DESIGN.md §0 and §5](docs/DESIGN.md#5-reasoner-and-examiner).

The core experiment: does **personalized-PageRank "push" crawling** reach the relevant
ecosystem in fewer fetches than **BFS**? Details are in [docs/DESIGN.md §3](docs/DESIGN.md#3-the-crawl-algorithm-and-estimating-coverage).

## Initial evaluation (v0.1)

**How it is measured.** The Examiner computes each turn's answer from the KB with graph algorithms,
an LLM only phrases the questions, deterministic checks reject leaks and empty keys, and a solver
gate (two model families, given the gold evidence) proves every turn is answerable. The Reasoner then
answers the same sessions in each retrieval mode. Scores are per turn (set F1, or exact status
labels), aggregated per session; intervals are 95% session-bootstrap; mode differences are paired
tests on the same sessions. Truth is checked separately (silver judges re-read the cited pages),
because KB-derived keys measure use of the KB, not whether the KB is right.

**Results on 10 sessions × 4 models × 5 modes** (mean turn F1; whole-session pass@1 in brackets):

| Model | Closed book | GraphRAG | KG tools | Graph query | Oracle |
|---|---|---|---|---|---|
| Inkling-2-small | 0.19 (0%) | 0.26 (0%) | **0.86 (40%)** | 0.51 (0%) | 0.90 (60%) |
| Qwen3.5-35B-A3B | 0.05 (0%) | 0.20 (0%) | 0.67 (20%) | 0.45 (0%) | 0.77 (40%) |
| Mistral-Small-2603 | 0.07 (0%) | 0.16 (0%) | 0.49 (10%) | 0.44 (0%) | 0.63 (40%) |
| Nemotron-3.5-lightning | 0.06 (0%) | 0.13 (0%) | 0.37 (0%) | 0.22 (0%) | 0.54 (0%) |

**What it says, and how sure we are**

- **The KB is what makes these answers possible.** No model gets a whole session right closed book;
  with KG tools Inkling reaches 0.86, near its 0.90 with perfect evidence (oracle). The KG-tools vs
  closed-book gain is significant for every model (paired Δ F1 from +0.31 to +0.67, all intervals above 0).
- **One-shot GraphRAG barely helps** (+0.07 for Inkling, interval crosses 0). Its PageRank retrieval
  ignores relation types, and these sessions are typed and multi-hop.
- **Model-written graph queries trail the step-by-step walk** (0.51 vs 0.86, paired Δ +0.34
  [+0.07, +0.63]). Unexplored: the query tool's interface may be what fails, not the idea.
- **Nemotron-lightning's ceiling is low** (0.54 even with the oracle): it measures the model, not the KB.
- **Uncertainty is large.** 10 sessions give pass@1 intervals ~60 points wide. Next run: 40 sessions,
  3 trials each (pass^3 for reliability), precision / recall / citation validity, an owner audit of 20 keys.

**Not optimised yet:** the harness has default prompts and tool descriptions, no retries, no
self-verification and no tuning per model. Bugs fixed while building this (all with tests): answers
listing the question's subject instead of the answer (now schema-enforced), a prompt that suppressed
tool use, lineage keys asking for data the source never recorded, and JSONL records split by
Unicode line separators.

## Quickstart

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
make setup          # creates .venv, installs deps, creates .env from .env.example
# edit .env  → OPENROUTER_API_KEY=...   (HF_TOKEN optional if `hf auth login` was done)
make doctor         # checks keys (presence only), configs, folders
make test           # runs the test suite
uv run cf --help    # crawl · rank · ask · viz · eval · release
```

Optional extras: `uv sync --extra extract-baseline` (GLiNER, pulls torch), `--extra resolve`,
`--extra data`, `--extra release`, `--extra js` (Playwright).

## Commands

| Command | Does | Milestone |
|---|---|---|
| `cf doctor` | environment and config check | ✅ |
| `cf scout --pages 6 --hop2-orgs 25` | multi-seed crawl → extract → verify → explorer | ✅ |
| `cf build` | rebuild graph from cache + HF adapter + ER + segments + report | ✅ |
| `cf silver --version v1` | ensemble silver labels; owner dispute queue | ✅ |
| `cf tasks` / `cf bench` | use-case tasks from the KG; agent benchmark + leaderboard | ✅ |
| `cf sessions` / `cf sessions-bench` | Examiner: build + gate multi-turn sessions; Reasoner runs them in every retrieval mode, per-turn scores | ✅ |
| `cf silver-kb` | does the status ladder mean anything? edges stratified by status, judged on their cited page; verifier + ER vs silver | ✅ |
| `cf eval` | per-KB scorecard → `reports/scorecard-<kb>.md` | ✅ |
| `cf crawl --budget N [--resume\|--status]` | PPR frontier crawl, noise gates, checkpoints (`scripts/crawl_supervisor.sh` keeps it alive) | ✅ |
| `cf serve` | local dashboard: crawl monitor at `/`, explorer at `/explorer` | ✅ |
| `cf lookup "<name or url>"` / `cf cache` | answer from KG or fetch live · cache freshness and refresh cost | ✅ |
| `cf docs` / `cf ask "<q>" --mode graph_rag` | GraphRAG document index · grounded answers citing passages + edges | ✅ |
| `cf kb list\|show\|diff\|use` | versioned KB snapshots (manifest: counts, models, prompts, git) | ✅ |
| `cf release [--push --repo …]` | HF collection: kg · bench (tasks + sessions) · runs · labels (push is private, explicit) | ✅ |
| `cf crawl --policy bfs` vs `ppr` | the core crawl comparison | built, comparison run pending |

## Project layout

```
connected-frontiers/
├── README.md · PROBLEM.md · EVAL.md · DECISIONS.md
├── pyproject.toml · Makefile · .env.example
├── docs/       DESIGN.md · DATASET.md · architecture.svg
├── configs/    seeds.yaml · crawl.yaml · eval.yaml
├── src/cf/     cli · config · interfaces · crawl/ extract/ resolve/ graph/ rank/ reason/ viz/ eval/ llm/
├── tests/      notebooks/
├── data/       raw/ interim/ processed/ (gitignored) · samples/
└── eval/       gold/ (frozen) · results/ (gitignored)
```

## Documents

| Doc | Read it for |
|---|---|
| [PROBLEM.md](PROBLEM.md) | north star, user, task, objective: the eight objects |
| [docs/DESIGN.md](docs/DESIGN.md) | **layered architecture** (acquire → extract/verify → curate → represent → use → evaluate → release), crawl algorithm, understanding views |
| [docs/DISCOVERY.md](docs/DISCOVERY.md) | opportunity discovery and education uses (owner priorities) |
| [EVAL.md](EVAL.md) | metrics, frozen test sets, baselines, results log |
| [docs/EVIDENCE.md](docs/EVIDENCE.md) | truth vs claim: evidence grading, Reasoner wording rules |
| [docs/DATASET.md](docs/DATASET.md) | Hugging Face dataset and benchmark plan |
| [DECISIONS.md](DECISIONS.md) | dated decisions and open questions |

## Principles

- **Algorithms decide, models judge.** Crawl policy and stopping rules are algorithms, so they
  can be compared. Models handle reading and judgment, and each has a non-LLM baseline.
- **Claim ≠ fact.** Every edge is graded by its citations: who says it (self, counterparty,
  independent record, press), how many independent publishers back it, and whether the quote
  really supports it. The ladder runs unsupported → claimed → confirmed → corroborated → verified,
  with contested and stale flags. Answers must word claims as claims. See
  [docs/EVIDENCE.md](docs/EVIDENCE.md).
- **Measured, not asserted.** Coverage is estimated, improvements show learning curves, and
  failures are logged.
- **Polite crawling.** Respect robots.txt, rate-limit requests, cache raw pages, no logins, and no
  personal data.
