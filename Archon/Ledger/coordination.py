"""Process-local consistency scopes shared by users of one persistence dataset."""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import sqlite3
import threading
from Aegis.Shared.errors import BusyError


class PersistenceCoordinator:
    def __init__(self, database):
        self.database = Path(database).expanduser().resolve()
        self._lock = threading.RLock()
        self._local = threading.local()

    @contextmanager
    def operation(self):
        """Protect one read/write unit, including nested Ledger calls."""
        with self._lock:
            self._local.depth = getattr(self._local, "depth", 0) + 1
            try:
                yield
            finally:
                self._local.depth -= 1

    @contextmanager
    def maintenance(self, *, blocking=True):
        """Exclude dataset operations during snapshot or replacement/rollback."""
        if getattr(self._local, "depth", 0) or not self._lock.acquire(blocking=blocking):
            raise BusyError("Persistent data is in use; retry the maintenance operation")
        try:
            yield
        finally:
            self._lock.release()

    @contextmanager
    def connection(self, *, timeout=5, row_factory=None):
        """Close every live-dataset connection before releasing its scope."""
        with self.operation():
            connection = sqlite3.connect(self.database, timeout=timeout)
            try:
                connection.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
                connection.row_factory = row_factory
                with connection:
                    yield connection
            finally:
                connection.close()


_registry_lock = threading.Lock()
_registry = {}


def coordinator_for(database):
    """Resolve the Ledger-owned coordinator independently from a database path."""
    path = Path(database).expanduser().resolve()
    key = os.path.normcase(str(path))
    with _registry_lock:
        if key not in _registry:
            _registry[key] = PersistenceCoordinator(path)
        return _registry[key]


def persistence_operation(method):
    @wraps(method)
    def protected(self, *args, **kwargs):
        with self.operation():
            return method(self, *args, **kwargs)
    return protected


def maintenance_operation(method):
    @wraps(method)
    def protected(self, *args, **kwargs):
        with self.coordination.maintenance():
            return method(self, *args, **kwargs)
    return protected
