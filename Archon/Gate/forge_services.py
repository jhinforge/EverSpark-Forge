"""Compatibility composition of existing Forge services; resource policy stays in Forges."""
from concept_forge.factory import create_service
from image_forge.factory import create_management
from image_forge.port import ImageRequest


class ForgeServices:
    def __init__(self, config, concept_logger=None):
        self.concept, self.concept_connections = create_service(config, concept_logger)
        image = create_management(config)
        self.manifests, self.engines = image.manifests, image.engines
        self.gateway, self.plugins = image.gateway, image.plugins

    @staticmethod
    def image_request(**kwargs):
        return ImageRequest(**kwargs)
