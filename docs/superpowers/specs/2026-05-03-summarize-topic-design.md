# `summarize_topic` Tool — Design Spec

- **Status**: approved 2026-05-03 (auto-confirmed via brainstorming Q&A)
- **Target version**: 0.2.0
- **Owner**: istefox
- **Scope**: new read-only MCP tool exposing topic-faceted retrieval
- **Out of scope**: server-side LLM-generated summaries, cross-database joins, persistent caching

---

## 1. Context

Until 0.2.0, `ask_database` is the only retrieval-with-context tool. It returns a flat list of citations with a placeholder `answer` string the client (Claude) is expected to synthesize.

This works for *single-question* prompts ("Quali isolatori abbiamo proposto a Keraglass?") but is awkward for *exploration* prompts ("Cosa abbiamo su Keraglass?", "Panoramica delle bollette 2025"). In the exploration case, the LLM benefits from retrieving more records *organized by dimension* (date, tags, kind, location) rather than a single ranked list. The client can then narrate "X invoices in Q1, Y emails in Q2, Z reports tagged 'review'" without doing the grouping itself.

ADR-0004 originally excluded this tool with the rationale "replicable client-side via `ask_database` + prompt template". The 0.2.0 reconsideration: server-side clustering produces a *structured shape* the client can rely on (sortable, paginate-able, schema-stable), which is genuinely different from a flat citation list. The capability is structural, not just a wrapper.

## 2. Goals

- Return records grouped by user-selected dimensions (default: `date` + `tags`).
- Reuse existing retrieval (vector if RAG enabled, BM25 fallback) — no new infrastructure.
- Bounded output: max 50 records retrieved, max 10 clusters per dimension, max 10 records per cluster (all configurable).
- Stable schema: clients (Claude, scripts) can rely on `clusters[].dimension` / `.label` / `.records`.
- Coexist with `ask_database`: this tool is for exploration ("show me a structured panorama"), not for direct answers.

## 3. Non-goals

- Server-side summarization via LLM. The connector remains a stateless data layer; synthesis stays at the client.
- Cross-database joins. Each retrieval respects the `databases` filter and clusters within the union of returned records.
- Persistent caching. Each call hits the retrieval layer fresh; the existing 5-min cache on `list_databases` is not extended here.
- Multi-pass / multi-query retrieval (Q3 option D rejected — too complex for v1).
- Faceted dimensions beyond the initial four (date / tags / kind / location). Custom dimensions are post-MVP.

## 4. Tool description (for the LLM)

```
summarize_topic — Retrieve and group records related to a topic by dimension
(date, tags, kind, location). Returns a structured panorama for exploration
prompts ("cosa abbiamo su X?", "panoramica delle Y").

When to use:
- The user wants an overview / panorama of a topic across multiple records.
- You need to narrate "X items by date, Y items by tag, Z by kind" without
  grouping the data yourself.
- The expected answer spans multiple records sorted by category, not a
  single synthesized response.

Don't use for:
- Direct questions with one synthesized answer → use `ask_database`.
- Listing candidate documents to drill into → use `search`.
- Finding documents similar to a known one → use `find_related`.

Example:
{"topic": "bollette 2025", "cluster_by": ["date", "tags"]}
→ groups records by year-month (date) and by tag, returns top 10 records
  per cluster, top 10 clusters per dimension.
```

## 5. Input schema

`SummarizeTopicInput` (StrictModel) — added to `libs/schemas/src/istefox_dt_mcp_schemas/tools.py`:

| Field | Type | Default | Constraints |
|---|---|---|---|
| `topic` | `str` | required | min_length=3, max_length=2000 |
| `databases` | `list[str] \| None` | `None` | None = all open DBs |
| `cluster_by` | `list[Literal["date", "tags", "kind", "location"]]` | `["date", "tags"]` | min_items=1, max_items=4. Duplicates deduplicated via Pydantic `field_validator` (preserves first occurrence) |
| `max_records` | `int` | `50` | ge=1, le=200 |
| `max_per_cluster` | `int` | `10` | ge=1, le=50 |
| `max_clusters` | `int` | `10` | ge=1, le=50 |

