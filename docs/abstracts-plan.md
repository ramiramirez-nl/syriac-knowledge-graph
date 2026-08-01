# Feeding abstracts into the embeddings

Status: **proposed, not implemented.** This note records what was measured and
what the design has to handle, so the work can start without redoing the
investigation.

## Why titles are the quality ceiling

`compute_analysis.py` embeds a title and nothing else:

```python
model = SentenceTransformer("intfloat/multilingual-e5-small")
matrix = model.encode(["query: " + t for t in titles], normalize_embeddings=True)
```

A Syriac Studies title averages roughly 8–10 words, and a large share of them
are near-generic: *"Ephrem the Syrian"*, *"The Syriac World"*, *"Syriac
Mysticism"*. Two unrelated works can therefore land at cosine ~1.0 simply
because both titles are short and share a proper noun. That single weakness
propagates into everything downstream:

- **Clusters** merge on vocabulary rather than argument. A study of Ephrem's
  *theology* and an edition of Ephrem's *manuscripts* look identical to the model.
- **Collaboration candidates** inherit it directly — author centroids are means
  of work vectors, so the panel still carries the warning that its top pairs may
  be artefacts.
- **Duplicate detection** cannot use the semantic signal at all; the triage
  rules had to fall back on DOI shape, authorship and venue.

An abstract carries ~115 words of actual argument. That is roughly a tenfold
increase in signal per work.

## What the corpus actually offers (measured 2026-08-01)

Sampled 200 random live works against the OpenAlex API:

| | coverage |
|---|---|
| **Overall** | **104/200 = 52%** |
| Books | 21/28 (75%) |
| Articles | 42/71 (59%) |
| Reference entries | 3/6 (50%) |
| Book chapters | 26/68 (38%) |
| Paratext / libguides | 0/7 (0%) |

Mean abstract length: **115 words**.

Two consequences follow, and they drive the whole design:

1. **Abstracts are worth fetching.** Half the corpus gaining ten times more text
   is a large win, and it is concentrated in books and articles — the records
   that matter most.
2. **Coverage is uneven, so a naive merge is harmful.** Book chapters are the
   worst-covered type *and* the most duplicated. If a work with an abstract is
   compared against one without, the two vectors are built from different kinds
   of text, and similarity scores stop being comparable across pairs. Worse, the
   works that keep title-only vectors would cluster with each other purely
   because they are short — a coverage artefact masquerading as a topic.

## Design

### 1. Storage

OpenAlex returns `abstract_inverted_index` (`{word: [positions]}`), not plain
text. Reconstruct once at fetch time and store it, rather than re-deriving it on
every analysis run:

```sql
ALTER TABLE works ADD COLUMN abstract TEXT;
ALTER TABLE works ADD COLUMN abstract_source TEXT;  -- 'openalex' | 'crossref' | 'manual'
```

Add `abstract_inverted_index` to `SELECT_FIELDS` in `fetch_openalex.py`. This is
free — it rides along on requests already being made.

### 2. Two vectors per work, not one

The core decision. Do **not** concatenate title and abstract into one string:
that is exactly what makes scores incomparable between covered and uncovered
works.

Instead embed both fields separately and combine at comparison time:

```
sim(a, b) = w_title · cos(title_a, title_b)
          + w_abstract · cos(abstract_a, abstract_b)   # only when both exist
```

with the weights renormalized per pair. A title-only pair is then scored on the
title axis alone, and its score stays on the same scale as an abstract-backed
pair instead of being silently penalised.

Suggested starting point: `w_title = 0.35`, `w_abstract = 0.65` when both are
present. These belong next to the existing `WEIGHTS` dict so they are tunable.

### 3. Cost

`multilingual-e5-small` truncates at 512 tokens, so a 115-word abstract fits
whole — no chunking needed. Encoding ~3,300 abstracts adds a few minutes to a
run that already takes longer than that for layout. Cache embeddings in a table
keyed by work id + a hash of the text, so re-running after a partial fetch only
encodes what changed.

### 4. Rollout

1. Add the columns and the fetch, run it, and **measure real coverage** on the
   full corpus. The 52% figure is a 200-work sample.
2. Backfill from Crossref for records OpenAlex leaves empty — worth a spike,
   since it is strongest exactly where OpenAlex is weakest (book chapters).
3. Implement dual-vector similarity behind a flag
   (`--use-abstracts`) so the current graph stays reproducible.
4. Compare the two runs before switching: cluster count and size distribution,
   how many collaboration candidates survive, and a manual read of the top 20
   pairs. The success criterion is qualitative — *do the top collaboration
   candidates stop being obvious artefacts?*
5. Update the site caveat text, which currently describes title-only embeddings.

### 5. Watch for

- **Language mixing.** Abstracts appear in English, French, German and Italian.
  `multilingual-e5` handles this, but verify that clusters do not start
  splitting by language rather than topic.
- **Review abstracts.** `is_review_like()` already zeroes review vectors; make
  sure the same masking applies to the abstract vector, or reviews re-enter the
  graph through the new field.
- **Publisher boilerplate.** Some "abstracts" are series blurbs repeated across
  every volume of a set — the exact false-similarity pattern book reviews caused.
  Detect and drop abstracts that repeat verbatim across more than a handful of works.

## Estimate

Roughly a day: schema + fetch (small), dual-vector similarity (moderate),
evaluation and tuning (the real cost).
