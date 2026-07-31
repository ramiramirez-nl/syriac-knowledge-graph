import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from api.auth import get_current_user
from api.models import ClaimAuthorRequest

router = APIRouter()
DB_PATH = Path("data/syriac.db")

@router.post("/claim")
def claim_author(request: ClaimAuthorRequest, current_user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        author = conn.execute("SELECT id FROM authors WHERE id = ?", (request.author_id,)).fetchone()
        if not author:
            raise HTTPException(status_code=404, detail="Author not found")
            
        # Check if already claimed by someone
        existing_claim = conn.execute("SELECT * FROM user_claims WHERE author_id = ?", (request.author_id,)).fetchone()
        if existing_claim:
            if existing_claim["user_id"] == current_user["user_id"]:
                return {"message": "You have already claimed this author profile"}
            else:
                raise HTTPException(status_code=400, detail="Author profile already claimed by another user")
                
        conn.execute(
            "INSERT INTO user_claims (user_id, author_id, status) VALUES (?, ?, ?)",
            (current_user["user_id"], request.author_id, "approved") # Auto-approve for prototype
        )
        conn.commit()
        return {"message": "Author profile claimed successfully"}
    finally:
        conn.close()

@router.get("/me")
def get_my_profile(current_user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        user = conn.execute("SELECT id, email, role FROM users WHERE id = ?", (current_user["user_id"],)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        claims = conn.execute(
            """SELECT c.author_id, a.name, a.bio, a.interests, c.status 
               FROM user_claims c 
               JOIN authors a ON c.author_id = a.id 
               WHERE c.user_id = ?""",
            (current_user["user_id"],)
        ).fetchall()
        
        return {
            "user": dict(user),
            "claims": [dict(c) for c in claims]
        }
    finally:
        conn.close()
