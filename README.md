# Grounded

Turn raw meeting notes into a briefing where **every bullet is either cited back to
a specific source note, or explicitly marked as invented**. No orphan claims.

The model does not get to decide which is which. It supplies a verbatim quote as
evidence for each claim, and the server checks that quote against the note before
the bullet is allowed to call itself cited.

---

## Run it

**Requirements:** Python 3.10+ and an Anthropic API key
([console.anthropic.com](https://console.anthropic.com) → Settings → API keys).

### Windows

```powershell
copy .env.example .env
notepad .env          # paste your key into GROUNDED_ANTHROPIC_API_KEY
.\start.ps1
```

### macOS / Linux

```bash
cp .env.example .env
$EDITOR .env          # paste your key into GROUNDED_ANTHROPIC_API_KEY
./start.sh
```

Either script creates a virtualenv, installs dependencies, starts both servers,
waits for the API to answer a health check, opens the app, and appends the result
to [BUILD_LOG.md](BUILD_LOG.md) — status table, detected red flags, and full
restore/server output.

* App — <http://127.0.0.1:5173>
* API docs (OpenAPI) — <http://127.0.0.1:8000/docs>

If a port is taken: `.\start.ps1 -ApiPort 8001 -WebPort 5174` (or
`API_PORT=8001 WEB_PORT=5174 ./start.sh`). The conflict is logged before it exits.

### Tests

```powershell
.\start.ps1 -Test     # Windows
./start.sh test       # macOS / Linux
```

45 tests, no network and no API key required — they run against a deterministic
stub provider, but every layer beneath it is the real one.

### Manual start

```bash
pip install -r requirements.txt
uvicorn app.backend.main:app --port 8000        # terminal 1
python -m http.server 5173 --directory app/frontend   # terminal 2
```

---

## How it works

```
notes ──► budget ──► LLM ──► VERIFY ──► dedupe ──► contradictions ──► SQLite ──► UI
                              ▲
                    the model's claim is an input here,
                    never the output
```

### 1. Proving a citation is real

This is the core of the product, and the reason the model's own label is never
trusted.

A model can write `"note_id": 3` for free. It cannot fake the presence of a span
of text inside a note we already hold. So the prompt requires a **verbatim quote**
alongside every grounded claim, and tells the model plainly that the quote will be
checked — which also gives it an honest exit (`"invented": true`) instead of
pressure to fabricate an attribution.

Every bullet then goes through `verification.verify_bullet`:

| What we find | Result |
|---|---|
| Quote is in the note the model cited | **cited** — offsets stored so the UI highlights the exact span |
| Quote is in a *different* note (higher bar: 90) | **cited**, re-attributed, and the correction is logged |
| Quote matches nothing | **invented** — downgraded regardless of what the model claimed |
| Model offered no quote | **invented** — honest admission, recorded as such |

Downgrading is the default. A bullet becomes cited only by passing, never by the
absence of a failure.

Matching is fuzzy (rapidfuzz partial-ratio alignment, threshold 82) rather than
exact-substring, because models normalise whitespace, straighten quotes and drop
trailing punctuation when quoting. An exact check would reject honest citations of
messy real-world notes — and these notes are somebody's standup scribbles. The
threshold is deliberately biased toward **false "invented" over false "cited"**: a
human glancing at an over-cautious flag costs seconds, a fabrication presented as
sourced costs trust.

**The database enforces the same rule independently:**

```sql
CHECK ((provenance = 'invented' AND verified_note_id IS NULL)
    OR (provenance = 'cited'    AND verified_note_id IS NOT NULL))
```

A single guard in application code is one refactor away from being bypassed. This
one is not. There is a test that tries to insert a fabricated bullet as `cited`
directly via SQL and asserts the database rejects it.

### 2. When two notes disagree

`analysis.find_contradictions` extracts measurements (value + normalised unit)
from every note and flags pairs that share a unit, differ in value, and whose
surrounding sentences share at least two meaningful words. That word overlap is
what stops "25% increase in tickets" being compared against "15% drop in churn".

Given real conflicting notes it surfaces `25% vs 10% [increase / ops / sso]` as a
banner above the briefing, quoting both sides. The briefing is not silently
"corrected" — a machine picking a winner between two humans is exactly the wrong
move. It flags the dispute and shows both, because the person reading knows which
source to trust and the tool does not.

Tuned for **false positives over false negatives**: a spurious flag is dismissed
in a second; a missed conflict means a briefing states one side of a live
disagreement as settled fact.

### 3. When the notes are garbage

`analysis.groundedness_budget` derives the bullet count from how much usable
source text exists (~100 characters per bullet), instead of always asking for 8.

The failure this prevents is specific: thin notes, model asked for 8 bullets,
model obliges by inventing 6. **Padding to a fixed count manufactures the exact
thing this product exists to catch.** With too little material the app generates
fewer bullets and says why:

> Only 2 bullets generated: 1 usable note totalling 146 characters supports roughly
> that much. Padding to a fixed count would mean inventing the difference.

With nothing usable it refuses to generate at all rather than produce a briefing
made entirely of invention.

### 4. Other logic that isn't "call the model"

* **Full-text retrieval** — SQLite FTS5 with porter stemming, kept in sync by
  triggers rather than application code so the index cannot drift from the table.
* **Near-duplicate detection** — `token_set_ratio` ≥ 78, calibrated against real
  data: genuine restatements score ~83, unrelated bullets 30–65.
* **Edit diffs** — word-level diff between the model's original and the human's
  version, shown inline and stored in the audit trail.
* **Source snapshots** — each briefing stores the note text as it was at
  generation time, so editing a note later cannot silently invalidate a citation
  that was true when it was made.

---

## Build log

Every run appends to [BUILD_LOG.md](BUILD_LOG.md): a status table, auto-detected red
flags (tracebacks, port conflicts, `database is locked`, constraint violations,
missing API key, CORS blocks), and the full output. Above the run entries is a
hand-maintained **Lessons learned** table — what broke, why, and what it taught.
That table is where the "what I learned" material comes from.

## Data model

```
notes ──┬── briefing_notes (snapshot of the text used) ──┐
        │                                               ├── briefings
        └── bullets.verified_note_id ───────────────────┘      │
                     │                                          │
                     ├── bullet_events  (append-only audit)     │
                     └── contradictions ──────────────────────┘
```

`claimed_note_id` (what the model said) and `verified_note_id` (what we proved)
are separate columns on purpose — when they disagree, the disagreement is itself
a signal worth keeping.

One audit table, not two. Foreign keys enforced, `CHECK` constraints on every
enumerated column, indexes on all foreign keys, WAL journal mode.

---

## API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | liveness + active provider |
| `GET` `POST` | `/api/notes` | list / create notes |
| `GET` | `/api/notes/search?q=` | FTS5 full-text search |
| `DELETE` | `/api/notes/{id}` | delete a note |
| `POST` | `/api/briefings/generate` | generate + verify (optional `note_ids`) |
| `GET` | `/api/briefings` | list past briefings with stats |
| `GET` | `/api/briefings/{id}` | full briefing: bullets, sources, contradictions |
| `POST` | `/api/briefings/{id}/save` | save and lock |
| `GET` | `/api/briefings/{id}/audit` | full audit trail |
| `PATCH` | `/api/bullets/{id}` | edit text |
| `PATCH` | `/api/bullets/{id}/status` | accept / reject / reset |

Saved briefings return `409` on further edits, so a saved record cannot drift.

---

## What I cut

Time-boxed, in priority order — recorded here because the choices were deliberate:

* **Auth and multi-user.** Single-user local app. Everything else would have been
  shallower to add it.
* **Sentence-level citation within a bullet.** One quote per bullet, not per
  clause. A bullet fusing two notes cites the stronger one; splitting attribution
  mid-sentence needs a UI that earns its complexity.
* **Re-verification after a human edit.** An edited bullet keeps its original
  citation and is badged `Edited` with a visible diff, rather than being
  re-checked against the note. Re-running verification on human prose would flag
  the human's own words as unsourced — the wrong signal entirely.
* **Streaming generation.** A spinner with honest status text instead of
  token-by-token streaming.
* **Semantic/embedding retrieval.** FTS5 keyword search is enough at this corpus
  size, and it is inspectable — you can see why a note matched.

## Known limits

* Verification catches **unsupported** claims, not **misread** ones. A bullet can
  quote a note accurately and still draw a wrong conclusion from it. Showing the
  quote inline is the mitigation: the reader can check the inference themselves.
* The contradiction detector is numeric only. "Sarah approved it" vs "Sarah
  rejected it" is not caught.
* A model that paraphrases instead of quoting verbatim gets downgraded to
  invented. Correct-by-design, but it means citation yield depends on the model
  following instructions; weaker models will show more invented bullets.
