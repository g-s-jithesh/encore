"""SQLite card store. State persists across sessions (the point of Encore)."""
import os
import sqlite3
from datetime import date

import srs

DB_PATH = os.environ.get("ENCORE_DB", "encore.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY, title TEXT, "
        "question TEXT, answer TEXT, box INTEGER DEFAULT 0, due TEXT)"
    )
    return c


def add_cards(title: str, cards: list[dict]) -> int:
    with _conn() as c:
        c.executemany(
            "INSERT INTO cards (title, question, answer, due) VALUES (?,?,?,?)",
            [(title, x["question"], x["answer"], date.today().isoformat()) for x in cards],
        )
    return len(cards)


def _topic(title: str | None) -> tuple[str, tuple]:
    """SQL filter for an optional, case-insensitive topic title."""
    return (" AND LOWER(title) = LOWER(?)", (title.strip(),)) if title and title.strip() else ("", ())


def next_due(title: str | None = None) -> dict | None:
    where, args = _topic(title)
    with _conn() as c:
        r = c.execute(
            f"SELECT * FROM cards WHERE due <= ?{where} ORDER BY due, id LIMIT 1",
            (date.today().isoformat(), *args),
        ).fetchone()
    return dict(r) if r else None


def list_cards() -> list[dict]:
    """Return all saved flashcards in review order."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM cards ORDER BY due, id").fetchall()
    return [dict(row) for row in rows]


def next_review(title: str | None = None) -> str | None:
    """Earliest future due date, or None if there are no cards."""
    where, args = _topic(title)
    with _conn() as c:
        return c.execute(f"SELECT MIN(due) FROM cards WHERE 1=1{where}", args).fetchone()[0]


def materials() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT title, COUNT(*) AS cards, SUM(due <= ?) AS due_today FROM cards "
            "GROUP BY LOWER(title) ORDER BY MIN(id)",
            (date.today().isoformat(),),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_material(title: str) -> int:
    where, args = _topic(title)
    if not where:
        return 0
    with _conn() as c:
        return c.execute(f"DELETE FROM cards WHERE 1=1{where}", args).rowcount


def grade(card_id: int, correct: bool) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not r:
            return None
        box, due = srs.review(r["box"], correct)
        c.execute("UPDATE cards SET box=?, due=? WHERE id=?", (box, due.isoformat(), card_id))
    return {**dict(r), "box": box, "due": due.isoformat()}


def stats() -> dict:
    with _conn() as c:
        total, due, mastered = c.execute(
            "SELECT COUNT(*), SUM(due <= ?), SUM(box >= 3) FROM cards",
            (date.today().isoformat(),),
        ).fetchone()
    return {"total": total, "due_today": due or 0, "mastered": mastered or 0}
