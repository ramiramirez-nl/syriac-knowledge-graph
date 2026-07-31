"""Detect likely duplicate works and store a review queue in SQLite.

The detector combines DOI equality, character n-gram title similarity,
publication year proximity, and venue similarity. It never merges records;
a curator must review every candidate.

Usage:
    uv run scripts/find_duplicates.py
    uv run scripts/find_duplicates.py --threshold 0.86 --limit 30
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "").casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            work_id_a TEXT NOT NULL REFERENCES works(id),
            work_id_b TEXT NOT NULL REFERENCES works(id),
            score REAL NOT NULL,
            title_similarity REAL NOT NULL,
            same_doi INTEGER NOT NULL DEFAULT 0,
            year_difference INTEGER,
            venue_similarity REAL NOT NULL DEFAULT 0,
            reasons TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'pending',
            curator_note TEXT,
            detected_at TEXT NOT NULL,
            PRIMARY KEY (work_id_a, work_id_b)
        );
        CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_review
            ON duplicate_candidates(review_status, score DESC);
        """
    )


def detect_candidates(rows: list[sqlite3.Row], threshold: float) -> list[tuple]:
    ids = [row["id"] for row in rows]
    titles = [normalize_text(row["title"]) for row in rows]
    years = [row["year"] for row in rows]
    venues = [normalize_text(row["venue"]) for row in rows]
    dois = [normalize_doi(row["doi"]) for row in rows]

    title_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    title_matrix = title_vectorizer.fit_transform(titles)
    venue_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    venue_matrix = venue_vectorizer.fit_transform([v or "unknownvenue" for v in venues])

    neighbor_count = min(10, len(rows))
    neighbors = NearestNeighbors(n_neighbors=neighbor_count, metric="cosine", algorithm="brute")
    neighbors.fit(title_matrix)
    distances, indices = neighbors.kneighbors(title_matrix)

    pairs: dict[tuple[int, int], float] = {}
    for i, (row_distances, row_indices) in enumerate(zip(distances, indices)):
        for distance, j in zip(row_distances, row_indices):
            if i == j:
                continue
            title_sim = 1.0 - float(distance)
            if title_sim >= 0.70:
                pairs[(min(i, int(j)), max(i, int(j)))] = title_sim

    doi_groups: dict[str, list[int]] = {}
    for i, doi in enumerate(dois):
        if doi:
            doi_groups.setdefault(doi, []).append(i)
    for group in doi_groups.values():
        for pos, i in enumerate(group):
            for j in group[pos + 1:]:
                pairs[(min(i, j), max(i, j))] = float(cosine_similarity(title_matrix[i], title_matrix[j])[0, 0])

    detected_at = datetime.now(timezone.utc).isoformat()
    candidates = []
    for (i, j), title_sim in pairs.items():
        same_doi = bool(dois[i] and dois[i] == dois[j])
        year_diff = abs(years[i] - years[j]) if years[i] is not None and years[j] is not None else None
        venue_sim = float(cosine_similarity(venue_matrix[i], venue_matrix[j])[0, 0]) if venues[i] and venues[j] else 0.0

        score = title_sim * 0.80
        reasons = [f"title={title_sim:.3f}"]
        if same_doi:
            score += 0.20
            reasons.append("same DOI")
        if year_diff == 0:
            score += 0.10
            reasons.append("same year")
        elif year_diff == 1:
            score += 0.05
            reasons.append("years differ by 1")
        if venue_sim >= 0.75:
            score += 0.05
            reasons.append(f"venue={venue_sim:.3f}")
        score = min(score, 1.0)

        if same_doi or score >= threshold:
            a, b = sorted((ids[i], ids[j]))
            candidates.append((a, b, score, title_sim, int(same_doi), year_diff, venue_sim, "; ".join(reasons), "pending", detected_at))

    candidates.sort(key=lambda row: (-row[2], row[0], row[1]))
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a duplicate-work review queue.")
    parser.add_argument("--threshold", type=float, default=0.86, help="Minimum composite score (default: 0.86)")
    parser.add_argument("--limit", type=int, default=20, help="Number of top candidates to print")
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        rows = list(conn.execute("SELECT id, doi, title, year, venue FROM works ORDER BY id"))
        candidates = detect_candidates(rows, args.threshold)

        previous_reviews = {
            (row[0], row[1]): (row[2], row[3])
            for row in conn.execute(
                "SELECT work_id_a, work_id_b, review_status, curator_note FROM duplicate_candidates WHERE review_status <> 'pending'"
            )
        }
        conn.execute("DELETE FROM duplicate_candidates")
        conn.executemany(
            """INSERT INTO duplicate_candidates
               (work_id_a, work_id_b, score, title_similarity, same_doi, year_difference,
                venue_similarity, reasons, review_status, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            candidates,
        )
        for (a, b), (status, note) in previous_reviews.items():
            conn.execute(
                "UPDATE duplicate_candidates SET review_status=?, curator_note=? WHERE work_id_a=? AND work_id_b=?",
                (status, note, a, b),
            )
        conn.commit()

        print(f"Stored {len(candidates)} duplicate candidates (threshold={args.threshold:.2f}).")
        query = """SELECT d.score, d.reasons, a.title, a.year, b.title, b.year
                   FROM duplicate_candidates d
                   JOIN works a ON a.id=d.work_id_a JOIN works b ON b.id=d.work_id_b
                   ORDER BY d.score DESC LIMIT ?"""
        for score, reasons, title_a, year_a, title_b, year_b in conn.execute(query, (args.limit,)):
            print(f"\n[{score:.3f}] {title_a} ({year_a})\n        {title_b} ({year_b})\n        {reasons}")


if __name__ == "__main__":
    main()
