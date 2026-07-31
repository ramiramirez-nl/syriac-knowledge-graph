from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
import os

from api.routes import works, authors, curation, import_data, auth, users, contributions, notifications
from api.auth import get_current_admin

app = FastAPI(title="Syriac Studies Knowledge Graph API")

# The site is served by this same app, so same-origin requests need no CORS at
# all. Cross-origin access (e.g. a separate dev frontend) is opt-in via the
# ALLOWED_ORIGINS env var (comma-separated).
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# data.json is several MB; gzip brings it down to a fraction of that.
app.add_middleware(GZipMiddleware, minimum_size=5000)

app.include_router(works.router, prefix="/api/works", tags=["works"])
app.include_router(authors.router, prefix="/api/authors", tags=["authors"])
app.include_router(curation.router, prefix="/api/curation", tags=["curation"])
app.include_router(import_data.router, prefix="/api/import", tags=["import"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(contributions.router, prefix="/api/contributions", tags=["contributions"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/api/status")
def get_status(admin: dict = Depends(get_current_admin)):
    plan_path = os.path.join(ROOT, "PLAN.md")
    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        return {"content": f"Error loading status: {e}"}

site_dir = os.path.join(ROOT, "site")
app.mount("/", StaticFiles(directory=site_dir, html=True), name="site")
