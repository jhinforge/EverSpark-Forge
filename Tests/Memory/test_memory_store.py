from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Memory"))

from everspark_memory import SQLiteMemoryStore  # noqa: E402


class SQLiteMemoryStoreTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
