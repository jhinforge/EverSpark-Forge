from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SubjectRevisionConflictError(RuntimeError):
    pass


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
                    subject_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subjects (
                    subject_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subject_revisions (
                    subject_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(subject_id, revision)
                );

                CREATE INDEX IF NOT EXISTS idx_subject_revisions_subject_id
                    ON subject_revisions(subject_id, revision DESC);
                """
            )
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "subject_id" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN subject_id TEXT")

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
                "subject": result.get("subject"),
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
                    negative_prompt, image_count, queue_items, subject_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_text,
                    result["model"],
                    result["positive_prompt"],
                    result["negative_prompt"],
                    result["count"],
                    json.dumps(result["items"], ensure_ascii=False),
                    (
                        result.get("subject", {}).get("subject_id")
                        if isinstance(result.get("subject"), dict)
                        else None
                    ),
                    now,
                ),
            )

    def clear_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def save_subject(self, document: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise ValueError("Subject document must be an object")
        subject_id = document.get("subject_id")
        revision = document.get("revision")
        if not isinstance(subject_id, str) or not subject_id:
            raise ValueError("Subject document requires subject_id")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("Subject document requires a positive integer revision")

        serialized = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, created_at FROM subjects WHERE subject_id = ?",
                (subject_id,),
            ).fetchone()
            expected_revision = 1 if row is None else int(row[0]) + 1
            if revision != expected_revision:
                raise SubjectRevisionConflictError(
                    f"Subject {subject_id!r} requires revision {expected_revision}; "
                    f"received {revision}"
                )
            created_at = now if row is None else str(row[1])
            connection.execute(
                """
                INSERT INTO subjects(subject_id, revision, document, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(subject_id) DO UPDATE SET
                    revision = excluded.revision,
                    document = excluded.document,
                    updated_at = excluded.updated_at
                """,
                (subject_id, revision, serialized, created_at, now),
            )
            connection.execute(
                """
                INSERT INTO subject_revisions(subject_id, revision, document, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (subject_id, revision, serialized, now),
            )
        return document

    def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM subjects WHERE subject_id = ?", (subject_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_subjects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject_id, revision, document, created_at, updated_at
                FROM subjects
                ORDER BY updated_at DESC, subject_id ASC
                """
            ).fetchall()
        result = []
        for subject_id, revision, raw_document, created_at, updated_at in rows:
            document = json.loads(raw_document)
            result.append(
                {
                    "subject_id": subject_id,
                    "revision": revision,
                    "display_name": document.get("identity", {}).get(
                        "display_name", ""
                    ),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return result

    def get_subject_revisions(self, subject_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision, document, created_at
                FROM subject_revisions
                WHERE subject_id = ?
                ORDER BY revision DESC
                """,
                (subject_id,),
            ).fetchall()
        return [
            {
                "revision": revision,
                "document": json.loads(document),
                "created_at": created_at,
            }
            for revision, document, created_at in rows
        ]
