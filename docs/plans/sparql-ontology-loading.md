# Feature Plan: Wire SPARQL Endpoint to Project Ontology Graphs

## Problem

The SPARQL endpoint (`POST /api/v1/search/sparql`) always executes queries
against an empty RDFLib `Graph` because the route never loads an ontology.
The `SPARQLQuery` schema already defines `ontology_id` and `default_graph`
fields, but they are unused — every query returns empty results.

## Current State

- **Route** (`ontokit/api/routes/search.py`): calls `service.execute_sparql(query)`
  without passing a graph.
- **Service** (`ontokit/services/search.py`): `execute_sparql()` accepts
  `graph: Graph | None = None` and silently falls back to `Graph()`.
- **Schema** (`ontokit/schemas/search.py`): `SPARQLQuery` has `ontology_id`
  and `default_graph` fields that are never read.

## Proposed Fix

### 1. Update the route handler to load the ontology graph

Follow the established pattern from `quality.py` (`_load_graph`):

```python
@router.post("/sparql", response_model=SPARQLResponse)
async def execute_sparql(
    query: SPARQLQuery,
    service: Annotated[SearchService, Depends(get_search_service)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    branch: str = Query(default=None),
) -> SPARQLResponse:
    # Block UPDATE queries (existing logic)
    ...

    # Require ontology_id
    if not query.ontology_id:
        raise HTTPException(400, detail="ontology_id is required")

    project_id = UUID(query.ontology_id)

    # Load graph (reuse _load_graph pattern from quality.py)
    graph = await _load_graph(project_id, resolved_branch, db)

    return await service.execute_sparql(query, graph=graph)
```

### 2. Add branch resolution

Use the same `git.get_default_branch(project_id)` pattern established in
the embeddings and projects routes:

```python
git = get_git_service()
resolved_branch = branch or git.get_default_branch(project_id)
```

### 3. Add auth and access control

The endpoint currently has no authentication. Add `OptionalUser` or
`RequiredUser` depending on whether public projects should allow
unauthenticated SPARQL queries. Follow the `_verify_access` pattern from
`semantic_search.py`.

### 4. Extract shared `_load_graph` helper

The graph-loading pattern is duplicated across `quality.py` and
`projects.py`. Extract it into a shared utility (e.g.,
`ontokit/api/dependencies.py` or `ontokit/services/ontology.py`) so the
SPARQL route and others can reuse it.

### 5. Keep the empty-graph fallback for tests only

The `execute_sparql` service method should keep accepting `graph: Graph | None`
for unit testing, but the route handler should always pass a loaded graph.

## Files to Modify

| File | Change |
|------|--------|
| `ontokit/api/routes/search.py` | Add db/user/branch deps, load graph, pass to service |
| `ontokit/schemas/search.py` | Make `ontology_id` required (or validate in route) |
| `ontokit/services/search.py` | Optionally raise if graph is None (service-level guard) |
| `ontokit/api/dependencies.py` (new or existing) | Extract shared `_load_graph` helper |

## References

- Existing graph-loading pattern: `ontokit/api/routes/quality.py:_load_graph`
- Branch resolution pattern: `ontokit/api/routes/projects.py:533`
- Access control pattern: `ontokit/api/routes/semantic_search.py:_verify_access`
