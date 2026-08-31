"""Pydantic request/response models — the API contract."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1)


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    body: str
    created_at: datetime


class BulletEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    from_status: str | None
    to_status: str | None
    from_text: str | None
    to_text: str | None
    detail: str | None
    created_at: datetime


class CitationOut(BaseModel):
    note_id: int
    note_title: str
    quote: str
    quote_start: int | None
    quote_end: int | None
    match_score: float | None
    context_before: str
    context_after: str


class BulletOut(BaseModel):
    id: int
    position: int
    text: str
    original_text: str
    edited: bool
    provenance: str
    verification_outcome: str
    verification_detail: str | None
    status: str
    claimed_note_id: int | None
    duplicate_of_id: int | None
    citation: CitationOut | None
    diff: list[dict] | None


class ContradictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    note_a_id: int
    note_b_id: int
    subject: str
    value_a: str
    value_b: str
    excerpt_a: str
    excerpt_b: str


class BriefingSourceOut(BaseModel):
    note_id: int
    title: str
    body: str


class BriefingOut(BaseModel):
    id: int
    title: str
    status: str
    coverage_note: str | None
    model_name: str | None
    created_at: datetime
    saved_at: datetime | None
    stats: dict
    bullets: list[BulletOut]
    sources: list[BriefingSourceOut]
    contradictions: list[ContradictionOut]


class BriefingSummary(BaseModel):
    id: int
    title: str
    status: str
    created_at: datetime
    saved_at: datetime | None
    stats: dict


class GenerateIn(BaseModel):
    note_ids: list[int] | None = None


class BulletEditIn(BaseModel):
    text: str = Field(min_length=1)


class BulletStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|accepted|rejected)$")


class SaveBriefingIn(BaseModel):
    title: str | None = None
