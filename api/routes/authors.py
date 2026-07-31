from fastapi import APIRouter, Depends, HTTPException
import sqlite3
from typing import List

from api.database import get_db
from api.models import Author, AuthorUpdate, MergeAuthorsRequest
from api.auth import get_current_user

router = APIRouter()

@router.get("", response_model=List[Author])
def get_authors(skip: int = 0, limit: int = 50, q: str = None, db: sqlite3.Connection = Depends(get_db)):
    query = "SELECT * FROM authors WHERE status != 'deleted' "
    params = []
    
    if q:
        query += "AND name LIKE ? "
        params.append(f"%{q}%")
        
    query += "LIMIT ? OFFSET ?"
    params.extend([limit, skip])
    
    cursor = db.execute(query, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

@router.post("/merge")
def merge_authors(request: MergeAuthorsRequest, db: sqlite3.Connection = Depends(get_db)):
    try:
        for sec_id in request.secondary_ids:
            db.execute("UPDATE OR IGNORE authorship SET author_id = ? WHERE author_id = ?", (request.primary_id, sec_id))
            db.execute("DELETE FROM authorship WHERE author_id = ?", (sec_id,))
            db.execute("UPDATE authors SET status = 'deleted' WHERE id = ?", (sec_id,))
            
        db.commit()
        return {"message": "Authors merged successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{author_id}", response_model=Author)
def update_author(author_id: str, author_update: AuthorUpdate, current_user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    # Verify the user has claimed this author
    claim = db.execute(
        "SELECT status FROM user_claims WHERE user_id = ? AND author_id = ?", 
        (current_user["user_id"], author_id)
    ).fetchone()
    
    if not claim or claim["status"] != "approved":
        raise HTTPException(status_code=403, detail="Not authorized to edit this author profile")
        
    cursor = db.execute("SELECT * FROM authors WHERE id = ?", (author_id,))
    existing = cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Author not found")
        
    db.execute(
        "UPDATE authors SET bio = ?, interests = ? WHERE id = ?",
        (author_update.bio, author_update.interests, author_id)
    )
    db.commit()
    
    cursor = db.execute("SELECT * FROM authors WHERE id = ?", (author_id,))
    return dict(cursor.fetchone())
