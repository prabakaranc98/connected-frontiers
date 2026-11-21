"""Node scores on the graded graph: global PageRank and personalized PageRank from the seeds.

Edge weight = relation weight (configs/crawl.yaml) x evidence strength (grading). Unsupported
edges (strength 0) carry no importance. The scout symmetrizes the graph so that importance can
flow both ways along a relation; the directed, push-based version is M3.
"""

from __future__ import annotations

import networkx as nx

from cf import config
from cf.graph.schema import Edge


def to_graph(entities: dict[str, dict], edges: list[Edge], rel_weights: dict | None = None) -> nx.Graph:
    rel_weights = rel_weights or config.load_yaml("crawl.yaml").get("relation_weights", {})
    g = nx.Graph()
    g.add_nodes_from(entities)
    for e in edges:
        w = float(rel_weights.get(e.relation.value if hasattr(e.relation, "value") else e.relation, 0.5)) * e.strength
        if w <= 0:
            continue
        prev = g.get_edge_data(e.head, e.tail, {}).get("weight", 0.0)
        g.add_edge(e.head, e.tail, weight=prev + w)
    return g


def scores(g: nx.Graph, seeds: list[str], alpha: float = 0.85) -> dict[str, dict]:
    if g.number_of_edges() == 0:
        return {n: {"pagerank": 0.0, "ppr": 0.0, "degree": 0} for n in g}
    pr = nx.pagerank(g, alpha=alpha, weight="weight")
    pers = {n: (1.0 if n in seeds else 0.0) for n in g}
    ppr = nx.pagerank(g, alpha=alpha, weight="weight", personalization=pers) if any(pers.values()) else pr
    return {n: {"pagerank": round(pr[n], 6), "ppr": round(ppr[n], 6), "degree": g.degree(n)} for n in g}
