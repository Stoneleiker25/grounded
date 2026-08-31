"""FastAPI application. JSON only — the frontend is a separate static app."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from . import analysis, schemas
from .config import settings
from .database import get_session, init_db
from .models import Briefing, BriefingNote, Bullet, BulletEvent, Note, utcnow
from .pipeline import GenerationError, generate_briefing, generation_stats

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Grounded API", version="1.0.0", lifespan=lifespan)

# Any loopback origin is allowed, on any port. This is a single-user app whose API
# binds to 127.0.0.1, so the browser's origin check is not the security boundary --
# the bind address is. Pinning to one port instead would silently break the app the
# moment someone runs it on a different one (e.g. because 5173 was taken), which is
# a much more likely failure than a hostile page on the user's own loopback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ serializers

CONTEXT_CHARS = 90


def _bullet_out(bullet: Bullet, sources: dict[int, BriefingNote]) -> schemas.BulletOut:
    citation = None
    if bullet.provenance == "cited" and bullet.verified_note_id in sources:
        src = sources[bullet.verified_note_id]
        body = src.body_snapshot
        start = bullet.quote_start if bullet.quote_start is not None else 0
        end = bullet.quote_end if bullet.quote_end is not None else 0
        citation = schemas.CitationOut(
            note_id=src.note_id,
            note_title=src.title_snapshot,
            quote=body[start:end] if end > start else (bullet.quote or ""),
            quote_start=bullet.quote_start,
            quote_end=bullet.quote_end,
            match_score=bullet.match_score,
            context_before=body[max(0, start - CONTEXT_CHARS):start],
            context_after=body[end:end + CONTEXT_CHARS],
        )

    detail = None
    for ev in bullet.events:
        if ev.action == "generated":
            detail = ev.detail
            break

    edited = bullet.text.strip() != bullet.original_text.strip()
    return schemas.BulletOut(
        id=bullet.id,
        position=bullet.position,
        text=bullet.text,
        original_text=bullet.original_text,
        edited=edited,
        provenance=bullet.provenance,
        verification_outcome=bullet.verification_outcome,
        verification_detail=detail,
        status=bullet.status,
        claimed_note_id=bullet.claimed_note_id,
        duplicate_of_id=bullet.duplicate_of_id,
        citation=citation,
        diff=analysis.word_diff(bullet.original_text, bullet.text) if edited else None,
    )


def _briefing_out(briefing: Briefing) -> schemas.BriefingOut:
    sources = {s.note_id: s for s in briefing.sources}
    return schemas.BriefingOut(
        id=briefing.id,
        title=briefing.title,
        status=briefing.status,
        coverage_note=briefing.coverage_note,
        model_name=briefing.model_name,
        created_at=briefing.created_at,
        saved_at=briefing.saved_at,
        stats=generation_stats(briefing),
        bullets=[_bullet_out(b, sources) for b in briefing.bullets],
        sources=[
            schemas.BriefingSourceOut(
                note_id=s.note_id, title=s.title_snapshot, body=s.body_snapshot
            )
            for s in briefing.sources
        ],
        contradictions=[schemas.ContradictionOut.model_validate(c) for c in briefing.contradictions],
    )


def _get_briefing(session: Session, briefing_id: int) -> Briefing:
    briefing = session.get(Briefing, briefing_id)
    if briefing is None:
        raise HTTPException(404, "Briefing not found")
    return briefing


def _get_bullet(session: Session, bullet_id: int) -> Bullet:
    bullet = session.get(Bullet, bullet_id)
    if bullet is None:
        raise HTTPException(404, "Bullet not found")
    if bullet.briefing.status == "saved":
        raise HTTPException(409, "This briefing is saved and can no longer be edited.")
    return bullet


# ------------------------------------------------------------------------ notes


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "provider": settings.llm_provider}


@app.get("/api/notes", response_model=list[schemas.NoteOut])
def list_notes(session: Session = Depends(get_session)):
    return (
        session.query(Note)
        .filter(Note.deleted_at.is_(None))
        .order_by(Note.created_at.desc())
        .all()
    )


@app.post("/api/notes", response_model=schemas.NoteOut, status_code=201)
def create_note(payload: schemas.NoteIn, session: Session = Depends(get_session)):
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, "Note body cannot be empty.")
    title = (payload.title or "").strip() or _derive_title(body)
    note = Note(title=title, body=body)
    session.add(note)
    session.flush()
    return note


def _derive_title(body: str) -> str:
    first = body.strip().splitlines()[0].strip()
    return (first[:60] + "…") if len(first) > 60 else (first or "Untitled note")


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int, session: Session = Depends(get_session)):
    """Soft delete. The note leaves the workspace but stays readable by any briefing
    that already cited it -- see the comment on Note.deleted_at."""
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise HTTPException(404, "Note not found")
    note.deleted_at = utcnow()


@app.get("/api/notes/search", response_model=list[schemas.NoteOut])
def search_notes(q: str = Query(min_length=1), session: Session = Depends(get_session)):
    """Full-text search over notes, using the FTS5 index."""
    safe = " ".join(f'"{tok}"' for tok in q.replace('"', " ").split() if tok)
    if not safe:
        return []
    rows = session.execute(
        sql_text(
            "SELECT n.id FROM notes_fts f JOIN notes n ON n.id = f.rowid "
            "WHERE notes_fts MATCH :q ORDER BY rank LIMIT 50"
        ),
        {"q": safe},
    ).scalars().all()
    if not rows:
        return []
    notes = (
        session.query(Note)
        .filter(Note.id.in_(rows), Note.deleted_at.is_(None))
        .all()
    )
    order = {nid: i for i, nid in enumerate(rows)}
    return sorted(notes, key=lambda n: order[n.id])


# -------------------------------------------------------------------- briefings


@app.post("/api/briefings/generate", response_model=schemas.BriefingOut, status_code=201)
def generate(payload: schemas.GenerateIn, session: Session = Depends(get_session)):
    try:
        briefing = generate_briefing(session, payload.note_ids)
    except GenerationError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.flush()
    session.refresh(briefing)
    return _briefing_out(briefing)


@app.get("/api/briefings", response_model=list[schemas.BriefingSummary])
def list_briefings(session: Session = Depends(get_session)):
    briefings = session.query(Briefing).order_by(Briefing.created_at.desc()).all()
    return [
        schemas.BriefingSummary(
            id=b.id, title=b.title, status=b.status,
            created_at=b.created_at, saved_at=b.saved_at,
            note_count=len(b.sources), stats=generation_stats(b),
        )
        for b in briefings
    ]


@app.get("/api/briefings/{briefing_id}", response_model=schemas.BriefingOut)
def get_briefing(briefing_id: int, session: Session = Depends(get_session)):
    return _briefing_out(_get_briefing(session, briefing_id))


@app.post("/api/briefings/{briefing_id}/save", response_model=schemas.BriefingOut)
def save_briefing(
    briefing_id: int, payload: schemas.SaveBriefingIn, session: Session = Depends(get_session)
):
    briefing = _get_briefing(session, briefing_id)
    if briefing.status == "saved":
        raise HTTPException(409, "Briefing is already saved.")
    if payload.title and payload.title.strip():
        briefing.title = payload.title.strip()
    briefing.status = "saved"
    briefing.saved_at = utcnow()
    session.flush()
    session.refresh(briefing)
    return _briefing_out(briefing)


@app.get("/api/briefings/{briefing_id}/audit", response_model=list[schemas.BulletEventOut])
def briefing_audit(briefing_id: int, session: Session = Depends(get_session)):
    briefing = _get_briefing(session, briefing_id)
    ids = [b.id for b in briefing.bullets]
    if not ids:
        return []
    return (
        session.query(BulletEvent)
        .filter(BulletEvent.bullet_id.in_(ids))
        .order_by(BulletEvent.created_at.desc(), BulletEvent.id.desc())
        .all()
    )


# ---------------------------------------------------------------------- bullets


@app.patch("/api/bullets/{bullet_id}/status", response_model=schemas.BulletOut)
def set_bullet_status(
    bullet_id: int, payload: schemas.BulletStatusIn, session: Session = Depends(get_session)
):
    bullet = _get_bullet(session, bullet_id)
    previous = bullet.status
    if previous != payload.status:
        bullet.status = payload.status
        session.add(BulletEvent(
            bullet_id=bullet.id, action=f"marked_{payload.status}",
            from_status=previous, to_status=payload.status,
        ))
        session.flush()
    session.refresh(bullet)
    sources = {s.note_id: s for s in bullet.briefing.sources}
    return _bullet_out(bullet, sources)


@app.patch("/api/bullets/{bullet_id}", response_model=schemas.BulletOut)
def edit_bullet(
    bullet_id: int, payload: schemas.BulletEditIn, session: Session = Depends(get_session)
):
    bullet = _get_bullet(session, bullet_id)
    new_text = payload.text.strip()
    if not new_text:
        raise HTTPException(422, "Bullet text cannot be empty.")

    if new_text != bullet.text:
        before = bullet.text
        bullet.text = new_text
        session.add(BulletEvent(
            bullet_id=bullet.id, action="edited",
            from_text=before, to_text=new_text,
            detail="Human edit. Citation left attached to the original quote span.",
        ))
        session.flush()
    session.refresh(bullet)
    sources = {s.note_id: s for s in bullet.briefing.sources}
    return _bullet_out(bullet, sources)


@app.get("/api/bullets/{bullet_id}/events", response_model=list[schemas.BulletEventOut])
def bullet_events(bullet_id: int, session: Session = Depends(get_session)):
    bullet = session.get(Bullet, bullet_id)
    if bullet is None:
        raise HTTPException(404, "Bullet not found")
    return bullet.events
