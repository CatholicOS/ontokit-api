"""Change event service — track entity modifications from graph diffs."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.models.change_event import ChangeEventType, EntityChangeEvent
from ontokit.schemas.analytics import (
    ActivityDay,
    ChangeEvent,
    ContributorStats,
    EntityHistoryResponse,
    HotEntity,
    ProjectActivity,
    TopEditor,
)

logger = logging.getLogger(__name__)

_TYPE_CHECKS: list[tuple[URIRef, str]] = [
    (OWL.Class, "class"),
    (OWL.ObjectProperty, "property"),
    (OWL.DatatypeProperty, "property"),
    (OWL.AnnotationProperty, "property"),
    (OWL.NamedIndividual, "individual"),
]


def _get_entity_type(graph: Graph, uri: URIRef) -> str:
    for rdf_type, label in _TYPE_CHECKS:
        if (uri, RDF.type, rdf_type) in graph:
            return label
    return "unknown"


def _get_labels(graph: Graph, uri: URIRef) -> list[str]:
    return [str(o) for o in graph.objects(uri, RDFS.label) if isinstance(o, RDFLiteral)]


def _get_parents(graph: Graph, uri: URIRef) -> list[str]:
    return [str(p) for p in graph.objects(uri, RDFS.subClassOf) if isinstance(p, URIRef)]


def _is_deprecated(graph: Graph, uri: URIRef) -> bool:
    return any(str(obj).lower() in ("true", "1") for obj in graph.objects(uri, OWL.deprecated))


def _get_declared_entities(graph: Graph) -> dict[str, str]:
    """Get {iri: entity_type} for all declared entities in graph."""
    entities: dict[str, str] = {}
    for s in graph.subjects(RDF.type, None):
        if not isinstance(s, URIRef) or s == OWL.Thing:
            continue
        etype = _get_entity_type(graph, s)
        if etype != "unknown":
            entities[str(s)] = etype
    return entities


class ChangeEventService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def record_event(
        self,
        project_id: UUID,
        branch: str,
        entity_iri: str,
        entity_type: str,
        event_type: str,
        user_id: str,
        user_name: str | None = None,
        commit_hash: str | None = None,
        changed_fields: list[str] | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
    ) -> EntityChangeEvent:
        event = EntityChangeEvent(
            project_id=project_id,
            branch=branch,
            entity_iri=entity_iri,
            entity_type=entity_type,
            event_type=event_type,
            user_id=user_id,
            user_name=user_name,
            commit_hash=commit_hash,
            changed_fields=changed_fields or [],
            old_values=old_values,
            new_values=new_values,
        )
        self._db.add(event)
        return event

    async def record_events_from_diff(
        self,
        project_id: UUID,
        branch: str,
        old_graph: Graph | None,
        new_graph: Graph,
        user_id: str,
        user_name: str | None,
        commit_hash: str | None,
    ) -> list[EntityChangeEvent]:
        """Compare two RDFLib graphs and generate change events."""
        old_entities = _get_declared_entities(old_graph) if old_graph else {}
        new_entities = _get_declared_entities(new_graph)

        events: list[EntityChangeEvent] = []
        old_iris = set(old_entities.keys())
        new_iris = set(new_entities.keys())

        # Created entities
        for iri in new_iris - old_iris:
            events.append(
                await self.record_event(
                    project_id,
                    branch,
                    iri,
                    new_entities[iri],
                    ChangeEventType.CREATE,
                    user_id,
                    user_name,
                    commit_hash,
                )
            )

        # Deleted entities
        for iri in old_iris - new_iris:
            events.append(
                await self.record_event(
                    project_id,
                    branch,
                    iri,
                    old_entities[iri],
                    ChangeEventType.DELETE,
                    user_id,
                    user_name,
                    commit_hash,
                )
            )

        # Modified entities
        for iri in old_iris & new_iris:
            uri = URIRef(iri)
            etype = new_entities[iri]
            changed_fields: list[str] = []
            old_vals: dict = {}
            new_vals: dict = {}

            # Check labels
            old_labels = _get_labels(old_graph, uri) if old_graph else []
            new_labels = _get_labels(new_graph, uri)
            if sorted(old_labels) != sorted(new_labels):
                changed_fields.append("labels")
                old_vals["labels"] = old_labels
                new_vals["labels"] = new_labels

            # Check parents
            old_parents = _get_parents(old_graph, uri) if old_graph else []
            new_parents = _get_parents(new_graph, uri)
            if sorted(old_parents) != sorted(new_parents):
                changed_fields.append("parents")
                old_vals["parents"] = old_parents
                new_vals["parents"] = new_parents

            # Check deprecated
            old_dep = _is_deprecated(old_graph, uri) if old_graph else False
            new_dep = _is_deprecated(new_graph, uri)
            if old_dep != new_dep:
                changed_fields.append("deprecated")
                old_vals["deprecated"] = old_dep
                new_vals["deprecated"] = new_dep

            # Check comments
            old_comments = (
                [str(o) for o in old_graph.objects(uri, RDFS.comment) if isinstance(o, RDFLiteral)]
                if old_graph
                else []
            )
            new_comments = [
                str(o) for o in new_graph.objects(uri, RDFS.comment) if isinstance(o, RDFLiteral)
            ]
            if sorted(old_comments) != sorted(new_comments):
                changed_fields.append("comments")

            if not changed_fields:
                # Check if any triples changed at all for this entity
                old_triples = set(old_graph.triples((uri, None, None))) if old_graph else set()
                new_triples = set(new_graph.triples((uri, None, None)))
                if old_triples != new_triples:
                    changed_fields.append("other")

            if not changed_fields:
                continue

            # Determine event type
            if "labels" in changed_fields and len(changed_fields) == 1:
                event_type = ChangeEventType.RENAME
            elif "parents" in changed_fields and len(changed_fields) == 1:
                event_type = ChangeEventType.REPARENT
            elif "deprecated" in changed_fields:
                event_type = ChangeEventType.DEPRECATE
            else:
                event_type = ChangeEventType.UPDATE

            events.append(
                await self.record_event(
                    project_id,
                    branch,
                    iri,
                    etype,
                    event_type,
                    user_id,
                    user_name,
                    commit_hash,
                    changed_fields,
                    old_vals or None,
                    new_vals or None,
                )
            )

        if events:
            await self._db.commit()

        return events

    async def get_entity_history(
        self,
        project_id: UUID,
        entity_iri: str,
        branch: str | None = None,
        limit: int = 50,
    ) -> EntityHistoryResponse:
        query = (
            select(EntityChangeEvent)
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.entity_iri == entity_iri,
            )
            .order_by(EntityChangeEvent.created_at.desc())
            .limit(limit)
        )
        if branch:
            query = query.where(EntityChangeEvent.branch == branch)

        result = await self._db.execute(query)
        rows = result.scalars().all()

        events = [
            ChangeEvent(
                id=str(r.id),
                project_id=str(r.project_id),
                branch=r.branch,
                entity_iri=r.entity_iri,
                entity_type=r.entity_type,
                event_type=r.event_type,
                user_id=r.user_id,
                user_name=r.user_name,
                commit_hash=r.commit_hash,
                changed_fields=r.changed_fields or [],
                old_values=r.old_values,
                new_values=r.new_values,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ]

        # Get total count
        count_q = (
            select(func.count())
            .select_from(EntityChangeEvent)
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.entity_iri == entity_iri,
            )
        )
        if branch:
            count_q = count_q.where(EntityChangeEvent.branch == branch)
        total = (await self._db.execute(count_q)).scalar() or 0

        return EntityHistoryResponse(
            entity_iri=entity_iri,
            events=events,
            total=total,
        )

    async def get_activity(self, project_id: UUID, days: int = 30) -> ProjectActivity:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Daily counts
        daily_q = (
            select(
                func.date_trunc("day", EntityChangeEvent.created_at).label("day"),
                func.count().label("cnt"),
            )
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.created_at >= cutoff,
            )
            .group_by("day")
            .order_by("day")
        )
        daily_result = await self._db.execute(daily_q)
        daily_counts = [
            ActivityDay(date=row.day.strftime("%Y-%m-%d"), count=row.cnt) for row in daily_result
        ]

        # Total
        total_q = (
            select(func.count())
            .select_from(EntityChangeEvent)
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.created_at >= cutoff,
            )
        )
        total = (await self._db.execute(total_q)).scalar() or 0

        # Top editors
        editors_q = (
            select(
                EntityChangeEvent.user_id,
                EntityChangeEvent.user_name,
                func.count().label("cnt"),
            )
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.created_at >= cutoff,
            )
            .group_by(EntityChangeEvent.user_id, EntityChangeEvent.user_name)
            .order_by(func.count().desc())
            .limit(10)
        )
        editors_result = await self._db.execute(editors_q)
        top_editors = [
            TopEditor(user_id=row.user_id, user_name=row.user_name or "", edit_count=row.cnt)
            for row in editors_result
        ]

        return ProjectActivity(
            daily_counts=daily_counts,
            total_events=total,
            top_editors=top_editors,
        )

    async def get_hot_entities(self, project_id: UUID, limit: int = 20) -> list[HotEntity]:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=30)

        q = (
            select(
                EntityChangeEvent.entity_iri,
                EntityChangeEvent.entity_type,
                func.count().label("edit_count"),
                func.count(func.distinct(EntityChangeEvent.user_id)).label("editor_count"),
                func.max(EntityChangeEvent.created_at).label("last_edited_at"),
            )
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.created_at >= cutoff,
            )
            .group_by(EntityChangeEvent.entity_iri, EntityChangeEvent.entity_type)
            .order_by(func.count().desc())
            .limit(limit)
        )
        result = await self._db.execute(q)

        return [
            HotEntity(
                entity_iri=row.entity_iri,
                entity_type=row.entity_type,
                label=None,  # Could resolve from graph, but keeping it simple
                edit_count=row.edit_count,
                editor_count=row.editor_count,
                last_edited_at=row.last_edited_at.isoformat(),
            )
            for row in result
        ]

    async def get_contributors(self, project_id: UUID, days: int = 30) -> list[ContributorStats]:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)

        q = (
            select(
                EntityChangeEvent.user_id,
                EntityChangeEvent.user_name,
                func.count().filter(EntityChangeEvent.event_type == "create").label("create_count"),
                func.count()
                .filter(
                    EntityChangeEvent.event_type.in_(["update", "rename", "reparent", "deprecate"])
                )
                .label("update_count"),
                func.count().filter(EntityChangeEvent.event_type == "delete").label("delete_count"),
                func.count().label("total_count"),
                func.max(EntityChangeEvent.created_at).label("last_active_at"),
            )
            .where(
                EntityChangeEvent.project_id == project_id,
                EntityChangeEvent.created_at >= cutoff,
            )
            .group_by(EntityChangeEvent.user_id, EntityChangeEvent.user_name)
            .order_by(func.count().desc())
        )
        result = await self._db.execute(q)

        return [
            ContributorStats(
                user_id=row.user_id,
                user_name=row.user_name or "",
                create_count=row.create_count,
                update_count=row.update_count,
                delete_count=row.delete_count,
                total_count=row.total_count,
                last_active_at=row.last_active_at.isoformat(),
            )
            for row in result
        ]
