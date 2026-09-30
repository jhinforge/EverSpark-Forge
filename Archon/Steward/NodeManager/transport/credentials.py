"""Injectable secret storage. Persistent index files never contain bearer secrets."""
import os
from pathlib import Path


class FileCredential:
    def __init__(self, path):
        self.path = Path(path)

    def get(self):
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def set(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        with os.fdopen(os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    def delete(self):
        self.path.unlink(missing_ok=True)


class MemoryCredential:
    def __init__(self, values, key):
        self.values, self.key = values, key

    def get(self):
        return self.values.get(self.key)

    def set(self, value):
        self.values[self.key] = value

    def delete(self):
        self.values.pop(self.key, None)
