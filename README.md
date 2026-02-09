# Axigraph API

Collaborative OWL ontology curation API built with FastAPI.

## Features

- **RESTful API** for managing ontologies, classes, properties, and individuals
- **Project management** with public/private visibility and team collaboration
- **Authentication** via Zitadel (OpenID Connect)
- **Real-time collaboration** support via WebSockets
- **Object storage** integration with MinIO for ontology files

## Quick Start

### Full Docker Mode

```bash
# Start all services
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head
```

### Hybrid Mode (API on host)

```bash
# Start infrastructure
docker compose -f compose.prod.yaml up -d

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Configure
cp .env.example .env

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

## Documentation

See the [wiki](https://github.com/your-org/axigraph-api/wiki) for full documentation.

## Tech Stack

- **Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 17 + SQLAlchemy 2.0 (async)
- **Cache**: Redis
- **Object Storage**: MinIO (S3-compatible)
- **Authentication**: Zitadel (OIDC)
- **Ontology Processing**: RDFLib, OWLReady2

## License

MIT
