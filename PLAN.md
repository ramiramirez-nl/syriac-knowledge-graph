# Syriac Studies Knowledge Graph — Project Plan

> Last update: 2026-07-05
> Status: Phase 0 + Phase 1 completed (clustering, similarity network, collaboration candidates working). Next: Phase 2 (curation).

## 1. Vision

To gather publications and researchers in the field of Syriac Studies on a single interactive platform. The goal is not just a citation network:

1. **Relationship discovery** — which work is related to which (citation, co-author, shared topic).
2. **Pattern and clustering** — automatically detecting and visualizing subsets of the field (thematic schools, periods, geographies).
3. **Collaboration discovery** — matching researchers working on intersecting topics who are unaware of each other (the "these two people work on similar topics but have never cited each other" signal).
4. **Community platform** — a living system where researchers can sign up via email, create profiles, and enter/correct their own data.

Strategy: **from simple to complex.** First, a solid core data + prototype; membership and community features will be built on top of this core in later phases.

## 2. Verified Findings (2026-07-05)

OpenAlex API (free, no key required, `https://api.openalex.org`):

- **4,538** publications with "syriac" in the title; **22,237** publications with it in the full text. Even works from 1904 are indexed (e.g. Nöldeke, *Compendious Syriac Grammar*, W1481040678).
- Every publication record has a `referenced_works` field → **citation network comes ready**, no need to manually process bibliographies.
- Every author has a persistent OpenAlex Author ID → name variants ("S.P. Brock" / "Sebastian Brock") merge largely automatically.
- There is **no** ready "Syriac Studies" topic/concept tag → we will draw the field boundary ourselves: search term list + manual curation.

### Known risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Poor book/book chapter coverage in OpenAlex | Important monographs might be missing | Manual addition mechanism designed from the start (Phase 2) |
| Non-Western language publications (Arabic, Syriac, Turkish) missing | Part of the field remains invisible | Completion through community contribution (Phase 3) |
| False positives (irrelevant medical/linguistic articles) | Network gets polluted | Curation step + exclusion list |
| Author disambiguation errors | Same person becomes two nodes | Rely on OpenAlex ID; manual merge tool |

## 3. Phases

### Phase 0 — Core Data + Prototype ✅ COMPLETED (2026-07-05)

Goal: An interactive graph demo working with real data, without manual data entry.

- [x] Python ETL script (with `uv`): `scripts/fetch_openalex.py` — Fetches publication + author + citation data from OpenAlex using 17 terms in `config/terms.yaml` → SQLite (`data/syriac.db`). Result: **5,733 works, 2,671 authors, 1,753 citation edges** (edges are only "internal" citations where both ends are in the corpus).
- [x] Data model established: `works`, `authors`, `authorship` (N-N), `citations` (work→work). Each record has `source` (openalex/manual) and `status` (auto/curated) fields — manual feeding in Phase 2/3 directly fits this schema.
- [x] `scripts/export_json.py`: Exports SQLite to `site/data.json`; precomputes layout with networkx `spring_layout` (no need for client-side layout library). Disconnected (citation-less) nodes are handled separately and placed in a ring around the core network — otherwise, ~4,000 isolated nodes massively expanded the coordinate space and made the connected network invisible on screen.
- [x] Static prototype site (`site/index.html`, English interface): Graph with Sigma.js (CDN, UMD, no build step); click a node → detail panel (title, year, journal, authors, "cites"/"cited by" lists); click an author name → all other works of that author in the corpus are listed (core of the desired "profile page" behavior); search box (live filter on title + author name); "show works with no citation link" toggle; color scale by year decimal + legend.
- [x] Tested locally with `preview` server: node clicking, author navigation, inter-node navigation from citation lists, search, isolated node toggle — all verified.

Tech: Python (uv, requests, networkx, sqlite3) + pure HTML/JS + Sigma.js UMD. No backend, no build step, no server cost.

**Files:** `config/terms.yaml`, `scripts/fetch_openalex.py`, `scripts/export_json.py`, `data/syriac.db`, `site/index.html`, `site/data.json`, `.claude/launch.json` (preview server).

