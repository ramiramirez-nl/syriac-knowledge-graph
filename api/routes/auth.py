import sqlite3
from fastapi import APIRouter, HTTPException, status, Depends
from api.database import get_db
from api.auth import get_password_hash, verify_password, create_access_token
from api.models import UserCreate, UserLogin, Token

router = APIRouter()

@router.post("/register", response_model=Token)
def register(user: UserCreate, db: sqlite3.Connection = Depends(get_db)):
    existing = db.execute("SELECT id FROM users WHERE email = ?", (user.email,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user.password)

    # Bootstrap: the very first registered account becomes the admin, so the
    # moderation/curation tooling is usable without manual SQL. Every account
    # after that gets the default 'user' role.
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    role = "admin" if user_count == 0 else "user"

    cursor = db.execute(
        "INSERT INTO users (email, hashed_password, role) VALUES (?, ?, ?)",
        (user.email, hashed_password, role)
    )
    db.commit()
    user_id = cursor.lastrowid

    access_token = create_access_token(data={"sub": str(user_id)})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
def login(user: UserLogin, db: sqlite3.Connection = Depends(get_db)):
    db_user = db.execute("SELECT * FROM users WHERE email = ?", (user.email,)).fetchone()
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(db_user["id"])})
    return {"access_token": access_token, "token_type": "bearer"}
