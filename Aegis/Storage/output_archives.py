"""Node-owned asynchronous ZIPs with bounded retention and private download URLs."""
import ipaddress
import re
import secrets
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

TTL = 3600
MAX_BYTES = 2 * 1024 * 1024 * 1024


def validate_result(value):
    if not isinstance(value, dict) or value.get('status') not in {'preparing', 'ready', 'failed'}:
        raise ValueError('Invalid output archive response')
    if value['status'] == 'ready':
        address = urlsplit(value.get('url', ''))
        try:
            private = ipaddress.ip_address(address.hostname) in ipaddress.ip_network('100.64.0.0/10')
        except (ValueError, TypeError):
            private = False
        if address.scheme != 'http' or not private or address.username or address.password or address.path != '/archive':
            raise ValueError('Invalid private archive URL')
    return value


class OutputArchives:
    def __init__(self, outputs, directory=None):
        self.outputs = outputs
        self.directory = Path(directory or tempfile.mkdtemp(prefix='everspark-archives-'))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.inventories = {}
        self.lock = threading.RLock()

    def cleanup(self):
        with self.lock:
            now = time.time()
            for job_id, job in list(self.jobs.items()):
                if job['status'] != 'preparing' and job['expires'] <= now:
                    (self.directory / (job_id + '.zip')).unlink(missing_ok=True)
                    del self.jobs[job_id]
                    self.inventories.pop(job_id, None)
            # Also remove expired artifacts left by an earlier service process.
            for path in [*self.directory.glob('*.zip'), *self.directory.glob('*.part')]:
                if path.stem not in self.jobs and path.stat().st_mtime + TTL <= now:
                    path.unlink(missing_ok=True)

    def request(self, job_id=''):
        if not isinstance(job_id, str) or (job_id and not re.fullmatch('[0-9a-f]{32}', job_id)):
            raise ValueError('Invalid archive job')
        self.cleanup()
        with self.lock:
            if job_id:
                if job_id not in self.jobs:
                    raise ValueError('Archive expired or unavailable; prepare a new ZIP')
            else:
                # Repeated clicks share a running job; keep retained disk use bounded.
                for failed, job in list(self.jobs.items()):
                    if job['status'] == 'failed':
                        del self.jobs[failed]
                        self.inventories.pop(failed, None)
                for existing, job in self.jobs.items():
                    if job['status'] == 'preparing':
                        return {'job_id': existing, **job}
                inventory = []
                for file in self.outputs.files():
                    stat = file.stat()
                    inventory.append((str(file.relative_to(self.outputs.directory)), stat.st_size, stat.st_mtime_ns))
                for existing, job in self.jobs.items():
                    if job['status'] == 'ready' and self.inventories.get(existing) == inventory:
                        return {'job_id': existing, **job}
                if len(self.jobs) >= 4:
                    raise ValueError('Too many retained archives; retry after an archive expires')
                job_id = secrets.token_hex(16)
                self.jobs[job_id] = {'status': 'preparing', 'expires': int(time.time()) + TTL}
                self.inventories[job_id] = inventory
                threading.Thread(target=self._build, args=(job_id,), daemon=True).start()
            return {'job_id': job_id, **self.jobs[job_id]}

    def _build(self, job_id):
        path = self.directory / (job_id + '.zip')
        partial = path.with_suffix('.part')
        try:
            files = self.outputs.files()
            if not files:
                raise ValueError('No outputs available to archive')
            total = 0
            with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for file in files:
                    relative = file.relative_to(self.outputs.directory)
                    file = self.outputs.path(file.name, relative.parent.as_posix())
                    total += file.stat().st_size
                    if total > MAX_BYTES:
                        raise ValueError('Output archive exceeds 2 GiB')
                    archive.write(file, 'EverSpark-Outputs/' + relative.as_posix())
            if partial.stat().st_size > MAX_BYTES:
                raise ValueError('Output archive exceeds 2 GiB')
            partial.replace(path)
            with self.lock:
                self.jobs[job_id].update(status='ready', expires=int(time.time()) + TTL, bytes=path.stat().st_size, files=len(files))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            path.unlink(missing_ok=True)
            with self.lock:
                self.jobs[job_id].update(status='failed', error=str(exc), expires=int(time.time()) + TTL)
        finally:
            partial.unlink(missing_ok=True)

    def path(self, job_id):
        job = self.request(job_id)
        if job['status'] != 'ready':
            raise ValueError('Archive is not ready')
        return self.directory / (job_id + '.zip')
