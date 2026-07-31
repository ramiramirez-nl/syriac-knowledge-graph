from fastapi import APIRouter, Depends
import sqlite3
import re
from typing import List, Dict, Any
from thefuzz import fuzz

from api.database import get_db

router = APIRouter()

def get_block_key(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r'^(a|an|the)\s+', '', t)
    t = re.sub(r'[^a-z]', '', t)
    return t[:4]

@router.get("/duplicates")
def get_potential_duplicates(limit: int = 50, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT id, title, year FROM works WHERE status NOT IN ('deleted', 'excluded')")
    works = [dict(r) for r in cursor.fetchall()]
    
    # Group by block key
    blocks: Dict[str, List[Dict[str, Any]]] = {}
    for w in works:
        key = get_block_key(w.get('title', ''))
        if len(key) >= 3:
            if key not in blocks:
                blocks[key] = []
            blocks[key].append(w)
            
    duplicates = []
    
    for key, block_works in blocks.items():
        if len(duplicates) >= limit:
            break
            
        n = len(block_works)
        for i in range(n):
            if len(duplicates) >= limit:
                break
            for j in range(i + 1, n):
                w1 = block_works[i]
                w2 = block_works[j]
                
                t1 = w1['title'] or ""
                t2 = w2['title'] or ""
                
                if len(t1) < 10 or len(t2) < 10:
                    continue
                    
                # Use token_set_ratio for robustness against reordering or missing words
                ratio = fuzz.token_set_ratio(t1.lower(), t2.lower())
                if ratio > 90:
                    # Double check with standard ratio to avoid matching completely different length strings
                    # that just happen to share all words of the shorter string.
                    std_ratio = fuzz.ratio(t1.lower(), t2.lower())
                    if std_ratio > 70:
                        duplicates.append({
                            "work1": w1,
                            "work2": w2,
                            "similarity": ratio
                        })
                
    # Sort duplicates by similarity descending
    duplicates.sort(key=lambda x: x['similarity'], reverse=True)
    return duplicates[:limit]
