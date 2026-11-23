# Retrieval, grounding and use: how the graph reaches an answer

Status: 2026-11-22 · one model (Inkling-2-small), 6 hand-written questions, one trial each. Read the numbers as a
diagnosis, not a benchmark.

## 1. Five ways to answer, from no retrieval to agentic GraphRAG

| Condition | What happens | Closest prior work |
|---|---|---|
| `closed_book` | the model answers from memory | – |
| `kg_rag` (typical GraphRAG) | one retrieval pass: link the question's entities, take their best-supported edges, add passage search (personalized PageRank over entities + BM25), pack it all into the prompt, answer once | GraphRAG [1], HippoRAG [2, 3], LightRAG [8] |
| `kg_tools` (plain tool loop) | the model calls graph tools freely (find, neighbours, evidence, passages, PPR) in one ReAct-style loop | ReAct [11], KG-Agent [6], Graph-CoT [16] |
| `kg_agentic` (agentic GraphRAG) | plan sub-questions → multi-step research with tools → evidence gate (read sources before relying on them) → notes (findings with cited edge ids) → coverage reflection → advice built on findings → synthesis check | Think-on-Graph [4], RoG [5] (plan, then retrieve), Self-RAG [12] (critique), GraphReader [14] (agent with a notebook) |
| `kg_enrich` (memory-first) | the model's own answer is the draft; it lists claims to check, checks them in the graph and explores beyond them, then revises only what the evidence changes, recording each change | corrective/adaptive RAG in the agentic-RAG survey [10] |

The graph is the retrieval substrate in all of them: typed edges, each with an evidence status (claimed → confirmed →
corroborated → verified) and quotes; a passage index linked to entities and edges; segments.

## 2. How we measure it: retrieved → grounded → used

A RAG answer can fail in three different places, so we score them separately (the retriever/generator split of
RAGChecker [17]):

| Stage | Metric | Question it answers |
|---|---|---|
| retrieval | **retrieved** = gold entities that reached the model's context | did the right facts come back? |
| grounding | **grounded** = gold entities written into findings with cited edges | did the model take them in? |
| use | **used** = gold entities named in the answer · **utilisation** = used ÷ retrieved | did they change the advice? |
| focus | **precision** = gold ÷ all retrieved entities | how much noise came with them? |
| calibration | **doubt** = phrases calling a claim "unverified" | does it treat "not in the graph" as false? |

