# Test Coverage Plan: 72% → 80%

**Created:** 2026-04-08
**Baseline:** 72% (6891/9571 statements covered, 861 tests)
**Target:** 80% (7657 statements covered, ~766 more needed)

## Phase 1 — Highest Impact Services (~550 statements)

| File | Current | Missed | Target | To Recover |
|------|---------|--------|--------|------------|
| `services/pull_request_service.py` | 56% | 305 | 80% | ~170 |
| `services/suggestion_service.py` | 39% | 238 | 80% | ~160 |
| `services/project_service.py` | 55% | 195 | 80% | ~110 |
| `services/embedding_service.py` | 33% | 182 | 80% | ~110 |

### 1. project_service.py (55% → 80%)
- [ ] `create()` — project creation with git repo init
- [ ] `create_from_import()` — file upload import flow
- [ ] `create_from_github()` — GitHub clone flow
- [ ] `list_accessible()` — query with role filtering
- [ ] `get()` — retrieval with membership check
- [ ] `update()` — metadata update with permission check
- [ ] `delete()` — cascading delete
- [ ] `list_members()`, `add_member()`, `update_member()`, `remove_member()`
- [ ] `transfer_ownership()`
- [ ] `get_branch_preference()`, `set_branch_preference()`

### 2. suggestion_service.py (39% → 80%)
- [ ] `save()` — persist changes to suggestion branch
- [ ] `submit()` — submit suggestion as PR
- [ ] `approve()` — approve and merge
- [ ] `reject()` — reject suggestion
- [ ] `request_changes()` — request revision
- [ ] `resubmit()` — resubmit after feedback
- [ ] `beacon_save()` — sendBeacon auto-save
- [ ] `auto_submit_stale_sessions()` — cron auto-submit
- [ ] `discard()` — delete session and branch

### 3. embedding_service.py (33% → 80%)
- [ ] `embed_project()` — full project embedding job
- [ ] `embed_single_entity()` — re-embed one entity
- [ ] `semantic_search()` — similarity search
- [ ] `find_similar()` — find similar entities
- [ ] `rank_suggestions()` — rank candidates
- [ ] Provider initialization and selection logic
- [ ] Edge cases: no provider configured, empty embeddings

### 4. pull_request_service.py (56% → 80%)
- [ ] `create_pull_request()` — creation with validation
- [ ] `merge_pull_request()` — merge strategies
- [ ] `close_pull_request()`, `reopen_pull_request()`
- [ ] Review CRUD: `create_review()`, `list_reviews()`
- [ ] Comment CRUD: `create_comment()`, `list_comments()`, `update_comment()`, `delete_comment()`
- [ ] Branch management: `list_branches()`, `create_branch()`
- [ ] GitHub integration: `create_github_integration()`, `update_github_integration()`, `delete_github_integration()`
- [ ] Webhook handlers: `handle_github_pr_webhook()`, `handle_github_review_webhook()`, `handle_github_push_webhook()`
- [ ] PR settings: `get_pr_settings()`, `update_pr_settings()`

## Phase 2 — Medium Impact (~250 statements)

| File | Current | Missed | Target | To Recover |
|------|---------|--------|--------|------------|
| `git/bare_repository.py` | 70% | 150 | 80% | ~55 |
| `worker.py` | 70% | 111 | 80% | ~40 |
| `services/ontology_extractor.py` | 64% | 93 | 80% | ~45 |
| `services/indexed_ontology.py` | 44% | 50 | 80% | ~30 |
| `services/github_sync.py` | 61% | 46 | 80% | ~25 |
| `services/ontology_index.py` | 75% | 89 | 80% | ~25 |
| `services/normalization_service.py` | 73% | 25 | 80% | ~10 |
| `services/embedding_providers/*` | 0-75% | ~108 | 80% | ~20 |

## Phase 3 — Diminishing Returns

| File | Current | Notes |
|------|---------|-------|
| `main.py` | 54% | Startup/lifespan — hard to unit test |
| `runner.py` | 0% | 6 lines, CLI entry point |
| `services/ontology.py` | 82% | Already above target |
| `services/linter.py` | 80% | Already at target |

## Execution Order

1. `project_service.py` — quickest win, good test scaffolding exists
2. `suggestion_service.py` — large gap, self-contained methods
3. `embedding_service.py` + providers — lowest %, clear mock boundaries
4. `pull_request_service.py` — largest file, most mocking needed
5. Phase 2 files as needed to close remaining gap

Phase 1 alone should reach ~79%. Phase 2 pushes past 80%.
