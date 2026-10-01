"""Construct Concept Forge execution connections from Vault configuration."""
from .connections import ConceptConnections
from .remote import RemoteConceptConnections
from .service import ConceptService


def create_service(config, logger=None):
    settings = config["concept_forge"]
    remote = config.get("remote_nodes", {})
    identity = remote.get("concept_node_id") or int(remote.get("concept_instance_id", 0))
    if identity:
        if str(settings.get("provider", "ollama")) != "ollama":
            raise ValueError("Remote Concept Forge currently requires the Ollama provider")
        connections = RemoteConceptConnections(settings, identity,
            str(remote.get("control_url", "http://127.0.0.1:8765")), logger=logger)
    else:
        connections = ConceptConnections(settings, logger=logger)
    return ConceptService(connections.gateway), connections
