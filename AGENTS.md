# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OntoKit API is a collaborative OWL ontology curation platform built with FastAPI (Python 3.11+). It provides a RESTful API for managing ontologies, semantic web knowledge graphs, and team collaboration with git-based version control. Distributed as the `ontokit` package on PyPI.

## Commands

### Development Server
```bash
uvicorn ontokit.main:app --reload
# Or using the installed CLI:
ontokit --reload
```

### Docker Compose (Full Stack)
```bash
docker compose up -d
```

### Linting & Formatting
```bash
ruff check ontokit/ --fix     # Lint with auto-fix
ruff format ontokit/          # Format code
```

### Type Checking
```bash
mypy ontokit/             # authoritative — gates CI & pre-commit
uv run pyright ontokit/   # advisory — non-gating CI job + IDE
```

**mypy is authoritative**: strict mode with the `pydantic.mypy` plugin, run in
pre-commit and the `lint` CI job — it is the only type checker that gates merges.
**pyright is advisory**: a `continue-on-error` CI job (issue #134) and the default
IDE checker. It catches issues mypy misses (possibly-unbound vars, narrowing) but
lacks mypy's plugin coverage (Pydantic field typing), so when they disagree, mypy
wins until pyright is promoted to gating. Pyright only recognizes keyword
defaults — prefer `Field(default=None)` over `Field(None)` in Pydantic schemas.

### Security Scanning

CI runs `semgrep ci` (diff-aware against the PR baseline). For local one-shot
scans you have two options depending on whether you've signed up for Semgrep
Pro:

**With Pro entitlement** — runs the same engine as CI, including taint
analysis and the curated Pro rule pack. Mirrors what CI runs
(`.github/workflows/semgrep.yml`); `.semgrepignore` excludes are honored
automatically.

```bash
semgrep --pro \
  --config p/default \
  --config p/owasp-top-ten \
  --config p/python \
  --config p/fastapi \
  --config p/jwt
```

**Without Pro (community fallback)** — drop `--pro`. You get the same rule
packs but only the OSS engine; some advanced cross-file taint findings won't
surface. Useful for forks and external contributors.

```bash
semgrep \
  --config p/default \
  --config p/owasp-top-ten \
  --config p/python \
  --config p/fastapi \
  --config p/jwt
```

### Testing
```bash
pytest tests/ -v --cov=ontokit                    # Run all tests with coverage
pytest tests/unit/test_health.py -v                 # Run single test file
pytest tests/ -k "test_name" -v                     # Run tests matching pattern
```

### Building & Publishing
```bash
uv build                           # Build sdist + wheel
uv run twine check --strict dist/* # Validate package
uv publish                         # Publish to PyPI
```

### Database Migrations
```bash
alembic upgrade head      # Apply all migrations
alembic downgrade -1      # Rollback one migration
alembic revision --autogenerate -m "description"  # Create new migration
```

### Release Management
```bash
python scripts/prepare-release.py        # Strip -dev suffix, commit
git tag -s ontokit-X.Y.Z               # Tag the release
git push --tags                          # Trigger CI/CD publish
python scripts/set-version.py X.Y.Z     # Set next dev version (adds -dev)
```

## Architecture

### Layer Structure
```
ontokit/
├── api/routes/       # REST endpoints (FastAPI routers)
├── services/         # Business logic layer
├── models/           # SQLAlchemy ORM models
├── schemas/          # Pydantic v2 request/response schemas
├── core/             # Config, database, auth infrastructure
├── git/              # Git repository management
├── collab/           # WebSocket real-time collaboration
├── version.py        # Version management (Weblate-style)
├── runner.py         # CLI entry point
└── worker.py         # ARQ background job queue
```

The URL prefix `/api/v1/` is preserved in `main.py` router registration — the version is a URL concern, not a directory concern.

### Key Services
- **ontology.py** - RDF/OWL graph operations using RDFLib and OWLReady2
- **linter.py** - Ontology validation with 20+ rule checks
- **pull_request_service.py** - Git-based PR workflow with diff generation
- **github_service.py** - GitHub App integration for syncing
- **project_service.py** - Project CRUD and member management

### Git Module (`ontokit/git/`)
The git module uses **pygit2 with bare repositories** for concurrent access:
- **bare_repository.py** - Core implementation using pygit2
  - `BareOntologyRepository` - Direct git object manipulation without working directory
  - `BareGitRepositoryService` - Service layer with backward-compatible API
- **repository.py** - Legacy GitPython implementation (deprecated)
- Bare repos allow multiple users to work on different branches simultaneously
- All file operations work directly on git blobs/trees, no checkout needed

### Technology Stack
- **Database**: PostgreSQL 17 (async via asyncpg + SQLAlchemy 2.0)
- **Cache/Queue**: Redis 7 (ARQ job queue, pub/sub)
- **Storage**: MinIO (S3-compatible object storage)
- **Auth**: Zitadel (OIDC/OAuth2 with JWT validation)
- **RDF**: RDFLib 7.1+ for graph manipulation
- **Git**: pygit2 with bare repositories for concurrent version control

### Key Patterns
- Async-first: All I/O uses async/await
- Dependency injection via FastAPI's `Depends()`
- Pydantic v2 for strict validation with computed fields
- Service singletons obtained via `get_service_name()` dependencies
- UTC timezone-aware datetime fields throughout

## Configuration

Environment variables are configured in `.env` (see `.env.example`). Key sections:
- Database: `DATABASE_URL` (PostgreSQL with asyncpg driver)
- Auth: `ZITADEL_ISSUER`, `ZITADEL_CLIENT_ID`, `ZITADEL_CLIENT_SECRET`
- Storage: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`
- Git: `GIT_REPOS_BASE_PATH` for local repository storage

## Code Quality Settings

From pyproject.toml:
- Line length: 100 characters
- Ruff rules: E, W, F, I, B, C4, UP, ARG, SIM
- MyPy: Strict mode enabled, Python 3.11 target — authoritative, gates CI
- Pyright: standard mode, advisory only (non-gating CI + IDE); see Type Checking

## Scripts

### Git Repository Migration
To migrate existing working-directory repositories to bare repositories:
```bash
python scripts/migrate_to_bare_repos.py --dry-run  # Preview changes
python scripts/migrate_to_bare_repos.py            # Execute migration
python scripts/migrate_to_bare_repos.py --keep-old # Keep old repos after migration
```
