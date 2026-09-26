"""OpenAI Chat Completions wire format for user-configured compatible services."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..port import ChatRequest, ChatResponse, ConceptError
from ..trace import current_trace_id


def _upstream_error(exc: HTTPError, api_key: str) -> str:
    """Expose a bounded provider error while keeping credentials out of the UI."""
    message = f"OpenAI Compatible HTTP {exc.code}"
    try:
        body = json.loads(exc.read(8192).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return message
    if not isinstance(body, dict):
        return message
    # Some compatible gateways use {"code": ..., "message": ...} instead.
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    detail = error.get("message")
    if not isinstance(detail, str):
        return message
    detail = detail.replace(api_key, "[redacted]")
    detail = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [redacted]", detail)
    detail = " ".join(detail.split())[:300]
    return f"{message}: {detail}" if detail else message


def _stream_content(response: Any) -> str:
    """Collect standard Chat Completions SSE chunks into a single response."""
    pieces: list[str] = []
    size = 0
    for line in response:
        size += len(line)
        if size > 16 * 1024 * 1024:
            raise ValueError("stream_too_large")
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            return "".join(pieces)
        if not data:
            continue
        event = json.loads(data.decode("utf-8"))
        choices = event["choices"]
        if not choices:  # stream_options.include_usage sends a final usage-only chunk.
            continue
        content = choices[0]["delta"].get("content")
        if content is not None:
            if not isinstance(content, str):
                raise ValueError("invalid_delta")
            pieces.append(content)
    raise ValueError("missing_done")


class OpenAICompatibleAdapter:
    name = "openai_compatible"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.api_key = str(config["api_key"])
        self.model = str(config["model"])
        self.timeout = int(config.get("timeout", 180))
        self.json_mode = bool(config.get("json_mode", False))
        self.stream = config.get("stream", False) is True
        self.logger = config.get("_logger")
        self.trace_id = str(config.get("_trace_id", ""))

    def list_models(self) -> list[str]:
        # /models is optional on compatible services. This is the tested model ID.
        return [self.model]

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": request.messages,
            "stream": self.stream,
        }
        if self.stream:
            payload["stream_options"] = {"include_usage": True}
        if request.json_mode and self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        wire = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        started = time.monotonic()
        trace_id = self.trace_id or current_trace_id()
        if self.logger is not None:
            self.logger.info(
                "api.request", "Concept Forge request started",
                trace_id=trace_id, host=urlparse(self.base_url).hostname or "",
                model=payload["model"], path="/v1/chat/completions",
                stream=self.stream, json_mode="response_format" in payload,
            )
        try:
            with urlopen(wire, timeout=self.timeout) as response:
                result = (_stream_content(response) if self.stream else
                          json.loads(response.read().decode("utf-8")))
        except HTTPError as exc:
            error = _upstream_error(exc, self.api_key)
            if self.logger is not None:
                self.logger.error(
                    "api.http_error", "Concept Forge provider returned an error",
                    trace_id=trace_id, model=payload["model"], http_status=exc.code,
                    upstream_request_id=_safe_request_id(
                        exc.headers.get("x-request-id", "") if exc.headers else ""),
                    elapsed_ms=round((time.monotonic() - started) * 1000), error=error,
                )
            raise ConceptError(error) from exc
        except URLError as exc:
            if self.logger is not None:
                self.logger.error(
                    "api.connection_error", "Concept Forge could not reach provider",
                    trace_id=trace_id, model=payload["model"],
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    error_type=type(exc.reason).__name__,
                )
            raise ConceptError(f"OpenAI Compatible connection failed: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._log_response_error(trace_id, payload["model"], started, "invalid_json")
            raise ConceptError("OpenAI Compatible returned invalid JSON") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._log_response_error(trace_id, payload["model"], started, "invalid_stream")
            raise ConceptError("OpenAI Compatible returned an invalid stream") from exc
        if self.stream:
            content = result
        else:
            try:
                content = result["choices"][0]["message"]["content"]
            except (IndexError, KeyError, TypeError) as exc:
                self._log_response_error(trace_id, payload["model"], started, "invalid_chat_response")
                raise ConceptError("OpenAI Compatible returned an invalid chat response") from exc
        if not isinstance(content, str):
            self._log_response_error(trace_id, payload["model"], started, "non_text_response")
            raise ConceptError("OpenAI Compatible returned a non-text response")
        if self.logger is not None:
            self.logger.ok(
                "api.ok", "Concept Forge provider returned text",
                trace_id=trace_id, model=payload["model"], http_status=200,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
        return ChatResponse(content)

    def _log_response_error(self, trace_id: str, model: str, started: float, reason: str) -> None:
        if self.logger is not None:
            self.logger.error(
                "api.response_error", "Concept Forge received an invalid provider response",
                trace_id=trace_id, model=model, reason=reason,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )


def _safe_request_id(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value or "") else ""
