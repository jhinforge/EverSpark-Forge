"""Image Forge owns adapter construction and execution resource configuration."""
from pathlib import Path
from .adapters import create_engines, discover_plugins
from .gateway import ImageGateway
from .plugins import PluginManager
from .remote import RemoteImageGateway, RemoteImagePlugins


def create_management(config):
    from .management import ImageManagement
    settings = config["image_forge"]
    remote = config.get("remote_nodes", {})
    identity = remote.get("image_node_id") or int(remote.get("image_instance_id", 0))
    output = settings.get("output_directory", str(
        Path(config["memory"]["database"]).parents[1] / "Outputs"))
    manifests = discover_plugins()
    if identity:
        gateway = RemoteImageGateway(identity,
            str(remote.get("control_url", "http://127.0.0.1:8765")),
            output, str(settings.get("adapter", "comfyui")))
        engines = gateway.engines
        plugins = RemoteImagePlugins(gateway)
    else:
        engines = create_engines(settings["adapters"], config["workflow"], manifests)
        gateway = ImageGateway(engines, config["memory"]["database"], output,
            default_engine=str(settings.get("adapter", "")).strip().lower())
        plugins = PluginManager(manifests, gateway)
    manager = ImageManagement(gateway, plugins)
    manager.manifests = manifests
    manager.engines = engines
    return manager
