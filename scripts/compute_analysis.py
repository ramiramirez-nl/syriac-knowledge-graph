"""Phase 1 analysis: relatedness signals, clustering, and collaboration candidates.

Builds a combined work-work similarity graph from three signals:
  - bibliographic coupling (two works sharing references, incl. references
    outside the corpus — e.g. both citing the same monograph)
  - co-citation (two corpus works both cited by a third corpus work)
  - TF-IDF title similarity (coarse topical proxy; see limitations in PLAN.md)

Runs Leiden community detection on the combined graph to find thematic
clusters, then flags author pairs whose work is topically similar but who
have no existing link (no co-authorship, no citation in either direction) —
the "unaware researchers working on related problems" signal.

Writes results back into data/syriac.db (tables: work_clusters, clusters,
similarity_edges, collaboration_candidates) so they are durable and queryable,
not just baked into the site export.

Usage:
    uv run scripts/compute_analysis.py
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import igraph as ig
import leidenalg
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

# A reference cited by more than this many corpus works is treated as too
# generic to be a meaningful coupling signal (e.g. a standard grammar or the
# Peshitta text itself) and is excluded from bibliographic coupling.
MAX_REFERENCE_FANOUT = 30

# Signal weights for the combined similarity graph.
WEIGHTS = {"citation": 0.35, "coupling": 0.30, "cocitation": 0.20, "tfidf": 0.15}

TOP_K_NEIGHBORS = 6  # keep at most this many strongest edges per work
MIN_EDGE_WEIGHT = 0.05

AUTHOR_MIN_WORKS = 1
AUTHOR_SIM_THRESHOLD = 0.35
# Near-perfect similarity (>0.97) between two DIFFERENT authors' title-derived
# centroids is, in practice, almost always a short-title TF-IDF artifact
# (e.g. "The Church of the East" vs "Crosses of the Church of the East")
# rather than genuine independent convergence on identical phrasing. Title-only
# TF-IDF is a coarse v1 proxy — see PLAN.md Faz 1 limitations — a future pass
# with real semantic embeddings (e.g. multilingual-e5) should replace this
# ceiling with an actual precision fix.
AUTHOR_SIM_CEILING = 0.97
TOP_COLLABORATION_CANDIDATES = 300


REVIEW_TITLE_PREFIXES = ("book review", "review of", "review essay", "review article")
# Substring markers typical of review/citation-style entries: publisher
# metadata (ISBN, page counts, price), edited-volume framing ("ed. by",
# "eds.)"), or embedded HTML markup used to typeset the reviewed work's
# own title/author within the review's title.
REVIEW_TITLE_MARKERS = ("isbn", " pp.", "review:", " ed. ", "eds.)", "(hb)", "(pb)", "<i>", "<b>", " €", "$")
# Citation-style suffix commonly used when a review's title is just the
# reviewed book's title followed by its author, e.g. "... . By SEBASTIAN BROCK."
REVIEW_BY_AUTHOR_SUFFIX = re.compile(r"\.\s*by\s+[a-z][a-z.\s]{2,40}\.?\s*$", re.IGNORECASE)


def is_review_like(title: str, work_type: str) -> bool:
    """Book reviews of the same publication share near-identical titles with
    each other (both echoing the reviewed book's title), which looks like a
    collaboration signal but really just means two people reviewed the same
    book. OpenAlex tags very few of these correctly as work_type='review', so
    title heuristics catch more (not exhaustive — see PLAN.md limitations)."""
    if work_type in ("review", "book-review"):
        return True
    t = (title or "").strip().lower()
    if any(t.startswith(p) for p in REVIEW_TITLE_PREFIXES):
        return True
    if any(marker in t for marker in REVIEW_TITLE_MARKERS):
        return True
    return bool(REVIEW_BY_AUTHOR_SUFFIX.search(t))


def load_data(conn: sqlite3.Connection):
    works = {row[0]: row[1] for row in conn.execute("SELECT id, title FROM works")}
    work_types = {row[0]: row[1] for row in conn.execute("SELECT id, work_type FROM works")}
    citations = list(conn.execute("SELECT citing_work_id, cited_work_id FROM citations"))
    references = list(conn.execute("SELECT work_id, referenced_work_id FROM work_references"))
    authorship = list(conn.execute("SELECT work_id, author_id FROM authorship"))
    author_names = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM authors")}
    return works, work_types, citations, references, authorship, author_names


def compute_coupling(references: list[tuple[str, str]]) -> Counter:
    """Two works that both cite the same reference get +1 coupling weight."""
    ref_to_works: dict[str, list[str]] = defaultdict(list)
    for work_id, ref_id in references:
        ref_to_works[ref_id].append(work_id)

    coupling: Counter = Counter()
    for ref_id, citing in ref_to_works.items():
        unique_citing = sorted(set(citing))
        if len(unique_citing) < 2 or len(unique_citing) > MAX_REFERENCE_FANOUT:
            continue
        for a, b in combinations(unique_citing, 2):
            coupling[(a, b)] += 1
    return coupling


def compute_cocitation(citations: list[tuple[str, str]]) -> Counter:
    """Two works that are both cited by the same third corpus work get +1."""
    citing_to_cited: dict[str, list[str]] = defaultdict(list)
    for citing_id, cited_id in citations:
        citing_to_cited[citing_id].append(cited_id)

    cocitation: Counter = Counter()
    for citing_id, cited_list in citing_to_cited.items():
        unique_cited = sorted(set(cited_list))
        if len(unique_cited) < 2:
            continue
        for a, b in combinations(unique_cited, 2):
            cocitation[(a, b)] += 1
    return cocitation


def normalize_counter(counter: Counter) -> dict:
    if not counter:
        return {}
    max_val = max(counter.values())
    return {k: v / max_val for k, v in counter.items()}


def compute_tfidf_similarity(works: dict[str, str], work_types: dict[str, str]):
    """Returns (work_ids list, tfidf matrix, top-k similarity dict {(a,b): score})."""
    work_ids = list(works.keys())
    titles = [works[wid] or "" for wid in work_ids]

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2, max_df=0.5)
    matrix = vectorizer.fit_transform(titles)

    # Titles with fewer than 3 distinctive (non-stopword) terms — e.g. short
    # book-review headers like "Syriac", or generic phrases like "The Church
    # of the East" — produce meaningless perfect-similarity matches against
    # any other short title sharing those same 1-2 words (a 2-term vector's
    # direction is fully determined by those terms, so cosine saturates at
    # 1.0 far too easily). Zero out their rows so they can't drive TF-IDF
    # signals (they can still connect via citation/coupling edges).
    nnz_per_row = np.diff(matrix.tocsr().indptr)
    thin_title_mask = nnz_per_row < 3

    review_mask = np.array([is_review_like(works[wid], work_types.get(wid)) for wid in work_ids])

    exclude_mask = thin_title_mask | review_mask
    if exclude_mask.any():
        matrix = matrix.tolil()
        matrix[exclude_mask, :] = 0
        matrix = matrix.tocsr()
        print(
            f"  ({thin_title_mask.sum()} works have too-generic titles, "
            f"{review_mask.sum()} look like book reviews; both excluded from TF-IDF signal)"
        )

    sim_edges: dict[tuple, float] = {}
    # Process in chunks to bound memory for the dense similarity block.
    chunk_size = 500
    n = len(work_ids)
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        block = cosine_similarity(matrix[start:end], matrix)
        for local_i, global_i in enumerate(range(start, end)):
            row = block[local_i]
            row[global_i] = 0  # exclude self
            top_idx = np.argpartition(-row, min(TOP_K_NEIGHBORS, n - 1) - 1)[:TOP_K_NEIGHBORS]
            for j in top_idx:
                score = float(row[j])
                if score < 0.12:
                    continue
                a, b = work_ids[global_i], work_ids[j]
                key = (a, b) if a < b else (b, a)
                if key not in sim_edges or sim_edges[key] < score:
                    sim_edges[key] = score
    return work_ids, matrix, sim_edges, vectorizer


def build_combined_graph(work_ids: list[str], citation_pairs: set, coupling: dict, cocitation: dict, tfidf_edges: dict):
    edge_weights: dict[tuple, dict] = defaultdict(dict)

    for a, b in citation_pairs:
        key = (a, b) if a < b else (b, a)
        edge_weights[key]["citation"] = 1.0
    for (a, b), v in coupling.items():
        edge_weights[(a, b)]["coupling"] = v
    for (a, b), v in cocitation.items():
        edge_weights[(a, b)]["cocitation"] = v
    for (a, b), v in tfidf_edges.items():
        edge_weights[(a, b)]["tfidf"] = v

    combined: dict[tuple, float] = {}
    signal_breakdown: dict[tuple, dict] = {}
    for key, signals in edge_weights.items():
        weight = sum(WEIGHTS[sig] * val for sig, val in signals.items())
        if weight >= MIN_EDGE_WEIGHT:
            combined[key] = weight
            signal_breakdown[key] = signals

    # Keep only the strongest TOP_K_NEIGHBORS edges per node to bound density.
    per_node: dict[str, list] = defaultdict(list)
    for (a, b), w in combined.items():
        per_node[a].append((w, b))
        per_node[b].append((w, a))

    kept_edges: dict[tuple, float] = {}
    for node, neighbors in per_node.items():
        neighbors.sort(key=lambda x: -x[0])
        for w, other in neighbors[:TOP_K_NEIGHBORS]:
            key = (node, other) if node < other else (other, node)
            kept_edges[key] = combined[key]

    return kept_edges, signal_breakdown


def run_leiden(work_ids: list[str], edges: dict[tuple, float]):
    id_to_idx = {wid: i for i, wid in enumerate(work_ids)}
    g = ig.Graph()
    g.add_vertices(len(work_ids))
    edge_list = [(id_to_idx[a], id_to_idx[b]) for (a, b) in edges]
    g.add_edges(edge_list)
    g.es["weight"] = list(edges.values())

    partition = leidenalg.find_partition(
        g, leidenalg.RBConfigurationVertexPartition, weights="weight", seed=42, resolution_parameter=0.4
    )
    membership = partition.membership
    return {work_ids[i]: membership[i] for i in range(len(work_ids))}


def label_clusters(cluster_of: dict[str, int], work_ids: list[str], matrix, vectorizer) -> dict[int, dict]:
    feature_names = np.array(vectorizer.get_feature_names_out())
    id_to_idx = {wid: i for i, wid in enumerate(work_ids)}

    members: dict[int, list[str]] = defaultdict(list)
    for wid, cid in cluster_of.items():
        members[cid].append(wid)

    labels = {}
    for cid, member_ids in members.items():
        idxs = [id_to_idx[m] for m in member_ids]
        centroid = np.asarray(matrix[idxs].mean(axis=0)).ravel()
        top_idx = np.argsort(-centroid)[:6]
        top_terms = [feature_names[i] for i in top_idx if centroid[i] > 0]
        labels[cid] = {"size": len(member_ids), "top_terms": top_terms}
    return labels


def compute_author_centroids(authorship: list[tuple[str, str]], work_ids: list[str], matrix):
    id_to_idx = {wid: i for i, wid in enumerate(work_ids)}
    author_to_works: dict[str, list[str]] = defaultdict(list)
    for work_id, author_id in authorship:
        if work_id in id_to_idx:
            author_to_works[author_id].append(work_id)

    author_ids = [a for a, w in author_to_works.items() if len(w) >= AUTHOR_MIN_WORKS]
    rows = []
    for a in author_ids:
        idxs = [id_to_idx[w] for w in author_to_works[a]]
        centroid = np.asarray(matrix[idxs].mean(axis=0)).ravel()
        rows.append(centroid)
    centroid_matrix = np.vstack(rows) if rows else np.empty((0, matrix.shape[1]))
    return author_ids, centroid_matrix, author_to_works


def normalize_title(title: str) -> str:
    return "".join(ch.lower() for ch in (title or "") if ch.isalnum() or ch.isspace()).strip()


def find_duplicate_title_pairs(works: dict[str, str], author_to_works: dict[str, list[str]]) -> set:
    """Author pairs that share an exact-duplicate-titled work between them.

    OpenAlex occasionally double-indexes the same publication under two work
    IDs with inconsistent author attribution (verified case: same title, same
    year, same venue, two different author names on the two copies). That
    produces a spurious cosine similarity of 1.0 between otherwise unrelated
    authors — a data artifact, not a genuine research-overlap signal — so
    such pairs are excluded from collaboration candidates.
    """
    title_to_works: dict[str, list[str]] = defaultdict(list)
    for work_id, title in works.items():
        norm = normalize_title(title)
        if norm:
            title_to_works[norm].append(work_id)

    author_of_work: dict[str, list[str]] = defaultdict(list)
    for author_id, work_ids in author_to_works.items():
        for w in work_ids:
            author_of_work[w].append(author_id)

    duplicate_pairs = set()
    for norm, ids in title_to_works.items():
        if len(ids) < 2:
            continue
        authors_involved = set()
        for wid in ids:
            authors_involved.update(author_of_work.get(wid, []))
        for a, b in combinations(sorted(authors_involved), 2):
            duplicate_pairs.add((a, b))
    return duplicate_pairs


def find_collaboration_candidates(author_ids, centroid_matrix, author_to_works, citations, authorship, works):
    if len(author_ids) < 2:
        return []

    sims = cosine_similarity(centroid_matrix)

    # Existing links to exclude: co-authorship, or a citation between any pair of their works.
    work_to_authors: dict[str, set] = defaultdict(set)
    for work_id, author_id in authorship:
        work_to_authors[work_id].add(author_id)

    coauthor_pairs = set()
    for authors in work_to_authors.values():
        for a, b in combinations(sorted(authors), 2):
            coauthor_pairs.add((a, b))

    author_of_work = {}
    for work_id, authors in work_to_authors.items():
        author_of_work[work_id] = authors

    citation_linked_pairs = set()
    for citing_work, cited_work in citations:
        citing_authors = author_of_work.get(citing_work, set())
        cited_authors = author_of_work.get(cited_work, set())
        for a in citing_authors:
            for b in cited_authors:
                if a != b:
                    citation_linked_pairs.add((a, b) if a < b else (b, a))

    duplicate_title_pairs = find_duplicate_title_pairs(works, author_to_works)

    excluded = coauthor_pairs | citation_linked_pairs | duplicate_title_pairs

    candidates = []
    n = len(author_ids)
    for i in range(n):
        for j in range(i + 1, n):
            score = sims[i, j]
            if score < AUTHOR_SIM_THRESHOLD or score > AUTHOR_SIM_CEILING:
                continue
            a, b = author_ids[i], author_ids[j]
            key = (a, b) if a < b else (b, a)
            if key in excluded:
                continue
            candidates.append((key[0], key[1], float(score)))

    candidates.sort(key=lambda x: -x[2])
    return candidates[:TOP_COLLABORATION_CANDIDATES]


def write_results(conn, cluster_of, cluster_labels, kept_edges, signal_breakdown, candidates):
    conn.executescript(
        """
        DROP TABLE IF EXISTS work_clusters;
        DROP TABLE IF EXISTS clusters;
        DROP TABLE IF EXISTS similarity_edges;
        DROP TABLE IF EXISTS collaboration_candidates;

        CREATE TABLE work_clusters (work_id TEXT PRIMARY KEY, cluster_id INTEGER);
        CREATE TABLE clusters (cluster_id INTEGER PRIMARY KEY, size INTEGER, top_terms TEXT);
        CREATE TABLE similarity_edges (
            work_id_a TEXT, work_id_b TEXT, weight REAL,
            has_citation INTEGER, coupling REAL, cocitation REAL, tfidf REAL,
            PRIMARY KEY (work_id_a, work_id_b)
        );
        CREATE TABLE collaboration_candidates (
            author_id_a TEXT, author_id_b TEXT, similarity REAL,
            PRIMARY KEY (author_id_a, author_id_b)
        );
        """
    )

    conn.executemany(
        "INSERT INTO work_clusters (work_id, cluster_id) VALUES (?, ?)",
        list(cluster_of.items()),
    )
    conn.executemany(
        "INSERT INTO clusters (cluster_id, size, top_terms) VALUES (?, ?, ?)",
        [(cid, info["size"], ",".join(info["top_terms"])) for cid, info in cluster_labels.items()],
    )
    conn.executemany(
        """INSERT INTO similarity_edges
           (work_id_a, work_id_b, weight, has_citation, coupling, cocitation, tfidf)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                a, b, w,
                1 if "citation" in signal_breakdown.get((a, b), {}) else 0,
                signal_breakdown.get((a, b), {}).get("coupling", 0.0),
                signal_breakdown.get((a, b), {}).get("cocitation", 0.0),
                signal_breakdown.get((a, b), {}).get("tfidf", 0.0),
            )
            for (a, b), w in kept_edges.items()
        ],
    )
    conn.executemany(
        "INSERT INTO collaboration_candidates (author_id_a, author_id_b, similarity) VALUES (?, ?, ?)",
        candidates,
    )
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Loading data...")
    works, work_types, citations, references, authorship, author_names = load_data(conn)
    print(f"  works={len(works)} citations={len(citations)} references={len(references)} authorship={len(authorship)}")

    print("Computing bibliographic coupling...")
    coupling_raw = compute_coupling(references)
    coupling = normalize_counter(coupling_raw)
    print(f"  coupling pairs (raw): {len(coupling_raw)}")

    print("Computing co-citation...")
    cocitation_raw = compute_cocitation(citations)
    cocitation = normalize_counter(cocitation_raw)
    print(f"  co-citation pairs (raw): {len(cocitation_raw)}")

    print("Computing TF-IDF title similarity...")
    work_ids, matrix, tfidf_edges, vectorizer = compute_tfidf_similarity(works, work_types)
    print(f"  tfidf similarity pairs (top-k, thresholded): {len(tfidf_edges)}")

    citation_pairs = {(a, b) if a < b else (b, a) for a, b in citations if a != b}

    print("Combining signals into weighted graph...")
    kept_edges, signal_breakdown = build_combined_graph(work_ids, citation_pairs, coupling, cocitation, tfidf_edges)
    print(f"  combined graph edges (after top-{TOP_K_NEIGHBORS} pruning): {len(kept_edges)}")

    print("Running Leiden clustering...")
    cluster_of = run_leiden(work_ids, kept_edges)
    n_clusters = len(set(cluster_of.values()))
    print(f"  clusters found: {n_clusters}")

    print("Labeling clusters...")
    cluster_labels = label_clusters(cluster_of, work_ids, matrix, vectorizer)

    print("Computing author centroids for collaboration candidates...")
    author_ids, centroid_matrix, author_to_works = compute_author_centroids(authorship, work_ids, matrix)
    candidates = find_collaboration_candidates(author_ids, centroid_matrix, author_to_works, citations, authorship, works)
    print(f"  collaboration candidates found: {len(candidates)}")
    if candidates:
        a, b, score = candidates[0]
        print(f"  top candidate: {author_names.get(a)} <-> {author_names.get(b)} (sim={score:.2f})")

    print("Writing results to database...")
    write_results(conn, cluster_of, cluster_labels, kept_edges, signal_breakdown, candidates)
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
