from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path


class LearningMemory:
    """Small persistent feedback store used to improve later responses."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    response TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    feedback TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def record_interaction(
        self, prompt: str, response: str, score: int = 0, feedback: str = ""
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO interactions(prompt,response,score,feedback) VALUES(?,?,?,?)",
                (prompt, response, score, feedback.strip()),
            )

    def improvement_hints(self, prompt: str, limit: int = 5) -> str:
        words = {w for w in re.findall(r"[a-z0-9]+", prompt.lower()) if len(w) > 3}
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT prompt, feedback FROM interactions "
                "WHERE score < 0 AND feedback != '' ORDER BY id DESC LIMIT 50"
            ).fetchall()
        ranked = sorted(
            rows,
            key=lambda row: len(words & set(re.findall(r"[a-z0-9]+", row[0].lower()))),
            reverse=True,
        )
        hints = [row[1] for row in ranked[:limit] if row[1]]
        return "\n".join(dict.fromkeys(hints))

    def recent_context(self, limit: int = 6, char_limit: int | None = None) -> str:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT prompt,response FROM interactions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        turns = [f"User: {prompt}\nFaye: {response}" for prompt, response in rows]
        if char_limit is None:
            return "\n".join(reversed(turns))

        newest: list[str] = []
        length = 0
        for turn in turns:
            separator_length = 1 if newest else 0
            if length + separator_length + len(turn) > char_limit:
                break
            newest.append(turn)
            length += separator_length + len(turn)
        return "\n".join(reversed(newest))
