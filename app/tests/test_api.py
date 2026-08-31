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
