from fastapi import APIRouter, Depends, HTTPException
import sqlite3
from typing import List, Dict, Any
import uuid

from api.database import get_db
from api.models import Work, WorkCreate, WorkUpdate, MergeWorksRequest
from api.auth import get_current_admin

router = APIRouter()


@router.get("", response_model=List[Work])
def get_works(skip: int = 0, limit: int = 50, q: str = None, db: sqlite3.Connection = Depends(get_db)):
    query = "SELECT * FROM works WHERE status != 'deleted' "
    params = []
    
    if q:
        query += "AND title LIKE ? "
        params.append(f"%{q}%")
        
    query += "LIMIT ? OFFSET ?"
    params.extend([limit, skip])
    
    cursor = db.execute(query, params)
    rows = cursor.fetchall()
    
    works_list = []
    for row in rows:
        work_dict = dict(row)
        if work_dict.get("work_type") == "manuscript":
            md_cursor = db.execute("SELECT language, date_composed, archive_location, shelfmark, incipit FROM manuscript_details WHERE work_id = ?", (work_dict["id"],))
            md_row = md_cursor.fetchone()
            if md_row:
                work_dict["manuscript_details"] = dict(md_row)
        works_list.append(work_dict)
        
    return works_list

@router.post("", response_model=Work)
def create_work(work: WorkCreate, db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    work_id = work.id or f"manual:{uuid.uuid4().hex[:8]}"
    
    try:
        db.execute(
            "INSERT INTO works (id, doi, title, year, venue, work_type, cited_by_count, source, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'curated')",
            (work_id, work.doi, work.title, work.year, work.venue, work.work_type, 0)
        )
        
        # Simple author handling (assuming author names for manual entry)
        if work.authors:
            for i, author_name in enumerate(work.authors):
                author_id = f"manual_author:{uuid.uuid4().hex[:8]}"
                db.execute("INSERT INTO authors (id, name, source, status) VALUES (?, ?, 'manual', 'curated')", (author_id, author_name))
                db.execute("INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, ?)", (work_id, author_id, "middle" if i > 0 and i < len(work.authors)-1 else ("first" if i == 0 else "last")))
                
        # Handle manuscript details
        if work.work_type == "manuscript" and work.manuscript_details:
            md = work.manuscript_details
            db.execute(
                "INSERT INTO manuscript_details (work_id, language, date_composed, archive_location, shelfmark, incipit) VALUES (?, ?, ?, ?, ?, ?)",
                (work_id, md.language, md.date_composed, md.archive_location, md.shelfmark, md.incipit)
            )
            
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Work ID already exists")
        
    return _get_single_work(db, work_id)
    
def _get_single_work(db: sqlite3.Connection, work_id: str):
    cursor = db.execute("SELECT * FROM works WHERE id = ?", (work_id,))
    row = cursor.fetchone()
    if not row: return None
    work_dict = dict(row)
    if work_dict.get("work_type") == "manuscript":
        md_cursor = db.execute("SELECT language, date_composed, archive_location, shelfmark, incipit FROM manuscript_details WHERE work_id = ?", (work_id,))
        md_row = md_cursor.fetchone()
        if md_row:
            work_dict["manuscript_details"] = dict(md_row)
    return work_dict

@router.delete("/{work_id}")
def delete_work(work_id: str, db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    # Soft delete
    db.execute("UPDATE works SET status = 'deleted' WHERE id = ?", (work_id,))
    db.commit()
    return {"message": "Work soft-deleted successfully"}

@router.put("/{work_id}")
def update_work(work_id: str, work_update: WorkUpdate, db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    cursor = db.execute("SELECT * FROM works WHERE id = ?", (work_id,))
    existing = cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Work not found")
        
    updates = []
    params = []
    if work_update.title is not None:
        updates.append("title = ?")
        params.append(work_update.title)
    if work_update.doi is not None:
        updates.append("doi = ?")
        params.append(work_update.doi)
    if work_update.year is not None:
        updates.append("year = ?")
        params.append(work_update.year)
        
    if work_update.work_type is not None:
        updates.append("work_type = ?")
        params.append(work_update.work_type)
        
    if updates:
        params.append(work_id)
        query = f"UPDATE works SET {', '.join(updates)} WHERE id = ?"
        db.execute(query, params)
        
    if work_update.manuscript_details:
        md = work_update.manuscript_details
        db.execute("INSERT OR REPLACE INTO manuscript_details (work_id, language, date_composed, archive_location, shelfmark, incipit) VALUES (?, ?, ?, ?, ?, ?)",
                   (work_id, md.language, md.date_composed, md.archive_location, md.shelfmark, md.incipit))
                   
    db.commit()
    
    return _get_single_work(db, work_id)

@router.post("/{work_id}/exclude")
def exclude_work(work_id: str, db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    db.execute("UPDATE works SET status = 'excluded' WHERE id = ?", (work_id,))
    db.commit()
    return {"message": "Work marked as excluded successfully"}

@router.post("/merge")
def merge_works(request: MergeWorksRequest, db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    try:
        pid = request.primary_id
        sid = request.secondary_id
        
        # Update citations where sid is citing. The column is `citing_work_id`
        # (an earlier version used a non-existent `work_id` column here, which
        # made every merge fail with "no such column").
        db.execute("UPDATE OR IGNORE citations SET citing_work_id = ? WHERE citing_work_id = ?", (pid, sid))
        db.execute("DELETE FROM citations WHERE citing_work_id = ?", (sid,))

        # Update citations where sid is cited
        db.execute("UPDATE OR IGNORE citations SET cited_work_id = ? WHERE cited_work_id = ?", (pid, sid))
        db.execute("DELETE FROM citations WHERE cited_work_id = ?", (sid,))

        # Remapping can turn a pid—sid citation into a self-citation; drop those
        # so the merge cannot introduce the exact defect check_data.py flags.
        db.execute("DELETE FROM citations WHERE citing_work_id = cited_work_id")
        db.execute("DELETE FROM work_references WHERE work_id = referenced_work_id")
        
        # Update authorship
        db.execute("UPDATE OR IGNORE authorship SET work_id = ? WHERE work_id = ?", (pid, sid))
        db.execute("DELETE FROM authorship WHERE work_id = ?", (sid,))
        
        # Update work_references
        db.execute("UPDATE OR IGNORE work_references SET work_id = ? WHERE work_id = ?", (pid, sid))
        db.execute("DELETE FROM work_references WHERE work_id = ?", (sid,))

        # Update similarity edges (both endpoints)
        db.execute("UPDATE OR IGNORE similarity_edges SET work_id_a = ? WHERE work_id_a = ?", (pid, sid))
        db.execute("UPDATE OR IGNORE similarity_edges SET work_id_b = ? WHERE work_id_b = ?", (pid, sid))
        db.execute("DELETE FROM similarity_edges WHERE work_id_a = ? OR work_id_b = ?", (sid, sid))
        # A pid—sid edge becomes a self-loop after remapping; drop those
        db.execute("DELETE FROM similarity_edges WHERE work_id_a = work_id_b")

        # Update cluster assignments
        db.execute("UPDATE OR IGNORE work_clusters SET work_id = ? WHERE work_id = ?", (pid, sid))
        db.execute("DELETE FROM work_clusters WHERE work_id = ?", (sid,))

        # Update manuscript details
        db.execute("UPDATE OR IGNORE manuscript_details SET work_id = ? WHERE work_id = ?", (pid, sid))
        db.execute("DELETE FROM manuscript_details WHERE work_id = ?", (sid,))

        # Soft delete the secondary work
        db.execute("UPDATE works SET status = 'deleted' WHERE id = ?", (sid,))

        # Close the review queue entry for this pair (in either column order),
        # otherwise a pair merged from the admin UI stays 'pending' forever and
        # the curator is shown a decision they already made.
        db.execute(
            "UPDATE duplicate_candidates SET review_status = 'merged', curator_note = ?"
            " WHERE review_status = 'pending'"
            "   AND ((work_id_a = ? AND work_id_b = ?) OR (work_id_a = ? AND work_id_b = ?))",
            (f"merged via admin UI: kept {pid}", pid, sid, sid, pid),
        )

        # Any other pending pair that referenced the now-deleted work is stale.
        db.execute(
            "UPDATE duplicate_candidates SET review_status = 'resolved',"
            " curator_note = COALESCE(curator_note, 'one side merged away')"
            " WHERE review_status = 'pending' AND (work_id_a = ? OR work_id_b = ?)",
            (sid, sid),
        )

        db.commit()
        return {"message": "Works merged successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
