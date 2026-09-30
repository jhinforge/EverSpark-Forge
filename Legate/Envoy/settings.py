"""Portable Agent paths; provider bootstrap scripts may override them."""
import os
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("EVERSPARK_NODE_DATA_DIR", str(Path.home()/".everspark"/"node")))
TASK_JOURNAL = Path(os.environ.get("EVERSPARK_TASK_JOURNAL", str(DATA_DIR/"tasks.json")))
STARTUP_STATUS = Path(os.environ.get("EVERSPARK_STARTUP_STATUS", str(DATA_DIR/"startup.status")))
