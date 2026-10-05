"""Construct Concept Forge execution connections from Vault configuration."""
from .connections import ConceptConnections
from .remote import RemoteConceptConnections
from .service import ConceptService
from .port import ConceptError


class UnavailableLocalConcept:
    name = "ollama"
    def __init__(self, model):
        self.model = model
    def list_models(self):
        return []
    def chat(self, request):
        raise ConceptError("Select a Concept Forge node or an OpenAI Compatible connection")


class APIOnlyConnections(ConceptConnections):
    def __init__(self, settings, logger=None):
        super().__init__(settings, logger=logger)
        self._disable_local()
    def _disable_local(self):
        self.gateway.adapters["ollama"] = UnavailableLocalConcept(self.configured["providers"]["ollama"]["model"])
    def _refresh(self):
        super()._refresh()
        self._disable_local()


def create_service(config, logger=None):
    settings = config["concept_forge"]
    remote = config.get("remote_nodes", {})
    identity = remote.get("concept_node_id") or int(remote.get("concept_instance_id", 0))
    if identity:
        connections = RemoteConceptConnections(settings, identity,
            str(remote.get("control_url", "http://127.0.0.1:8765")), logger=logger)
    else:
        connections = (APIOnlyConnections(settings, logger=logger) if remote.get("remote_only")
                       else ConceptConnections(settings, logger=logger))
    return ConceptService(connections.gateway, settings.get("max_model_retries", 3)), connections
