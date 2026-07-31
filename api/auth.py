import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from passlib.context import CryptContext
import jwt
from jwt.exceptions import PyJWTError
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from api.database import get_db

# SECRET_KEY must come from the environment in production. If it is missing we
# generate a random per-process key so the app never runs with a publicly known
# secret — the trade-off is that existing tokens are invalidated on restart.
_env_secret = os.environ.get("SECRET_KEY", "").strip()
if _env_secret:
    SECRET_KEY = _env_secret
else:
    SECRET_KEY = secrets.token_hex(32)
    print(
        "WARNING: SECRET_KEY environment variable is not set. "
        "A random key was generated for this process; all login tokens will be "
        "invalidated when the server restarts. Set SECRET_KEY before deploying."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week for prototype convenience

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme), db: sqlite3.Connection = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user_id = int(user_id)
    except (PyJWTError, ValueError):
        raise credentials_exception

    # The token is only meaningful if the user still exists.
    row = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise credentials_exception
    return {"user_id": user_id}

def get_current_admin(current_user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    user = db.execute("SELECT role FROM users WHERE id = ?", (current_user["user_id"],)).fetchone()
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user
