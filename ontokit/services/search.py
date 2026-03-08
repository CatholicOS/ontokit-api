"""Search service for ontology content."""

import logging
import re
import time

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.processor import SPARQLResult
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.models.project import Project
from ontokit.schemas.search import (
    SearchQuery,
    SearchResponse,
    SearchResult,
    SPARQLBinding,
    SPARQLQuery,
    SPARQLResponse,
)

logger = logging.getLogger(__name__)

# Regex to strip characters that are invalid in a tsquery input.
# PostgreSQL to_tsquery expects word tokens separated by operators; special
# characters such as parentheses, colons, and exclamation marks can cause
# syntax errors if passed through unescaped.
_TSQUERY_INVALID_CHARS = re.compile(r"[^\w\s]", re.UNICODE)


def _sanitize_tsquery_input(raw: str) -> str:
    """Sanitize a raw user search string for use with PostgreSQL to_tsquery.

    Steps:
      1. Strip characters that are not word characters or whitespace.
      2. Collapse multiple spaces and trim.
      3. Join remaining tokens with ' & ' so each word must match.

    Returns an empty string when no usable tokens remain.
    """
    cleaned = _TSQUERY_INVALID_CHARS.sub(" ", raw)
    tokens = cleaned.split()
    if not tokens:
        return ""
    return " & ".join(tokens)


