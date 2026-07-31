from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from api.routes import works, authors, curation, import_data, auth, users, contributions, notifications

app = FastAPI(title="Syriac Studies Knowledge Graph API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(works.router, prefix="/api/works", tags=["works"])
app.include_router(authors.router, prefix="/api/authors", tags=["authors"])
app.include_router(curation.router, prefix="/api/curation", tags=["curation"])
app.include_router(import_data.router, prefix="/api/import", tags=["import"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(contributions.router, prefix="/api/contributions", tags=["contributions"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@app.get("/api/status")
def get_status():
    plan_path = os.path.join(ROOT, "PLAN.md")
    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        return {"content": f"Error loading status: {e}"}

site_dir = os.path.join(ROOT, "site")
app.mount("/", StaticFiles(directory=site_dir, html=True), name="site")
