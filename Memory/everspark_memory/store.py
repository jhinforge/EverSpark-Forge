from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
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
        self.subject_root = ((self.database.parent.parent if self.database.parent.name == "Memory" else self.database.parent) / "Subjects")
        self._subject_lock = threading.RLock()
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

                CREATE TABLE IF NOT EXISTS session_subjects (
                    session_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

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

                CREATE TABLE IF NOT EXISTS subject_prompts (
                    subject_id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subject_prompt_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id TEXT NOT NULL,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            # Older databases restricted each subject to one session. Rebuild
            # only that table so existing characters can be selected elsewhere.
            for index in connection.execute("PRAGMA index_list(session_subjects)").fetchall():
                if not index[2]:
                    continue
                columns = [row[2] for row in connection.execute(
                    f'PRAGMA index_info("{index[1]}")'
                ).fetchall()]
                if columns == ["subject_id"]:
                    connection.execute("""
                        CREATE TABLE session_subjects_new (
                            session_id TEXT PRIMARY KEY,
                            subject_id TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    connection.execute("""
                        INSERT INTO session_subjects_new
                        SELECT session_id, subject_id, created_at, updated_at FROM session_subjects
                    """)
                    connection.execute("DROP TABLE session_subjects")
                    connection.execute("ALTER TABLE session_subjects_new RENAME TO session_subjects")
                    break
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "subject_id" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN subject_id TEXT")
            # Move old prompt contracts into their own JSON records. Keep history readable.
            for subject_id, raw in connection.execute(
                "SELECT subject_id, document FROM subjects"
            ).fetchall():
                document = json.loads(raw)
                contract = document.pop("prompt_contract", None)
                if contract is None:
                    continue
                prompt = {
                    "positive_prompt": ", ".join(
                        [*contract.get("locked_traits", []), *contract.get("positive_terms", [])]
                    ),
                    "negative_prompt": ", ".join(contract.get("negative_terms", [])),
                }
                connection.execute(
                    "INSERT OR IGNORE INTO subject_prompts VALUES (?, ?, ?)",
                    (subject_id, json.dumps(prompt, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
                )
                connection.execute(
                    "UPDATE subjects SET document = ? WHERE subject_id = ?",
                    (json.dumps(document, ensure_ascii=False), subject_id),
                )
            for subject_id, revision, raw in connection.execute(
                "SELECT subject_id, revision, document FROM subject_revisions"
            ).fetchall():
                document = json.loads(raw)
                if document.pop("prompt_contract", None) is not None:
                    connection.execute(
                        "UPDATE subject_revisions SET document = ? WHERE subject_id = ? AND revision = ?",
                        (json.dumps(document, ensure_ascii=False), subject_id, revision),
                    )
            # Existing SQLite subjects are migrated once; completed folders become
            # the source of current content. SQLite retains revision history.
            for subject_id, revision, raw in connection.execute("SELECT subject_id, revision, document FROM subjects").fetchall():
                folder = self._subject_dir(subject_id)
                previous = self.subject_root / f".subject-prev-{subject_id}"
                if previous.is_dir():
                    if folder.is_dir() and self._read_folder(folder)[0]["revision"] == revision:
                        shutil.rmtree(previous)
                    else:
                        if folder.exists():
                            shutil.rmtree(folder)
                        os.replace(previous, folder)
                if folder.is_dir() and self._read_folder(folder)[0]["revision"] == revision:
                    continue
                if folder.exists():
                    shutil.rmtree(folder)
                prompt_row = connection.execute(
                    "SELECT document FROM subject_prompts WHERE subject_id = ?", (subject_id,)
                ).fetchone()
                prompts = json.loads(prompt_row[0]) if prompt_row else {}
                self._write_subject_files(json.loads(raw), prompts)

    def _subject_dir(self, subject_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", subject_id):
            raise ValueError("Invalid subject_id for storage")
        return self.subject_root / subject_id

    @staticmethod
    def _read_folder(folder: Path) -> tuple[dict[str, Any], dict[str, str]]:
        subject = json.loads((folder / "subject.json").read_text(encoding="utf-8"))
        subject["metadata"] = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        positive = json.loads((folder / "positive_prompt.json").read_text(encoding="utf-8"))
        negative = json.loads((folder / "negative_prompt.json").read_text(encoding="utf-8"))
        if not isinstance(positive.get("positive_prompt"), str) or not isinstance(negative.get("negative_prompt"), str):
            raise ValueError("Subject prompt files must contain strings")
        return subject, {"positive_prompt": positive["positive_prompt"], "negative_prompt": negative["negative_prompt"]}

    def _write_subject_files(self, document: dict[str, Any], prompts: dict[str, str]) -> Path | None:
        folder = self._subject_dir(document["subject_id"])
        self.subject_root.mkdir(parents=True, exist_ok=True)
        previous = self.subject_root / f".subject-prev-{document['subject_id']}"
        if previous.exists():
            raise RuntimeError(f"Subject update recovery is required: {previous}")
        stage = Path(tempfile.mkdtemp(prefix=".subject-stage-", dir=self.subject_root))
        try:
            files = {
                "subject.json": {key: value for key, value in document.items() if key != "metadata"},
                "metadata.json": document["metadata"],
                "positive_prompt.json": {"positive_prompt": prompts.get("positive_prompt", "")},
                "negative_prompt.json": {"negative_prompt": prompts.get("negative_prompt", "")},
            }
            for name, payload in files.items():
                (stage / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if folder.exists():
                os.replace(folder, previous)
            os.replace(stage, folder)
            return previous if previous.exists() else None
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            if previous.exists() and not folder.exists():
                os.replace(previous, folder)
            raise

    def get_subject_prompt(self, subject_id: str) -> dict[str, str] | None:
        with self._subject_lock:
            folder = self._subject_dir(subject_id)
            if folder.is_dir():
                return self._read_folder(folder)[1]
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT document FROM subject_prompts WHERE subject_id = ?", (subject_id,)
                ).fetchone()
            return json.loads(row[0]) if row else None

    def save_subject_prompt(self, subject_id: str, positive: str, negative: str) -> dict[str, str]:
        document = {"positive_prompt": positive, "negative_prompt": negative}
        with self._subject_lock:
            subject = self.get_subject(subject_id)
            if subject is None:
                raise ValueError(f"Subject not found: {subject_id}")
            previous = self._write_subject_files(subject, document)
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO subject_prompt_revisions(subject_id, document, created_at) VALUES (?, ?, ?)",
                        (subject_id, json.dumps(document, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
                    )
            except Exception:
                shutil.rmtree(self._subject_dir(subject_id))
                if previous:
                    os.replace(previous, self._subject_dir(subject_id))
                raise
            if previous:
                shutil.rmtree(previous)
        return document

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

    def get_or_create_session_subject_id(self, session_id: str) -> str:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT subject_id FROM session_subjects WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is not None:
                return str(row[0])
            subject_id = f"subject-{secrets.token_hex(8)}"
            connection.execute(
                """
                INSERT INTO session_subjects(session_id, subject_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, subject_id, now, now),
            )
        return subject_id

    def get_session_subject_id(self, session_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT subject_id FROM session_subjects WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def select_session_subject(self, session_id: str, subject_id: str) -> None:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        if not subject_id or self.get_subject(subject_id) is None:
            raise ValueError(f"Subject not found: {subject_id}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("""
                INSERT INTO session_subjects(session_id, subject_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    subject_id = excluded.subject_id,
                    updated_at = excluded.updated_at
            """, (session_id, subject_id, now, now))

    def record_conversation(
        self, session_id: str, user_text: str, assistant_text: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
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
                    (session_id, "assistant", assistant_text, now),
                ],
            )

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
            connection.execute(
                "DELETE FROM session_subjects WHERE session_id = ?", (session_id,)
            )

    def save_subject(self, document: dict[str, Any], prompts: dict[str, str] | None = None) -> dict[str, Any]:
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
        with self._subject_lock:
            folder = self._subject_dir(subject_id)
            previous: Path | None = None
            had_folder = folder.exists()
            wrote_folder = False
            try:
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
                    current_prompts = prompts if prompts is not None else (self.get_subject_prompt(subject_id) if had_folder else {})
                    previous = self._write_subject_files(document, current_prompts or {})
                    wrote_folder = True
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
                    if prompts is not None:
                        connection.execute(
                            "INSERT INTO subject_prompt_revisions(subject_id, document, created_at) VALUES (?, ?, ?)",
                            (subject_id, json.dumps(prompts, ensure_ascii=False), now),
                        )
            except Exception:
                if wrote_folder and folder.exists():
                    shutil.rmtree(folder)
                if previous and previous.exists():
                    os.replace(previous, folder)
                raise
            if previous:
                shutil.rmtree(previous)
        return document

    def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        with self._subject_lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT document FROM subjects WHERE subject_id = ?", (subject_id,)
                ).fetchone()
            if row is None:
                return None
            folder = self._subject_dir(subject_id)
            if folder.is_dir():
                return self._read_folder(folder)[0]
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
