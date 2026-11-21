# Decisions log — Connected Frontiers

Newest first. Gate passes, kills, scope changes, method and stack choices.

## 2026-11-21 — Keep Gemma-3-27B as the escalation verifier (owner)
- Roles: extract Inkling-2-mini (fallback Qwen3.5 on long pages) · verify DeepSeek-v4.1-flash ·
  second opinion on risky claims Gemma-3-27B.
- Owner accepted Gemma 3 here, although it is older than the preferred set: it works and cut false
  support 0.43 → 0.14. No switch, so no re-verification of the ~830 cached pages.
- Revisit if: escalation precision drops on the next silver check, or the KB is rebuilt anyway
  (then Mistral-Small-2603 is the drop-in alternative).

## 2026-11-21 — Direction: opportunity discovery + education (owner)
- **Lead:** (A) **opportunity discovery**: problems, white space, "what to build" briefs, recurring
  patterns; (B) **education**: overview maps, pattern cards, learning paths, guided tours,
  self-check quizzes. See docs/DISCOVERY.md §0.
- **Deprioritized:** funding and financial data, partnership and investment forecasting, the
  world-model framing, people (later).
- Why (owner): the KG is knowledge to *use*, to understand the ecosystem and decide what to build
  or learn. Forecasting money flows isn't the point now.
- Revisit: people nodes after the crawl and quality loop settle; temporal checks once a second
  snapshot exists.

## 2026-11-21 — Scale-up, silver labels, fallbacks, agents + benchmark v0, object layer v0
- **Scale:** 48 seeds across all categories plus hop 2 by PPR → 245 pages, 50 publishers, 3,433
  entities. HF Hub adapter (no LLM): 238 rows → 132 `offers`, 62 `trained_on`, 44 `builds_on` (26
  fine-tunes, 18 quantizations). HF metadata is uploader-declared on an independent registry,
  graded `verified` with that caveat.
- **Models (owner preference):** recent small open models; **no gpt-oss**. Roles and fallbacks are
  in `configs/models.yaml`:
  - extract: Inkling-2-mini
  - verify: DeepSeek-v4.1-flash, escalating to Gemma-3-27b
  - ER: DeepSeek
  - agents: Qwen3.5-35B-A3B, Inkling-2-mini, Nemotron-3.5-lightning, Mistral-Small-2603
- **Per-model parameter profiles** (measured): Inkling *requires* reasoning (400 if disabled);
  Nemotron-3.5 and Qwen3.5 *ignore* reasoning caps (whole budget spent on reasoning → empty
  answers), so reasoning is off for them; DeepSeek, Mistral and Gemma accept "off".
- **Fallbacks:**
  1. ordered model chains per role on errors;
  2. empty-answer-after-truncation → retry with reasoning off (or more tokens);
  3. **verification escalation:** accepted items with a risky relation or a fragment quote need a
     second family to agree;
  4. **ER:** only a strict key (casefold + punctuation + legal suffix) may auto-merge; same-domain,
     containment, fuzzy and loose-normalized pairs go to the 3-way judge.
- **Silver labels by ensemble vote** (4 judges, production components excluded). Disputes go to
  the owner, and only those become gold. Measured gains: false support 0.43 → 0.14, false merges
  0.48 → 0.17.
- **Agents + benchmark v0:** 6 KG tools; harness with closed-book / KG-tools / oracle conditions;
  4 use-case task families with answer keys computed from the KG; rule-based scoring (no LLM
  judge). Grounding raises the mean from 0.11–0.17 to 0.52–0.67. The retrieval gap (oracle − KG
  tools) is about 0.1; the reasoning gap (perfect − oracle) is about 0.22–0.25.
- **Explorer:** sigma.js WebGL with the layout precomputed; **relation lens** focus (sectors by
  relation, outgoing right / incoming left, fan-out of hop 2); segment bubbles with LLM-written
  names; edge tooltips; path finder; layer swimlanes.
