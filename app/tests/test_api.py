"""End-to-end API tests, plus the database-level invariants.

These run against the deterministic ``echo`` provider so they need no network and
no API key, but every layer under the provider is the real one.
"""
from __future__ import annotations

import pytest
import sqlalchemy
from fastapi.testclient import TestClient

# Provider and database location are configured in conftest.py, which pytest
# imports before any test module. See the note there.
from app.backend.database import engine
from app.backend.main import app

NOTES = [
    "standup 3/4 discussed budget scraps for next quarter. Sarah says ops needs a "
    "25% increase on vender SSO she thinks 2 more weeks maybe new 15 roles",
    "Finance review: ops budget increase capped at 10% for SSO vendor work. "
    "Timeline is 6 weeks not 2. Headcount request deferred to Q1.",
    "Customer call with Northwind. They renewed for 12 months. Asked about SSO "
    "timeline repeatedly, this is now a blocker for their security review.",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        for body in NOTES:
            c.post("/api/notes", json={"body": body})
        yield c


class TestNotes:
    def test_notes_persist_across_requests(self, client):
        assert len(client.get("/api/notes").json()) >= 3

    def test_empty_note_is_rejected(self, client):
        assert client.post("/api/notes", json={"body": "   "}).status_code == 422

    def test_full_text_search_finds_notes(self, client):
        hits = client.get("/api/notes/search", params={"q": "SSO"}).json()
        assert len(hits) >= 2

    def test_search_with_no_hits_returns_empty(self, client):
        assert client.get("/api/notes/search", params={"q": "zebracorn"}).json() == []


class TestGeneration:
    def test_generates_a_verified_briefing(self, client):
        r = client.post("/api/briefings/generate", json={})
        assert r.status_code == 201
        d = r.json()
        assert d["stats"]["total"] > 0
        assert d["bullets"], "expected bullets"

    def test_every_bullet_is_cited_or_invented_with_no_orphans(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        for b in d["bullets"]:
            assert b["provenance"] in ("cited", "invented")
            if b["provenance"] == "cited":
                # The product's central promise: a cited bullet always carries
                # a real quote from a real note.
                assert b["citation"] is not None
                assert b["citation"]["quote"].strip()
                assert b["citation"]["note_id"] in [s["note_id"] for s in d["sources"]]
            else:
                assert b["citation"] is None

    def test_sources_are_snapshotted_with_the_briefing(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        assert len(d["sources"]) >= 3
        assert all(s["body"].strip() for s in d["sources"])

    def test_contradictions_are_surfaced(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        assert any(c["value_a"] != c["value_b"] for c in d["contradictions"])


class TestDecisions:
    def test_accept_reject_edit_persist_and_reopen(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        bid, ids = d["id"], [b["id"] for b in d["bullets"]]

        assert client.patch(f"/api/bullets/{ids[0]}/status",
                            json={"status": "accepted"}).status_code == 200
        assert client.patch(f"/api/bullets/{ids[1]}/status",
                            json={"status": "rejected"}).status_code == 200
        edited = client.patch(f"/api/bullets/{ids[0]}",
                              json={"text": "Rewritten by a human."}).json()
        assert edited["edited"] is True
        assert edited["diff"]

        reopened = client.get(f"/api/briefings/{bid}").json()
        assert reopened["stats"]["accepted"] == 1
        assert reopened["stats"]["rejected"] == 1
        assert any(b["text"] == "Rewritten by a human." for b in reopened["bullets"])

    def test_saved_briefing_is_locked(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        bid = d["id"]
        assert client.post(f"/api/briefings/{bid}/save", json={}).status_code == 200
        # Further edits must be refused, so a saved record cannot drift.
        r = client.patch(f"/api/bullets/{d['bullets'][0]['id']}/status",
                         json={"status": "accepted"})
        assert r.status_code == 409

    def test_audit_trail_records_every_action(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        client.patch(f"/api/bullets/{d['bullets'][0]['id']}/status", json={"status": "accepted"})
        events = client.get(f"/api/briefings/{d['id']}/audit").json()
        actions = {e["action"] for e in events}
        assert "generated" in actions
        assert "marked_accepted" in actions

    def test_missing_bullet_returns_404(self, client):
        assert client.patch("/api/bullets/999999/status",
                            json={"status": "accepted"}).status_code == 404


class TestDatabaseInvariants:
    """The application guard is not the only guard."""

    def test_cited_bullet_without_a_verified_note_is_rejected_by_the_database(self, client):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text(
                        "INSERT INTO bullets (briefing_id, position, text, original_text,"
                        " provenance, verification_outcome, verified_note_id, status,"
                        " created_at, updated_at)"
                        " VALUES (1, 99, 'fake', 'fake', 'cited', 'verified', NULL,"
                        " 'pending', datetime('now'), datetime('now'))"
                    )
                )

    def test_foreign_keys_are_enforced(self, client):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text(
                        "INSERT INTO bullets (briefing_id, position, text, original_text,"
                        " provenance, verification_outcome, status, created_at, updated_at)"
                        " VALUES (999999, 0, 'x', 'x', 'invented', 'no_quote_offered',"
                        " 'pending', datetime('now'), datetime('now'))"
                    )
                )

    def test_invalid_status_is_rejected(self, client):
        # Target a bullet we know exists, rather than assuming id 1 is present.
        bullet_id = client.post("/api/briefings/generate", json={}).json()["bullets"][0]["id"]
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text("UPDATE bullets SET status = 'banana' WHERE id = :i"),
                    {"i": bullet_id},
                )


class TestNoteDeletion:
    """Regression: deleting a note must never damage a briefing that cites it.

    The original hard delete set bullets.verified_note_id to NULL while provenance
    stayed 'cited', which tripped ck_cited_requires_verified_note and returned a 500 --
    and without that constraint would have silently destroyed the citation instead.
    """

    def test_deleting_a_cited_note_leaves_the_briefing_intact(self, client):
        d = client.post("/api/briefings/generate", json={}).json()
        bid = d["id"]
        cited = [b for b in d["bullets"] if b["provenance"] == "cited"]
        assert cited, "need at least one cited bullet to make this meaningful"
        note_id = cited[0]["citation"]["note_id"]

        client.patch(f"/api/bullets/{cited[0]['id']}/status", json={"status": "accepted"})
        assert client.delete(f"/api/notes/{note_id}").status_code == 204

        reopened = client.get(f"/api/briefings/{bid}")
        assert reopened.status_code == 200
        j = reopened.json()
        assert note_id in [s["note_id"] for s in j["sources"]], "source snapshot was lost"
        still = next(b for b in j["bullets"] if b["id"] == cited[0]["id"])
        assert still["provenance"] == "cited"
        assert still["citation"] is not None and still["citation"]["quote"].strip()
        assert still["status"] == "accepted", "human decision was lost"

    def test_deleted_note_leaves_the_workspace(self, client):
        note_id = client.post("/api/notes", json={"body": "ephemeral note " * 5}).json()["id"]
        client.delete(f"/api/notes/{note_id}")
        assert note_id not in [n["id"] for n in client.get("/api/notes").json()]
        assert note_id not in [
            n["id"] for n in client.get("/api/notes/search", params={"q": "ephemeral"}).json()
        ]
        assert client.delete(f"/api/notes/{note_id}").status_code == 404

    def test_deleted_note_is_not_used_for_new_briefings(self, client):
        note_id = client.post("/api/notes", json={"body": "zebracorn quarterly " * 6}).json()["id"]
        client.delete(f"/api/notes/{note_id}")
        d = client.post("/api/briefings/generate", json={}).json()
        assert note_id not in [s["note_id"] for s in d["sources"]]


class TestHistoryPayload:
    """The Past-briefings tree groups by year/month/week/day entirely client-side,
    so it depends on two things the API must guarantee."""

    def test_timestamps_are_explicit_utc(self):
        """Naive timestamps are read by JavaScript as LOCAL time, which shifts every
        value by the viewer's offset and files late-evening briefings under the wrong
        day. Every timestamp must carry an offset."""
        with TestClient(app) as c:
            c.post("/api/notes", json={"body": NOTES[0]})
            d = c.post("/api/briefings/generate", json={}).json()
            saved = c.post(f"/api/briefings/{d['id']}/save", json={}).json()

            assert saved["created_at"].endswith("+00:00"), saved["created_at"]
            assert saved["saved_at"].endswith("+00:00"), saved["saved_at"]
            for row in c.get("/api/briefings").json():
                assert row["created_at"].endswith("+00:00")
                if row["saved_at"]:
                    assert row["saved_at"].endswith("+00:00")

    def test_summary_carries_the_counts_the_tree_displays(self):
        with TestClient(app) as c:
            c.post("/api/notes", json={"body": NOTES[1]})
            d = c.post("/api/briefings/generate", json={}).json()
            c.patch(f"/api/bullets/{d['bullets'][0]['id']}/status", json={"status": "accepted"})

            row = next(r for r in c.get("/api/briefings").json() if r["id"] == d["id"])
            assert row["note_count"] >= 1
            for key in ("accepted", "rejected", "pending", "cited", "invented"):
                assert key in row["stats"], f"tree needs stats.{key}"
            assert row["stats"]["accepted"] == 1
