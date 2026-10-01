"""Concept Memory API backed by the existing Ledger persistence implementation."""
from __future__ import annotations
import json
import secrets
from datetime import datetime, timezone
from typing import Any
from Archon.Ledger.store import SQLiteLedgerStore, SubjectRevisionConflictError

class SQLiteMemoryStore(SQLiteLedgerStore):
    def get_or_create_session_subject_id(self, session_id: str) -> str:
        return super().get_or_create_session_subject_id(session_id,
            f"subject-{secrets.token_hex(8)}")

    def _migrate_business_records(self, connection):
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

    def record_success(
        self, session_id: str, user_text: str, result: dict[str, Any]
    ) -> None:
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
        subject = result.get("subject")
        self.record_generation(session_id, user_text, assistant_content,
            {**result, "subject_id": subject.get("subject_id") if isinstance(subject, dict) else None})

    def list_subjects(self) -> list[dict[str, Any]]:
        rows = self.subject_records()
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
