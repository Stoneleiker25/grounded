"""ORM models.

Design notes worth stating explicitly, because they are the difference between
"the model said it was cited" and "we proved it was cited":

* ``Bullet.claimed_note_id`` is what the LLM asserted. ``Bullet.verified_note_id``
  is what the server was able to prove. They are separate columns on purpose --
  when they disagree we keep both, because the disagreement is itself a signal.
* ``provenance`` is never written from the model's own tag. It is always derived
  by ``verification.verify_bullet``.
* One audit table (``BulletEvent``), not two. Every decision, edit and automatic
  re-classification lands there.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


PROVENANCE = ("cited", "invented")
BULLET_STATUS = ("pending", "accepted", "rejected")
BRIEFING_STATUS = ("draft", "saved")
VERIFICATION_OUTCOME = (
    "verified",            # quote found in the note the model claimed
    "reattributed",        # quote found, but in a different note
    "unverified_quote",    # model gave a quote, it matches nothing
    "no_quote_offered",    # model admitted it was inventing
    "claimed_note_missing",  # model cited a note id outside the briefing's set
)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (CheckConstraint("length(trim(body)) > 0", name="ck_note_body_nonempty"),)


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    # Human-readable explanation when we deliberately produced fewer bullets than
    # asked for -- the "what does good look like when the notes are garbage" answer.
    coverage_note: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime)

    bullets: Mapped[list["Bullet"]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan", order_by="Bullet.position"
    )
    sources: Mapped[list["BriefingNote"]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan"
    )
    contradictions: Mapped[list["Contradiction"]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','saved')", name="ck_briefing_status"
        ),
    )


class BriefingNote(Base):
    """Snapshot of which notes fed a briefing, and their text at generation time.

    Keeping ``body_snapshot`` means reopening an old briefing shows the note as it
    was when the claim was verified, even if the user has since edited the note.
    Without this, citations silently rot.
    """

    __tablename__ = "briefing_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False
    )
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    body_snapshot: Mapped[str] = mapped_column(Text, nullable=False)

    briefing: Mapped[Briefing] = relationship(back_populates="sources")
    note: Mapped[Note] = relationship()

    __table_args__ = (
        UniqueConstraint("briefing_id", "note_id", name="uq_briefing_note"),
        Index("ix_briefing_notes_briefing", "briefing_id"),
    )


class Bullet(Base):
    __tablename__ = "bullets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)

    # --- provenance, decided by the server, never by the model ---
    provenance: Mapped[str] = mapped_column(String(16), nullable=False)
    verification_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    claimed_note_id: Mapped[int | None] = mapped_column(ForeignKey("notes.id", ondelete="SET NULL"))
    verified_note_id: Mapped[int | None] = mapped_column(ForeignKey("notes.id", ondelete="SET NULL"))
    quote: Mapped[str | None] = mapped_column(Text)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    match_score: Mapped[float | None] = mapped_column(Float)

    # --- human decision ---
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("bullets.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    briefing: Mapped[Briefing] = relationship(back_populates="bullets")
    events: Mapped[list["BulletEvent"]] = relationship(
        back_populates="bullet", cascade="all, delete-orphan", order_by="BulletEvent.created_at"
    )

    __table_args__ = (
        CheckConstraint("provenance IN ('cited','invented')", name="ck_bullet_provenance"),
        CheckConstraint(
            "status IN ('pending','accepted','rejected')", name="ck_bullet_status"
        ),
        # The core invariant of the product, enforced by the database itself:
        # a bullet may only be 'cited' if a note was actually proven to contain it.
        CheckConstraint(
            "(provenance = 'invented' AND verified_note_id IS NULL)"
            " OR (provenance = 'cited' AND verified_note_id IS NOT NULL)",
            name="ck_cited_requires_verified_note",
        ),
        Index("ix_bullets_briefing", "briefing_id"),
    )


class BulletEvent(Base):
    """Append-only audit trail. One table, one source of truth."""

    __tablename__ = "bullet_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bullet_id: Mapped[int] = mapped_column(
        ForeignKey("bullets.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    from_text: Mapped[str | None] = mapped_column(Text)
    to_text: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    bullet: Mapped[Bullet] = relationship(back_populates="events")

    __table_args__ = (Index("ix_bullet_events_bullet", "bullet_id"),)


class Contradiction(Base):
    """A detected disagreement between two source notes."""

    __tablename__ = "contradictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False
    )
    note_a_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    note_b_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    value_a: Mapped[str] = mapped_column(String(100), nullable=False)
    value_b: Mapped[str] = mapped_column(String(100), nullable=False)
    excerpt_a: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt_b: Mapped[str] = mapped_column(Text, nullable=False)

    briefing: Mapped[Briefing] = relationship(back_populates="contradictions")

    __table_args__ = (Index("ix_contradictions_briefing", "briefing_id"),)
