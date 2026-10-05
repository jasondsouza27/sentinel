"""Explicitly saved cases, stored only on the local machine."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class CaseStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, input_json TEXT NOT NULL,
                result_json TEXT NOT NULL, feedback TEXT, feedback_note TEXT
            )""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _record(row):
        return {
            "id": row[0], "created_at": row[1], "input": json.loads(row[2]),
            "result": json.loads(row[3]), "feedback": row[4], "feedback_note": row[5],
        }

    def save(self, submitted, result):
        case_id = uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)",
                       (case_id, created, json.dumps(submitted), json.dumps(result), None, None))
        return self.get(case_id)

    def list_cases(self):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
        return [self._record(row) for row in rows]

    def get(self, case_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return self._record(row) if row else None

    def feedback(self, case_id, verdict, note=""):
        if verdict not in ("correct", "incorrect", "unsure"):
            raise ValueError("Feedback must be correct, incorrect, or unsure")
        if len(note) > 1000:
            raise ValueError("Feedback note is too long")
        with self._connect() as db:
            changed = db.execute("UPDATE cases SET feedback = ?, feedback_note = ? WHERE id = ?",
                                 (verdict, note, case_id)).rowcount
        return bool(changed)

    def export(self, case_id):
        return self.get(case_id)

    def delete(self, case_id):
        with self._connect() as db:
            changed = db.execute("DELETE FROM cases WHERE id = ?", (case_id,)).rowcount
        return bool(changed)
