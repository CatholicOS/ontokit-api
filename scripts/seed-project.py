#!/usr/bin/env python3
"""
Seed a project by importing an OWL file and building the ontology index.

Bypasses the API (which requires MinIO for imports and Redis for indexing)
by directly creating the git repo, database records, and index.

Usage:
    # Import FOLIO from GitHub and index it
    python scripts/seed-project.py \
        --name "FOLIO" \
        --description "Free Open Legal Information Ontology" \
        --owl-url "https://raw.githubusercontent.com/alea-institute/FOLIO/main/FOLIO.owl" \
        --public

    # Import from a local file
    python scripts/seed-project.py \
        --name "My Ontology" \
        --owl-file /path/to/ontology.owl

    # Index only (project already exists with git repo)
    python scripts/seed-project.py \
        --project-id "db045aca-a6ce-4f1d-b06c-5fbe475c9e08" \
        --index-only

    # Configure upstream sync after import
    python scripts/seed-project.py \
        --name "FOLIO" \
        --owl-url "https://raw.githubusercontent.com/alea-institute/FOLIO/main/FOLIO.owl" \
        --public \
        --upstream-repo "alea-institute/FOLIO" \
        --upstream-branch main \
        --upstream-file "FOLIO.owl"

Environment:
    DATABASE_URL  - PostgreSQL connection string (reads from .env)
    GIT_REPOS_BASE_PATH - Base path for bare git repos (reads from .env)
"""

import argparse
import asyncio
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

from rdflib import Graph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ontokit.core.config import settings
from ontokit.services.ontology_index import OntologyIndexService


async def create_project(
    session: AsyncSession,
    project_id: UUID,
    name: str,
    description: str,
    is_public: bool,
    source_file_path: str,
    owner_id: str = "anonymous",
) -> None:
    """Insert project record into database."""
    await session.execute(
        text("""
            INSERT INTO projects (id, name, description, is_public, owner_id, source_file_path, created_at, updated_at)
            VALUES (:id, :name, :description, :is_public, :owner_id, :source_file_path, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                source_file_path = EXCLUDED.source_file_path,
                updated_at = NOW()
        """),
        {
            "id": str(project_id),
            "name": name,
            "description": description,
            "is_public": is_public,
            "owner_id": owner_id,
            "source_file_path": source_file_path,
        },
    )
    # Add owner as project member
    await session.execute(
        text("""
            INSERT INTO project_members (id, project_id, user_id, role, joined_at)
            VALUES (:id, :project_id, :user_id, 'owner', NOW())
            ON CONFLICT (project_id, user_id) DO NOTHING
        """),
        {"id": str(uuid4()), "project_id": str(project_id), "user_id": owner_id},
    )
    await session.commit()
    print(f"  Project record created: {project_id}")


def create_git_repo(repo_path: Path, owl_content: bytes, filename: str) -> str:
    """Create a bare git repo with the OWL file and return the commit hash."""
    if repo_path.exists():
        # Get existing commit hash
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Git repo already exists at {repo_path}")
            return result.stdout.strip()

    # Create bare repo
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(repo_path)],
        check=True, capture_output=True,
    )

    # Clone to temp, add file, push
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir) / "work"
        subprocess.run(["git", "clone", str(repo_path), str(workdir)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(workdir), "config", "user.email", "ontokit@localhost"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(workdir), "config", "user.name", "OntoKit"], check=True, capture_output=True)

        (workdir / filename).write_bytes(owl_content)
        subprocess.run(["git", "-C", str(workdir), "add", filename], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(workdir), "commit", "-m", f"Import {filename}"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "-C", str(workdir), "push", "origin", "main"], check=True, capture_output=True)

    # Get commit hash
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    commit_hash = result.stdout.strip()
    print(f"  Git repo created: {repo_path}")
    print(f"  Commit: {commit_hash}")
    return commit_hash


async def build_index(
    session: AsyncSession,
    project_id: UUID,
    branch: str,
    owl_content: bytes,
    commit_hash: str,
    owl_format: str = "xml",
) -> int:
    """Parse OWL file and build PostgreSQL ontology index."""
    print(f"  Parsing OWL file ({len(owl_content)} bytes)...")
    graph = Graph()
    graph.parse(data=owl_content, format=owl_format)
    print(f"  Graph loaded: {len(graph)} triples")

    service = OntologyIndexService(session)
    print(f"  Building index...")
    count = await service.full_reindex(project_id, branch, graph, commit_hash)
    await session.commit()
    print(f"  Indexed {count} entities")
    return count


