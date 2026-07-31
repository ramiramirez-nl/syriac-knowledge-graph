<div align="center">
  
# 🕸️ Syriac Studies Network

**Interactive bibliometric network visualization and collaboration discovery platform for Syriac Studies research.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Sigma.js](https://img.shields.io/badge/Sigma.js-WebGL-e8453c.svg)](https://www.sigmajs.org/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg?logo=docker)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<br/>

[Overview](#overview) · [Quick Start](#quick-start) · [Usage](#usage) · [Architecture](#architecture) · [Limitations](#known-limitations) · [Roadmap](#roadmap)

</div>

---

## Overview

Syriac Studies Network maps relationships between academic publications in Syriac Studies through:

- **Citation networks**: Direct citations between works
- **Thematic clustering**: Automatic detection of research clusters using the Leiden algorithm
- **Bibliographic coupling**: Works sharing references  
- **Co-citation analysis**: Works cited together by other works
- **Semantic similarity**: Context-based textual similarities
- **Collaboration discovery**: Researchers working on similar topics but unaware of each other

The primary goal of this project is to provide a bird's-eye view of the field of Syriac Studies, allowing researchers to effortlessly discover new literature, spot thematic trends, and find potential collaborators around the world.

## Current Status

- **Data Pipeline**: Automated data collection from OpenAlex, review cleanup, incremental updates, and JSON export.
- **Analysis Engine**: Bibliometric analysis, multilingual semantic similarity, and Leiden thematic clustering.
- **Interactive UI**: WebGL-powered graph visualization with search, detail panels, cluster exploration, and collaboration hints.
- **Curation & Auth**: FastAPI backend, admin authentication, manual work entry/editing, duplicate review, false-positive exclusion, and BibTeX import.
- **Community Platform**: Phase 3 is next: notifications, production hosting, and richer member-facing workflows.

## Corpus Composition

The current exported corpus contains **6,554 works** and **2,779 authors** from multiple publication types:

| Type | Count | Description |
|---|---|---|
| Articles | ~2,850 | Journal articles |
| Book Chapters | ~2,220 | Chapters in edited volumes |
| Books | ~740 | Monographs and edited volumes |
| Dissertations | ~145 | PhD and master's theses |
| Datasets | ~144 | Research datasets |
| Conference Papers | ~94 | Conference proceedings |
| Other | ~460+ | Reference entries, software, preprints, etc. |

Data is primarily sourced from **OpenAlex** (open-access academic metadata), supplemented with manually curated imports.

## Quick Start

### Prerequisites

- Python 3.12+
- `uv` package manager (recommended) or standard `pip`
- Docker (optional)

### Local Installation

```bash
# Clone repo
git clone https://github.com/ramiramirez-nl/syriac-knowledge-graph.git
cd syriac-knowledge-graph

# Install dependencies using uv
uv sync

# Run the web server
uv run main.py
# Opens http://localhost:8000
```

### Docker Deployment

```bash
# Build and run using Docker Compose
docker-compose up --build -d
```

### Updating Data (Optional)

If you want to recalculate the graph from scratch:

```bash
# Fetch fresh works from OpenAlex
uv run scripts/fetch_openalex.py

# Remove book reviews (to clean up false clusters)
uv run scripts/remove_reviews.py

# Compute similarity graph & Leiden clusters
uv run scripts/compute_analysis.py

# Export to JSON for visualization
uv run scripts/export_json.py
```

## Usage

**Search**: Full-text title/author search in the left panel.

**Graph Modes**:
- **Similarity & Clusters**: Densely connected thematic clusters based on citations and semantic meaning.
- **Citations Only**: Purely direct citation edges.

**Interaction**:
- **Hover**: View work title and basic info immediately on hover without screen clutter.
- **Click Work**: View detailed info, citing/cited works, and cluster membership.
- **Click Author**: Show all works by that author.
- **Legend**: Click on a cluster in the legend to highlight its members.

**Collaboration Candidates**: Shows top researcher pairs working on similar topics but not yet co-authoring.

## Architecture

### Four-Signal Similarity

Weighted combination for discovery:
- **Citation** (0.35): Direct work-to-work citation edges
- **Bibliographic coupling** (0.30): Works sharing external references
- **Co-citation** (0.20): Works cited together by a third work
- **Semantic Text** (0.15): Multilingual text embeddings for title-level semantic similarity

### Leiden Clustering

- The algorithm groups nodes into communities (clusters).
- The current export contains 41 substantial clusters.
- Dynamic color palettes assign distinct, visually appealing colors to clusters, cycling to ensure visual clarity.

### Tech Stack

- **Data**: OpenAlex API (open-access metadata)
- **ETL**: Python, SQLite, networkx
- **Analysis**: Leiden clustering, multilingual-e5 semantic embeddings, bibliographic coupling, co-citation
- **Visualization**: Sigma.js (WebGL graph rendering)
- **Frontend**: Vanilla JS, HTML, CSS
- **Backend**: FastAPI (serves static files, auth, and admin endpoints)

## Known Limitations

1. **Title-only semantics**: Multilingual embeddings are stronger than the earlier TF-IDF signal, but title-only similarity still needs curator judgment for short or generic titles.
2. **Book review artifacts**: OpenAlex indexes book reviews as separate works with near-identical titles. We actively filter these out (`scripts/remove_reviews.py`).
3. **OpenAlex duplicates**: The same paper can be indexed twice. Duplicate detection logic helps highlight these in the curation admin; the current integrity check reports 23 duplicate DOI groups for review.

## Roadmap

### Phase 2: Curation (Completed)
- Duplicate record detection and merge tooling
- Manual false-positive filtering
- BibTeX import and admin-authenticated curation workflows

### Phase 3: Community Platform
- Notifications for new related publications or researchers
- Production hosting for the full authenticated app
- Richer member profiles and contribution workflows

## Contributing

Contributions are welcome! Please open issues for:
- Missing search boundary terms
- Duplicate detection reports
- UI/UX improvements

## License

MIT License — see LICENSE file.