class SearchService:
    """Service for searching ontology content.

    Provides two main capabilities:
      - Full-text search over project names and descriptions using PostgreSQL
        ``tsvector`` / ``tsquery``.
      - SPARQL query execution against an in-memory RDFLib ``Graph``.
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Full-text search
    # ------------------------------------------------------------------

    async def search(self, query: SearchQuery) -> SearchResponse:
        """Execute a full-text search query across projects / ontologies.

        The search targets the ``name`` and ``description`` columns of the
        ``projects`` table using PostgreSQL's built-in full-text search via
        ``to_tsvector`` / ``to_tsquery``.  Inputs are sanitized with
        ``_sanitize_tsquery_input`` before being passed to ``to_tsquery``.
        Results are ranked with ``ts_rank`` and support pagination through
        ``offset`` / ``limit``.

        Only *public* projects are returned (``is_public = True``).  If
        ``ontology_ids`` is provided on the query, results are further
        filtered to the given project IDs.
        """
        start_time = time.perf_counter()

        if self._db is None:
            # No database session available -- return empty results.
            elapsed = (time.perf_counter() - start_time) * 1000
            return SearchResponse(
                results=[],
                total=0,
                query=query.query,
                took_ms=elapsed,
            )

        sanitized = _sanitize_tsquery_input(query.query)
        if not sanitized:
            elapsed = (time.perf_counter() - start_time) * 1000
            return SearchResponse(
                results=[],
                total=0,
                query=query.query,
                took_ms=elapsed,
            )

        # Build the tsvector over name and description, and the tsquery
        # from the user's sanitized input.
        tsvector = func.to_tsvector(
            "english",
            func.coalesce(Project.name, "") + " " + func.coalesce(Project.description, ""),
        )
        tsquery = func.to_tsquery("english", sanitized)

        rank = func.ts_rank(tsvector, tsquery).label("rank")

        # Base filter: public projects that match the query.
        conditions = [
            Project.is_public.is_(True),
            tsvector.op("@@")(tsquery),
        ]

        # Optional: restrict to specific project (ontology) IDs.
        if query.ontology_ids:
            conditions.append(cast(Project.id, String).in_(query.ontology_ids))

        # ----- Count query (total matching rows) -----
        count_stmt = select(func.count()).select_from(Project).where(*conditions)
        count_result = await self._db.execute(count_stmt)
        total: int = count_result.scalar_one()

        # ----- Data query with ranking and pagination -----
        data_stmt = (
            select(Project, rank)
            .where(*conditions)
            .order_by(rank.desc())
            .offset(query.offset)
            .limit(query.limit)
        )
        rows = await self._db.execute(data_stmt)

        results: list[SearchResult] = []
        for project, score in rows:
            # Each project maps to a search result.  Because the current
            # data model stores ontologies as projects (one ontology per
            # project), we use the project's ontology_iri as the IRI and
            # represent the result as a "class" entity type by default.
            results.append(
                SearchResult(
                    iri=project.ontology_iri or f"urn:project:{project.id}",
                    entity_type="class",
                    label=project.name,
                    description=project.description,
                    ontology_id=str(project.id),
                    ontology_title=project.name,
                    score=float(score) if score else 0.0,
                )
            )

        elapsed = (time.perf_counter() - start_time) * 1000

        return SearchResponse(
            results=results,
            total=total,
            query=query.query,
            took_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # SPARQL execution
    # ------------------------------------------------------------------

    async def execute_sparql(
        self,
        query: SPARQLQuery,
        graph: Graph | None = None,
    ) -> SPARQLResponse:
        """Execute a SPARQL query against an RDFLib ``Graph``.

        Parameters
        ----------
        query:
            The validated SPARQL query request.
        graph:
            An optional pre-loaded RDFLib graph.  If ``None``, an empty
            graph is used (useful for testing or when no ontology is loaded).

        Returns
        -------
        SPARQLResponse
            The structured response containing variables / bindings for
            SELECT queries, a boolean for ASK queries, or a serialized
            graph for CONSTRUCT queries.
        """
        start_time = time.perf_counter()

        if graph is None:
            graph = Graph()

        query_text = query.query.strip()

        # Parse the query up front to determine the operation type and
        # validate syntax before execution.
        _SPARQL_TYPE_MAP = {
            "SelectQuery": "SELECT",
            "AskQuery": "ASK",
            "ConstructQuery": "CONSTRUCT",
            "DescribeQuery": "CONSTRUCT",  # RDFLib treats DESCRIBE like CONSTRUCT
        }
        try:
            parsed = parseQuery(query_text)
            query_type = _SPARQL_TYPE_MAP.get(parsed[1].name, "SELECT")
        except Exception as exc:
            logger.warning("SPARQL query parse failed: %s", exc)
            raise ValueError(f"Invalid SPARQL query: {exc}") from exc

        try:
            result: SPARQLResult = graph.query(query_text)
        except Exception as exc:
            logger.warning("SPARQL query execution failed: %s", exc)
            elapsed = (time.perf_counter() - start_time) * 1000
            return SPARQLResponse(
                query_type=query_type,  # type: ignore[arg-type]
                variables=[],
                bindings=[],
                took_ms=elapsed,
            )

        elapsed = (time.perf_counter() - start_time) * 1000

        # ----- SELECT -----
        if query_type == "SELECT":
            variables = [str(v) for v in (result.vars or [])]
            bindings: list[dict[str, SPARQLBinding]] = []

            for row in result:
                binding_row: dict[str, SPARQLBinding] = {}
                for idx, var in enumerate(variables):
                    value = row[idx]
                    if value is None:
                        continue
                    binding_row[var] = _rdf_term_to_binding(value)
                bindings.append(binding_row)

            return SPARQLResponse(
                query_type="SELECT",
                variables=variables,
                bindings=bindings,
                took_ms=elapsed,
            )

        # ----- ASK -----
        if query_type == "ASK":
            boolean_result = (
                bool(result.askAnswer) if hasattr(result, "askAnswer") else bool(result)
            )
            return SPARQLResponse(
                query_type="ASK",
                boolean=boolean_result,
                took_ms=elapsed,
            )

        # ----- CONSTRUCT / DESCRIBE -----
        if query_type == "CONSTRUCT":
            # result.graph contains the constructed graph.
            constructed = (
                result.graph if hasattr(result, "graph") and result.graph is not None else Graph()
            )
            serialized = constructed.serialize(format="turtle")
            return SPARQLResponse(
                query_type="CONSTRUCT",
                graph=serialized,
                took_ms=elapsed,
            )

        # Fallback (should not be reached)
        return SPARQLResponse(
            query_type=query_type,  # type: ignore[arg-type]
            variables=[],
            bindings=[],
            took_ms=elapsed,
        )


# ------------------------------------------------------------------
# Helper utilities
# ------------------------------------------------------------------


def _rdf_term_to_binding(term: URIRef | Literal | BNode) -> SPARQLBinding:
    """Convert an RDFLib term to a ``SPARQLBinding`` schema instance."""
    if isinstance(term, URIRef):
        return SPARQLBinding(type="uri", value=str(term))
    if isinstance(term, Literal):
        return SPARQLBinding(
            type="literal",
            value=str(term),
            datatype=str(term.datatype) if term.datatype else None,
            lang=term.language,
        )
    if isinstance(term, BNode):
        return SPARQLBinding(type="bnode", value=str(term))
    # Unknown term type -- treat as literal.
    return SPARQLBinding(type="literal", value=str(term))


def get_search_service(db: AsyncSession | None = None) -> SearchService:
    """Factory function for dependency injection."""
    return SearchService(db=db)
