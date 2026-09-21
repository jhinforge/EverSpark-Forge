from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, TextIO


OK_LEVEL = 25
logging.addLevelName(OK_LEVEL, "OK")

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "OK": OK_LEVEL,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
_SENSITIVE_KEY = re.compile(
    r"api[_-]?key|authorization|cookie|credential|passwd|password|secret|token",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"((?:api[_-]?key|authorization|cookie|credential|passwd|password|secret|token)\s*=\s*)\S+",
    re.IGNORECASE,
)
_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_EVENT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "1" if default else "0")
    if raw not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1")
    return raw == "1"


def _generate_run_id() -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    return f"{stamp}-{os.getpid()}-{os.urandom(3).hex()}"


def _redact_message(message: str) -> str:
    return _SENSITIVE_VALUE.sub(r"\1[REDACTED]", message)


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_message(value)
    if isinstance(value, Mapping):
        return _redact_fields(value)
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    return str(value)


def _redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in fields.items():
        if _SENSITIVE_KEY.search(str(key)):
            redacted[str(key)] = "[REDACTED]"
        else:
            redacted[str(key)] = _safe_value(value)
    return redacted


@dataclass(frozen=True)
class LogConfig:
    level: int
    format: str
    console: bool
    run_id: str

    @classmethod
    def from_env(cls) -> "LogConfig":
        level_name = os.environ.get("EVERSPARK_LOG_LEVEL", "INFO").upper()
        if level_name not in _LEVELS:
            raise ValueError(f"invalid EVERSPARK_LOG_LEVEL: {level_name}")

        output_format = os.environ.get("EVERSPARK_LOG_FORMAT", "text").lower()
        if output_format not in {"text", "json"}:
            raise ValueError(f"invalid EVERSPARK_LOG_FORMAT: {output_format}")

        run_id = os.environ.get("EVERSPARK_RUN_ID") or _generate_run_id()
        os.environ["EVERSPARK_RUN_ID"] = run_id
        return cls(
            level=_LEVELS[level_name],
            format=output_format,
            console=_env_bool("EVERSPARK_LOG_CONSOLE", True),
            run_id=run_id,
        )


class RecordFormatter(logging.Formatter):
    def __init__(self, output_format: str, run_id: str):
        super().__init__()
        self.output_format = output_format
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone().isoformat(
            timespec="seconds"
        )
        component = str(getattr(record, "component", record.name))
        event = str(getattr(record, "event", "message"))
        fields = _redact_fields(getattr(record, "fields", {}))
        message = _redact_message(record.getMessage())
        level = "WARN" if record.levelname == "WARNING" else record.levelname

        if self.output_format == "json":
            return json.dumps(
                {
                    "timestamp": timestamp,
                    "level": level,
                    "component": component,
                    "event": event,
                    "message": message,
                    "run_id": self.run_id,
                    "pid": record.process,
                    "fields": fields,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

        suffix = "".join(f" {key}={value}" for key, value in fields.items())
        return (
            f"{timestamp} {level:<5} {component} {event} "
            f"run_id={self.run_id} pid={record.process} message={message}{suffix}"
        )


class EverSparkLogger:
    def __init__(self, logger: logging.Logger, component: str):
        self._logger = logger
        self.component = component

    def _emit(
        self,
        level: int,
        event: str,
        message: str | None = None,
        **fields: Any,
    ) -> None:
        if message is None:
            message = event
            event = "message"
        if not _EVENT.fullmatch(event):
            raise ValueError(f"invalid log event: {event}")
        self._logger.log(
            level,
            message,
            extra={"component": self.component, "event": event, "fields": fields},
        )

    def debug(self, event: str, message: str | None = None, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, message, **fields)

    def info(self, event: str, message: str | None = None, **fields: Any) -> None:
        self._emit(logging.INFO, event, message, **fields)

    def ok(self, event: str, message: str | None = None, **fields: Any) -> None:
        self._emit(OK_LEVEL, event, message, **fields)

    def warning(self, event: str, message: str | None = None, **fields: Any) -> None:
        self._emit(logging.WARNING, event, message, **fields)

    warn = warning

    def error(self, event: str, message: str | None = None, **fields: Any) -> None:
        self._emit(logging.ERROR, event, message, **fields)

    def close(self) -> None:
        for handler in tuple(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)


def get_logger(
    component: str,
    log_file: str | Path | None = None,
    *,
    stream: TextIO | None = None,
    config: LogConfig | None = None,
) -> EverSparkLogger:
    if not _COMPONENT.fullmatch(component):
        raise ValueError(f"invalid log component: {component}")

    config = config or LogConfig.from_env()
    logger = logging.Logger(f"everspark.{component}", level=config.level)
    logger.propagate = False
    formatter = RecordFormatter(config.format, config.run_id)

    if config.console:
        console_handler = logging.StreamHandler(stream or sys.stderr)
        console_handler.setLevel(config.level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file is not None:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        path.touch(mode=0o640, exist_ok=True)
        path.chmod(0o640)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(config.level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return EverSparkLogger(logger, component)
