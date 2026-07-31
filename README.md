# Syriac Studies Network

Interactive bibliometric network visualization and collaboration discovery platform for Syriac Studies research.

## Overview

Syriac Studies Network maps relationships between academic publications in Syriac Studies through:

- **Citation networks**: Direct citations between works
- **Thematic clustering**: Automatic detection of research clusters using Leiden algorithm
- **Bibliographic coupling**: Works sharing references  
- **Co-citation analysis**: Works cited together by other works
- **TF-IDF similarity**: Title-based semantic similarity
- **Collaboration discovery**: Researchers working on similar topics but unaware of each other

## Current Status: Phase 1 Complete ✓

- ✅ **Phase 0**: Data collection from OpenAlex (5,360 works, 2,510 authors — book reviews removed, see below)
- ✅ **Phase 1**: Bibliometric analysis & clustering (95 thematic clusters)
- ⏳ **Phase 2**: Curation UI (duplicate detection, manual filtering)
- 🔮 **Phase 3**: Community platform (user registration, profiles, member contributions)

## Quick Start

### Prerequisites

- Python 3.9+
- `uv` package manager

### Installation

```bash
# Clone repo
git clone https://github.com/ramiramirez-nl/syriac-knowledge-graph.git
cd syriac-knowledge-graph

# Install dependencies
uv sync

# View in browser
uv run main.py
# Opens http://localhost:8000
```

### Update Data (Optional)

```bash
# Fetch fresh works from OpenAlex
uv run scripts/fetch_openalex.py

# Remove book reviews (out of scope — see Known Limitations)
uv run scripts/remove_reviews.py

# Compute similarity graph & clusters
uv run scripts/compute_analysis.py

# Export to JSON for visualization
uv run scripts/export_json.py
```

## Usage

**Search**: Full-text title/author search in left panel

**Graph modes**:
- "Similarity & Clusters": Densely connected thematic clusters (11,547 edges)
- "Citations Only": Direct citation edges only (1,753 edges)

**Interact**:
- Click work node → view details, citing/cited works, cluster membership
- Click author name → show all works by that author
- Click cluster in legend → focus cluster, highlight members
- Toggle "Show isolated works" to hide unconnected publications

**Collaboration candidates**: Top 60 researcher pairs working on similar topics but not yet co-authoring

## Project Structure

```
config/
├── terms.yaml           # OpenAlex search boundary (16 domain keywords)

scripts/
├── fetch_openalex.py    # ETL: OpenAlex → SQLite
├── remove_reviews.py    # Cleanup: strip book reviews from corpus
├── compute_analysis.py  # Phase 1: Similarity graph, clustering
├── export_json.py       # Export normalized data for static site

data/
├── syriac.db            # SQLite normalized schema
│   ├── works
│   ├── authors
│   ├── authorship (positions: first/middle/last)
│   ├── citations
│   ├── work_references (full reference lists)
│   ├── similarity_edges (Phase 1 computed)
│   ├── work_clusters (Leiden assignments)
│   └── collaboration_candidates

site/
├── index.html           # Sigma.js interactive visualization
├── data.json            # Pre-computed layout + graph (4 MB)

PLAN.md                 # Detailed design docs, decisions, limitations
```

## Architecture

### Three-Signal Similarity (Phase 1)

Weighted combination for discovery:
- **Citation** (0.35): Direct work-to-work citation edges
- **Bibliographic coupling** (0.30): Works sharing external references
- **Co-citation** (0.20): Works cited together by a third work
- **TF-IDF title** (0.15): Title token overlap (filtered for robustness)

Combined graph: 11,547 edges, spring-layout node positions pre-computed server-side.

### Leiden Clustering

- Resolution: 0.4
- Output: 96 clusters with ≥3 members (+ 937 singletons)
- Top terms extracted via TF-IDF centroids
- Deterministic golden-angle coloring (hex output for WebGL)

### Static Architecture

- No backend server required for Phases 1–2
- JSON data bundled once per analysis run
- Sigma.js WebGL canvas for rendering 5,360 nodes + 12,091 edges in-browser
- Light theme for readability

## Known Limitations

See **PLAN.md** for detailed trade-offs. Key issues:

1. **Short-title false positives**: Titles with <3 distinctive terms (e.g., "The Church of the East") produce ~100% TF-IDF similarity against other short titles. *Mitigation*: Filtered from TF-IDF signal; future work will use multilingual semantic embeddings (multilingual-e5).

2. **Book review artifacts**: OpenAlex indexes book reviews as separate works with near-identical titles to each other (both echo the reviewed book's title), which created false clustering/collaboration signals. *Mitigation*: Fully removed from the corpus via `scripts/remove_reviews.py` (373 removed), detected by review-type tag, title prefixes ("Review of...", "Book Review"), and citation-style markers (ISBN, price, page count). A handful of true reviews may still slip through if their titles don't match any marker.

3. **OpenAlex duplicates**: Same paper indexed twice with different IDs and inconsistent author lists. *Mitigation*: Detected via duplicate-title pairs in collaboration candidates.

4. **Isolation bias**: Works with no similarity edges default to cluster=null and appear as gray on "Similarity & Clusters" view. Reflects limited connection signal, not low quality.

## Roadmap

### Phase 2: Curation (Q3 2026)

- Duplicate record detection & merge UI
- Manual false-positive filtering
- BibTeX/RIS/Zotero import
- User-contributed corrections

### Phase 3: Community Platform (Q4 2026+)

- User registration & profiles
- Member-contributed data with moderation workflow
- Discussion threads per work/cluster
- Author disambiguation & verification
- DOI/ISBN/ORCID linking

### Phase 1 Quality Improvements

- Replace title-only TF-IDF with multilingual semantic embeddings (multilingual-e5)
- Use abstract text + title for similarity
- Improve cluster-layout spatial alignment (current: members scattered, just logically grouped)

## Configuration

Edit `config/terms.yaml` to adjust OpenAlex search boundary:

```yaml
include_terms:
  - syriac
  - peshitta
  - "ephrem the syrian"
  # ... (16 total)

exclude_terms: []

api:
  base_url: "https://api.openalex.org"
  mailto: "your-email@example.com"  # OpenAlex polite pool
  per_page: 200
```

## Technology

- **Data**: OpenAlex API (open-access metadata)
- **ETL**: Python, SQLite, networkx
- **Analysis**: Leiden clustering, TF-IDF (scikit-learn)
- **Visualization**: Sigma.js (WebGL graph rendering)
- **Layout**: Networkx spring_layout (force-directed)
- **Frontend**: Vanilla JS, light theme CSS

## Contributing

Contributions welcome. Open issues for:
- Missing terms (expand search boundary)
- Duplicate detection (report OpenAlex IDs)
- UI/UX improvements
- Phase 2 curation tools

## License

MIT License — see LICENSE file.


---

**Built with Claude Code** 🤖
