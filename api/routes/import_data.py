from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import sqlite3
import uuid
import bibtexparser

from api.database import get_db
from api.auth import get_current_admin

router = APIRouter()

@router.post("/bibtex")
async def import_bibtex(file: UploadFile = File(...), db: sqlite3.Connection = Depends(get_db), admin: dict = Depends(get_current_admin)):
    if not file.filename.endswith('.bib'):
        raise HTTPException(status_code=400, detail="Only .bib files are supported")
        
    content = await file.read()
    try:
        bib_str = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")
        
    try:
        bib_database = bibtexparser.loads(bib_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse BibTeX: {e}")
        
    entries = bib_database.entries
    added_works = 0
    skipped_works = 0
    
    for entry in entries:
        title = entry.get('title', '').replace('{', '').replace('}', '').strip()
        doi = entry.get('doi', '')
        year = entry.get('year', '')
        venue = entry.get('journal', entry.get('booktitle', ''))
        work_type = entry.get('ENTRYTYPE', 'misc')
        
        if not title:
            skipped_works += 1
            continue
            
        cursor = db.execute("SELECT id FROM works WHERE (doi != '' AND doi = ?) OR title = ?", (doi, title))
        existing = cursor.fetchone()
        
        if existing:
            skipped_works += 1
            continue
            
        work_id = f"manual:{uuid.uuid4().hex[:8]}"
        
        try:
            db.execute(
                "INSERT INTO works (id, doi, title, year, venue, work_type, cited_by_count, source, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'curated')",
                (work_id, doi, title, int(year) if str(year).isdigit() else None, venue, work_type, 0)
            )
            
            author_str = entry.get('author', '')
            if author_str:
                authors = [a.strip() for a in author_str.split(' and ')]
                for i, author_name in enumerate(authors):
                    author_id = f"manual_author:{uuid.uuid4().hex[:8]}"
                    db.execute("INSERT INTO authors (id, name, source, status) VALUES (?, ?, 'manual', 'curated')", (author_id, author_name))
                    
                    pos = "middle"
                    if len(authors) == 1:
                        pos = "first"
                    elif i == 0:
                        pos = "first"
                    elif i == len(authors) - 1:
                        pos = "last"
                        
                    db.execute("INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, ?)", (work_id, author_id, pos))
                    
            db.commit()
            added_works += 1
        except Exception as e:
            db.rollback()
            print(f"Error inserting work {title}: {e}")
            skipped_works += 1
            
    return {
        "message": "Import completed",
        "added": added_works,
        "skipped": skipped_works,
        "total_processed": len(entries)
    }
