from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SQLiteMemoryStore:
    def __init__(self, database: str, max_history_messages: int = 20):
        self.database = Path(database).expanduser()
        self.max_history_messages = max(0, int(max_history_messages))
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                    ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    positive_prompt TEXT NOT NULL,
                    negative_prompt TEXT NOT NULL,
                    image_count INTEGER NOT NULL,
                    queue_items TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        if self.max_history_messages == 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM (
                    SELECT id, role, content
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (session_id, self.max_history_messages),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def record_success(
        self, session_id: str, user_text: str, result: dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        assistant_content = json.dumps(
            {
                "model": result["model"],
                "positive_prompt": result["positive_prompt"],
                "negative_prompt": result["negative_prompt"],
                "count": result["count"],
                "status": "over",
            },
            ensure_ascii=False,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (session_id, now, now),
            )
            connection.executemany(
                """
                INSERT INTO messages(session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (session_id, "user", user_text, now),
                    (session_id, "assistant", assistant_content, now),
                ],
            )
            connection.execute(
                """
                INSERT INTO tasks(
                    session_id, user_text, model, positive_prompt,
                    negative_prompt, image_count, queue_items, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_text,
                    result["model"],
                    result["positive_prompt"],
                    result["negative_prompt"],
                    result["count"],
                    json.dumps(result["items"], ensure_ascii=False),
                    now,
                ),
            )

    def clear_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
