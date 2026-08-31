"""Tests for the non-LLM logic: contradictions, duplicates, budget, diffs."""
from __future__ import annotations

from app.backend.analysis import (
    extract_measurements,
    find_contradictions,
    groundedness_budget,
    mark_duplicates,
    word_diff,
)

NOTE_1 = (
    "standup 3/4 discussed budget scraps for next quarter. Sarah says ops needs a "
    "25% increase on vender SSO she thinks 2 more weeks maybe new 15 roles"
)
NOTE_2 = (
    "Finance review: ops budget increase capped at 10% for SSO vendor work. "
    "Timeline is 6 weeks not 2. Headcount request deferred to Q1."
)
NOTE_3 = "Office plants were watered. The kitchen tap is fixed."


class TestMeasurements:
    def test_extracts_value_and_unit(self):
        found = {(m.value, m.unit) for m in extract_measurements("ops needs a 25% increase")}
        assert ("25", "%") in found

    def test_normalises_unit_aliases(self):
        units = {m.unit for m in extract_measurements("hired 3 FTEs and 4 roles")}
        assert units == {"role"}


class TestContradictions:
    def test_flags_conflicting_percentages_on_the_same_subject(self):
        hits = find_contradictions({1: NOTE_1, 2: NOTE_2})
        assert hits, "should flag 25% vs 10% on the ops/SSO increase"
        values = {(h.value_a, h.value_b) for h in hits}
        assert ("25%", "10%") in values

    def test_does_not_flag_unrelated_numbers(self):
        assert find_contradictions({1: NOTE_1, 3: NOTE_3}) == []

    def test_single_note_cannot_contradict_itself(self):
        assert find_contradictions({1: NOTE_1}) == []

    def test_identical_values_are_not_a_conflict(self):
        notes = {1: "ops needs a 25% increase on SSO", 2: "confirmed the 25% increase on SSO"}
        assert find_contradictions(notes) == []


class TestDuplicates:
    def test_detects_reordered_restatement(self):
        texts = [
            "Ops needs a 25% budget increase for SSO.",
            "Revenue projections were updated.",
            "For SSO, ops needs a budget increase of 25%.",
        ]
        assert mark_duplicates(texts) == {2: 0}

    def test_distinct_bullets_are_not_duplicates(self):
        texts = ["Ops needs more budget.", "The office tap was fixed."]
        assert mark_duplicates(texts) == {}


class TestGroundednessBudget:
    def test_refuses_to_brief_from_nothing(self):
        assert groundedness_budget({}).n_bullets == 0
        assert groundedness_budget({1: "hi"}).n_bullets == 0

    def test_thin_notes_produce_fewer_bullets_and_say_so(self):
        b = groundedness_budget({1: NOTE_1})
        assert 0 < b.n_bullets < 8
        assert b.coverage_note and "invent" in b.coverage_note.lower()

    def test_plenty_of_material_reaches_the_target(self):
        notes = {i: NOTE_1 + " " + NOTE_2 for i in range(1, 6)}
        assert groundedness_budget(notes).n_bullets == 8

    def test_never_exceeds_the_target(self):
        notes = {i: NOTE_1 * 20 for i in range(1, 40)}
        assert groundedness_budget(notes).n_bullets == 8


class TestWordDiff:
    def test_reports_insertions_and_deletions(self):
        ops = word_diff("headcount increased by 3 FTEs", "headcount increased by 5 FTEs")
        assert {"op": "delete", "text": "3"} in ops
        assert {"op": "insert", "text": "5"} in ops

    def test_identical_text_is_all_equal(self):
        assert all(o["op"] == "equal" for o in word_diff("same text", "same text"))