## 6. Output schema

`Cluster` (StrictModel) and `SummarizeTopicResult`/`SummarizeTopicOutput`:

```python
class Cluster(StrictModel):
    dimension: Literal["date", "tags", "kind", "location"]
    label: str             # e.g. "2026-03", "invoices", "PDF", "/Inbox/Triage"
    count: int             # records in this cluster (post-filter)
    records: list[Citation]  # top max_per_cluster, sorted by relevance


class SummarizeTopicResult(StrictModel):
    topic: str
    clusters: list[Cluster]              # flat list across dimensions
    total_records_retrieved: int          # actual N retrieved (≤ max_records)
    retrieval_mode: Literal["vector", "bm25"]


class SummarizeTopicOutput(Envelope[SummarizeTopicResult]):
    pass
```

`Citation` is reused from the existing schema (uuid + name + snippet + reference_url).

Empty clusters (a dimension that produced zero matches across the retrieved records) are *omitted* from the response — no `count: 0` placeholder.

## 7. Algorithm

```python
async def summarize_topic_op(deps, input) -> SummarizeTopicResult:
    # 1. Retrieve
    if rag_available(deps):
        hits = await deps.rag.query(input.topic, k=input.max_records,
                                     filters=RAGFilter(databases=input.databases))
        retrieval_mode = "vector"
    else:
        hits = await deps.adapter.search(input.topic,
                                          databases=input.databases,
                                          max_results=input.max_records)
        retrieval_mode = "bm25"

    # 2. Hydrate to Records (location, tags, kind, modification_date)
    records = await hydrate_records(deps, hits)

    # 3. Cluster per requested dimension
    clusters: list[Cluster] = []
    for dim in input.cluster_by:
        clusters.extend(
            cluster_records(records, dim,
                             max_clusters=input.max_clusters,
                             max_per_cluster=input.max_per_cluster)
        )

    return SummarizeTopicResult(
        topic=input.topic,
        clusters=clusters,
        total_records_retrieved=len(records),
        retrieval_mode=retrieval_mode,
    )
```

### Clustering rules per dimension

- **`date`** — group by `modification_date` (preferred) or `creation_date` (fallback). Adaptive granularity:
  - if `(max_date - min_date).days > 730` (≈24 months): label = `"YYYY"`
  - else: label = `"YYYY-MM"`
  - Sort clusters reverse-chronologically.
- **`tags`** — explode tags, group by tag string. A record with multiple tags appears in multiple clusters. Sort by record count desc, then alphabetically.
- **`kind`** — group by `RecordKind` enum value (`PDF`, `Markdown`, `Email`, etc.). Sort by record count desc.
- **`location`** — group by `location` path. Use full path as label. Sort by record count desc.

For each dimension, take the top `max_clusters` clusters; within each cluster, take the top `max_per_cluster` records sorted by retrieval score (descending). Records inside a cluster preserve the retrieval order — the more relevant come first.

### Hydration

`hydrate_records(deps, hits)` returns `list[(Record, score)]` with full metadata. Both retrieval modes need full records:

- **Vector hits**: `RAGHit.uuid` is the only stable identifier; tags/kind/modification_date are not part of the embedding payload, so `deps.adapter.get_record(hit.uuid)` is required for every hit.
- **BM25 hits**: `SearchResult` exposes uuid, name, location, reference_url — but NOT tags/kind/modification_date directly. Hydration via `get_record()` is still required.

Both paths therefore produce N `get_record` calls. Mitigations:

- Run hydration in parallel via `asyncio.gather` (bounded by the JXA pool semaphore, default 4-8 concurrent).
- Reuse the existing 60s SQLite cache on `get_record` results (`deps.cache`).
- Skip records where hydration fails; log `summarize_topic_hydration_failed` with uuid+error.

Score retention: vector mode preserves `RAGHit.score` (cosine similarity). BM25 mode synthesizes a rank-based score (`1.0 - i / len(hits)`) so within-cluster ordering remains meaningful even without native scores.

## 8. Error handling

