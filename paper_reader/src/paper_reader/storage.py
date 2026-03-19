from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path


@dataclass(slots=True)
class SeenPaper:
    key: str
    paper_url: str
    source_id: str
    source_name: str
    seen_at: str


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_run_at TEXT
            );

            CREATE TABLE IF NOT EXISTS seen_papers (
                paper_key TEXT PRIMARY KEY,
                paper_url TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                seen_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def get_last_run_at(self) -> datetime | None:
        row = self.conn.execute("SELECT last_run_at FROM runs WHERE id = 1").fetchone()
        if not row or not row["last_run_at"]:
            return None
        return datetime.fromisoformat(row["last_run_at"])

    def set_last_run_at(self, dt: datetime) -> None:
        self.conn.execute(
            "INSERT INTO runs (id, last_run_at) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_run_at = excluded.last_run_at",
            (dt.astimezone(UTC).isoformat(),),
        )
        self.conn.commit()

    def has_seen_paper(self, key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_papers WHERE paper_key = ?",
            (key,),
        ).fetchone()
        return row is not None

    def mark_paper_seen(self, paper: SeenPaper) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seen_papers
            (paper_key, paper_url, source_id, source_name, seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (paper.key, paper.paper_url, paper.source_id, paper.source_name, paper.seen_at),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
