import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "grounded.db"

LIVE_STATUSES = (
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("notes", "Notes"),
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            is_draft INTEGER NOT NULL DEFAULT 0,
            saved_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS bullets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            briefing_id INTEGER NOT NULL,
            tag TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            flagged INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (briefing_id) REFERENCES briefings(id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            selected INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS live_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            detail TEXT,
            status TEXT,
            notes TEXT,
            previous_status TEXT,
            previous_notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS bullet_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bullet_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            changed_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (bullet_id) REFERENCES bullets(id)
        );
        """
    )

    conn.executemany(
        "INSERT OR IGNORE INTO live_statuses (code, label, sort_order) VALUES (?, ?, ?)",
        [(code, label, idx) for idx, (code, label) in enumerate(LIVE_STATUSES)],
    )
    conn.commit()
    conn.close()


def log_history(table_name, record_id, action, detail=None, status=None, notes=None, previous_status=None, previous_notes=None):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO history (
            table_name, record_id, action, detail, status, notes, previous_status, previous_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            table_name,
            record_id,
            action,
            detail,
            status,
            notes,
            previous_status,
            previous_notes,
        ),
    )

    if table_name == "bullets":
        conn.execute(
            "INSERT INTO bullet_status_history (bullet_id, status, notes) VALUES (?, ?, ?)",
            (record_id, status or "pending", notes or ""),
        )

    conn.commit()
    conn.close()


def get_live_statuses():
    conn = get_connection()
    rows = conn.execute(
        "SELECT code, label, sort_order FROM live_statuses ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_draft_briefing_id():
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM briefings WHERE is_draft = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def ensure_draft_briefing():
    briefing_id = get_draft_briefing_id()
    if briefing_id:
        return briefing_id

    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO briefings (title, is_draft) VALUES ('Current Draft', 1)"
    )
    conn.commit()
    briefing_id = cur.lastrowid
    conn.close()
    return briefing_id


def seed_db():
    conn = get_connection()
    has_bullets = conn.execute("SELECT COUNT(*) AS c FROM bullets").fetchone()["c"]
    has_notes = conn.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"]
    conn.close()

    if has_bullets > 0 and has_notes > 0:
        return

    briefing_id = ensure_draft_briefing()
    conn = get_connection()

    if has_bullets == 0:
        sample_bullets = [
            ("", "Project milestone achieved ahead of schedule with 15% budget savings.", "approved", 0, 1),
            ("invented", "Client expressed strong interest in expanding the partnership scope.", "pending", 0, 2),
            ("", "Revenue projections updated to reflect Q4 market conditions.", "pending", 1, 3),
            ("", "Team headcount increased by 3 FTEs to support new initiatives.", "approved", 0, 4),
            ("", "Next review meeting scheduled for November 5th at 2:00 PM.", "approved", 0, 5),
        ]
        conn.executemany(
            """
            INSERT INTO bullets (briefing_id, tag, text, status, flagged, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(briefing_id, tag, text, status, flagged, order) for tag, text, status, flagged, order in sample_bullets],
        )

    if has_notes == 0:
        sample_notes = [
            ("Note 1: Project Update - Oct 26", "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."),
            ("Note 2: Client Meeting Notes", "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat."),
            ("Note 3: Research Findings", "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur."),
            ("Note 4: Weekly Summary", "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."),
        ]
        conn.executemany(
            "INSERT INTO notes (title, body) VALUES (?, ?)",
            sample_notes,
        )

    conn.commit()
    conn.close()


