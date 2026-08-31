"""Tests for the part that matters: a citation is only accepted if it is provable."""
from __future__ import annotations

import pytest

from app.backend.verification import locate_quote, normalize, verify_bullet

NOTE_1 = (
    "standup 3/4 discussed budget scraps for next quarter. Sarah says ops needs a "
    "25% increase on vender SSO she thinks 2 more weeks maybe new 15 roles"
)
NOTE_2 = (
    "Finance review: ops budget increase capped at 10% for SSO vendor work. "
    "Timeline is 6 weeks not 2. Headcount request deferred to Q1."
)
NOTES = {1: NOTE_1, 2: NOTE_2}


class TestNormalize:
    def test_folds_smart_punctuation_and_whitespace(self):
        assert normalize("It’s   fine—really") == "it's fine-really"

    def test_case_insensitive(self):
        assert normalize("ABC") == normalize("abc")


class TestLocateQuote:
    def test_exact_span_scores_100_and_returns_offsets(self):
        quote = "ops needs a 25% increase on vender SSO"
        m = locate_quote(quote, NOTE_1)
        assert m.found and m.score == 100
        assert NOTE_1[m.start:m.end] == quote

    def test_absent_text_scores_low(self):
        m = locate_quote("the board approved a merger with Acme Corp", NOTE_1)
        assert m.score < 60

    def test_empty_inputs_do_not_match(self):
        assert not locate_quote("", NOTE_1).found
        assert not locate_quote("anything", "").found

    def test_quote_longer_than_note_is_rejected(self):
        assert not locate_quote("x" * 500, "short note body here").found


class TestVerifyBullet:
    def test_true_citation_is_accepted(self):
        r = verify_bullet(
            claimed_note_id=1, quote="Sarah says ops needs a 25% increase", notes=NOTES
        )
        assert r.provenance == "cited"
        assert r.outcome == "verified"
        assert r.verified_note_id == 1

    def test_fabricated_quote_is_downgraded_not_trusted(self):
        """The model claims a citation; the quote exists nowhere. Must be downgraded."""
        r = verify_bullet(
            claimed_note_id=1,
            quote="the board unanimously approved the Acme acquisition",
            notes=NOTES,
        )
        assert r.provenance == "invented"
        assert r.outcome == "unverified_quote"
        assert r.verified_note_id is None

    def test_misattributed_quote_is_reattributed_to_the_real_note(self):
        r = verify_bullet(
            claimed_note_id=2, quote="Sarah says ops needs a 25% increase", notes=NOTES
        )
        assert r.provenance == "cited"
        assert r.outcome == "reattributed"
        assert r.verified_note_id == 1

    def test_honest_admission_of_invention_is_respected(self):
        r = verify_bullet(
            claimed_note_id=None, quote=None, notes=NOTES, self_declared_invented=True
        )
        assert r.provenance == "invented"
        assert r.outcome == "no_quote_offered"

    def test_citing_a_note_outside_the_briefing_is_rejected(self):
        r = verify_bullet(claimed_note_id=99, quote="ops needs a 25% increase", notes={2: NOTE_2})
        assert r.provenance == "invented"
        assert r.outcome in ("claimed_note_missing", "unverified_quote")

    def test_a_model_claiming_invented_false_cannot_force_cited(self):
        """Provenance is never taken from the model's own label."""
        r = verify_bullet(
            claimed_note_id=1, quote="completely made up sentence", notes=NOTES,
            self_declared_invented=False,
        )
        assert r.provenance == "invented"

    @pytest.mark.parametrize(
        "quote",
        [
            "Sarah says ops needs a 25% increase on vender SSO",   # exact
            "sarah says ops needs a 25% increase on vender sso",   # case
            "Sarah says ops needs a 25% increase on vender SSO.",  # trailing punctuation
            "Sarah  says   ops needs a 25% increase on vender SSO",  # whitespace
        ],
    )
    def test_tolerates_benign_rendering_differences(self, quote):
        r = verify_bullet(claimed_note_id=1, quote=quote, notes=NOTES)
        assert r.provenance == "cited", f"rejected a legitimate quote: {quote!r}"
