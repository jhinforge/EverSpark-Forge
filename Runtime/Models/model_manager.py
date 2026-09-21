from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("default_models.json")
STATE_PATH = REPO_ROOT / "Data" / "Runtime" / "Models" / "state.json"
MODELFILE_PATH = REPO_ROOT / "Data" / "Runtime" / "Models" / "ConceptForge.Modelfile"


class ModelManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    component: str
    source: str
    repo_id: str
    filename: str
    revision: str
    target: str
    license: str
    runtime_name: str = ""
    prompt_mode: str = ""
    architecture: str = ""

    @property
    def target_path(self) -> Path:
        candidate = (REPO_ROOT / self.target).resolve()
        data_root = (REPO_ROOT / "Data").resolve()
        try:
            candidate.relative_to(data_root)
        except ValueError as exc:
            raise ModelManagerError(
                f"Model target must remain under Data/: {self.target}"
            ) from exc
        return candidate


def load_specs(path: str | Path = DEFAULT_MANIFEST) -> list[ModelSpec]:
    selected = Path(path)
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelManagerError(f"Model manifest not found: {selected}") from exc
    except json.JSONDecodeError as exc:
        raise ModelManagerError(f"Invalid model manifest JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ModelManagerError("Model manifest schema_version must be 1")
    entries = payload.get("models")
    if not isinstance(entries, list) or not entries:
        raise ModelManagerError("Model manifest requires a non-empty models array")
    specs: list[ModelSpec] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ModelManagerError("Every model manifest entry must be an object")
        try:
            spec = ModelSpec(**entry)
        except TypeError as exc:
            raise ModelManagerError(f"Invalid model manifest entry: {exc}") from exc
        if spec.id in seen:
            raise ModelManagerError(f"Duplicate model id: {spec.id}")
        if spec.source != "huggingface":
            raise ModelManagerError(f"Unsupported model source: {spec.source}")
        if not spec.repo_id or not spec.filename or not spec.revision:
            raise ModelManagerError(f"Incomplete model source: {spec.id}")
        spec.target_path
        specs.append(spec)
        seen.add(spec.id)
    return specs


def select_specs(specs: list[ModelSpec], selection: str) -> list[ModelSpec]:
    if selection == "all":
        return specs
    component = {
        "concept": "concept_forge",
        "image": "image_forge",
    }.get(selection)
    if component is None:
        raise ModelManagerError(f"Unknown model selection: {selection}")
    selected = [spec for spec in specs if spec.component == component]
    if not selected:
        raise ModelManagerError(f"No models are configured for selection: {selection}")
    return selected


def model_status(spec: ModelSpec) -> dict[str, Any]:
    path = spec.target_path
    return {
        **asdict(spec),
        "path": str(path),
        "installed": path.is_file() and path.stat().st_size > 0,
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }


def _huggingface_download(spec: ModelSpec) -> str:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise ModelManagerError(
            "huggingface_hub is unavailable; run ./everspark setup"
        ) from exc
    return hf_hub_download(
        repo_id=spec.repo_id,
        filename=spec.filename,
        revision=spec.revision,
        local_dir=spec.target_path.parent,
    )


def download_models(
    specs: list[ModelSpec],
    downloader: Callable[[ModelSpec], str] = _huggingface_download,
) -> list[dict[str, Any]]:
    installed: list[dict[str, Any]] = []
    for spec in specs:
        target = spec.target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.stat().st_size > 0:
            installed.append(model_status(spec))
            continue
        try:
            downloaded = Path(downloader(spec)).resolve()
        except ModelManagerError:
            raise
        except Exception as exc:
            raise ModelManagerError(f"Model download failed for {spec.id}: {exc}") from exc
        if not downloaded.is_file() or downloaded.stat().st_size < 1:
            raise ModelManagerError(f"Downloaded model is missing or empty: {spec.id}")
        if downloaded != target:
            shutil.copyfile(downloaded, target)
        installed.append(model_status(spec))
    _write_state(installed)
    return installed


def _write_state(models: list[dict[str, Any]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "models": models,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def prepare_concept_runtime(
    specs: list[ModelSpec],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    candidates = [spec for spec in specs if spec.component == "concept_forge"]
    if len(candidates) != 1:
        raise ModelManagerError("Exactly one default Concept Forge model is required")
    spec = candidates[0]
    if not spec.target_path.is_file():
        raise ModelManagerError("Concept Forge model is not downloaded")
    if not spec.runtime_name:
        raise ModelManagerError("Concept Forge model requires runtime_name")
    ollama = shutil.which("ollama")
    if ollama is None:
        raise ModelManagerError(
            "Ollama is not installed; install it before importing the Concept Forge model"
        )
    MODELFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODELFILE_PATH.write_text(
        f"FROM {spec.target_path}\nPARAMETER num_ctx 8192\n",
        encoding="utf-8",
    )
    try:
        completed = run(
            [ollama, "create", spec.runtime_name, "-f", str(MODELFILE_PATH)],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise ModelManagerError(f"Could not start Ollama model import: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise ModelManagerError(f"Ollama model import failed: {detail}")
    return {
        "ok": True,
        "runtime": "ollama",
        "model": spec.runtime_name,
        "modelfile": str(MODELFILE_PATH),
    }


def plan(specs: list[ModelSpec]) -> list[dict[str, str]]:
    return [
        {
            "id": spec.id,
            "source": f"hf://{spec.repo_id}@{spec.revision}/{spec.filename}",
            "target": str(spec.target_path),
            "license": spec.license,
        }
        for spec in specs
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="EverSpark managed model installer")
    parser.add_argument("command", choices=("plan", "status", "download", "import-concept"))
    parser.add_argument("--models", choices=("all", "concept", "image"), default="all")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()
    try:
        all_specs = load_specs(args.manifest)
        selected = select_specs(all_specs, args.models)
        if args.command == "plan":
            result: Any = {"ok": True, "models": plan(selected)}
        elif args.command == "status":
            statuses = [model_status(spec) for spec in selected]
            result = {
                "ok": True,
                "ready": all(item["installed"] for item in statuses),
                "models": statuses,
            }
        elif args.command == "download":
            result = {"ok": True, "models": download_models(selected)}
        else:
            result = prepare_concept_runtime(all_specs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ModelManagerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
