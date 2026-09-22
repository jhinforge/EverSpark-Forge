from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Memory"))

from everspark_memory import (  # noqa: E402
    SQLiteMemoryStore,
    SubjectRevisionConflictError,
)


class SQLiteMemoryStoreTests(unittest.TestCase):
    def test_session_subject_is_automatic_stable_and_cleared_with_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteMemoryStore(str(Path(directory) / "memory.db"))
            first = store.get_or_create_session_subject_id("session-a")
            self.assertTrue(first.startswith("subject-"))
            self.assertEqual(store.get_or_create_session_subject_id("session-a"), first)
            self.assertNotEqual(
                store.get_or_create_session_subject_id("session-b"), first
            )
            store.clear_session("session-a")
            self.assertIsNone(store.get_session_subject_id("session-a"))

    def test_history_persists_and_clears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "memory.db"
            store = SQLiteMemoryStore(str(database), 20)
            result = {
                "model": "illustrious",
                "positive_prompt": "red hair",
                "negative_prompt": "bad quality",
                "count": 2,
                "items": [
                    {"index": 1, "prompt_id": "p1", "seed": 1},
                    {"index": 2, "prompt_id": "p2", "seed": 2},
                ],
            }
            store.record_success("main", "生成两张红发女孩", result)

            reopened = SQLiteMemoryStore(str(database), 20)
            history = reopened.get_history("main")
            self.assertEqual(
                [message["role"] for message in history], ["user", "assistant"]
            )
            self.assertIn("生成两张", history[0]["content"])

            reopened.clear_session("main")
            self.assertEqual(reopened.get_history("main"), [])

    def test_history_limit_is_applied_in_chronological_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteMemoryStore(str(Path(directory) / "memory.db"), 2)
            for number in range(2):
                store.record_success(
                    "main",
                    f"request-{number}",
                    {
                        "model": "illustrious",
                        "positive_prompt": f"prompt-{number}",
                        "negative_prompt": "negative",
                        "count": 1,
                        "items": [{"index": 1, "prompt_id": str(number), "seed": number}],
                    },
                )
            history = store.get_history("main")
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["content"], "request-1")
            self.assertEqual(history[1]["role"], "assistant")

    def test_subject_versions_are_persistent_and_sequential(self) -> None:
        example_path = (
            REPO_ROOT
            / "ConceptForge"
            / "Examples"
            / "character_subject.example.json"
        )
        document = json.loads(example_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteMemoryStore(str(Path(directory) / "memory.db"), 20)
            store.save_subject(document)
            self.assertEqual(store.get_subject("ember-keeper"), document)
            self.assertEqual(store.list_subjects()[0]["display_name"], "Ember Keeper")

            revision_two = json.loads(json.dumps(document))
            revision_two["revision"] = 2
            revision_two["appearance"]["hair"]["color"] = "silver"
            store.save_subject(revision_two)
            revisions = store.get_subject_revisions("ember-keeper")
            self.assertEqual([item["revision"] for item in revisions], [2, 1])

            with self.assertRaises(SubjectRevisionConflictError):
                store.save_subject(revision_two)


if __name__ == "__main__":
    unittest.main()
