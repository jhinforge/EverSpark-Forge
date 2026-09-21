from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Logging"))

from everspark_logging import LogConfig, get_logger  # noqa: E402


class EverSparkLoggingTests(unittest.TestCase):
    def test_json_contract_and_redaction(self) -> None:
        stream = io.StringIO()
        config = LogConfig(level=10, format="json", console=True, run_id="run-1")
        logger = get_logger("test.python", stream=stream, config=config)

        logger.info(
            "request.accepted",
            "Request token=plain-secret",
            request_id="abc",
            api_key="another-secret",
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["component"], "test.python")
        self.assertEqual(payload["event"], "request.accepted")
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["fields"]["request_id"], "abc")
        self.assertEqual(payload["fields"]["api_key"], "[REDACTED]")
        self.assertNotIn("plain-secret", stream.getvalue())
        self.assertNotIn("another-secret", stream.getvalue())

    def test_warning_name_and_non_json_field(self) -> None:
        stream = io.StringIO()
        config = LogConfig(level=10, format="json", console=True, run_id="run-warn")
        logger = get_logger("test.warning", stream=stream, config=config)
        logger.warning("request.slow", "Slow request", path=Path("/tmp/example"))

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["level"], "WARN")
        self.assertEqual(payload["fields"]["path"], "/tmp/example")

    def test_level_filter_and_compatibility_message(self) -> None:
        stream = io.StringIO()
        config = LogConfig(level=20, format="text", console=True, run_id="run-2")
        logger = get_logger("test.python", stream=stream, config=config)

        logger.debug("debug.hidden", "Hidden")
        logger.info("Compatibility message")

        output = stream.getvalue()
        self.assertNotIn("Hidden", output)
        self.assertIn("test.python message", output)
        self.assertIn("Compatibility message", output)

    def test_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.log"
            config = LogConfig(level=20, format="text", console=False, run_id="run-3")
            logger = get_logger("test.file", path, config=config)
            logger.ok("service.ready", "Ready")
            for handler in logger._logger.handlers:
                handler.flush()
            self.assertIn("service.ready", path.read_text(encoding="utf-8"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            logger.close()

    def test_invalid_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"EVERSPARK_LOG_LEVEL": "LOUD", "EVERSPARK_LOG_FORMAT": "text"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                LogConfig.from_env()

        with patch.dict(
            os.environ,
            {"EVERSPARK_LOG_LEVEL": "INFO", "EVERSPARK_LOG_FORMAT": "xml"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                LogConfig.from_env()


if __name__ == "__main__":
    unittest.main()
