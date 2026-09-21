from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from log_manifest import (
    ManifestError,
    collect_log_status,
    configured_log_dir,
    configured_manifest_path,
    is_safe_regular_file,
    load_manifest,
    resolve_policy,
    rotated_files,
)


def _action(
    actions: list[dict[str, Any]],
    action: str,
    path: Path,
    *,
    reason: str,
    dry_run: bool,
) -> None:
    actions.append(
        {
            "action": action,
            "filename": path.name,
            "reason": reason,
            "dry_run": dry_run,
        }
    )


def _remove(
    path: Path,
    actions: list[dict[str, Any]],
    *,
    reason: str,
    dry_run: bool,
) -> None:
    _action(actions, "remove", path, reason=reason, dry_run=dry_run)
    if not dry_run:
        path.unlink(missing_ok=True)


def _maintain_entry(
    root: Path,
    manifest: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    now: float,
    dry_run: bool,
    environ: Mapping[str, str],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    path = root / str(entry["filename"])
    policy = resolve_policy(manifest, entry, environ)
    max_age_seconds = policy["max_age_days"] * 86400

    if os.path.lexists(path) and not is_safe_regular_file(path):
        _action(
            actions,
            "skip",
            path,
            reason="unsafe_file_type",
            dry_run=dry_run,
        )
        return actions

    for index, backup in rotated_files(path):
        age = max(0.0, now - backup.stat().st_mtime)
        if index > policy["keep_files"]:
            _remove(
                backup,
                actions,
                reason="exceeds_keep_files",
                dry_run=dry_run,
            )
        elif age > max_age_seconds:
            _remove(
                backup,
                actions,
                reason="exceeds_max_age",
                dry_run=dry_run,
            )

    if not path.is_file() or path.stat().st_size < policy["max_bytes"]:
        return actions

    oldest = path.with_name(f"{path.name}.{policy['keep_files']}")
    if oldest.exists():
        _remove(oldest, actions, reason="rotation_limit", dry_run=dry_run)

    for index in range(policy["keep_files"] - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        if not source.exists():
            continue
        _action(
            actions,
            "rename",
            source,
            reason=f"to_{target.name}",
            dry_run=dry_run,
        )
        if not dry_run:
            source.replace(target)

    first_backup = path.with_name(f"{path.name}.1")
    _action(actions, "copytruncate", path, reason=first_backup.name, dry_run=dry_run)
    if not dry_run:
        shutil.copy2(path, first_backup)
        with path.open("r+b") as handle:
            handle.truncate(0)
        path.chmod(0o640)
    return actions


def maintain_logs(
    manifest_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    *,
    dry_run: bool = False,
    now: float | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    manifest_file = Path(manifest_path or configured_manifest_path(env))
    root = Path(log_dir or configured_log_dir(env))
    manifest = load_manifest(manifest_file)
    timestamp = time.time() if now is None else now

    if not dry_run:
        root.mkdir(parents=True, exist_ok=True, mode=0o750)
    actions: list[dict[str, Any]] = []

    def run() -> None:
        for entry in manifest["logs"]:
            actions.extend(
                _maintain_entry(
                    root,
                    manifest,
                    entry,
                    now=timestamp,
                    dry_run=dry_run,
                    environ=env,
                )
            )

    if dry_run:
        run()
    else:
        lock_path = root / ".maintenance.lock"
        lock_fd = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o640,
        )
        with os.fdopen(lock_fd, "a+", encoding="utf-8") as lock:
            lock_path.chmod(0o640)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            run()

    return {
        "ok": True,
        "dry_run": dry_run,
        "actions": actions,
        "action_count": len(actions),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EverSpark managed log maintenance")
    parser.add_argument(
        "--manifest",
        default=str(configured_manifest_path()),
        help="Path to the logical log manifest.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(configured_log_dir()),
        help="Managed log directory.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Print managed log status as JSON.")
    rotate = subparsers.add_parser("rotate", help="Apply rotation and retention policy.")
    rotate.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "status":
            result = {
                "ok": True,
                **collect_log_status(args.manifest, args.log_dir),
            }
        else:
            result = maintain_logs(
                args.manifest,
                args.log_dir,
                dry_run=args.dry_run,
            )
    except (ManifestError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