**Gold is question-aware** (`cf/bench/retrieval.py`). Each question lists the graph facts that answer it, e.g. for
"Harvey is our customer: what will it connect to and how does it build agents?" the gold is Harvey's `uses_tech`,
`uses_method`, `offers`, `works_on` and `partners_with` edges. For "which open bases do people build on?" it is the
5 most built-on models. An earlier reference (an anchor's strongest edges whatever was asked) could not tell good
retrieval from bad, and was replaced.

## 3. What we found and fixed

Diagnosis on the first run, then one fix at a time, same questions:

| Finding | Evidence | Fix |
|---|---|---|
| **Retrieved, then dropped.** Long tool loops bury early results | Harvey: 12/12 key neighbours touched, 0 in findings. Matches "lost in the middle" [13] and distraction by irrelevant context [18] | the notes step receives a compact list of every fact the research touched, best supported first (`_facts_block`) |
| **No way to rank.** "Which bases are most built on?" needs counting | 0/5 gold reached by every condition | `top(relation, direction, type)`: rank entities by distinct connections |
| **Wrong starting point** | the agent searched words instead of the question's entities | entity linking before planning (`link`) |
| **Stopped at a thin node** | "agentic RL" has 1 edge; its parent "reinforcement learning" has 41 | `broader()`: hierarchy, `subtype_of`, head noun with abbreviations expanded; shown when a node has < 5 edges |
| **Evidence split across ER twins** | 395 names exist as both an org and a technology (vLLM: 272 + 23 edges; Cursor, GitHub, Slack, Modal…); 80 duplicate edges | `neighbors` merges same-name twins (`merge_twins`), metrics count a twin as the same entity |
| **"Not in the graph" read as false** | QLoRA called "unverified" on the LoRA control question | coverage card + rule: missing ≠ false; flag only self-claimed or contradicted claims |
| **Memory-first searched too narrowly** | it checked only the draft's own claims | it must also explore from the question's entities with `top` / `graph_query` |

## 4. Results (means over 6 questions, one trial)

Run `eval/experiments/retrieval_eval/20261122-0619`, $0.19.

| Condition | retrieved | grounded | used | utilisation | precision | doubt | tool calls |
|---|---|---|---|---|---|---|---|
| memory | 0.00 | – | 0.03 | – | – | 0.00 | 0 |
| typical GraphRAG | 0.18 | – | 0.09 | 0.53 | 0.18 | 0.00 | 1 |
| plain tool loop | 0.65 | – | 0.12 | 0.18 | 0.29 | 0.00 | 10 |
| agentic v2 (start) | 0.61 | 0.33 | 0.14 | 0.28 | 0.16 | 0.50 | 24 |
| agentic v3 (+top, link, facts) | 0.63 | 0.44 | 0.21 | 0.36 | 0.21 | 0.00 | 15 |
| agentic v4 (+broader, twins) | **0.76** | 0.44 | 0.21 | 0.28 | 0.20 | 0.00 | 16 |
| memory-first v1 (start) | 0.60 | 0.45 | 0.18 | 0.25 | 0.41 | 0.67 | 14 |
| memory-first v2 (+explore, facts) | 0.60 | **0.50** | **0.29** | **0.54** | 0.24 | 0.00 | 10 |
| memory-first v3 (+broader, twins) | 0.68 | 0.46 | 0.25 | 0.38 | 0.28 | 0.17 | 9 |

What this says:

1. **Typical GraphRAG retrieves the wrong things, then uses them well.** Its ranking ignores the question (for Harvey
   it packs the law firms that use Harvey), so retrieval is 0.18; but half of what it packs reaches the answer
   (utilisation 0.53). One pass is cheap and focused, not targeted.
2. **Agents retrieve most of the gold (0.6-0.76) and use little of it (0.12-0.29).** The bottleneck is not retrieval
   any more; it is selection and synthesis. Retrieval fixes (broader, twins) raised retrieval from 0.63 to 0.76 and
   left use flat.
3. **Handing retrieved facts to the notes step helps** (grounded 0.33 → 0.44 agentic, used 0.14 → 0.21), and the
   missing ≠ false rule removed nearly all false doubt (0.50 → 0.00).
4. **Memory-first uses retrieved facts best** (utilisation 0.54 at v2): it edits a plan instead of writing one from
   a pile of tool results.
5. **Noise is large.** One trial per cell: Harvey's "used" moved 0.47 → 0.23 between v3 and v4 with the same
   retrieval. Version-to-version differences under about 0.1 are not distinguishable here.
6. **"Used" has a ceiling.** An answer names at most about 20 items (6 topics, 3 projects × 6 tools, 8 stack), while
   gold sets have 22-39 entities, so 1.0 is not reachable; compare conditions, not absolute values.

### Generated task set (11 tasks, 3 trials): see [AGENCY_EVAL.md](AGENCY_EVAL.md#use-case-testbed-v1-2026-11-22-generated-tasks-three-trials-judges)

With relevance-ranked facts and two-hop patterns (agentic v5), Inkling-2-small retrieved 0.90 of the gold, grounded
0.69 and used 0.37 ± 0.03 across three trials; typical GraphRAG used 0.14.

## 5. Next

- 3 trials per cell and the 16-task set, so differences are measurable; report intervals.
- Selection: rank retrieved facts by relevance to each sub-question (not only by evidence status) before the notes
  step; that is where facts are lost now.
- Two-hop questions (who hires for X → what they use) are still weak for every agent: retrieval 0.18-0.31 on the job
  question. A suggested `graph_query` pattern per question type may help.
- ER, at the source: link same-name org and product with an `offers` edge in the Constructor instead of merging at
  query time; review the 24 same-type pairs with the same normalised name (Scale / Scale AI, Meta / Meta AI,
  Fermilab / fermilab.ai) by hand, since some are different organisations.
- Judges: pairwise preference on these answers, to check that more grounded facts make better advice.

## 6. Practice from the field, mapped to this system

Collected 2026-11-22 from fetched primary sources (Anthropic, OpenAI and LangChain engineering guidance, Chroma's
context-rot report, and recent benchmark-generation papers; for arXiv papers only the abstracts were read). Status:
**adopted** = in the code now · **partly** · **planned**.

| # | Recommendation | Component | Status | Sources |
|---|---|---|---|---|
| 1 | Merge overlapping tools, namespace them, build for workflows not endpoints (`neighbors` / `graph_query` / `ppr` / `top` overlap) | tools | planned | [A2, A3, A5] |
| 2 | Let the agent choose response size (concise vs detailed), paginate, say how to narrow a truncated result | tools | partly (truncation notices, limits) | [A2] |
| 3 | Errors that teach: say what was wrong and show a valid call | tools | partly (empty-result hints, thin-node `broader`) | [A1, A2] |
| 4 | Clear raw tool output once it is in the notes; keep plan and notes outside the history; compact long runs | context | partly (retrieved facts handed to notes) | [A3, A4, A6] |
| 5 | Less context, ordered by relevance: only facts that matter go into synthesis | context | adopted (relevance-ranked fact list) | [A6, A7] |
| 6 | Scale effort to the question: short path for lookups, full phases for hard questions; broad searches first | harness | planned | [A1, A4] |
| 7 | Explicit stopping rule (coverage complete or hard cap); citation check as a separate pass | harness | partly (coverage reflection, step caps) | [A4, A5] |
| 8 | Drop or flag tasks a closed-book solver already answers, and single-hop "cheatable" ones | curator | adopted as a flag (memory-answerable tasks reported separately) | [B7, B8] |
| 9 | Tag difficulty (hops, query-evidence distance); keep the gold path as a reference solution; include "insufficient evidence" tasks | curator, gold | partly (hops tag, gold path stored) | [B1, B6] |
| 10 | Steer generation to where models fail; graduate saturated templates to regression; keep a held-out split | autopilot | planned | [A2, B1, B3] |
| 11 | Grade the outcome for pass/fail; use path metrics to diagnose; report pass^k | metrics | adopted (outcome pass, pass@k, pass^k; stages as diagnosis) | [B1, B5] |
| 12 | Calibrate judges on human labels, allow "unknown", reason first, control length; judge family ≠ solver family | judges | partly (families separated, rationale first, length checked; human labels pending) | [B1, B2, B9] |

Tensions the sources leave open: one holistic judge vs one judge per dimension [A4 vs B1]; seven fixed phases vs
"start simple" and effort scaling [A1, A4]; stage metrics grade the path, which [B1] warns against for pass/fail (here
they only diagnose); a closed-book filter removes the best-known entities, which are often the most useful tasks
[B3, B8], so memory-answerable tasks are flagged, not dropped.

### Autopilot: how the testbed runs end to end

    catalogue (use cases) ─▶ generate: sample anchors (rich/thin) ─▶ Examiner: intent-aware check + persona rewrite
        ─▶ leak check + generic-name filter ─▶ gold from the graph (hops tagged)
        ─▶ answer: every condition × model × trial (cached) ─▶ score: stages · outcome pass@k/pass^k · checklist · judges
        ─▶ report per use case ─▶ diagnose (where retrieval/use fails) ─▶ fix the harness or tools
        ─▶ confirm on a held-out task set the loop never tuned on

`cf usecases <config>` runs it; `cf meta` is the same loop for the QA sessions, with an LLM proposer and held-out
confirmation. Adding a use case is a catalogue entry (`configs/usecases.yaml`), not code.

### Sources for §6

- [A1] Anthropic, *Building effective agents*, 2024. https://www.anthropic.com/engineering/building-effective-agents
- [A2] Anthropic, *Writing effective tools for agents — with agents*, 2025. https://www.anthropic.com/engineering/writing-tools-for-agents
- [A3] Anthropic, *Effective context engineering for AI agents*, 2025. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- [A4] Anthropic, *How we built our multi-agent research system*, 2025. https://www.anthropic.com/engineering/multi-agent-research-system
- [A5] OpenAI, *A practical guide to building agents*. https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- [A6] LangChain, *Context Engineering*, 2025. https://www.langchain.com/blog/context-engineering-for-agents
- [A7] Hong, Troynikov, Huber (Chroma), *Context Rot: How Increasing Input Tokens Impacts LLM Performance*, 2025. https://www.trychroma.com/research/context-rot
- [B1] Anthropic, *Demystifying evals for AI agents*, 2026. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- [B2] OpenAI, *Evaluation best practices*. https://developers.openai.com/api/docs/guides/evaluation-best-practices
- [B3] Li et al., *AutoBencher: Towards Declarative Benchmark Construction*, ICLR 2025. [arXiv:2407.08351](https://arxiv.org/abs/2407.08351)
- [B4] Yuan et al., *LLM-Powered Benchmark Factory: Reliable, Generic, and Efficient*, 2025. [arXiv:2502.01683](https://arxiv.org/abs/2502.01683)
- [B5] *Establishing Best Practices for Building Rigorous Agentic Benchmarks*, 2025. [arXiv:2507.02825](https://arxiv.org/abs/2507.02825) (seen via search only: unverified)
- [B6] Lee, Kwon, Jin, *GRADE: multi-hop QA and fine-grained difficulty matrix for RAG evaluation*, EMNLP 2025 Findings. [arXiv:2508.16994](https://arxiv.org/abs/2508.16994)
- [B7] Liu et al., *Investigating RAG Systems on Unanswerable, Uncheatable, Realistic, Multi-hop Queries*, ECIR 2026. [arXiv:2510.11956](https://arxiv.org/abs/2510.11956)
- [B8] Liu et al., *Generating Leakage-Free Benchmarks for Robust RAG Evaluation*, 2026. [arXiv:2605.08838](https://arxiv.org/abs/2605.08838)
- [B9] Panickssery, Bowman, Feng, *LLM Evaluators Recognize and Favor Their Own Generations*, 2024. [arXiv:2404.13076](https://arxiv.org/abs/2404.13076)

## References

Titles, authors, years and arXiv ids verified against the arXiv API on 2026-11-22. The one-line mechanisms in §1
are summaries and have not yet been checked against each paper's text (per the project rule: unverified until read).

1. Edge et al. *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* 2024. [arXiv:2404.16130](https://arxiv.org/abs/2404.16130)
2. Gutiérrez et al. *HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models.* NeurIPS 2024. [arXiv:2405.14831](https://arxiv.org/abs/2405.14831)
3. Gutiérrez et al. *From RAG to Memory: Non-Parametric Continual Learning for Large Language Models* (HippoRAG 2). ICML 2025. [arXiv:2502.14802](https://arxiv.org/abs/2502.14802)
4. Sun et al. *Think-on-Graph: Deep and Responsible Reasoning of Large Language Model on Knowledge Graph.* ICLR 2024. [arXiv:2307.07697](https://arxiv.org/abs/2307.07697) · Ma et al. *Think-on-Graph 2.0.* 2024. [arXiv:2407.10805](https://arxiv.org/abs/2407.10805)
5. Luo et al. *Reasoning on Graphs: Faithful and Interpretable Large Language Model Reasoning.* ICLR 2024. [arXiv:2310.01061](https://arxiv.org/abs/2310.01061)
6. Jiang et al. *KG-Agent: An Efficient Autonomous Agent Framework for Complex Reasoning over Knowledge Graph.* 2024. [arXiv:2402.11163](https://arxiv.org/abs/2402.11163)
7. He et al. *G-Retriever: Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering.* 2024. [arXiv:2402.07630](https://arxiv.org/abs/2402.07630)
8. Guo et al. *LightRAG: Simple and Fast Retrieval-Augmented Generation.* 2024. [arXiv:2410.05779](https://arxiv.org/abs/2410.05779)
9. Peng et al. *Graph Retrieval-Augmented Generation: A Survey.* 2024. [arXiv:2408.08921](https://arxiv.org/abs/2408.08921)
10. Singh et al. *Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG.* 2025. [arXiv:2501.09136](https://arxiv.org/abs/2501.09136)
11. Yao et al. *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023. [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
12. Asai et al. *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection.* 2023. [arXiv:2310.11511](https://arxiv.org/abs/2310.11511)
13. Liu et al. *Lost in the Middle: How Language Models Use Long Contexts.* TACL. [arXiv:2307.03172](https://arxiv.org/abs/2307.03172)
14. Li et al. *GraphReader: Building Graph-based Agent to Enhance Long-Context Abilities of Large Language Models.* EMNLP 2024. [arXiv:2406.14550](https://arxiv.org/abs/2406.14550)
15. Es et al. *Ragas: Automated Evaluation of Retrieval Augmented Generation.* 2023. [arXiv:2309.15217](https://arxiv.org/abs/2309.15217)
16. Jin et al. *Graph Chain-of-Thought: Augmenting Large Language Models by Reasoning on Graphs.* 2024. [arXiv:2404.07103](https://arxiv.org/abs/2404.07103)
17. Ru et al. *RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation.* 2024. [arXiv:2408.08067](https://arxiv.org/abs/2408.08067)
18. Shi et al. *Large Language Models Can Be Easily Distracted by Irrelevant Context.* ICML 2023. [arXiv:2302.00093](https://arxiv.org/abs/2302.00093)
19. Andersen, Chung, Lang. *Local Graph Partitioning using PageRank Vectors* (approximate PPR push, used by the crawl). FOCS 2006. [doi:10.1109/FOCS.2006.44](https://doi.org/10.1109/FOCS.2006.44)
