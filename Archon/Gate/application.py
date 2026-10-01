"""Gate composes modules and routes the existing API to its business owner."""
from __future__ import annotations
from typing import Any
from pathlib import Path
from concept_forge.factory import create_service
from image_forge.factory import create_management
from concept_forge.workspace import ConceptWorkspace
from Aegis.Storage.service import StorageService
from orchestrator.core.orchestrator import Orchestrator
from orchestrator.core.task_runner import TaskRunner
from AudioForge.audio_forge.service import AudioService

class GateApplication:
    def __init__(self, config, logger=None, concept_logger=None):
        service, connections = create_service(config, concept_logger)
        self.concept = ConceptWorkspace(config, service, connections, concept_logger or logger)
        self.image = create_management(config)
        remote = config.get("remote_nodes", {})
        # Remote-only hosts must never fall back to local GPU execution.
        remote_concept = remote.get("concept_node_id") or remote.get("concept_instance_id")
        self.audio = AudioService(config) if (not remote_concept
            or remote.get("audio_node_id") or remote.get("audio_instance_id")) else None
        self.storage = StorageService(config)
        self.orchestrator = Orchestrator(TaskRunner(self.concept, self.image, self.audio), logger)

    def audio_path(self, filename):
        if self.audio is None:
            raise ValueError("Select an Audio Forge Node first")
        return self.audio.audio_path(filename)

    def resources(self, engine=""):
        # Combine independently owned resource catalogs only at the HTTP boundary.
        image = self.image.resources(engine)
        concept = self.concept.resources()
        image["defaults"].update(concept.pop("defaults"))
        return {**image, **concept}

    def image_health(self) -> dict[str, Any]:
        return self.image.image_health()

    def image_plugins(self) -> dict[str, Any]:
        return self.image.image_plugins()

    def image_plugin_job(self, job_id: str) -> dict[str, Any]:
        return self.image.image_plugin_job(job_id)

    def start_image_plugin(self, name: str, action: str) -> dict[str, Any]:
        return self.image.start_image_plugin(name, action)

    def set_default_image_plugin(self, name: str) -> dict[str, Any]:
        return self.image.set_default_image_plugin(name)

    def image_results(self, job_ids: list[str]) -> list[dict[str, Any]]:
        return self.image.image_results(job_ids)

    def image_history(self, limit: int) -> list[dict[str, str]]:
        return self.image.image_history(limit)

    def image_path(self, filename: str, subfolder: str, kind: str) -> Path:
        return self.image.image_path(filename, subfolder, kind)

    def storage_resources(self) -> dict[str, Any]:
        return self.storage.storage_resources()

    def export_data_archive(self) -> str:
        return self.storage.export_data_archive()

    def restore_data_archive(self, archive_id: str) -> dict[str, Any]:
        return self.storage.restore_data_archive(archive_id)

    def storage_scan(self) -> dict[str, Any]:
        return self.storage.storage_scan()

    def start_storage_scan(self) -> dict[str, Any]:
        return self.storage.start_storage_scan()

    def backup_resources(self) -> dict[str, Any]:
        return self.storage.backup_resources()

    def restore_points(self) -> list[dict[str, Any]]:
        return self.storage.restore_points()

    def start_restore(self, batch_id: str) -> dict[str, Any]:
        return self.storage.start_restore(batch_id)

    def save_storage_paths(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return self.storage.save_storage_paths(mapping)

    def start_backup(self, names: list[str], memory: bool = False,
                     targets: dict[str, str] | None = None, outputs: bool = False) -> dict[str, Any]:
        return self.storage.start_backup(names, memory, targets, outputs)

    def backup_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.storage.backup_job(job_id)

    def start_storage_pull(self, kind: str, name: str) -> dict[str, Any]:
        return self.storage.start_storage_pull(kind, name)

    def storage_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.storage.storage_job(job_id)

    def start_download(
        self,
        kind: str,
        url: str,
        filename: str = "",
        runtime_name: str = "",
    ) -> dict[str, Any]:
        return self.storage.start_download(kind, url, filename, runtime_name)

    def download_job(self, job_id: str = "") -> dict[str, Any] | None:
        return self.storage.download_job(job_id)

    def cancel_download(self, job_id: str) -> dict[str, Any]:
        return self.storage.cancel_download(job_id)

    def retry_download(self, job_id: str) -> dict[str, Any]:
        return self.storage.retry_download(job_id)

    def start_task(self, *args, **kwargs):
        return self.orchestrator.start_task(*args, **kwargs)

    def task_job(self, *args, **kwargs):
        return self.orchestrator.task_job(*args, **kwargs)

    def submit(self, *args, **kwargs):
        return self.orchestrator.submit(*args, **kwargs)

    def discuss(
        self,
        user_text: str,
        session_id: str,
        selection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.concept.discuss(user_text, session_id, selection)

    def get_session_subject(self, session_id: str) -> dict[str, Any] | None:
        return self.concept.get_session_subject(session_id)

    def select_session_subject(self, session_id: str, subject_id: str) -> dict[str, Any]:
        return self.concept.select_session_subject(session_id, subject_id)

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        return self.concept.get_history(session_id)

    def clear_memory(self, session_id: str) -> None:
        return self.concept.clear_memory(session_id)

    def save_subject(self, document: dict[str, Any]) -> dict[str, Any]:
        return self.concept.save_subject(document)

    def generate_subject(self, subject_id: str, user_text: str) -> dict[str, Any]:
        return self.concept.generate_subject(subject_id, user_text)

    def update_subject(
        self, subject_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        return self.concept.update_subject(subject_id, changes)

    def get_subject(self, subject_id: str) -> dict[str, Any]:
        return self.concept.get_subject(subject_id)

    def subject_bundle(self, subject_id: str) -> dict[str, Any]:
        return self.concept.subject_bundle(subject_id)

    def revise_subject_group(self, subject_id: str, group: str, instruction: str) -> dict[str, Any]:
        return self.concept.revise_subject_group(subject_id, group, instruction)

    def list_subjects(self) -> list[dict[str, Any]]:
        return self.concept.list_subjects()

    def get_subject_revisions(self, subject_id: str) -> list[dict[str, Any]]:
        return self.concept.get_subject_revisions(subject_id)

    def compile_subject(self, subject_id: str) -> dict[str, Any]:
        return self.concept.compile_subject(subject_id)

    def concept_connections(self) -> dict[str, Any]:
        return self.concept.concept_connections()

    def save_concept_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.concept.save_concept_connection(payload)

    def test_concept_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.concept.test_concept_connection(payload)

    def start_concept_connection_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.concept.start_concept_connection_test(payload)

    def concept_connection_test_job(self, job_id: str) -> dict[str, Any]:
        return self.concept.concept_connection_test_job(job_id)

    def remove_concept_connection(self, identifier: str) -> dict[str, Any]:
        return self.concept.remove_concept_connection(identifier)

    def default_concept_connection(self, identifier: str) -> dict[str, Any]:
        return self.concept.default_concept_connection(identifier)
