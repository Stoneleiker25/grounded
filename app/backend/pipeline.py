"""Generation pipeline: notes in, verified briefing out.

Order matters here.

    budget -> generate -> VERIFY -> dedupe -> contradictions -> persist

Verification sits between the model and the database, so an unverified claim can
never reach storage wearing a "cited" label. The database enforces the same rule
independently (see the ck_cited_requires_verified_note constraint), because a
single guard in application code is one refactor away from being bypassed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import analysis, verification
from .config import settings
from .llm import get_provider
from .models import Briefing, BriefingNote, Bullet, BulletEvent, Contradiction, Note, utcnow


class GenerationError(RuntimeError):
    pass


def generate_briefing(session: Session, note_ids: list[int] | None = None) -> Briefing:
    query = session.query(Note).filter(Note.deleted_at.is_(None))
    if note_ids:
        query = query.filter(Note.id.in_(note_ids))
    notes = query.order_by(Note.created_at).all()
    if not notes:
        raise GenerationError("No notes selected. Add or select at least one note first.")

    bodies = {n.id: n.body for n in notes}
    titled = {n.id: (n.title, n.body) for n in notes}

    # 1. How much can this material honestly support?
    budget = analysis.groundedness_budget(bodies)
    if budget.n_bullets == 0:
        raise GenerationError(budget.coverage_note or "Notes contain too little text to brief from.")

    # 2. Ask the model.
    provider = get_provider()
    try:
        drafts = provider.generate(titled, budget.n_bullets)
    except Exception as exc:  # surface provider errors as a clean 502 upstream
        raise GenerationError(f"LLM request failed: {exc}") from exc
    if not drafts:
        raise GenerationError("The model returned no bullets.")

    briefing = Briefing(
        title=f"Briefing {utcnow():%Y-%m-%d %H:%M}",
        status="draft",
        coverage_note=budget.coverage_note,
        model_name=getattr(provider, "model", provider.name),
    )
    session.add(briefing)
    session.flush()

    # Snapshot the sources, so a later edit to a note cannot silently invalidate
    # a citation that was true when it was made.
    for n in notes:
        session.add(BriefingNote(
            briefing_id=briefing.id, note_id=n.id,
            title_snapshot=n.title, body_snapshot=n.body,
        ))

    # 3. Verify every bullet against the notes. This is where "cited" is earned.
    verified: list[tuple[object, verification.VerificationResult]] = []
    for draft in drafts:
        result = verification.verify_bullet(
            claimed_note_id=draft.note_id,
            quote=draft.quote,
            notes=bodies,
            self_declared_invented=draft.invented,
        )
        verified.append((draft, result))

    # 4. Suppress near-duplicate restatements.
    dupes = analysis.mark_duplicates([d.text for d, _ in verified])

    created: list[Bullet] = []
    for idx, (draft, result) in enumerate(verified):
        bullet = Bullet(
            briefing_id=briefing.id,
            position=idx,
            text=draft.text,
            original_text=draft.text,
            provenance=result.provenance,
            verification_outcome=result.outcome,
            claimed_note_id=draft.note_id if draft.note_id in bodies else None,
            verified_note_id=result.verified_note_id,
            quote=result.quote,
            quote_start=result.start,
            quote_end=result.end,
            match_score=result.score,
            status="pending",
        )
        session.add(bullet)
        session.flush()
        created.append(bullet)

        session.add(BulletEvent(
            bullet_id=bullet.id, action="generated",
            to_status="pending", to_text=bullet.text, detail=result.detail,
        ))
        if result.outcome in ("unverified_quote", "claimed_note_missing"):
            session.add(BulletEvent(
                bullet_id=bullet.id, action="downgraded_to_invented", detail=result.detail,
            ))
        elif result.outcome == "reattributed":
            session.add(BulletEvent(
                bullet_id=bullet.id, action="citation_reattributed", detail=result.detail,
            ))

    for i, j in dupes.items():
        created[i].duplicate_of_id = created[j].id
        session.add(BulletEvent(
            bullet_id=created[i].id, action="flagged_duplicate",
            detail=f"Near-duplicate of bullet {created[j].id}.",
        ))

    # 5. Flag disagreements between the sources themselves.
    for hit in analysis.find_contradictions(bodies):
        session.add(Contradiction(
            briefing_id=briefing.id,
            note_a_id=hit.note_a_id, note_b_id=hit.note_b_id,
            subject=hit.subject, value_a=hit.value_a, value_b=hit.value_b,
            excerpt_a=hit.excerpt_a, excerpt_b=hit.excerpt_b,
        ))

    session.flush()
    return briefing


def generation_stats(briefing: Briefing) -> dict:
    bullets = briefing.bullets
    return {
        "total": len(bullets),
        "cited": sum(1 for b in bullets if b.provenance == "cited"),
        "invented": sum(1 for b in bullets if b.provenance == "invented"),
        "downgraded": sum(
            1 for b in bullets
            if b.verification_outcome in ("unverified_quote", "claimed_note_missing")
        ),
        "reattributed": sum(1 for b in bullets if b.verification_outcome == "reattributed"),
        "duplicates": sum(1 for b in bullets if b.duplicate_of_id is not None),
        "accepted": sum(1 for b in bullets if b.status == "accepted"),
        "rejected": sum(1 for b in bullets if b.status == "rejected"),
        "pending": sum(1 for b in bullets if b.status == "pending"),
    }
