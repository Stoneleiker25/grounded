"""Logic that is not "call the model".

Three pieces, each answering a question the brief deliberately left open:

* ``find_contradictions``  -- what do you do when two notes disagree?
* ``mark_duplicates``      -- stop the model saying the same thing three ways.
* ``groundedness_budget``  -- what does "good" look like when the notes are garbage?

plus ``word_diff`` for showing what a human changed about a bullet.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .config import settings

# ---------------------------------------------------------------- contradictions

# A "measurement": a number with an optional unit marker, e.g. 25%, $1.2m, 3 weeks.
_MEASUREMENT = re.compile(
    r"(?P<value>\$?\d[\d,]*\.?\d*)\s*(?P<unit>%|percent|k|m|bn|billion|million|"
    r"weeks?|days?|months?|quarters?|years?|hours?|fte|ftes|roles?|people|headcount)?",
    re.IGNORECASE,
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "with", "that", "this", "it", "as",
    "from", "we", "they", "she", "he", "says", "said", "think", "thinks", "maybe",
    "new", "next", "more", "about", "needs", "need", "has", "have", "will",
}

_UNIT_ALIASES = {
    "percent": "%", "%": "%",
    "week": "week", "weeks": "week",
    "day": "day", "days": "day",
    "month": "month", "months": "month",
    "quarter": "quarter", "quarters": "quarter",
    "year": "year", "years": "year",
    "fte": "role", "ftes": "role", "role": "role", "roles": "role",
    "people": "role", "headcount": "role",
    "k": "k", "m": "m", "bn": "bn", "million": "m", "billion": "bn",
}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _context_words(sentence: str) -> set[str]:
    words = re.findall(r"[a-z][a-z'-]{2,}", sentence.lower())
    return {w for w in words if w not in _STOPWORDS}


@dataclass(frozen=True)
class Measurement:
    value: str
    unit: str
    sentence: str
    context: frozenset[str]


def extract_measurements(text: str) -> list[Measurement]:
    out: list[Measurement] = []
    for sentence in _sentences(text):
        ctx = frozenset(_context_words(sentence))
        for m in _MEASUREMENT.finditer(sentence):
            raw_unit = (m.group("unit") or "").lower()
            unit = _UNIT_ALIASES.get(raw_unit, raw_unit)
            value = m.group("value").replace(",", "")
            # A bare number with no unit and no context is noise (dates, list markers).
            if not unit and not ctx:
                continue
            out.append(Measurement(value=value, unit=unit, sentence=sentence, context=ctx))
    return out


@dataclass(frozen=True)
class ContradictionHit:
    note_a_id: int
    note_b_id: int
    subject: str
    value_a: str
    value_b: str
    excerpt_a: str
    excerpt_b: str


def find_contradictions(notes: dict[int, str], *, min_overlap: int = 2) -> list[ContradictionHit]:
    """Flag places where two notes give different numbers for the same thing.

    Heuristic and deliberately conservative: two measurements conflict when they
    share the same unit, differ in value, and their surrounding sentences share at
    least ``min_overlap`` meaningful words. That word overlap is what stops
    "25% increase in support tickets" from being compared against
    "15% drop in churn".

    False positives are cheap here (a human sees a flag and dismisses it);
    false negatives are expensive (a briefing silently states one side of a
    disagreement as fact). Tuned accordingly.
    """
    by_note = {nid: extract_measurements(body) for nid, body in notes.items()}
    hits: list[ContradictionHit] = []
    seen: set[tuple] = set()

    ids = sorted(by_note)
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1:]:
            for ma in by_note[a_id]:
                for mb in by_note[b_id]:
                    if ma.unit != mb.unit:
                        continue
                    if ma.value == mb.value:
                        continue
                    shared = ma.context & mb.context
                    if len(shared) < min_overlap:
                        continue
                    subject = " / ".join(sorted(shared)[:4])
                    key = (a_id, b_id, subject, ma.value, mb.value)
                    if key in seen:
                        continue
                    seen.add(key)
                    unit = f" {ma.unit}" if ma.unit and ma.unit != "%" else (ma.unit or "")
                    hits.append(
                        ContradictionHit(
                            note_a_id=a_id, note_b_id=b_id, subject=subject,
                            value_a=f"{ma.value}{unit}", value_b=f"{mb.value}{unit}",
                            excerpt_a=ma.sentence[:280], excerpt_b=mb.sentence[:280],
                        )
                    )
    return hits


# ------------------------------------------------------------------- duplicates


def mark_duplicates(texts: list[str]) -> dict[int, int]:
    """Map index -> index of the earlier bullet it duplicates.

    token_set_ratio rather than plain ratio: it is insensitive to word order and
    to one bullet carrying extra qualifiers, which is exactly how an LLM restates
    the same fact twice.
    """
    dupes: dict[int, int] = {}
    for i in range(len(texts)):
        for j in range(i):
            if j in dupes:
                continue
            if fuzz.token_set_ratio(texts[i], texts[j]) >= settings.duplicate_threshold:
                dupes[i] = j
                break
    return dupes


# --------------------------------------------------------------- groundedness


@dataclass(frozen=True)
class Budget:
    n_bullets: int
    coverage_note: str | None


def groundedness_budget(notes: dict[int, str]) -> Budget:
    """Decide how many bullets the material can actually support.

    The failure mode this prevents: thin or junk notes, model asked for 8 bullets,
    model obliges by inventing 6. Padding to a fixed count *manufactures* the very
    thing this product exists to catch, so the count is derived from the input.
    """
    usable = [b for b in notes.values() if len(b.strip()) >= 40]
    total_chars = sum(len(b.strip()) for b in usable)

    if not usable:
        return Budget(0, "No note contained enough text to brief from. Nothing was generated.")

    supported = max(1, total_chars // settings.chars_per_bullet)
    n = min(settings.target_bullets, supported)

    note = None
    if n < settings.min_bullets:
        note = (
            f"Only {n} bullet{'s' if n != 1 else ''} generated: "
            f"{len(usable)} usable note{'s' if len(usable) != 1 else ''} totalling "
            f"{total_chars} characters supports roughly that much. "
            "Padding to a fixed count would mean inventing the difference."
        )
    elif n < settings.target_bullets:
        note = (
            f"Generated {n} of a possible {settings.target_bullets} bullets — "
            "the source notes did not support more."
        )
    return Budget(n, note)


# -------------------------------------------------------------------- edit diff


def word_diff(before: str, after: str) -> list[dict]:
    """Word-level diff, for showing what a human changed about a model's bullet."""
    a, b = before.split(), after.split()
    ops: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag == "equal":
            ops.append({"op": "equal", "text": " ".join(a[i1:i2])})
        elif tag == "delete":
            ops.append({"op": "delete", "text": " ".join(a[i1:i2])})
        elif tag == "insert":
            ops.append({"op": "insert", "text": " ".join(b[j1:j2])})
        else:
            ops.append({"op": "delete", "text": " ".join(a[i1:i2])})
            ops.append({"op": "insert", "text": " ".join(b[j1:j2])})
    return [o for o in ops if o["text"]]
