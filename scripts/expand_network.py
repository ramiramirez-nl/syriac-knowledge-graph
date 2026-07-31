import sqlite3
import time
import requests
from urllib.parse import quote
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"
THRESHOLD = 3

SELECT_FIELDS = "id,doi,display_name,publication_year,cited_by_count,type,primary_location,authorships,referenced_works"

def create_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "mailto:admin@syriac-knowledge-graph.org"})
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

def short_id(openalex_url: str) -> str:
    return openalex_url.split("/")[-1] if openalex_url else ""

def get_internal_ids(cursor):
    cursor.execute("SELECT id FROM works WHERE id LIKE 'W%' AND status != 'deleted'")
    return [row[0] for row in cursor.fetchall()]

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def expand_network():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    session = create_session()
    
    internal_ids = get_internal_ids(cursor)
    internal_id_set = set(internal_ids)
    print(f"Found {len(internal_ids)} internal OpenAlex works.")
    
    # We will find external works that cite at least THRESHOLD internal works.
    external_cite_counts = defaultdict(int)
    external_work_data = {}
    
    # OpenAlex filter OR limits to 50 items. We chunk the internal IDs.
    id_chunks = list(chunks(internal_ids, 50))
    print(f"Divided into {len(id_chunks)} chunks for OpenAlex queries.")
    
    for i, chunk in enumerate(id_chunks):
        print(f"Processing chunk {i+1}/{len(id_chunks)}...")
        filter_str = "cites:" + "|".join(chunk)
        url = f"https://api.openalex.org/works?filter={filter_str}&select={SELECT_FIELDS}&per-page=200"
        
        while url:
            try:
                r = session.get(url, timeout=30)
                r.raise_for_status()
                data = r.json()
                
                for w in data.get("results", []):
                    w_id = short_id(w.get("id"))
                    if not w_id or w_id in internal_id_set:
                        continue
                        
                    # Calculate how many internal works this external work cites
                    refs = [short_id(ref) for ref in w.get("referenced_works", [])]
                    internal_refs = [ref for ref in refs if ref in internal_id_set]
                    
                    if len(internal_refs) >= THRESHOLD:
                        external_cite_counts[w_id] = len(internal_refs)
                        external_work_data[w_id] = w
                        
                # Pagination
                next_cursor = data.get("meta", {}).get("next_cursor")
                if next_cursor:
                    base_url = url.split("&cursor=")[0]
                    url = f"{base_url}&cursor={quote(next_cursor)}"
                else:
                    url = None
                    
            except Exception as e:
                print(f"Error querying chunk {i+1}: {e}")
                url = None
                
            time.sleep(0.1) # Be nice to the API
            
    print(f"\nFound {len(external_work_data)} external works meeting the threshold of {THRESHOLD} internal citations.")
    
    # Now insert the qualifying works
    added_works = 0
    for w_id, w in external_work_data.items():
        title = w.get("display_name")
        if not title:
            continue
            
        cursor.execute("SELECT id FROM works WHERE id = ?", (w_id,))
        if cursor.fetchone():
            continue # already exists
            
        year = w.get("publication_year")
        doi = w.get("doi")
        if doi:
            doi = doi.replace("https://doi.org/", "")
        work_type = w.get("type", "article")
        cited_by = w.get("cited_by_count", 0)
        
        venue = None
        loc = w.get("primary_location")
        if loc:
            source = loc.get("source")
            if source:
                venue = source.get("display_name")
                
        cursor.execute(
            "INSERT INTO works (id, title, year, doi, venue, work_type, cited_by_count, source, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'openalex', 'curated')",
            (w_id, title, year, doi, venue, work_type, cited_by)
        )
        added_works += 1
        
        # Authors
        for auth_obj in w.get("authorships", []):
            author_data = auth_obj.get("author", {})
            a_id = short_id(author_data.get("id"))
            a_name = author_data.get("display_name")
            if not a_id or not a_name:
                continue
                
            cursor.execute("SELECT id FROM authors WHERE id = ?", (a_id,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO authors (id, name, source, status) VALUES (?, ?, 'openalex', 'curated')",
                    (a_id, a_name)
                )
                
            pos = auth_obj.get("author_position", "middle")
            cursor.execute("SELECT work_id FROM authorship WHERE work_id = ? AND author_id = ?", (w_id, a_id))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, ?)", (w_id, a_id, pos))
                
        # Insert outgoing citations (only keeping internal citations to avoid graph explosion)
        for ref_url in w.get("referenced_works", []):
            ref_id = short_id(ref_url)
            if ref_id in internal_id_set:
                cursor.execute("INSERT OR IGNORE INTO citations (citing_work_id, cited_work_id) VALUES (?, ?)", (w_id, ref_id))
                
    conn.commit()
    conn.close()
    
    print(f"Successfully added {added_works} new works to the database.")

if __name__ == "__main__":
    expand_network()