def get_all_bullets():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, tag, text, status, flagged, notes, briefing_id, sort_order
        FROM bullets
        ORDER BY sort_order, id
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_draft_bullets():
    briefing_id = ensure_draft_briefing()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, tag, text, status, flagged, notes, sort_order
        FROM bullets
        WHERE briefing_id = ?
        ORDER BY sort_order, id
        """,
        (briefing_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_bullet(bullet_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM bullets WHERE id = ?", (bullet_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def approve_bullet(bullet_id):
    conn = get_connection()
    old = get_bullet(bullet_id)
    conn.execute("UPDATE bullets SET status = 'approved' WHERE id = ?", (bullet_id,))
    conn.commit()
    conn.close()
    if old:
        log_history(
            "bullets",
            bullet_id,
            "approved",
            detail=f"status: {old.get('status', 'pending')} -> approved",
            status="approved",
            notes=old.get("notes", ""),
            previous_status=old.get("status"),
            previous_notes=old.get("notes"),
        )


def reject_bullet(bullet_id):
    conn = get_connection()
    old = get_bullet(bullet_id)
    conn.execute("UPDATE bullets SET status = 'rejected' WHERE id = ?", (bullet_id,))
    conn.commit()
    conn.close()
    if old:
        log_history(
            "bullets",
            bullet_id,
            "rejected",
            detail=f"status: {old.get('status', 'pending')} -> rejected",
            status="rejected",
            notes=old.get("notes", ""),
            previous_status=old.get("status"),
            previous_notes=old.get("notes"),
        )


def update_bullet(bullet_id, text, notes=""):
    conn = get_connection()
    old = get_bullet(bullet_id)
    conn.execute(
        "UPDATE bullets SET text = ?, notes = ? WHERE id = ?",
        (text, notes, bullet_id),
    )
    conn.commit()
    conn.close()
    if old:
        log_history(
            "bullets",
            bullet_id,
            "edited",
            detail=f"text: {old['text']} -> {text}; notes: {old.get('notes', '')} -> {notes}",
            status=old.get("status"),
            notes=notes,
            previous_status=old.get("status"),
            previous_notes=old.get("notes"),
        )


def get_notes():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, body, selected, created_at FROM notes ORDER BY created_at DESC, id DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_note(title, body):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO notes (title, body) VALUES (?, ?)",
        (title.strip(), body.strip()),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    log_history("notes", note_id, "created", title)
    return note_id


def toggle_note_selected(note_id, selected):
    conn = get_connection()
    conn.execute("UPDATE notes SET selected = ? WHERE id = ?", (1 if selected else 0, note_id))
    conn.commit()
    conn.close()
    log_history("notes", note_id, "selected" if selected else "deselected")


def save_briefing(title=None):
    draft_id = ensure_draft_briefing()
    conn = get_connection()
    if not title:
        title = conn.execute(
            "SELECT strftime('%Y-%m-%d %H:%M', saved_at) AS t FROM briefings WHERE id = ?",
            (draft_id,),
        ).fetchone()["t"]
        title = f"Briefing {title}"

    conn.execute(
        "UPDATE briefings SET is_draft = 0, title = ?, saved_at = datetime('now') WHERE id = ?",
        (title, draft_id),
    )
    log_history("briefings", draft_id, "saved", title)

    conn.execute(
        "INSERT INTO briefings (title, is_draft) VALUES ('Current Draft', 1)"
    )
    new_draft_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    bullets = conn.execute(
        "SELECT tag, text, status, flagged, notes, sort_order FROM bullets WHERE briefing_id = ?",
        (draft_id,),
    ).fetchall()
    conn.executemany(
        """
        INSERT INTO bullets (briefing_id, tag, text, status, flagged, notes, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(new_draft_id, b["tag"], b["text"], "pending", b["flagged"], "", b["sort_order"]) for b in bullets],
    )

    conn.commit()
    conn.close()
    return draft_id


