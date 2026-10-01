"""Download a model directory through the persistence resource owner."""
from pathlib import Path


def download_snapshot(repo_id, directory):
    from huggingface_hub import snapshot_download
    return snapshot_download(repo_id=repo_id, local_dir=str(Path(directory).resolve()))


if __name__ == "__main__":
    import sys
    import json
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from Archon.Vault.runtime_config import load_config
    config = load_config()["audio_forge"]
    print(json.dumps({"directory": download_snapshot(config["model_repo"],
                                                    config["model_directory"])}))
