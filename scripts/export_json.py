"""Export data/syriac.db into site/data.json for the static Sigma.js prototype.

Includes both the raw citation graph and the Phase 1 combined similarity
graph (bibliographic coupling + co-citation + TF-IDF), Leiden cluster
assignments, and author collaboration candidates. Node layout is computed
once from the combined similarity graph (denser and more connected than
citations alone — see PLAN.md), so both the "Citations" and "Similarity &
Clusters" views in the site share stable node positions.

Usage:
    uv run scripts/export_json.py
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"
OUT_PATH = ROOT / "site" / "data.json"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    works = {}
    for row in conn.execute("SELECT id, title, year, venue, work_type, cited_by_count, source, status FROM works"):
        works[row["id"]] = {
            "id": row["id"],
            "title": row["title"],
            "year": row["year"],
            "venue": row["venue"],
            "type": row["work_type"],
            "citedByCount": row["cited_by_count"] or 0,
            "source": row["source"],
            "status": row["status"],
            "authors": [],
            "clusterId": None,
        }

    authors = {}
    for row in conn.execute("SELECT id, name FROM authors"):
        authors[row["id"]] = {"id": row["id"], "name": row["name"], "workIds": []}

    # author_position values are 'first'/'middle'/'last'; plain ORDER BY would
    # sort them alphabetically (first, last, middle) and misorder author lists.
    for row in conn.execute(
        """SELECT work_id, author_id FROM authorship
           ORDER BY CASE author_position
               WHEN 'first' THEN 0 WHEN 'middle' THEN 1 ELSE 2 END"""
    ):
        work_id, author_id = row["work_id"], row["author_id"]
        if work_id in works and author_id in authors:
            works[work_id]["authors"].append({"id": author_id, "name": authors[author_id]["name"]})
            authors[author_id]["workIds"].append(work_id)

    citations = [
        {"source": row["citing_work_id"], "target": row["cited_work_id"]}
        for row in conn.execute("SELECT citing_work_id, cited_work_id FROM citations")
    ]

    # Drop authors with zero attributed works (shouldn't happen, but guard).
    authors = {aid: a for aid, a in authors.items() if a["workIds"]}

    # --- Phase 1 analysis results ---
    similarity_edges = [
        {
            "source": row["work_id_a"],
            "target": row["work_id_b"],
            "weight": row["weight"],
            "hasCitation": bool(row["has_citation"]),
            "coupling": row["coupling"],
            "cocitation": row["cocitation"],
            "embedding": row["embedding"],
        }
        for row in conn.execute(
            "SELECT work_id_a, work_id_b, weight, has_citation, coupling, cocitation, embedding FROM similarity_edges"
        )
    ]

    for row in conn.execute("SELECT work_id, cluster_id FROM work_clusters"):
        if row["work_id"] in works:
            works[row["work_id"]]["clusterId"] = row["cluster_id"]

    clusters = [
        {
            "id": row["cluster_id"],
            "size": row["size"],
            "topTerms": [t for t in (row["top_terms"] or "").split(",") if t],
        }
        for row in conn.execute("SELECT cluster_id, size, top_terms FROM clusters")
    ]
    # Only clusters with >=3 members represent an actual thematic grouping;
    # smaller ones just mean "not enough signal yet" rather than a real cluster.
    substantial_cluster_ids = {c["id"] for c in clusters if c["size"] >= 3}
    for w in works.values():
        if w["clusterId"] not in substantial_cluster_ids:
            w["clusterId"] = None

    collaboration_candidates = [
        {
            "authorA": row["author_id_a"],
            "authorB": row["author_id_b"],
            "similarity": row["similarity"],
        }
        for row in conn.execute(
            "SELECT author_id_a, author_id_b, similarity FROM collaboration_candidates ORDER BY similarity DESC"
        )
        if row["author_id_a"] in authors and row["author_id_b"] in authors
    ]

    print("Computing layout (networkx spring_layout on the combined similarity graph)...")
    degree = {wid: 0 for wid in works}
    for e in similarity_edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
    connected_ids = [wid for wid, d in degree.items() if d > 0]
    isolated_ids = [wid for wid, d in degree.items() if d == 0]

    graph = nx.Graph()
    graph.add_nodes_from(connected_ids)
    graph.add_weighted_edges_from((e["source"], e["target"], e["weight"]) for e in similarity_edges)
    positions = nx.spring_layout(graph, k=None, iterations=50, seed=42, scale=500, weight="weight")
    for work_id, (x, y) in positions.items():
        works[work_id]["x"] = float(x)
        works[work_id]["y"] = float(y)

    # Isolated (no similarity-graph edges above threshold) works have no
    # layout force acting on them. Scatter them on a halo ring just outside
    # the connected network's radius, deterministically per work id, so the
    # connected core stays visually dominant instead of being dwarfed by an
    # arbitrarily large bounding box.
    if positions:
        radius = max(math.hypot(x, y) for x, y in positions.values())
    else:
        radius = 500.0
    radius = max(radius, 50.0)
    for work_id in isolated_ids:
        rnd = random.Random(work_id)
        angle = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(radius * 1.1, radius * 1.6)
        works[work_id]["x"] = r * math.cos(angle)
        works[work_id]["y"] = r * math.sin(angle)

    data = {
        "works": list(works.values()),
        "authors": list(authors.values()),
        "citations": citations,
        "similarityEdges": similarity_edges,
        "clusters": clusters,
        "collaborationCandidates": collaboration_candidates,
        "meta": {
            "workCount": len(works),
            "authorCount": len(authors),
            "citationCount": len(citations),
            "similarityEdgeCount": len(similarity_edges),
            "clusterCount": len(substantial_cluster_ids),
            "collaborationCandidateCount": len(collaboration_candidates),
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB)")
    print(
        f"works={data['meta']['workCount']} authors={data['meta']['authorCount']} "
        f"citations={data['meta']['citationCount']} similarityEdges={data['meta']['similarityEdgeCount']} "
        f"clusters={data['meta']['clusterCount']} collabCandidates={data['meta']['collaborationCandidateCount']}"
    )


if __name__ == "__main__":
    main()