def get_past_briefings():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT b.id, b.title, b.saved_at,
               (SELECT COUNT(*) FROM bullets WHERE briefing_id = b.id) AS bullet_count,
               (SELECT COUNT(*) FROM bullets WHERE briefing_id = b.id AND status = 'approved') AS approved_count
        FROM briefings b
        WHERE b.is_draft = 0
        ORDER BY b.saved_at DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_briefing(briefing_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, title, is_draft, saved_at FROM briefings WHERE id = ?",
        (briefing_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_briefing_bullets(briefing_id):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, tag, text, status, flagged, notes
        FROM bullets
        WHERE briefing_id = ?
        ORDER BY sort_order, id
        """,
        (briefing_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_briefing_history(briefing_id):
    conn = get_connection()
    bullet_ids = conn.execute(
        "SELECT id FROM bullets WHERE briefing_id = ?",
        (briefing_id,),
    ).fetchall()
    bullet_ids = [row["id"] for row in bullet_ids]

    if not bullet_ids:
        conn.close()
        return []

    placeholders = ", ".join("?" for _ in bullet_ids)
    rows = conn.execute(
        f"""
        SELECT id, table_name, record_id, action, detail, status, notes, previous_status, previous_notes, created_at
        FROM history
        WHERE (
            (table_name = 'bullets' AND record_id IN ({placeholders}))
            OR (table_name = 'briefings' AND record_id = ?)
            OR (table_name = 'notes')
        )
        ORDER BY created_at DESC, id DESC
        """,
        (*bullet_ids, briefing_id),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_history(limit=50):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, table_name, record_id, action, detail, status, notes, previous_status, previous_notes, created_at
        FROM history
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_history_timeline(limit=200):
    rows = get_history(limit)
    years = {}

    def add_count(bucket, action, row):
        bucket["total"] = bucket.get("total", 0) + 1
        if action == "approved":
            bucket["approved"] = bucket.get("approved", 0) + 1
        elif action == "rejected":
            bucket["rejected"] = bucket.get("rejected", 0) + 1
        bucket.setdefault("entries", []).append(row)

    for row in rows:
        created_at = row.get("created_at")
        if not created_at:
            continue

        try:
            dt = datetime.fromisoformat(created_at)
        except ValueError:
            try:
                dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

        action = (row.get("action") or "").lower()
        year_key = str(dt.year)
        month_key = dt.strftime("%Y-%m")
        week_key = dt.strftime("%Y-%W")
        day_key = dt.strftime("%Y-%m-%d")

        year_bucket = years.setdefault(
            year_key,
            {
                "year": int(year_key),
                "label": year_key,
                "approved": 0,
                "rejected": 0,
                "total": 0,
                "months": {},
            },
        )
        add_count(year_bucket, action, row)

        month_bucket = year_bucket["months"].setdefault(
            month_key,
            {
                "month": month_key,
                "label": dt.strftime("%B %Y"),
                "approved": 0,
                "rejected": 0,
                "total": 0,
                "weeks": {},
            },
        )
        add_count(month_bucket, action, row)

        week_bucket = month_bucket["weeks"].setdefault(
            week_key,
            {
                "week": week_key,
                "label": f"Week of {dt.strftime('%Y-%m-%d')}",
                "approved": 0,
                "rejected": 0,
                "total": 0,
                "days": {},
            },
        )
        add_count(week_bucket, action, row)

        day_bucket = week_bucket["days"].setdefault(
            day_key,
            {
                "day": day_key,
                "label": dt.strftime("%A, %Y-%m-%d"),
                "approved": 0,
                "rejected": 0,
                "total": 0,
                "entries": [],
            },
        )
        add_count(day_bucket, action, row)

    timeline = []
    for year_key in sorted(years.keys(), reverse=True):
        year_bucket = years[year_key]
        year_bucket["months"] = [
            month_bucket for _, month_bucket in sorted(year_bucket["months"].items(), reverse=True)
        ]

        for month_bucket in year_bucket["months"]:
            month_bucket["weeks"] = [
                week_bucket for _, week_bucket in sorted(month_bucket["weeks"].items(), reverse=True)
            ]

            for week_bucket in month_bucket["weeks"]:
                week_bucket["days"] = [
                    day_bucket for _, day_bucket in sorted(week_bucket["days"].items(), reverse=True)
                ]

                for day_bucket in week_bucket["days"]:
                    day_bucket["entries"] = sorted(
                        day_bucket.get("entries", []),
                        key=lambda item: item.get("created_at") or "",
                        reverse=True,
                    )

        timeline.append(year_bucket)

    return timeline


def print_all_bullets():
    bullets = get_all_bullets()
    print(f"{'ID':<5} {'TAG':<12} {'STATUS':<10} {'TEXT':<70} NOTES")
    print("-" * 130)
    for row in bullets:
        tag = row["tag"] or "-"
        status = row.get("status") or "pending"
        notes = row.get("notes") or ""
        text = row["text"]
        print(f"{row['id']:<5} {tag:<12} {status:<10} {text:<70} {notes}")


def print_history(limit=10):
    rows = get_history(limit)
    print(f"{'ID':<5} {'TABLE':<12} {'RECORD':<8} {'ACTION':<12} {'STATUS':<10} DETAIL")
    print("-" * 110)
    for row in rows:
        detail = row.get("detail") or ""
        print(
            f"{row['id']:<5} {row['table_name']:<12} {row['record_id']:<8} {row['action']:<12} {str(row.get('status') or '').upper():<10} {detail}"
        )


if __name__ == "__main__":
    init_db()
    seed_db()
    print_all_bullets()
    print("\n--- RECENT HISTORY ---")
    print_history(10)
