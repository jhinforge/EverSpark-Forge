from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config.config import ConfigError, load_config
from ..core.text import normalize_unicode


def request_json(
    url: str,
    timeout: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    method = "GET"
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except json.JSONDecodeError:
            return {"ok": False, "error": f"Orchestrator HTTP {exc.code}"}
    except URLError as exc:
        return {
            "ok": False,
            "error": f"无法连接 Orchestrator：{exc.reason}。请先运行 `everspark orchestrator start`。",
        }


def submit(
    base_url: str, text: str, timeout: int, session_id: str
) -> dict[str, Any]:
    return request_json(
        f"{base_url}/tasks",
        timeout,
        {"text": normalize_unicode(text), "session_id": session_id},
    )


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    settings = config["orchestrator"]
    base_url = f"http://{settings['host']}:{settings['port']}"
    timeout = int(settings.get("request_timeout", 600))
    session_id = str(config["memory"].get("default_session_id", "main"))
    print("EverSpark Orchestrator Console")
    print(f"当前会话：{session_id}")
    print("输入中文绘图需求并回车；/history 查看上下文；/clear 清空；/exit 退出。")
    while True:
        try:
            text = normalize_unicode(input("\nEverSpark > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if not text:
            continue
        if text.lower() in {"/exit", "/quit", "exit", "quit"}:
            print("已退出。")
            return 0
        if text.lower() == "/history":
            query = urlencode({"session_id": session_id})
            response = request_json(
                f"{base_url}/memory/history?{query}", timeout
            )
            if not response.get("ok"):
                print(f"[ERROR] {response.get('error', '未知错误')}")
                continue
            messages = response.get("messages", [])
            if not messages:
                print("当前会话没有上下文记录。")
            for message in messages:
                label = "你" if message["role"] == "user" else "Concept Forge"
                print(f"{label}: {message['content']}")
            continue
        if text.lower() in {"/clear", "/new"}:
            response = request_json(
                f"{base_url}/memory/clear",
                timeout,
                {"session_id": session_id},
            )
            if response.get("ok"):
                print("当前会话上下文已清空。")
            else:
                print(f"[ERROR] {response.get('error', '未知错误')}")
            continue

        response = submit(base_url, text, timeout, session_id)
        for notice in response.get("notices", []):
            print(notice)
        if not response.get("ok"):
            print(f"[ERROR] {response.get('error', '未知错误')}")
            continue
        result = response["result"]
        print(f"绘图模型：{result['model']}")
        print(f"已向 Image Forge 提交 {result['count']} 张图片：")
        for item in result["items"]:
            print(
                f"  [{item['index']}] prompt_id={item['prompt_id']} seed={item['seed']}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