- **Known limits:**
  - silver κ ≈ 0.4 (noisy), so owner review is needed;
  - U1 key (top-10 PageRank in a segment) is a weak proxy, so U1 needs redesign;
  - 5 Qwen KG-tool runs ended without valid JSON (step budget);
  - corroboration across company pages stays low (16 multi-publisher edges);
  - extract and verify share one cache key, so changing the verifier re-extracts (~$0.6 per
    245 pages); split planned.
- **Spend to date:** about $1.7 of the $10 owner budget.

## 2026-11-21 — Round 1 (manual) extractor + ER fixes; 8-seed build; WebGL explorer
- Changes:
  - new relations `offers`, `part_of`, `subtype_of`;
  - index-page rule in the extractor prompt;
  - verifier convention "own product listing → offers";
  - three-way ER (same / part_or_subtype / different), where part/subtype becomes a hierarchy
    link instead of a merge;
  - verifier switched to deepseek-v4.1-flash with reasoning off (Nemotron ignored reasoning
    caps; 0/8 planted false claims accepted vs 1/8 for Nemotron);
  - sigma.js WebGL explorer with the layout precomputed in Python.
- Results (52 pages, 8 seeds; reports/ has the full report):

  | Metric | Before | After round 1 |
  |---|---|---|
  | verifier rejects | 30% | 14.1% |
  | ER | 37 merges incl. over-merges | 34 merges + 28 hierarchy links |
  | $/page | — | $0.0024 |
  | $/verified edge | — | $0.0002 |
  | build time | — | 237 s |

- Remaining:
  - `serves` 30% / `uses_tech` 28% rejects; cursor.com 57%;
  - same-domain auto-merge swallowed NSF sub-units (fixed after this build: same domain now goes
    to the judge unless the names are near-identical);
  - one subtype direction error;
  - a GGUF quantization was merged into its base model (needs `builds_on` + derivation).
- Caveat: verifier accept/reject is the verifier's opinion. Precision and recall need the
  hand-labelled set.

## 2026-11-21 — Scout run: model roles, text extraction and verifier fixes (measured)
All on one page (appliedcompute.com/training), same prompt. Single run each, so treat as indicative,
not as a benchmark.
- **Extraction model** (time · cost · triples):

  | Model | Time | Cost | Triples | Notes |
  |---|---|---|---|---|
  | nemotron-3.5-lightning | 152 s | $0.0089 | 14 | ignored reasoning limits (19k reasoning tokens in one run) |
  | **inkling-2-mini** | **18 s** | **$0.0018** | **28** | best relation choices |
  | nemotron-3-super-120b | 58 s | $0.0113 | 29 | mislabels methods as `works_on` |

  **Decision:** extract = `thinkingmachines/inkling-2-mini`; verify =
  `nvidia/nemotron-3.5-lightning` (a different family, so the checker is independent of the
  maker); reason = `thinkingmachines/inkling-2-small`.
- **Reasoning tokens:** reasoning models can spend the whole `max_tokens` on hidden reasoning and
  return empty content. Fix: a hard `reasoning.max_tokens` cap (the "effort: low" hint was
  ignored), detect truncated or empty responses, and retry with a larger budget.
- **Page text:** trafilatura dropped the customer cards (2.9k of 4.3k characters). Fix: use the
  visible body text when trafilatura keeps < 80% of it, and append image alt texts (logos name
  customers).
