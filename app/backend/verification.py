"""Citation verification.

This module is the answer to "how do you prove a citation is real, not just
something the model claimed".

The model is asked to return, for every bullet, a *verbatim quote* from the note
it is citing. That quote is the falsifiable part. A model can assert
``note_id: 3`` for free, but it cannot fake the presence of a span of text inside
a note we already hold.

So the model's tag is never trusted. Every bullet goes through:

    claimed quote + claimed note
        -> is the quote actually in that note?           -> cited (verified)
        -> is it in some *other* note, above a higher bar? -> cited (reattributed)
        -> otherwise                                       -> INVENTED

Downgrading is the default. A bullet becomes "cited" only by passing, never by
the absence of a failure.

Matching is fuzzy rather than exact on purpose: models normalise whitespace,
fix typos, expand contractions and drop trailing punctuation when quoting. An
exact-substring check would reject honest citations of messy real-world notes
(and these notes are messy -- they are somebody's standup scribbles). We use
rapidfuzz's partial-ratio alignment, which finds the best-matching window in the
note and returns both a score and its offsets, so the UI can highlight the exact
span that justified the claim.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import Indel

from .config import settings

# Characters that vary freely between a note and a model's rendering of it.
_QUOTE_CHARS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
}
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Fold away the differences that should not affect whether a quote matches."""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _QUOTE_CHARS.items():
        text = text.replace(src, dst)
    return _WS.sub(" ", text).strip().lower()


def _offset_map(original: str) -> tuple[str, list[int]]:
    """Normalize while remembering where each output char came from.

    Needed so a match found in normalized space can be reported as offsets into
    the *original* note text, which is what the UI highlights.
    """
    text = unicodedata.normalize("NFKC", original)
    out_chars: list[str] = []
    out_idx: list[int] = []
    prev_space = True  # leading whitespace is stripped
    for i, ch in enumerate(text):
        ch = _QUOTE_CHARS.get(ch, ch)
        if ch.isspace():
            if prev_space:
                continue
            out_chars.append(" ")
            out_idx.append(i)
            prev_space = True
        else:
            out_chars.append(ch.lower())
            out_idx.append(i)
            prev_space = False
    while out_chars and out_chars[-1] == " ":
        out_chars.pop()
        out_idx.pop()
    return "".join(out_chars), out_idx


@dataclass(frozen=True)
class QuoteMatch:
    score: float
    start: int  # offsets into the ORIGINAL note text
    end: int

    @property
    def found(self) -> bool:
        return self.start >= 0


NO_MATCH = QuoteMatch(score=0.0, start=-1, end=-1)


def locate_quote(quote: str, note_body: str) -> QuoteMatch:
    """Find the best window in ``note_body`` matching ``quote``.

    Returns a score in 0..100 and offsets into the original (un-normalized) body.
    """
    if not quote or not quote.strip() or not note_body.strip():
        return NO_MATCH

    norm_quote = normalize(quote)
    norm_body, idx_map = _offset_map(note_body)
    if not norm_quote or not norm_body:
        return NO_MATCH

    # A quote longer than the note it supposedly came from is incoherent.
    if len(norm_quote) > len(norm_body) * 1.5:
        return NO_MATCH

    alignment = Indel.opcodes(norm_quote, norm_body)
    score = fuzz.partial_ratio(norm_quote, norm_body)

    # Recover the aligned window in the body.
    body_positions = [op.dest_start for op in alignment if op.tag != "insert"]
    if body_positions:
        lo = min(body_positions)
        hi = max(op.dest_end for op in alignment if op.tag != "insert")
    else:
        lo, hi = 0, min(len(norm_body), len(norm_quote))

    # partial_ratio's own alignment is more reliable for the window; prefer it.
    try:
        pa = fuzz.partial_ratio_alignment(norm_quote, norm_body)
        if pa is not None:
            lo, hi = pa.dest_start, pa.dest_end
    except Exception:  # pragma: no cover - defensive, older rapidfuzz
        pass

    lo = max(0, min(lo, len(idx_map) - 1))
    hi = max(lo + 1, min(hi, len(idx_map)))
    start = idx_map[lo]
    end = idx_map[hi - 1] + 1
    return QuoteMatch(score=float(score), start=start, end=end)


@dataclass
class VerificationResult:
    provenance: str            # "cited" | "invented"
    outcome: str               # one of models.VERIFICATION_OUTCOME
    verified_note_id: int | None
    quote: str | None
    start: int | None
    end: int | None
    score: float | None
    detail: str


def verify_bullet(
    *,
    claimed_note_id: int | None,
    quote: str | None,
    notes: dict[int, str],
    self_declared_invented: bool = False,
) -> VerificationResult:
    """Decide a bullet's provenance from evidence, not from the model's label.

    ``notes`` maps note id -> note body, restricted to the briefing's source set.
    """
    # The model explicitly declined to cite. Honest, and we take it at its word --
    # this direction of the claim is not one it can benefit from faking.
    if self_declared_invented or not quote or not quote.strip():
        return VerificationResult(
            provenance="invented",
            outcome="no_quote_offered",
            verified_note_id=None,
            quote=None, start=None, end=None, score=None,
            detail="Model offered no supporting quote.",
        )

    # 1. Check the note the model actually claimed.
    if claimed_note_id is not None and claimed_note_id in notes:
        match = locate_quote(quote, notes[claimed_note_id])
        if match.found and match.score >= settings.quote_match_threshold:
            return VerificationResult(
                provenance="cited",
                outcome="verified",
                verified_note_id=claimed_note_id,
                quote=quote, start=match.start, end=match.end, score=match.score,
                detail=f"Quote located in note {claimed_note_id} (score {match.score:.0f}).",
            )

    # 2. The claim failed. Before calling it invented, check whether the content is
    #    real but mis-attributed -- a common and materially different failure.
    best_id, best_match = None, NO_MATCH
    for note_id, body in notes.items():
        if note_id == claimed_note_id:
            continue
        m = locate_quote(quote, body)
        if m.found and m.score > best_match.score:
            best_id, best_match = note_id, m

    if best_id is not None and best_match.score >= settings.reattribution_threshold:
        return VerificationResult(
            provenance="cited",
            outcome="reattributed",
            verified_note_id=best_id,
            quote=quote, start=best_match.start, end=best_match.end, score=best_match.score,
            detail=(
                f"Model cited note {claimed_note_id}, but the quote is in note {best_id} "
                f"(score {best_match.score:.0f}). Re-attributed."
            ),
        )

    # 3. Nothing supports it. Downgrade regardless of what the model said.
    if claimed_note_id is not None and claimed_note_id not in notes:
        outcome, detail = (
            "claimed_note_missing",
            f"Model cited note {claimed_note_id}, which is not among this briefing's sources.",
        )
    else:
        outcome, detail = (
            "unverified_quote",
            f"Quote could not be located in any source note "
            f"(best score {best_match.score:.0f}). Downgraded to invented.",
        )
    return VerificationResult(
        provenance="invented",
        outcome=outcome,
        verified_note_id=None,
        quote=quote, start=None, end=None,
        score=best_match.score or 0.0,
        detail=detail,
    )
