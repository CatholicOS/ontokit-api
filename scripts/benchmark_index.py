#!/usr/bin/env python3
"""Benchmark: RDFLib graph queries vs PostgreSQL index queries.

Generates synthetic ontologies of configurable size and compares timing
and memory usage for common operations (root classes, children, search,
class detail, ancestor path).

Usage:
    # Against in-memory RDFLib only (no database required):
    python scripts/benchmark_index.py --sizes 100,1000,5000,10000

    # Against both RDFLib and PostgreSQL index (requires running DB):
    python scripts/benchmark_index.py --sizes 100,1000,5000 --with-db

    # Quick smoke test:
    python scripts/benchmark_index.py --sizes 100
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import logging
import os
import resource
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# Ontology generator
# ──────────────────────────────────────────────────────────

EX = Namespace("http://example.org/ontology#")


def generate_ontology(num_classes: int, branching_factor: int = 5) -> Graph:
    """Generate a synthetic OWL ontology with a class hierarchy.

    Creates a tree of classes with the given branching factor,
    plus labels, comments, annotations, and some properties.
    """
    g = Graph()
    g.bind("ex", EX)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("skos", SKOS)

    # Ontology declaration
    ont_uri = URIRef("http://example.org/ontology")
    g.add((ont_uri, RDF.type, OWL.Ontology))
    g.add((ont_uri, RDFS.label, Literal("Benchmark Ontology", lang="en")))

    classes: list[URIRef] = []
    class_idx = 0

    # Build tree hierarchy
    root_count = min(branching_factor, num_classes)
    queue: list[URIRef | None] = [None] * root_count  # None = root level

    while class_idx < num_classes and queue:
        parent = queue.pop(0)
        cls_uri = EX[f"Class_{class_idx:06d}"]
        classes.append(cls_uri)

        g.add((cls_uri, RDF.type, OWL.Class))
        g.add((cls_uri, RDFS.label, Literal(f"Class {class_idx}", lang="en")))
        g.add((cls_uri, RDFS.label, Literal(f"Classe {class_idx}", lang="it")))
        g.add((cls_uri, RDFS.comment, Literal(f"Description of class {class_idx}", lang="en")))
        g.add((cls_uri, SKOS.prefLabel, Literal(f"Preferred: Class {class_idx}", lang="en")))
        g.add(
            (
                cls_uri,
                SKOS.definition,
                Literal(f"A concept representing entity number {class_idx}"),
            )
        )

        if parent is not None:
            g.add((cls_uri, RDFS.subClassOf, parent))

        # Mark some as deprecated
        if class_idx % 50 == 0 and class_idx > 0:
            g.add((cls_uri, OWL.deprecated, Literal(True)))

        class_idx += 1

        # Add children to queue
        if class_idx < num_classes:
            for _ in range(min(branching_factor, num_classes - class_idx)):
                queue.append(cls_uri)

    # Add some properties
    for i in range(min(20, num_classes // 10)):
        prop_uri = EX[f"property_{i:04d}"]
        g.add((prop_uri, RDF.type, OWL.ObjectProperty))
        g.add((prop_uri, RDFS.label, Literal(f"Property {i}", lang="en")))
        if len(classes) > 1:
            g.add((prop_uri, RDFS.domain, classes[i % len(classes)]))
            g.add((prop_uri, RDFS.range, classes[(i + 1) % len(classes)]))

    # Add some individuals
    for i in range(min(10, num_classes // 20)):
        ind_uri = EX[f"individual_{i:04d}"]
        g.add((ind_uri, RDF.type, OWL.NamedIndividual))
        g.add((ind_uri, RDF.type, classes[i % len(classes)]))
        g.add((ind_uri, RDFS.label, Literal(f"Individual {i}", lang="en")))

    return g


# ──────────────────────────────────────────────────────────
# Measurement utilities
# ──────────────────────────────────────────────────────────


@dataclass
class BenchmarkResult:
    """Result of a single benchmark operation."""

    operation: str
    backend: str
    num_classes: int
    times_ms: list[float] = field(default_factory=list)
    peak_rss_kb: int = 0

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.times_ms) if self.times_ms else 0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times_ms) if self.times_ms else 0

    @property
    def min_ms(self) -> float:
        return min(self.times_ms) if self.times_ms else 0

    @property
    def max_ms(self) -> float:
        return max(self.times_ms) if self.times_ms else 0

    @property
    def stdev_ms(self) -> float:
        return statistics.stdev(self.times_ms) if len(self.times_ms) > 1 else 0


def get_rss_kb() -> int:
    """Get current resident set size in KB.

    Uses /proc/self/status on Linux for accurate current RSS
    (not lifetime peak). Falls back to ru_maxrss if unavailable.
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])  # already in KB
    except (OSError, ValueError, IndexError):
        pass
    # Fallback: ru_maxrss (lifetime peak, KB on Linux, bytes on macOS)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def measure_sync(func: Any, *args: Any, iterations: int = 3) -> tuple[list[float], int]:
    """Measure a sync function's execution time and peak RSS."""
    gc.collect()
    rss_before = get_rss_kb()
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func(*args)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    rss_after = get_rss_kb()
    return times, max(0, rss_after - rss_before)


