# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Axigraph API is a collaborative OWL ontology curation platform built with FastAPI (Python 3.11+). It provides a RESTful API for managing ontologies, semantic web knowledge graphs, and team collaboration with git-based version control. Distributed as the `axigraph` package on PyPI.

## Commands

### Development Server
```bash
uvicorn axigraph.main:app --reload
# Or using the installed CLI:
axigraph --reload
```

### Docker Compose (Full Stack)
```bash
docker compose up -d
```

### Linting & Formatting
```bash
ruff check axigraph/ --fix     # Lint with auto-fix
ruff format axigraph/          # Format code
```

### Type Checking
```bash
mypy axigraph/
```

### Testing
```bash
pytest tests/ -v --cov=axigraph                    # Run all tests with coverage
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
git tag -s axigraph-X.Y.Z               # Tag the release
git push --tags                          # Trigger CI/CD publish
python scripts/set-version.py X.Y.Z     # Set next dev version (adds -dev)
```

## Architecture

### Layer Structure
```
axigraph/
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

### Git Module (`axigraph/git/`)
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
- MyPy: Strict mode enabled, Python 3.11 target

## Scripts

### Git Repository Migration
To migrate existing working-directory repositories to bare repositories:
```bash
python scripts/migrate_to_bare_repos.py --dry-run  # Preview changes
python scripts/migrate_to_bare_repos.py            # Execute migration
python scripts/migrate_to_bare_repos.py --keep-old # Keep old repos after migration
```
