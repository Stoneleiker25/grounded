"""Engine and session setup.

Two things here are load-bearing and easy to get wrong with SQLite:

1. ``PRAGMA foreign_keys = ON`` must be issued on **every** connection. SQLite
   parses FOREIGN KEY declarations but ignores them unless enforcement is switched
   on per-connection, so without this the constraints are decorative and orphan
   rows are accepted silently.
2. ``PRAGMA journal_mode = WAL`` so a reader does not block a writer.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _configure_connection(dbapi_conn, _record):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA busy_timeout = 5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency. One session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registers mappers)
    from .models import Base

    Base.metadata.create_all(engine)

    # FTS5 index over notes, kept in sync by triggers so it can never drift from
    # the notes table the way an application-managed index would.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    title, body, content='notes', content_rowid='id',
                    tokenize='porter unicode61'
                )
                """
            )
        )
        for stmt in (
            """CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                   INSERT INTO notes_fts(rowid, title, body)
                   VALUES (new.id, new.title, new.body);
               END""",
            """CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                   INSERT INTO notes_fts(notes_fts, rowid, title, body)
                   VALUES ('delete', old.id, old.title, old.body);
               END""",
            """CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                   INSERT INTO notes_fts(notes_fts, rowid, title, body)
                   VALUES ('delete', old.id, old.title, old.body);
                   INSERT INTO notes_fts(rowid, title, body)
                   VALUES (new.id, new.title, new.body);
               END""",
        ):
            conn.execute(text(stmt))
