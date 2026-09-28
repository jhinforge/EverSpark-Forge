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


class LocalForgeBindings:
    def __init__(self, config: dict[str, Any], concept_logger: Any = None):
        concept_config = config["concept_forge"]
        image_config = config["image_forge"]
        self.concept_connections = ConceptConnections(concept_config, logger=concept_logger)
        self.concept = ConceptService(self.concept_connections.gateway)
        self.manifests = discover_plugins()
        self.engines = create_engines(image_config["adapters"], config["workflow"],
                                      self.manifests)
        self.gateway = ImageGateway(
            self.engines, config["memory"]["database"],
            image_config.get("output_directory", str(
                Path(config["memory"]["database"]).parents[1] / "Outputs")),
            default_engine=str(image_config.get("adapter", "")).strip().lower(),
        )
        self.plugins = PluginManager(self.manifests, self.gateway)

    @staticmethod
    def image_request(**kwargs: Any) -> ImageRequest:
        return ImageRequest(**kwargs)
