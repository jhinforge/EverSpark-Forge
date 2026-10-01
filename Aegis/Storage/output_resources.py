"""Safe output-file lookup, bounded transfer and local cache ownership."""
from __future__ import annotations
import base64
import os
import tempfile
from pathlib import Path


class OutputResources:
    def __init__(self, directory, suffixes, max_bytes=100 * 1024 * 1024):
        self.directory = Path(directory).resolve()
        self.suffixes = frozenset(suffixes)
        self.max_bytes = max_bytes

    def path(self, filename, subfolder="", *, require_file=True):
        if not filename or Path(filename).name != filename:
            raise ValueError("Invalid output resource path")
        path = (self.directory / subfolder / filename).resolve()
        if self.directory not in path.parents or path.suffix.lower() not in self.suffixes:
            raise ValueError("Invalid output resource path")
        if require_file and not path.is_file():
            raise ValueError("Output resource is unavailable")
        return path

    def receive(self, filename, subfolder, read_chunk):
        target = self.path(filename, subfolder, require_file=False)
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".transfer-", suffix=".part", dir=target.parent)
        temporary = Path(temporary_name)
        offset, expected_size = 0, None
        try:
            with os.fdopen(fd, "wb") as stream:
                while True:
                    chunk = read_chunk(offset)
                    size = chunk["size"]
                    data = base64.b64decode(chunk["data"], validate=True)
                    if (not isinstance(size, int) or isinstance(size, bool)
                            or not 1 <= size <= self.max_bytes or not data
                            or offset + len(data) > size
                            or (expected_size is not None and expected_size != size)):
                        raise ValueError("Invalid output resource transfer")
                    expected_size = size
                    stream.write(data)
                    offset += len(data)
                    if offset == size:
                        break
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def chunk(self, filename, subfolder, offset, chunk_bytes=24576):
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("Invalid output resource offset")
        path = self.path(filename, subfolder)
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ValueError("Output resource exceeds transfer limit")
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(chunk_bytes)
        return {"size": size, "data": base64.b64encode(data).decode("ascii")}

    def files(self):
        files = []
        for path in self.directory.rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in self.suffixes:
                continue
            if self.directory not in path.resolve().parents:
                continue
            files.append(path)
        return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
