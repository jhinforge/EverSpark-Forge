"""Compatibility adapter for the previous local Forge implementations.

The Orchestrator task runner consumes this boundary; remote Forge transports
can implement the same operations without changing task coordination.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from concept_forge.connections import ConceptConnections
from concept_forge.service import ConceptService
from image_forge.adapters import create_engines, discover_plugins
from image_forge.gateway import ImageGateway
from image_forge.port import ImageRequest
from image_forge.plugins import PluginManager

from .remote_concept import RemoteConceptConnections
from .remote_image import RemoteImageGateway, RemoteImagePlugins


class LocalForgeBindings:
    def __init__(self, config: dict[str, Any], concept_logger: Any = None):
        concept_config = config["concept_forge"]
        image_config = config["image_forge"]
        instance_id = int(config.get("remote_nodes", {}).get("concept_instance_id", 0))
        if instance_id:
            provider = str(concept_config.get("provider", "ollama"))
            if provider != "ollama":
                raise ValueError("Remote Concept Forge currently requires the Ollama provider")
            self.concept_connections = RemoteConceptConnections(
                concept_config, instance_id,
                str(config.get("remote_nodes", {}).get("control_url", "http://127.0.0.1:8765")),
                logger=concept_logger)
        else:
            self.concept_connections = ConceptConnections(concept_config, logger=concept_logger)
        self.concept = ConceptService(self.concept_connections.gateway)
        self.manifests = discover_plugins()
        output = image_config.get("output_directory", str(
            Path(config["memory"]["database"]).parents[1] / "Outputs"))
        remote_image_id = int(config.get("remote_nodes", {}).get("image_instance_id", 0))
        if remote_image_id:
            self.gateway = RemoteImageGateway(remote_image_id,
                str(config.get("remote_nodes", {}).get("control_url", "http://127.0.0.1:8765")),
                output, str(image_config.get("adapter", "comfyui")))
            self.engines = self.gateway.engines
            self.plugins = RemoteImagePlugins(self.gateway)
        else:
            self.engines = create_engines(image_config["adapters"], config["workflow"],
                                          self.manifests)
            self.gateway = ImageGateway(
                self.engines, config["memory"]["database"], output,
                default_engine=str(image_config.get("adapter", "")).strip().lower(),
            )
            self.plugins = PluginManager(self.manifests, self.gateway)

    @staticmethod
    def image_request(**kwargs: Any) -> ImageRequest:
        return ImageRequest(**kwargs)
