"""Pydantic schemas for analytics (change events, activity, contributors)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ChangeEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    branch: str
    entity_iri: str
    entity_type: str
    event_type: Literal["create", "update", "delete", "rename", "reparent", "deprecate"]
    user_id: str
    user_name: str | None = None
    commit_hash: str | None = None
    changed_fields: list[str] = []
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    created_at: str


class EntityHistoryResponse(BaseModel):
    entity_iri: str
    events: list[ChangeEvent]
    total: int


class ActivityDay(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class TopEditor(BaseModel):
    user_id: str
    user_name: str
    edit_count: int


class ProjectActivity(BaseModel):
    daily_counts: list[ActivityDay]
    total_events: int
    top_editors: list[TopEditor]


class HotEntity(BaseModel):
    entity_iri: str
    entity_type: str
    label: str | None = None
    edit_count: int
    editor_count: int
    last_edited_at: str


class ContributorStats(BaseModel):
    user_id: str
    user_name: str
    create_count: int
    update_count: int
    delete_count: int
    total_count: int
    last_active_at: str
