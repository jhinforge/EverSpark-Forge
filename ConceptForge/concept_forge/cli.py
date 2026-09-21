from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .subjects import (
    SubjectValidationError,
    compile_subject,
    new_subject,
    validate_subject,
)


def _read_document(path: str) -> dict[str, Any]:
    selected = Path(path).expanduser()
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Subject file not found: {selected}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid subject JSON: {selected}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Subject document root must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="everspark concept")
    commands = parser.add_subparsers(dest="command", required=True)

    new_parser = commands.add_parser("new", help="create a blank Character Subject v1")
    new_parser.add_argument("subject_id")
    new_parser.add_argument("display_name")

    validate_parser = commands.add_parser("validate", help="validate a subject JSON file")
    validate_parser.add_argument("path")

    compile_parser = commands.add_parser("compile", help="compile a subject into prompt fragments")
    compile_parser.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            result: Any = new_subject(args.subject_id, args.display_name)
        elif args.command == "validate":
            document = validate_subject(_read_document(args.path))
            result = {
                "ok": True,
                "subject_id": document["subject_id"],
                "revision": document["revision"],
            }
        else:
            compiled = compile_subject(_read_document(args.path))
            result = {
                "ok": True,
                "subject_id": compiled.subject_id,
                "revision": compiled.revision,
                "positive_prompt": compiled.positive_prompt,
                "negative_prompt": compiled.negative_prompt,
            }
    except (ValueError, SubjectValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
