from fastapi import APIRouter, Depends, HTTPException
import sqlite3
from typing import List

from api.database import get_db
from api.models import Notification
from api.auth import get_current_user

router = APIRouter()

@router.get("", response_model=List[Notification])
def get_notifications(current_user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC", 
        (current_user["user_id"],)
    )
    return [dict(row) for row in cursor.fetchall()]

@router.put("/{notification_id}/read")
def mark_read(notification_id: int, current_user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    # Verify ownership
    cursor = db.execute("SELECT * FROM notifications WHERE id = ? AND user_id = ?", (notification_id, current_user["user_id"]))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Notification not found")
        
    db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
    db.commit()
    return {"message": "Marked as read"}
