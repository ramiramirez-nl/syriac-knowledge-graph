from fastapi import APIRouter, Depends, HTTPException
import sqlite3
import json
import uuid

from api.database import get_db
from api.models import ContributionCreate, Contribution
from api.auth import get_current_user, get_current_admin

router = APIRouter()

@router.post("", response_model=dict)
def submit_contribution(contrib: ContributionCreate, current_user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    # Basic validation
    if contrib.type not in ["new_work", "edit_work"]:
        raise HTTPException(status_code=400, detail="Invalid contribution type")
        
    try:
        # Validate it's proper JSON
        json.loads(contrib.payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload must be valid JSON")
        
    db.execute(
        "INSERT INTO pending_contributions (user_id, type, payload, status) VALUES (?, ?, ?, 'pending')",
        (current_user["user_id"], contrib.type, contrib.payload)
    )
    db.commit()
    return {"message": "Contribution submitted successfully and is pending review"}

@router.get("", response_model=list[Contribution])
def list_contributions(status: str = "pending", admin_user: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT * FROM pending_contributions WHERE status = ? ORDER BY submitted_at DESC", (status,))
    return [dict(row) for row in cursor.fetchall()]

@router.post("/{contrib_id}/approve")
def approve_contribution(contrib_id: int, admin_user: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT * FROM pending_contributions WHERE id = ? AND status = 'pending'", (contrib_id,))
    contrib = cursor.fetchone()
    if not contrib:
        raise HTTPException(status_code=404, detail="Pending contribution not found")
        
    payload = json.loads(contrib["payload"])
    
    try:
        if contrib["type"] == "new_work":
            work_id = f"manual:{uuid.uuid4().hex[:8]}"
            db.execute(
                "INSERT INTO works (id, doi, title, year, venue, work_type, cited_by_count, source, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'curated')",
                (work_id, payload.get("doi"), payload.get("title"), payload.get("year"), payload.get("venue"), payload.get("work_type"), 0)
            )
            authors = payload.get("authors", [])
            for i, author_name in enumerate(authors):
                author_id = f"manual_author:{uuid.uuid4().hex[:8]}"
                db.execute("INSERT INTO authors (id, name, source, status) VALUES (?, ?, 'manual', 'curated')", (author_id, author_name))
                pos = "middle"
                if len(authors) == 1: pos = "first"
                elif i == 0: pos = "first"
                elif i == len(authors) - 1: pos = "last"
                db.execute("INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, ?)", (work_id, author_id, pos))
                
        elif contrib["type"] == "edit_work":
            work_id = payload.get("id")
            updates = []
            params = []
            if "title" in payload:
                updates.append("title = ?")
                params.append(payload["title"])
            if "doi" in payload:
                updates.append("doi = ?")
                params.append(payload["doi"])
            if "year" in payload:
                updates.append("year = ?")
                params.append(payload["year"])
                
            if updates:
                params.append(work_id)
                db.execute(f"UPDATE works SET {', '.join(updates)} WHERE id = ?", params)
        
        db.execute("UPDATE pending_contributions SET status = 'approved' WHERE id = ?", (contrib_id,))
        
        # Trigger Notifications for claimed authors
        if contrib["type"] == "new_work":
            authors = payload.get("authors", [])
            for author_name in authors:
                # Find if any claimed author has this exact name (simplified for prototype)
                # Ideally, the contribution payload would include author_ids, but it's just names right now.
                claimed_users = db.execute(
                    """SELECT user_id FROM user_claims c 
                       JOIN authors a ON c.author_id = a.id 
                       WHERE a.name = ? AND c.status = 'approved'""", 
                    (author_name,)
                ).fetchall()
                
                for user_claim in claimed_users:
                    msg = f"A new work '{payload.get('title')}' was added listing you as an author."
                    db.execute("INSERT INTO notifications (user_id, message) VALUES (?, ?)", (user_claim["user_id"], msg))
                    
        db.commit()
        return {"message": "Contribution approved and applied"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{contrib_id}/reject")
def reject_contribution(contrib_id: int, admin_user: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    db.execute("UPDATE pending_contributions SET status = 'rejected' WHERE id = ?", (contrib_id,))
    db.commit()
    return {"message": "Contribution rejected"}
