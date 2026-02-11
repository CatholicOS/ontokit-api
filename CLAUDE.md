# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Axigraph API is a collaborative OWL ontology curation platform built with FastAPI (Python 3.11+). It provides a RESTful API for managing ontologies, semantic web knowledge graphs, and team collaboration with git-based version control.

## Commands

### Development Server
```bash
uvicorn app.main:app --reload
```

### Docker Compose (Full Stack)
```bash
docker compose up -d
```

### Linting & Formatting
```bash
ruff check app/ --fix     # Lint with auto-fix
ruff format app/          # Format code
```

### Type Checking
```bash
mypy app/
```

### Testing
```bash
pytest tests/ -v --cov=app                    # Run all tests with coverage
pytest tests/unit/test_health.py -v           # Run single test file
pytest tests/ -k "test_name" -v               # Run tests matching pattern
```

### Database Migrations
```bash
alembic upgrade head      # Apply all migrations
alembic downgrade -1      # Rollback one migration
alembic revision --autogenerate -m "description"  # Create new migration
```

## Architecture

### Layer Structure
```
app/
├── api/v1/           # REST endpoints (FastAPI routers)
├── services/         # Business logic layer
├── models/           # SQLAlchemy ORM models
├── schemas/          # Pydantic v2 request/response schemas
├── core/             # Config, database, auth infrastructure
├── git/              # Git repository management
├── collab/           # WebSocket real-time collaboration
└── worker.py         # ARQ background job queue
```

### Key Services
- **ontology.py** - RDF/OWL graph operations using RDFLib and OWLReady2
- **linter.py** - Ontology validation with 20+ rule checks
- **pull_request_service.py** - Git-based PR workflow with diff generation
- **github_service.py** - GitHub App integration for syncing
- **project_service.py** - Project CRUD and member management

### Technology Stack
- **Database**: PostgreSQL 17 (async via asyncpg + SQLAlchemy 2.0)
- **Cache/Queue**: Redis 7 (ARQ job queue, pub/sub)
- **Storage**: MinIO (S3-compatible object storage)
- **Auth**: Zitadel (OIDC/OAuth2 with JWT validation)
- **RDF**: RDFLib 7.1+ for graph manipulation

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