async def measure_async(func: Any, *args: Any, iterations: int = 3) -> tuple[list[float], int]:
    """Measure an async function's execution time and peak RSS."""
    gc.collect()
    rss_before = get_rss_kb()
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await func(*args)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    rss_after = get_rss_kb()
    return times, max(0, rss_after - rss_before)


# ──────────────────────────────────────────────────────────
# RDFLib benchmarks
# ──────────────────────────────────────────────────────────


async def benchmark_rdflib(num_classes: int, iterations: int = 3) -> list[BenchmarkResult]:
    """Benchmark RDFLib-based ontology operations."""
    from ontokit.services.ontology import OntologyService

    results: list[BenchmarkResult] = []
    project_id = uuid.uuid4()
    branch = "main"
    label_prefs = ["rdfs:label@en", "rdfs:label", "skos:prefLabel@en"]

    # Generate ontology
    print(f"  Generating {num_classes}-class ontology...")
    gen_start = time.perf_counter()
    graph = generate_ontology(num_classes)
    gen_time = (time.perf_counter() - gen_start) * 1000
    triple_count = len(graph)
    print(f"  Generated {triple_count} triples in {gen_time:.1f}ms")

    # Simulate loading (parse from serialized Turtle)
    turtle_data = graph.serialize(format="turtle")
    turtle_bytes = len(turtle_data.encode("utf-8"))

    service = OntologyService()
    service.set_graph(project_id, branch, graph)

    # 1. Parse time
    gc.collect()
    parse_times = []
    for _ in range(iterations):
        g2 = Graph()
        start = time.perf_counter()
        g2.parse(data=turtle_data, format="turtle")
        parse_times.append((time.perf_counter() - start) * 1000)

    r = BenchmarkResult("parse", "rdflib", num_classes, parse_times)
    results.append(r)

    # 2. Get root classes
    times, rss = await measure_async(
        service.get_root_classes,
        project_id,
        label_prefs,
        branch,
        iterations=iterations,
    )
    results.append(BenchmarkResult("root_classes", "rdflib", num_classes, times, rss))

    # 3. Get children (of first root)
    roots = await service.get_root_classes(project_id, label_prefs, branch)
    if roots:
        first_root_iri = str(roots[0].iri)
        times, rss = await measure_async(
            service.get_class_children,
            project_id,
            first_root_iri,
            label_prefs,
            branch,
            iterations=iterations,
        )
        results.append(BenchmarkResult("children", "rdflib", num_classes, times, rss))

    # 4. Get class detail
    if roots:
        times, rss = await measure_async(
            service.get_class,
            project_id,
            first_root_iri,
            label_prefs,
            branch,
            iterations=iterations,
        )
        results.append(BenchmarkResult("class_detail", "rdflib", num_classes, times, rss))

    # 5. Search
    times, rss = await measure_async(
        service.search_entities,
        project_id,
        "Class 1",
        None,
        label_prefs,
        50,
        branch,
        iterations=iterations,
    )
    results.append(BenchmarkResult("search", "rdflib", num_classes, times, rss))

    # 6. Ancestor path (pick a deep class)
    deep_class_iri = f"http://example.org/ontology#Class_{num_classes - 1:06d}"
    times, rss = await measure_async(
        service.get_ancestor_path,
        project_id,
        deep_class_iri,
        label_prefs,
        branch,
        iterations=iterations,
    )
    results.append(BenchmarkResult("ancestor_path", "rdflib", num_classes, times, rss))

    # 7. Class count
    times, rss = await measure_async(
        service.get_class_count,
        project_id,
        branch,
        iterations=iterations,
    )
    results.append(BenchmarkResult("class_count", "rdflib", num_classes, times, rss))

    # Metadata
    results.append(
        BenchmarkResult(
            "turtle_size_kb",
            "rdflib",
            num_classes,
            [turtle_bytes / 1024],
        )
    )
    results.append(
        BenchmarkResult(
            "triple_count",
            "rdflib",
            num_classes,
            [triple_count],
        )
    )

    # Cleanup
    service.unload(project_id)

    return results


