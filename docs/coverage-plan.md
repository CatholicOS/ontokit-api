# Test Coverage Plan: 78% → 80%

**Created:** 2026-04-08
**Updated:** 2026-04-08
**Baseline:** 78% (7502/9571 statements covered, 983 tests)
**Target:** 80% (7657 statements covered, ~155 more needed)

## Completed

The following Phase 1 items have been completed:

| File | Before | After | Tests Added |
|------|--------|-------|-------------|
| `services/project_service.py` | 55% | 94% | ~40 |
| `services/suggestion_service.py` | 39% | 96% | ~51 |
| `services/embedding_service.py` | 33% | 99% | ~33 |

## Phase 1 — Remaining (~170 statements recoverable)

| File | Current | Missed | Target | To Recover |
|------|---------|--------|--------|------------|
| `services/pull_request_service.py` | 56% | 305 | 80% | ~170 |

### pull_request_service.py (56% → 80%)
- [ ] `create_pull_request()` — creation with validation
- [ ] `merge_pull_request()` — merge strategies
- [ ] `close_pull_request()`, `reopen_pull_request()`
- [ ] Review CRUD: `create_review()`, `list_reviews()`
- [ ] Comment CRUD: `create_comment()`, `list_comments()`, `update_comment()`, `delete_comment()`
- [ ] Branch management: `list_branches()`, `create_branch()`
- [ ] GitHub integration: `create_github_integration()`, `update_github_integration()`, `delete_github_integration()`
- [ ] Webhook handlers: `handle_github_pr_webhook()`, `handle_github_review_webhook()`, `handle_github_push_webhook()`
- [ ] PR settings: `get_pr_settings()`, `update_pr_settings()`

Covering ~155 of the 305 missed statements reaches 80% overall.

## Phase 2 — Medium Impact (~250 statements)

| File | Current | Missed | Target | To Recover |
|------|---------|--------|--------|------------|
| `git/bare_repository.py` | 70% | 150 | 80% | ~55 |
| `worker.py` | 70% | 111 | 80% | ~40 |
| `services/ontology_extractor.py` | 64% | 93 | 80% | ~45 |
| `services/ontology_index.py` | 75% | 89 | 80% | ~25 |
| `services/github_sync.py` | 61% | 46 | 80% | ~25 |
| `services/indexed_ontology.py` | 44% | 50 | 80% | ~30 |
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

1. `pull_request_service.py` — the only Phase 1 item remaining; ~155 statements gets us to 80%
2. Phase 2 files as needed to build further margin
