from fastapi import APIRouter, Depends, HTTPException
import sqlite3
from typing import List

from api.database import get_db
from api.models import Notification
from api.auth import get_current_user

router = APIRouter()

# Guard against a huge first-run backlog being sent to the browser at once.
MAX_PAGE_SIZE = 100


@router.get("", response_model=List[Notification])
def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    query = "SELECT * FROM notifications WHERE user_id = ? "
    params: list = [current_user["user_id"]]
    if unread_only:
        query += "AND is_read = 0 "
    # Newest first; id breaks ties because created_at only has second precision
    # and a generator run inserts many rows within the same second.
    query += "ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)

    cursor = db.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


@router.get("/unread-count")
def unread_count(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Cheap poll target for the header badge."""
    count = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
        (current_user["user_id"],),
    ).fetchone()[0]
    return {"unread": count}


@router.put("/read-all")
def mark_all_read(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    cursor = db.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
        (current_user["user_id"],),
    )
    db.commit()
    return {"message": "All notifications marked as read", "updated": cursor.rowcount}


@router.put("/{notification_id}/read")
def mark_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    # Scope the write to the owner instead of checking first and updating by id:
    # one statement, and a foreign notification can never be touched.
    cursor = db.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, current_user["user_id"]),
    )
    db.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Marked as read"}
