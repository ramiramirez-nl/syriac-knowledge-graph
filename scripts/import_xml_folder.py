import os
import glob
import sqlite3
import xml.etree.ElementTree as ET
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"
FOLDER_PATH = ROOT / "New folder"

KEYWORDS = ["syriac", "aramaic", "syr", "ephrem", "christian", "antiquity", "mesopotamia", "church of the east", "orthodox"]

def is_relevant(title, snippet):
    text = (title + " " + snippet).lower()
    for kw in KEYWORDS:
        if kw in text:
            return True
    return False

def run_import():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    xml_files = glob.glob(str(FOLDER_PATH / "*.xml"))
    
    added_count = 0
    skipped_dup = 0
    skipped_irrelevant = 0
    
    for file_path in xml_files:
        print(f"Processing {os.path.basename(file_path)}...")
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            for pub in root.findall('publication'):
                title = pub.find('title').text if pub.find('title') is not None else ""
                authors_str = pub.find('authors').text if pub.find('authors') is not None else ""
                year_str = pub.find('year').text if pub.find('year') is not None else ""
                venue = pub.find('source').text if pub.find('source') is not None else ""
                snippet = pub.find('snippet').text if pub.find('snippet') is not None else ""
                
                if not title:
                    continue
                    
                # Relevance check
                if not is_relevant(title, snippet):
                    skipped_irrelevant += 1
                    continue
                    
                # Duplicate check
                cursor.execute("SELECT id FROM works WHERE LOWER(title) = LOWER(?) AND status != 'deleted'", (title.strip(),))
                if cursor.fetchone():
                    skipped_dup += 1
                    continue
                    
                # Insert
                work_id = f"manual:{uuid.uuid4().hex[:8]}"
                year = int(year_str) if year_str and year_str.isdigit() else None
                
                cursor.execute(
                    "INSERT INTO works (id, title, year, venue, work_type, cited_by_count, source, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (work_id, title.strip(), year, venue.strip(), "article", 0, "manual_import", "curated")
                )
                
                # Authors
                if authors_str:
                    author_names = [a.strip() for a in authors_str.split(',')]
                    for i, a_name in enumerate(author_names):
                        if not a_name: continue
                        a_id = f"manual_author:{uuid.uuid4().hex[:8]}"
                        cursor.execute("INSERT INTO authors (id, name, source, status) VALUES (?, ?, 'manual_import', 'curated')", (a_id, a_name))
                        
                        pos = "middle"
                        if i == 0: pos = "first"
                        elif i == len(author_names) - 1: pos = "last"
                        
                        cursor.execute("INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, ?)", (work_id, a_id, pos))
                        
                added_count += 1
                
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            
    conn.commit()
    conn.close()
    
    print(f"Import complete.")
    print(f"Added: {added_count}")
    print(f"Skipped (Duplicate): {skipped_dup}")
    print(f"Skipped (Irrelevant): {skipped_irrelevant}")

if __name__ == "__main__":
    run_import()