- Empty retrieval (`hits == []`): return `SummarizeTopicResult(topic, clusters=[], total_records_retrieved=0, retrieval_mode=...)`. Envelope `success=True`, `warnings=["no records matched topic"]`. NOT an error.
- Database not found in `databases` filter: existing pattern — adapter raises `DATABASE_NOT_FOUND`, `safe_call` translates to envelope error.
- Hydration failure for individual hit: skip that record, log `summarize_topic_hydration_failed` with uuid + error. Continue with remaining records.
- Unknown dimension in `cluster_by`: caught at Pydantic validation stage (Literal type), returns 400-equivalent before reaching the operation.

## 9. Audit logging

Read tool, follows existing pattern:
- `tool_name = "summarize_topic"`
- `input_data = input.model_dump()` (hashed `topic` only — no PII; databases/cluster_by are config)
- `output_data = {"clusters_returned": len(clusters), "total_retrieved": ...}` (no record bodies, just shape stats)
- No `before_state` / `after_state` (read tool, no undo)

## 10. Test plan

### Unit (no JXA)

In `tests/unit/test_summarize_topic.py` (new file):

1. `test_cluster_by_date_adaptive_year_when_range_exceeds_24_months`
2. `test_cluster_by_date_adaptive_year_month_when_range_within_24_months`
3. `test_cluster_by_tags_explodes_multi_tag_records`
4. `test_cluster_by_kind_groups_by_record_kind`
5. `test_cluster_by_location_groups_by_full_path`
6. `test_max_clusters_truncates_top_n`
7. `test_max_per_cluster_truncates_records`
8. `test_empty_clusters_omitted`
9. `test_multiple_dimensions_produce_flat_list`
10. `test_no_records_retrieved_returns_empty_clusters_with_warning`

### Contract (cassette-based)

In `tests/contract/test_summarize_topic_contract.py`: 1-2 cassettes capturing realistic JXA `search()` + `get_record()` chains for a known topic. Verify the full pipeline output shape matches a snapshot.

### Integration (`-m integration`, requires DT)

In `tests/integration/test_summarize_topic_integration.py`: 1 smoke test that calls the tool against a live DT database and asserts the response envelope is `success=True` with non-empty clusters. Skip-by-default.

## 11. ADR impact

ADR-0004 currently excludes `summarize_topic` with rationale "replicable client-side". This spec supersedes that exclusion for 0.2.0 with the updated rationale "server-side clustering is a structural capability, not a client-replicable wrapper". The PR landing this tool should:

- Add a note to ADR-0004 marking `summarize_topic` as "Reconsidered for 0.2.0 — see this spec".
- No new ADR required (the change is an inclusion within an existing scope discussion, not a new architectural decision).

## 12. Implementation note

- File layout (new):
  - `apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py` (~150 LoC, mirror `ask_database.py` shape)
  - `tests/unit/test_summarize_topic.py` (~200 LoC)
  - Contract + integration tests as outlined above
- Schema additions (in `libs/schemas/src/istefox_dt_mcp_schemas/tools.py`):
  - `SummarizeTopicInput`, `Cluster`, `SummarizeTopicResult`, `SummarizeTopicOutput`
- Registration: add `tool_summarize_topic.register(mcp, deps)` in `apps/server/src/istefox_dt_mcp_server/server.py`
- CHANGELOG `[Unreleased]` entry
- README "What you can ask Claude" section: add example
- Estimated effort: 2-3 sessions (~300 LoC + tests).

## 13. Risks & open questions

- **Risk**: hydration overhead. Each retrieved hit triggers a `get_record` JXA call (cached, but cold cache = N calls). With `max_records=50` and 5s timeout per call, worst case is uncomfortable. Mitigation: parallelize via `asyncio.gather`, leverage existing 60s cache, document that the first call on a cold cache is slower.
- **Risk**: `tags` dimension can explode if a single record has 10+ tags (each record contributes to multiple clusters). Bounded by `max_clusters=10`, but the *count* per cluster may inflate. Mitigation: clusters are sorted by record count desc; top 10 are most informative regardless.
- **Open**: should the response include a warning when `total_records_retrieved == max_records` (likely truncation)? Decision: yes, add `"max_records limit hit, results may be truncated"` to envelope warnings. Locked in §8.