**Known limitations / next improvements:**
- Only 17 search terms were used; the field boundary is still rough. Term list can be expanded.
- Of the 5,733 works, only 1,753 citation edges are in the internal corpus — most citations go outside the corpus (books, works not in OpenAlex). This confirms why bibliographic coupling / co-citation / embedding similarity edges in Phase 1 are important: a pure citation network remains too sparse.
- A development/testing hook was left in `window.__debug` (graph, renderer, data access) — can be removed when moving to production but is harmless.

### Phase 1 — Analysis Layer: Clustering and Patterns ✅ COMPLETED (2026-07-05)

Goal: Automated answer to "What does the field look like?"

- [x] Similarity edges (`scripts/compute_analysis.py`):
      - **Bibliographic coupling**: `work_references` table (full reference list including out-of-corpus references, e.g. if two articles cite the same book, a link is established) — 4,841 pairs. Overly generic references (cited by >30 works) were eliminated.
      - **Co-citation**: pair co-cited by the same third work — 7,587 pairs.
      - **TF-IDF title similarity** (scikit-learn, unigram+bigram): 23,183 above-threshold pairs. Note: title-only TF-IDF was used instead of true multilingual embedding (multilingual-e5) — see "Known limitations".
      - Three signals were weighted and aggregated (citation 0.35, coupling 0.30, co-citation 0.20, tfidf 0.15), keeping the top 6 strongest edges per node → **12,764-edge** combined similarity graph (connected nodes: 4,589 of 5,733 — a much richer structure compared to 1,161 in the citation-only graph).
- [x] Cluster extraction with **Leiden algorithm** (python-igraph + leidenalg, RBConfigurationVertexPartition, resolution=0.4): **96 meaningful clusters** (≥3 members). Automatic labeling from the TF-IDF centroid vector (highest-weighted terms). The resulting clusters align with field expertise: "ephrem, ephrem syrian, syrian" (660), "peshitta, old testament" (569), "church of the east" (441), "syriac grammar" (414), "syriac orthodox" (219), "syro-malabar" (133), "incantation bowls" (117), "galen, syriac galen" (87), "assyrian church" (74) etc.
- [x] Collaboration opportunity signal (`collaboration_candidates` table): cosine similarity ≥0.35 between author centroid TF-IDF vectors, pairs with no existing co-authorship/citation connection, 300 candidates generated. Displayed on the site as "Potential Collaborations" panel; clicking lists the works of the two authors comparatively.
- [x] Visualization (`site/index.html`): "Similarity & clusters" / "Citations only" view toggle (sharing the same node positions); coloring by cluster (golden-angle HSL, auto-color for 96 clusters); clicking the cluster list highlights members of that cluster and focuses the camera.

Tech: Python (scikit-learn TfidfVectorizer, python-igraph, leidenalg). Still a static site, no backend.

**Files:** `scripts/compute_analysis.py` (main analysis), updated `scripts/fetch_openalex.py` (new `work_references` table — full reference list including out-of-corpus), updated `scripts/export_json.py` (layout is now computed from the similarity graph, cluster/similarity/collaboration data is exported).

**Known limitations (to be taken seriously):**
- **Title-only TF-IDF is a real weakness.** Short titles ("The Church of the East", 2-3 words) can produce 100% cosine similarity with almost randomly different short titles (vector direction is fully determined by very few terms). Mitigated with a requirement of ≥3 distinguishing terms and a "ceiling" filter (>0.97 similarity = likely noise, excluded) but not fully solved.
- **Book review pollution:** The review titles of two different authors reviewing the same book are almost identical (both repeat the title of the reviewed book) — this is a data pattern, not a real "shared interest" signal. 503 works were excluded from the TF-IDF signal using `work_type` and title patterns (ISBN, "pp.", "ed. by", ". By AUTHOR." etc.), but it doesn't catch all variations — **the candidates in the "Potential Collaborations" panel, especially the highest-scoring ones, may still contain false positives; it should be presented as a "hint list" requiring manual verification, not a definitive result** (this warning is already in the site UI).
- **Duplicate records found in OpenAlex:** Instances where the same article is indexed with two different work IDs and assigned to different author names were confirmed (`W2080959781` / `W4255695122`, "Two Palestinian Syriac Texts..."). Pairs with exact title matches were eliminated from collaboration candidates, but close-but-not-exact matches (e.g. "...Volume I" / "..." truncated title) can still leak through. General duplicate-record cleanup is deferred to Phase 2 curation.
- **Cluster-layout alignment is imperfect:** The members of a cluster are not always spatially contiguous in the graph (since spring_layout is computed for the entire combined graph, members of large clusters can scatter to different regions). Highlighting works correctly when clicking a cluster, just the visual placement isn't perfect.
- All the above limitations will significantly improve with the use of true multilingual semantic embedding (e.g. multilingual-e5) and/or abstract text — this is a natural next improvement step for Phase 1 (see section 5).

