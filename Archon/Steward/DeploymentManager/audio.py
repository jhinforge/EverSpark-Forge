"""Audio deployment reuses the registered-Node deployment and recovery flow."""
from .image import ImageDeploymentManager


class AudioDeploymentManager(ImageDeploymentManager):
    forge = "audio"
    label = "Audio Forge"
