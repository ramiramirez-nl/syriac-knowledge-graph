from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import sqlite3
import re
from typing import List, Dict, Any, Optional
from thefuzz import fuzz

from api.database import get_db
from api.auth import get_current_admin

router = APIRouter()

MAX_QUEUE_PAGE = 200


class RejectPairRequest(BaseModel):
    work_id_a: str
    work_id_b: str
    note: Optional[str] = None


@router.get("/queue")
def get_review_queue(
    limit: int = 50,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """The real duplicate queue: rows triage_duplicates.py could not decide.

    Distinct from /duplicates, which recomputes candidates from scratch with a
    fuzzy title match. That is useful for spotting pairs the pipeline never
    recorded, but it cannot be worked through to completion because it does not
    persist decisions. This endpoint reads duplicate_candidates, so rejecting or
    merging a pair actually removes it from the backlog.
    """
    limit = max(1, min(limit, MAX_QUEUE_PAGE))
    offset = max(0, offset)

    total = db.execute(
        """
        SELECT COUNT(*) FROM duplicate_candidates d
        JOIN works a ON a.id = d.work_id_a
        JOIN works b ON b.id = d.work_id_b
        WHERE d.review_status = 'pending'
          AND a.status NOT IN ('deleted', 'excluded')
          AND b.status NOT IN ('deleted', 'excluded')
        """
    ).fetchone()[0]

    rows = db.execute(
        """
        SELECT d.work_id_a, d.work_id_b, d.score, d.same_doi, d.reasons,
               a.title AS title_a, a.year AS year_a, a.venue AS venue_a,
               a.doi AS doi_a, a.cited_by_count AS cited_a, a.work_type AS type_a,
               b.title AS title_b, b.year AS year_b, b.venue AS venue_b,
               b.doi AS doi_b, b.cited_by_count AS cited_b, b.work_type AS type_b
        FROM duplicate_candidates d
        JOIN works a ON a.id = d.work_id_a
        JOIN works b ON b.id = d.work_id_b
        WHERE d.review_status = 'pending'
          AND a.status NOT IN ('deleted', 'excluded')
          AND b.status NOT IN ('deleted', 'excluded')
        ORDER BY d.score DESC, d.work_id_a
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()

    pairs = []
    for r in rows:
        row = dict(r)
        for side in ("a", "b"):
            row[f"authors_{side}"] = [
                x[0]
                for x in db.execute(
                    "SELECT au.name FROM authorship s"
                    " JOIN authors au ON au.id = s.author_id"
                    " WHERE s.work_id = ?",
                    (row[f"work_id_{side}"],),
                )
            ]
        pairs.append(row)

    return {"total": total, "limit": limit, "offset": offset, "pairs": pairs}


@router.post("/reject")
def reject_pair(
    request: RejectPairRequest,
    db: sqlite3.Connection = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Mark a pair as 'not a duplicate' so it leaves the queue permanently.

    Without this, a curator can only ever merge, and every correctly-distinct
    pair stays in the backlog forever.
    """
    cur = db.execute(
        "UPDATE duplicate_candidates SET review_status = 'rejected', curator_note = ?"
        " WHERE work_id_a = ? AND work_id_b = ? AND review_status = 'pending'",
        (request.note or f"rejected by {admin.get('email', 'admin')}",
         request.work_id_a, request.work_id_b),
    )
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="No pending candidate for that pair")
    db.commit()
    return {"message": "Pair marked as distinct", "remaining": _pending_count(db)}


def _pending_count(db: sqlite3.Connection) -> int:
    return db.execute(
        """
        SELECT COUNT(*) FROM duplicate_candidates d
        JOIN works a ON a.id = d.work_id_a
        JOIN works b ON b.id = d.work_id_b
        WHERE d.review_status = 'pending'
          AND a.status NOT IN ('deleted', 'excluded')
          AND b.status NOT IN ('deleted', 'excluded')
        """
    ).fetchone()[0]

def get_block_key(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r'^(a|an|the)\s+', '', t)
    t = re.sub(r'[^a-z]', '', t)
    return t[:4]

@router.get("/duplicates")
def get_potential_duplicates(limit: int = 50, db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    cursor = db.execute("SELECT id, title, year FROM works WHERE status NOT IN ('deleted', 'excluded')")
    works = [dict(r) for r in cursor.fetchall()]
    
    # Group by block key
    blocks: Dict[str, List[Dict[str, Any]]] = {}
    for w in works:
        key = get_block_key(w.get('title', ''))
        if len(key) >= 3:
            if key not in blocks:
                blocks[key] = []
            blocks[key].append(w)
            
    duplicates = []
    
    for key, block_works in blocks.items():
        if len(duplicates) >= limit:
            break
            
        n = len(block_works)
        for i in range(n):
            if len(duplicates) >= limit:
                break
            for j in range(i + 1, n):
                w1 = block_works[i]
                w2 = block_works[j]
                
                t1 = w1['title'] or ""
                t2 = w2['title'] or ""
                
                if len(t1) < 10 or len(t2) < 10:
                    continue
                    
                # Use token_set_ratio for robustness against reordering or missing words
                ratio = fuzz.token_set_ratio(t1.lower(), t2.lower())
                if ratio > 90:
                    # Double check with standard ratio to avoid matching completely different length strings
                    # that just happen to share all words of the shorter string.
                    std_ratio = fuzz.ratio(t1.lower(), t2.lower())
                    if std_ratio > 70:
                        duplicates.append({
                            "work1": w1,
                            "work2": w2,
                            "similarity": ratio
                        })
                
    # Sort duplicates by similarity descending
    duplicates.sort(key=lambda x: x['similarity'], reverse=True)
    return duplicates[:limit]
