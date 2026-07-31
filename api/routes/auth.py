import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from api.auth import get_password_hash, verify_password, create_access_token
from api.models import UserCreate, UserLogin, Token

router = APIRouter()
DB_PATH = Path("data/syriac.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

@router.post("/register", response_model=Token)
def register(user: UserCreate):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (user.email,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
            
        hashed_password = get_password_hash(user.password)
        cursor = conn.execute(
            "INSERT INTO users (email, hashed_password) VALUES (?, ?)",
            (user.email, hashed_password)
        )
        conn.commit()
        user_id = cursor.lastrowid
        
        access_token = create_access_token(data={"sub": str(user_id)})
        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        conn.close()

@router.post("/login", response_model=Token)
def login(user: UserLogin):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        db_user = conn.execute("SELECT * FROM users WHERE email = ?", (user.email,)).fetchone()
        if not db_user or not verify_password(user.password, db_user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token = create_access_token(data={"sub": str(db_user["id"])})
        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        conn.close()
