"""Compatibility module entry point for the portable Node Agent."""
from .agent import run
from .process_lock import identity_lock
from .settings import DATA_DIR

if __name__ == "__main__":
    with identity_lock(DATA_DIR):
        run()