### Phase 2 — Curation and Manual Feeding ✅ COMPLETED (2026-07-31)

Goal: Infrastructure to close gaps; data quality.

- [x] Simple admin interface: add/edit/delete/exclude records, merge authors, mark false positives.
- [x] Import: BibTeX export → convert to data model.
- [x] Auto-update: Incremental fetch from OpenAlex (via `scripts/update_openalex.py`).
- [x] A backend is required at this point: **FastAPI + SQLite** (migration to Postgres if scaling up).

### Phase 3 — Community Platform ← NEXT STEP

Goal: A living system; researchers manage their own data.

- [x] Membership: sign up via email (magic link or password + verification).
- [x] Profile pages: researcher "claims" their OpenAlex/ORCID record, edits biography, interests, publication list.
- [x] Contribution workflow: members can add publications/suggest corrections → moderation queue → merged into main data upon approval (Wikipedia-like, no direct writes).
- [ ] Notifications: alerts for "new publication/researcher intersecting with your work".
- [ ] Hosting: small VPS or free tier (like Fly.io / Railway); domain name.

### Phase 4 — (Future, optional)

- ORCID OAuth login, Zotero synchronization, English/Turkish UI toggle, opening the API (so other researchers can use the data), manuscript/edition records for older works without DOIs.

## 4. Architectural Principles

1. **Data model is future-proof from the start**: `source` (openalex/manual/member), `status` (auto/curated/pending) fields are in the schema since Phase 0. Prototype data doesn't get thrown away, it gets built upon.
2. **Stay static as long as static works**: No backend in Phase 0-1 → zero cost, zero maintenance. Backend only arrives when write needs emerge (Phase 2).
3. **OpenAlex IDs are preserved as primary keys**; manually added records get our own prefix-generated ID (e.g. `manual:0001`).
4. **Each phase is a standalone releasable product** — even Phase 0 is useful on its own.

## 5. Next Concrete Step

Phase 3 Community Platform: (a) Implement user membership/registration, (b) Author profile claiming workflow, (c) Contribution and moderation queues so users can submit corrections/additions without writing directly to the core tables.

## 6. Decision Log