- **Verifier without source context rejected 28/28 as "contradicts".** Quotes on a company's own
  page rarely name the company ("we…", "… with Harvey"). Fix: pass the publisher and title to the
  verifier, and add `not_enough_info` (FEVER's third label). Result: 11 supported, 12 not enough
  info, 0 false contradictions. The verifier is now on the strict side; calibrate on the labelled
  set rather than by eye.
- **Type-safe LLM calls:** Pydantic models define each call's contract, the JSON schema is
  generated from them, and responses are validated back into them.
- Revisit if: the labelled set shows the verifier's false-reject rate is high. Then try a
  stronger verifier, or let the extractor quote longer spans.

## 2026-11-21 — Claim vs truth: evidence grading
- Context: the owner asked that agents flag clearly what is truth vs claim, driven by how strong
  the citations are.
- Decision:
  - A deterministic grader (`src/cf/graph/grading.py`) turns each edge's citations into a
    status ladder (unsupported → claimed → confirmed → corroborated → verified), contested and
    stale flags, a strength score and readable reasons.
  - Models only judge per-citation stance and entailment (the Verifier is a separate call from
    the Extractor).
  - Quantitative claims don't count press echoes.
  - Strength weights PPR edges.
  - The Reasoner's wording must match the status.
- Why: a rule can be audited and tested (8 scenario tests); an LLM's "this seems true" can't be.
  Weak claims must not steer the crawl either.
- Revisit if: grader κ vs owner < 0.7, or calibration shows strength doesn't track truth.

## 2026-11-21 — North star set; scaffold, layers, coverage estimate, HF plan
- Context: the owner stated the aim: the entire frontier-AI ecosystem in one KG, built the
  PageRank way, plus helping people understand it.
- Decision:
  - "Entire" is made measurable with a capture–recapture coverage estimate (DESIGN §3.2).
  - Every entity gets an ecosystem `layer` (compute → … → adopter, plus research, talent and
    capital as cross-cutting layers).
  - An understanding layer of views (DESIGN §6) is added, evaluated with an orientation quiz.
  - The HF dataset and benchmark plan is in docs/DATASET.md.
  - Repo layout: `src/cf` package; framework docs stay at the root (FRAMEWORK.md §6); design and
    dataset docs go in `docs/`. Tooling: uv + Typer CLI + Makefile.
- Why: an unmeasurable "entire" invites Goodhart (counting nodes). Coverage with an interval is
  honest. Layers give readers a map.
- Revisit if: capture–recapture bias is too large to be useful. Then fall back to coverage of an
  external reference list (e.g. a curated industry list), per layer.

## 2026-11-21 — Project started at Phase 0; design drafted
- Context: the owner wants a crawl → rank → reason → visualize system for the frontier-AI
  ecosystem, built as two roles (Constructor, Reasoner) over one KG.
- Options considered: plain PageRank over a scraped corpus; LLM-driven crawling (agent picks the
  next URL); algorithm-driven crawling with LLM workers.
- Decision (proposed, awaiting owner): algorithm-driven, entity-level focused crawl with
  incremental PPR push. LLMs used for source finding, extraction, merge adjudication and
  reasoning. Python, SQLite, networkx, OpenRouter. Plain loop before LangGraph.
- Why: the control policy is the object under test and must be swappable and comparable against
  BFS. An LLM-chosen crawl can't be compared cleanly.
- Revisit if: PPR push doesn't beat BFS at M3 (then try the bandit and typed variants; if those
  also fail, record it as the result).

## Open, owner to decide
- [ ] Confirm the user and the moment of use (PROBLEM.md §1)
- [ ] Confirm objective thresholds (PROBLEM.md §6, EVAL.md)
- [ ] Choose the 3 seeds and build the gold entity set
- [ ] Person nodes in v1: yes or no

## 2026-11-21 · Three roles; explorer drill-down; metric nodes

- **Roles (owner):** Constructor = curation (not "training"), Reasoner = inference, plus an
  **Examiner** that builds and tests tasks from each KB release and is run against the Reasoner.
  Their gap per retrieval mode is the release scorecard ("what this KB can prove").
- **Retrieval modes made explicit:** `graph_rag` is fixed, one-shot (seed → PPR → passages); the
  model writes no query. `kg_tools` lets the model walk. A `graph_query` mode (model writes one typed
  path query, executed deterministically) is planned, as a controlled comparison, not a default.
- **Explorer:** overview first, details on demand: Map (segments) › Segment (top 40 + card) › Entity
  (lens capped at 12 per relation + card with sources). Reason: 9k nodes, 120 segments.
- **Metric nodes gated** ("1B events per month"): measured first: only 35 nodes, with false
  positives on orgs and paper titles ("10x Genomics", "10 years of AlphaGo"), so orgs and papers are
  exempt. Crowding came mostly from 2,353 paper/blog nodes and 844 isolates; the drill-down handles that.
- **Segment naming fixed:** one call for 120 clusters truncated silently and fell back to "A · B"
  names; now batched by 25, failures recorded in `graph.segment_naming`.
