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

- ✅ **Data Pipeline**: Automated data collection from OpenAlex (filtered & cleaned).
- ✅ **Analysis Engine**: Bibliometric analysis & thematic clustering (dynamically optimized into visually distinct clusters).
- ✅ **Interactive UI**: WebGL-powered graph visualization with node-hover interactions and curated color palettes.
- 🚧 **Curation & Auth**: Admin panel and user authentication prototype active.
- 🔮 **Community Platform**: Coming next (User-contributed corrections, profiles, discussion threads).

## Quick Start

### Prerequisites

- Python 3.9+
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

### Three-Signal Similarity

Weighted combination for discovery:
- **Citation** (0.35): Direct work-to-work citation edges
- **Bibliographic coupling** (0.30): Works sharing external references
- **Co-citation** (0.20): Works cited together by a third work
- **Semantic Text** (0.15): Title token overlap (filtered for robustness)

### Leiden Clustering

- The algorithm groups nodes into communities (clusters).
- Resolution is tuned to ~1.2 to provide balanced and distinct sub-topics (yielding ~37 major clusters).
- Dynamic color palettes assign distinct, visually appealing colors to clusters, cycling to ensure visual clarity.

### Tech Stack

- **Data**: OpenAlex API (open-access metadata)
- **ETL**: Python, SQLite, networkx
- **Analysis**: Leiden clustering, TF-IDF (scikit-learn)
- **Visualization**: Sigma.js (WebGL graph rendering)
- **Frontend**: Vanilla JS, HTML, CSS
- **Backend**: FastAPI (serves static files, auth, and admin endpoints)

## Known Limitations

1. **Short-title false positives**: Titles with <3 distinctive terms can produce false similarities. We've mitigated this by filtering the TF-IDF signal, with future updates aiming for multilingual semantic embeddings.
2. **Book review artifacts**: OpenAlex indexes book reviews as separate works with near-identical titles. We actively filter these out (`scripts/remove_reviews.py`).
3. **OpenAlex duplicates**: The same paper can be indexed twice. Duplicate detection logic helps highlight these in the curation admin.

## Roadmap

### Phase 2: Curation (In Progress)
- Duplicate record detection & merge UI
- Manual false-positive filtering
- BibTeX/RIS/Zotero import

### Phase 3: Community Platform
- User registration & profiles
- Member-contributed data with moderation workflow
- Author disambiguation & verification

## Contributing

Contributions are welcome! Please open issues for:
- Missing search boundary terms
- Duplicate detection reports
- UI/UX improvements

## License

MIT License — see LICENSE file.