# ──────────────────────────────────────────────────────────
# PostgreSQL index benchmarks
# ──────────────────────────────────────────────────────────


async def benchmark_postgres(num_classes: int, iterations: int = 3) -> list[BenchmarkResult]:
    """Benchmark PostgreSQL index-based ontology operations."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    # Import all models to ensure mappers initialize (Project references NormalizationRun)
    import ontokit.models  # noqa: F401
    import ontokit.models.normalization  # noqa: F401
    from ontokit.core.config import settings
    from ontokit.services.ontology_index import OntologyIndexService

    results: list[BenchmarkResult] = []
    project_id = uuid.uuid4()
    branch = "benchmark"
    label_prefs = ["rdfs:label@en", "rdfs:label", "skos:prefLabel@en"]

    # Generate ontology
    print(f"  Generating {num_classes}-class ontology...")
    graph = generate_ontology(num_classes)

    # Connect to database
    engine = create_async_engine(str(settings.database_url), echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from sqlalchemy import text as sa_text

    service: OntologyIndexService | None = None
    try:
        async with session_factory() as db:
            # Create a temporary project row to satisfy FK constraints
            await db.execute(
                sa_text(
                    "INSERT INTO projects (id, name, owner_id, is_public) "
                    "VALUES (:id, :name, :owner, true)"
                ),
                {"id": str(project_id), "name": f"benchmark-{num_classes}", "owner": "benchmark"},
            )
            await db.commit()

            service = OntologyIndexService(db)

            # 1. Full reindex time
            gc.collect()
            reindex_times = []
            for i in range(iterations):
                start = time.perf_counter()
                await service.full_reindex(project_id, branch, graph, f"bench_{i:03d}")
                reindex_times.append((time.perf_counter() - start) * 1000)

            results.append(BenchmarkResult("full_reindex", "postgres", num_classes, reindex_times))

            # 2. Root classes
            times, rss = await measure_async(
                service.get_root_classes,
                project_id,
                branch,
                label_prefs,
                iterations=iterations,
            )
            results.append(BenchmarkResult("root_classes", "postgres", num_classes, times, rss))

            # 3. Children
            roots = await service.get_root_classes(project_id, branch, label_prefs)
            if roots:
                first_root_iri = roots[0]["iri"]
                times, rss = await measure_async(
                    service.get_class_children,
                    project_id,
                    branch,
                    first_root_iri,
                    label_prefs,
                    iterations=iterations,
                )
                results.append(BenchmarkResult("children", "postgres", num_classes, times, rss))

            # 4. Class detail
            if roots:
                times, rss = await measure_async(
                    service.get_class_detail,
                    project_id,
                    branch,
                    first_root_iri,
                    label_prefs,
                    iterations=iterations,
                )
                results.append(BenchmarkResult("class_detail", "postgres", num_classes, times, rss))

            # 5. Search
            times, rss = await measure_async(
                service.search_entities,
                project_id,
                branch,
                "Class 1",
                None,
                label_prefs,
                50,
                iterations=iterations,
            )
            results.append(BenchmarkResult("search", "postgres", num_classes, times, rss))

            # 6. Ancestor path
            deep_class_iri = f"http://example.org/ontology#Class_{num_classes - 1:06d}"
            times, rss = await measure_async(
                service.get_ancestor_path,
                project_id,
                branch,
                deep_class_iri,
                label_prefs,
                iterations=iterations,
            )
            results.append(BenchmarkResult("ancestor_path", "postgres", num_classes, times, rss))

            # 7. Class count
            times, rss = await measure_async(
                service.get_class_count,
                project_id,
                branch,
                iterations=iterations,
            )
            results.append(BenchmarkResult("class_count", "postgres", num_classes, times, rss))

    finally:
        # Always clean up benchmark data and dispose engine
        try:
            async with session_factory() as db:
                cleanup_service = OntologyIndexService(db)
                await cleanup_service.delete_branch_index(project_id, branch)
                await db.execute(
                    sa_text("DELETE FROM projects WHERE id = :id"),
                    {"id": str(project_id)},
                )
                await db.commit()
        except Exception:
            logger.warning("Best-effort benchmark cleanup failed", exc_info=True)
        await engine.dispose()
    return results


# ──────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────


def print_results(all_results: list[BenchmarkResult], sizes: list[int]) -> None:
    """Print formatted comparison table."""
    # Group by operation
    operations = [
        "parse",
        "full_reindex",
        "root_classes",
        "children",
        "class_detail",
        "search",
        "ancestor_path",
        "class_count",
        "turtle_size_kb",
        "triple_count",
    ]

    for size in sizes:
        print(f"\n{'=' * 80}")
        print(f"  Ontology size: {size} classes")
        print(f"{'=' * 80}")

        # Find metadata
        for r in all_results:
            if r.num_classes == size and r.operation == "turtle_size_kb":
                print(f"  Turtle size: {r.mean_ms:.1f} KB")
            if r.num_classes == size and r.operation == "triple_count":
                print(f"  Triple count: {int(r.mean_ms)}")

        print()
        print(
            f"  {'Operation':<20} {'Backend':<10} {'Mean (ms)':>10} "
            f"{'Median':>10} {'Min':>10} {'Max':>10} {'StdDev':>10} "
            f"{'RSS (KB)':>10}"
        )
        print(f"  {'-' * 100}")

        for op in operations:
            if op in ("turtle_size_kb", "triple_count"):
                continue
            matching = [r for r in all_results if r.num_classes == size and r.operation == op]
            for r in sorted(matching, key=lambda x: x.backend):
                print(
                    f"  {r.operation:<20} {r.backend:<10} {r.mean_ms:>10.2f} "
                    f"{r.median_ms:>10.2f} {r.min_ms:>10.2f} {r.max_ms:>10.2f} "
                    f"{r.stdev_ms:>10.2f} {r.peak_rss_kb:>10}"
                )

        # Speedup comparison
        print()
        print(f"  {'Operation':<20} {'RDFLib (ms)':>12} {'Postgres (ms)':>14} {'Speedup':>10}")
        print(f"  {'-' * 60}")
        for op in operations:
            if op in ("parse", "full_reindex", "turtle_size_kb", "triple_count"):
                continue
            rdflib_r = next(
                (
                    r
                    for r in all_results
                    if r.num_classes == size and r.operation == op and r.backend == "rdflib"
                ),
                None,
            )
            pg_r = next(
                (
                    r
                    for r in all_results
                    if r.num_classes == size and r.operation == op and r.backend == "postgres"
                ),
                None,
            )
            if rdflib_r:
                rdflib_ms = f"{rdflib_r.mean_ms:.2f}"
                if pg_r:
                    pg_ms = f"{pg_r.mean_ms:.2f}"
                    speedup = rdflib_r.mean_ms / pg_r.mean_ms if pg_r.mean_ms > 0 else float("inf")
                    print(f"  {op:<20} {rdflib_ms:>12} {pg_ms:>14} {speedup:>9.1f}x")
                else:
                    print(f"  {op:<20} {rdflib_ms:>12} {'N/A':>14} {'--':>10}")


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark RDFLib vs PostgreSQL index queries")
    parser.add_argument(
        "--sizes",
        default="100,500,1000,5000",
        help="Comma-separated ontology sizes (number of classes). Default: 100,500,1000,5000",
    )
    parser.add_argument(
        "--with-db",
        action="store_true",
        help="Also benchmark PostgreSQL index (requires running database)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of iterations per measurement. Default: 3",
    )
    args = parser.parse_args()

    sizes = [int(s.strip()) for s in args.sizes.split(",")]
    all_results: list[BenchmarkResult] = []

    print("OntoKit Ontology Query Benchmark")
    print(f"Backends: RDFLib{' + PostgreSQL' if args.with_db else ''}")
    print(f"Sizes: {sizes}")
    print(f"Iterations: {args.iterations}")
    print()

    for size in sizes:
        print(f"\n--- Benchmarking {size} classes ---")

        print("\n[RDFLib]")
        rdflib_results = await benchmark_rdflib(size, args.iterations)
        all_results.extend(rdflib_results)

        if args.with_db:
            print("\n[PostgreSQL Index]")
            try:
                pg_results = await benchmark_postgres(size, args.iterations)
                all_results.extend(pg_results)
            except Exception as e:
                print(f"  ERROR: {e}")
                print("  Skipping PostgreSQL benchmark (is the database running?)")

    print_results(all_results, sizes)


if __name__ == "__main__":
    asyncio.run(main())
