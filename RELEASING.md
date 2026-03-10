# Development, Release & Deploy Lifecycle

This document describes the full lifecycle of the OntoKit API from local development through release and deployment.

## Version Management

Version is managed in a single source of truth: `ontokit/version.py`.

```python
VERSION = "0.2.0-dev"          # current working version
VERSION_BASE = "0.2.0"         # stripped for PyPI / __version__
TAG_NAME = "ontokit-0.2.0"    # corresponding git tag
```

- During development the version carries a `-dev` suffix (e.g. `0.2.0-dev`).
- At release time the suffix is stripped (e.g. `0.2.0`).
- `pyproject.toml` reads the version dynamically via hatch, so there is nothing else to keep in sync.

## Development

### Local setup

```bash
cd ontokit-api
uv sync --dev              # install all dependencies into .venv
source .venv/bin/activate
```

### Running the server

```bash
# Either:
uvicorn ontokit.main:app --reload

# Or via the installed CLI entry point:
ontokit --reload
```

### Running with Docker Compose

```bash
docker compose up -d                          # start all services
docker compose exec api alembic upgrade head  # apply migrations
```

The development `Dockerfile` mounts source code as a read-only volume and enables hot reload.

### Code quality

```bash
ruff check ontokit/ --fix     # lint with auto-fix
ruff format ontokit/          # format code
mypy ontokit/                 # type checking (strict mode)
pytest tests/ -v --cov=ontokit  # run tests with coverage
```

### Database migrations

```bash
alembic upgrade head                              # apply all pending migrations
alembic downgrade -1                              # rollback one migration
alembic revision --autogenerate -m "description"  # generate a new migration
```

## Continuous Integration

The GitHub Actions workflow (`.github/workflows/release.yml`) runs on every push and on pull requests that touch `ontokit-api/`.

| Job | What it does |
|-----|--------------|
| **lint** | `ruff check`, `ruff format --check`, `mypy` |
| **test** | `pytest` with coverage |
| **build** | `uv build` + `twine check --strict` on the resulting sdist/wheel |

These three jobs run on all pushes (except `renovate/**` branches) and on PRs. The publish jobs described in the next section only run when a release tag is pushed.

## Releasing

Releases follow a Weblate-inspired workflow. All commands below are run from the `ontokit-api/` directory.

### 1. Prepare the release

```bash
python scripts/prepare-release.py
```

This script:
1. Reads the current version from `ontokit/version.py` (e.g. `0.2.0-dev`).
2. Strips the `-dev` suffix to produce the release version (`0.2.0`).
3. Writes the updated version back to `ontokit/version.py`.
4. Creates a git commit: `chore: releasing 0.2.0`.

### 2. Tag the release

```bash
git tag -s ontokit-0.2.0
```

Tags must match the pattern `ontokit-*` to trigger the publish pipeline.

### 3. Push

```bash
git push && git push --tags
```

### 4. CI publishes automatically

When the tag reaches GitHub, the CI workflow runs the lint/test/build jobs and then three publish jobs in parallel:

- **publish_pypi** &mdash; Uploads the wheel and sdist to PyPI using trusted publishing (`uv publish --trusted-publishing always`). Requires `id-token: write` permission for OIDC-based authentication.
- **publish_github** &mdash; Creates a GitHub Release with auto-generated release notes and attaches the build artifacts.
- **publish_docker** &mdash; Builds the production Docker image (`Dockerfile.prod`) and pushes it to the GitHub Container Registry. The image is tagged with the release version, the major.minor version, and `latest`. For example, the tag `ontokit-0.2.0` produces:
  - `ghcr.io/<owner>/ontokit:0.2.0`
  - `ghcr.io/<owner>/ontokit:0.2`
  - `ghcr.io/<owner>/ontokit:latest`

### 5. Set the next development version

```bash
python scripts/set-version.py 0.3.0
```

This script:
1. Updates `ontokit/version.py` to `0.3.0-dev`.
2. Creates a git commit: `chore: setting version to 0.3.0-dev`.

Push the commit to start the next development cycle.

### Quick reference

```
                                                             ┌─ PyPI (sdist + wheel)
0.2.0-dev ──prepare-release.py──▸ 0.2.0 ──tag & push──▸ CI ─┼─ GitHub Release
                                                             └─ GHCR (Docker image)
                                                    │
                                  set-version.py 0.3.0
                                          │
                                      0.3.0-dev  (next cycle)
```

## Patch releases

Patch releases are for **backporting critical bug fixes** to an older release line after `main` has already moved to the next development version. New features always ship in the next minor or major release on `main`.

For example, if `main` is at `0.3.0-dev` but a bug is found in `0.2.0`:

### 1. Create a release branch from the tag

```bash
git checkout -b release/0.2.x ontokit-0.2.0
```

### 2. Cherry-pick the fix

```bash
git cherry-pick <commit-sha>    # the fix from main
```

### 3. Bump to the patch version

Edit `ontokit/version.py` to set `VERSION = "0.2.1"`, then commit:

```bash
git add ontokit/version.py
git commit -m "chore: releasing 0.2.1"
```

### 4. Tag and push

```bash
git tag -s ontokit-0.2.1
git push -u origin release/0.2.x && git push --tags
```

CI will run the lint/test/build checks and publish to PyPI, GitHub Releases, and GHCR as usual. The `release/0.2.x` branch can be kept for future patches on the same line.

> **Note:** The `latest` Docker tag will point to the patch release. If the latest minor/major release should remain `latest`, manually retag after publishing.

## Deployment

There are three ways to deploy the OntoKit API, depending on your needs.

### From PyPI

Install the published package and run via the CLI entry point:

```bash
pip install ontokit        # or: uv pip install ontokit
ontokit                    # starts uvicorn on 0.0.0.0:8000
```

### From GHCR (Docker image)

Pull the pre-built production image published by CI:

```bash
# latest release
docker pull ghcr.io/<owner>/ontokit:latest

# specific version
docker pull ghcr.io/<owner>/ontokit:0.2.0
```

Run it directly:

```bash
docker run -d \
  --name ontokit-api \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://... \
  -e REDIS_URL=redis://redis:6379/0 \
  ghcr.io/<owner>/ontokit:0.2.0
```

Or reference it in a compose file instead of building locally:

```yaml
services:
  api:
    image: ghcr.io/<owner>/ontokit:0.2.0
    # ...
```

### Local Docker build

Build the production image from source and run with compose:

```bash
docker compose -f compose.prod.yaml up -d
```

### Development vs production images

| | Development (`Dockerfile`) | Production (`Dockerfile.prod`) |
|---|---|---|
| System deps | git, curl, libgit2-dev | curl only |
| Git repos dir | `/data/repos` (created + chown) | not created |
| Source mount | read-only bind mount | baked into image |
| uvicorn | `--reload` | `--workers 4` |

### Post-deploy checklist

1. **Run migrations** &mdash; `alembic upgrade head` inside the container.
2. **Health check** &mdash; `GET /health` returns `{"status": "healthy"}`.
3. **Verify version** &mdash; `GET /` returns the deployed version string.

### Environment variables

The API requires the following environment variables (see `.env.example` for defaults):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection string |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Object storage |
| `ZITADEL_ISSUER`, `ZITADEL_CLIENT_ID`, `ZITADEL_CLIENT_SECRET` | OIDC auth |
| `GIT_REPOS_BASE_PATH` | Path for bare git repositories (default `/data/repos`) |
| `GITHUB_TOKEN_ENCRYPTION_KEY` | Encryption key for stored GitHub PATs |
| `SUPERADMIN_USER_IDS` | Comma-separated Zitadel user IDs with full access |
