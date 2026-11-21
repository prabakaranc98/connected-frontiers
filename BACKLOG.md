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