- 2026-07-05: Data source = OpenAlex (coverage test positive). Crossref as backup.
- 2026-07-05: Prototype visualization = Sigma.js (performant with thousands of nodes).
- 2026-07-05: Phasing from simple to complex; membership/profile deferred to Phase 3.
- 2026-07-05: Model switched from Fable 5 → Sonnet 5 (sufficient for implementation work; Fable 5 kept for architecture/analysis decisions).
- 2026-07-05: Phase 0 completed. Precomputed coordinates on Python side (networkx spring_layout) preferred over client-side library for layout — simpler, no dependencies, fast enough for prototype (~11s).
- 2026-07-05: Phase 1 completed. TF-IDF preferred over semantic embedding for v1 (speed, dependency weight); a serious weakness emerged during testing (short titles + book reviews produce fake 100% similarity) — partially fixed, remaining limitation clearly documented in PLAN.md and shown as a warning to the user in the site UI.
- 2026-07-05: Theme flipped dark → light (user request).
- 2026-07-05: Bugs found and fixed in review: (1) Sigma WebGL fails to parse hsl() color strings, clustered nodes were printed black → hex conversion added; (2) unclustered nodes fell to decade color in similarity view (mixing two color languages) → neutral gray + explanation line in legend; (3) programmatic view toggle (cluster/candidate click) didn't update legend → consolidated into single `setViewMode` helper; (4) author sorting was alphabetical ('first'<'last'<'middle'), middle authors fell to the end → fixed with CASE; (5) stale panel title when switching from candidate view to author view → resetting it.
- 2026-07-06: Book reviews completely removed from the corpus (user request — reviews are not original research, plus they produce fake clustering/collaboration signals with their nearly identical titles). The previous `is_review_like()` heuristic only excluded them from the TF-IDF signal; now they are permanently deleted from the database (works + authorship + citations + work_references, including authors now without works) via `scripts/remove_reviews.py`. Filter was refined in two rounds: (1) `<i>`/`<b>` HTML markup removed from being a signal — it also occurred in real article titles (e.g. "...the *Life of Anthony*"), causing ~140 false positives; (2) page count pattern expanded to catch variants without spaces ("182pp."), "book review" now also searched as a substring (for parenthesis/bracket variants). Result: 373 book reviews deleted (5,733 → 5,360 works), 161 single-contribution authors dropped with them (5,360/2,510). One edge case (in-content page reference like "pp. 283–292" in a review text) was intentionally left out — it's not a real review, it summarizes articles within an omitted volume.
- 2026-07-06: Added `cache: "no-cache"` to `fetch("data.json")` call in `site/index.html` — the browser cache was serving data.json without validating from the server when the pipeline was re-run (discovered during testing, would have affected returning visitors in production too).
- 2026-07-31: Phase 2 completed. Added FastAPI backend, BibTeX import, duplicate work merging, false positive exclusions, and manual work entry/editing. TF-IDF was successfully replaced with `multilingual-e5` for semantic embeddings to improve cluster quality. Now ready for Phase 3 (Community Platform).
- 2026-07-31: Code review round (security hardening + bug fixes). **Committed as 54f6ea9.** (a) All write/curation endpoints (`works` create/update/delete/exclude/merge, `authors` merge, `import`, `curation/duplicates`) now require an admin Bearer token via `get_current_admin`; (b) `SECRET_KEY` must come from env — a random key is generated per-process if missing (tokens invalidated on restart) instead of a hardcoded default; (c) `get_current_user` now verifies the user still exists in the DB; (d) first registered account bootstraps as `admin` so the moderation queue is usable without manual SQL; (e) fixed `WorkCreate`/`WorkUpdate` missing `manuscript_details`/`work_type` fields (AttributeError → 500 on the admin UI); (f) `merge_works` now also remaps `similarity_edges`, `work_clusters`, `manuscript_details`; (g) `export_json.py` excludes `deleted`/`excluded` works and dangling edges, `check_data.py` expectations updated to match; (h) CORS restricted to `ALLOWED_ORIGINS` env (default localhost), GZip middleware added for the multi-MB `data.json`, `/healthz` added, `/api/status` moved behind admin auth; (i) XSS hardening: `admin.js` rewritten (escapeHtml + token-gated + event-based handlers instead of inline onclick), `profile.html` escapes all user/DB strings; (j) `main.py` now boots the FastAPI app (single entry point, `--reload` option); (k) Docker: base image bumped to `python:3.12-slim`, `.dockerignore` added, `docker-compose.yml` added; (l) removed `window.__debug` hook; site About text updated to multilingual-e5.
- 2026-07-31: **TODO next session:** (1) re-run `scripts/export_json.py` + `scripts/check_data.py` — current `site/data.json` is stale (DB 6,554 works vs export 6,956; `check_data` reports 5 ERRORs); (2) full test run (`uv run python -m unittest discover tests -v`); (3) API smoke test (register first user → becomes admin, login, exercise admin flows); (4) README + PLAN Phase status refresh; (5) decide free hosting for a shareable link (GitHub Pages static demo is the free option; full app with auth needs a backend host later).