async def configure_upstream_sync(
    session: AsyncSession,
    project_id: UUID,
    repo_owner: str,
    repo_name: str,
    branch: str,
    file_path: str,
) -> None:
    """Configure upstream sync to track a GitHub repository."""
    await session.execute(
        text("""
            INSERT INTO upstream_sync_configs (id, project_id, repo_owner, repo_name, branch, file_path, frequency, update_mode, enabled, status, created_at, updated_at)
            VALUES (:id, :project_id, :repo_owner, :repo_name, :branch, :file_path, 'manual', 'auto_apply', true, 'idle', NOW(), NOW())
            ON CONFLICT (project_id) DO UPDATE SET
                repo_owner = EXCLUDED.repo_owner,
                repo_name = EXCLUDED.repo_name,
                branch = EXCLUDED.branch,
                file_path = EXCLUDED.file_path,
                updated_at = NOW()
        """),
        {
            "id": str(uuid4()),
            "project_id": str(project_id),
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch": branch,
            "file_path": file_path,
        },
    )
    await session.commit()
    print(f"  Upstream sync configured: {repo_owner}/{repo_name} ({branch}:{file_path})")


async def main():
    parser = argparse.ArgumentParser(description="Seed a project with an OWL file and build its index")
    parser.add_argument("--name", help="Project name")
    parser.add_argument("--description", default="", help="Project description")
    parser.add_argument("--owl-url", help="URL to download OWL file from")
    parser.add_argument("--owl-file", help="Local path to OWL file")
    parser.add_argument("--owl-format", default="xml", help="RDFLib format (xml, turtle, n3, json-ld)")
    parser.add_argument("--public", action="store_true", help="Make project public")
    parser.add_argument("--project-id", help="Use a specific project UUID (default: auto-generate)")
    parser.add_argument("--index-only", action="store_true", help="Only rebuild the index (project must exist)")
    parser.add_argument("--skip-index", action="store_true", help="Skip index building")
    parser.add_argument("--upstream-repo", help="GitHub repo for upstream sync (owner/name format)")
    parser.add_argument("--upstream-branch", default="main", help="Upstream branch to track")
    parser.add_argument("--upstream-file", help="File path in upstream repo")
    args = parser.parse_args()

    # Validate args
    if not args.index_only and not args.name:
        parser.error("--name is required unless --index-only is set")
    if not args.index_only and not args.owl_url and not args.owl_file:
        parser.error("--owl-url or --owl-file is required unless --index-only is set")

    project_id = UUID(args.project_id) if args.project_id else uuid4()
    repos_base = Path(settings.git_repos_base_path)
    repo_path = repos_base / f"{project_id}.git"

    # Download or read OWL file
    owl_content = None
    if args.owl_url:
        print(f"Downloading {args.owl_url}...")
        with urllib.request.urlopen(args.owl_url) as response:
            owl_content = response.read()
        print(f"  Downloaded {len(owl_content)} bytes")
    elif args.owl_file:
        owl_content = Path(args.owl_file).read_bytes()
        print(f"  Read {len(owl_content)} bytes from {args.owl_file}")

    # Determine filename
    if args.owl_url:
        filename = args.owl_url.split("/")[-1]
    elif args.owl_file:
        filename = Path(args.owl_file).name
    else:
        filename = "ontology.owl"

    engine = create_async_engine(str(settings.database_url))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        if args.index_only:
            # Index-only mode: read OWL from existing git repo
            print(f"Index-only mode for project {project_id}")
            result = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            )
            commit_hash = result.stdout.strip()

            # Find the OWL file in the repo
            result = subprocess.run(
                ["git", "-C", str(repo_path), "ls-tree", "--name-only", "HEAD"],
                capture_output=True, text=True, check=True,
            )
            files = result.stdout.strip().split("\n")
            owl_files = [f for f in files if f.endswith((".owl", ".ttl", ".rdf", ".n3"))]
            if not owl_files:
                print(f"ERROR: No OWL/TTL/RDF files found in repo")
                sys.exit(1)
            filename = owl_files[0]

            result = subprocess.run(
                ["git", "-C", str(repo_path), "show", f"HEAD:{filename}"],
                capture_output=True, check=True,
            )
            owl_content = result.stdout

            fmt = "xml" if filename.endswith((".owl", ".rdf")) else "turtle" if filename.endswith(".ttl") else "n3"
            await build_index(session, project_id, "main", owl_content, commit_hash, fmt)
        else:
            # Full seed: create project, git repo, index
            print(f"Seeding project: {args.name} ({project_id})")

            # 1. Create project record
            await create_project(session, project_id, args.name, args.description, args.public, filename)

            # 2. Create git repo with OWL file
            commit_hash = create_git_repo(repo_path, owl_content, filename)

            # 3. Build index
            if not args.skip_index:
                await build_index(session, project_id, "main", owl_content, commit_hash, args.owl_format)

            # 4. Configure upstream sync
            if args.upstream_repo:
                parts = args.upstream_repo.split("/")
                if len(parts) != 2:
                    print(f"ERROR: --upstream-repo must be 'owner/name' format, got '{args.upstream_repo}'")
                else:
                    await configure_upstream_sync(
                        session, project_id,
                        repo_owner=parts[0],
                        repo_name=parts[1],
                        branch=args.upstream_branch,
                        file_path=args.upstream_file or filename,
                    )

    await engine.dispose()
    print(f"\nDone! Project ID: {project_id}")


if __name__ == "__main__":
    asyncio.run(main())
