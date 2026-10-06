"""Private rclone import and user-selected model sources, independent of tunnels."""
from __future__ import annotations
from contextlib import nullcontext
import configparser
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from .import_config import parse_env, _render_env, _atomic_write

MANAGED = 'everspark-ui-image-models'
KEYS = ('EVERSPARK_STORAGE_BACKEND', 'RCLONE_CONFIG', 'RCLONE_BIN',
        'IMAGE_FORGE_RCLONE_REMOTE', 'CONCEPT_FORGE_RCLONE_REMOTE')
IMAGE_TYPES = {'checkpoint', 'diffusion_model', 'lora', 'vae'}


def parse_rclone(text):
    if not isinstance(text, str) or not 0 < len(text.encode('utf-8')) <= 45000:
        raise ValueError('Choose a rclone.conf file smaller than 45 KB')
    parser = configparser.RawConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text.lstrip('\ufeff'))
    except configparser.Error as exc:
        raise ValueError('Invalid rclone.conf format') from exc
    if not parser.sections() or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', s) or not parser.get(s, 'type', fallback='').strip() for s in parser.sections()):
        raise ValueError('Every rclone connection needs a valid name and type')
    return parser


class StorageConfiguration:
    def __init__(self, root, apply=None, run=subprocess.run, guard=None):
        self.root = Path(root)
        self.directory = self.root / 'Data/Configuration/rclone'
        self.draft = self.directory / 'import-draft.conf'
        self.selection = self.directory / 'selection.json'
        self.apply = apply or (lambda values: None)
        self.guard = guard or nullcontext
        self.run = run
        self.lock = threading.RLock()

    def values(self):
        path = self.root / '.env'
        values = parse_env(path) if path.is_file() else {}
        return {key: os.environ.get(key, values.get(key, '')) for key in KEYS}

    def status(self):
        with self.lock:
            values = self.values()
            try:
                selected = json.loads(self.selection.read_text(encoding='utf-8'))
            except FileNotFoundError:
                selected = {}
            if not isinstance(selected, dict):
                raise ValueError('Invalid saved cloud selection')
            active = Path(values['RCLONE_CONFIG']) if values['RCLONE_CONFIG'] else None
            source = self.draft if self.draft.is_file() else active
            remotes = []
            revision = ''
            if source and source.is_file():
                text = source.read_text(encoding='utf-8-sig')
                parser = parse_rclone(text)
                remotes = [{'name': s, 'type': parser.get(s, 'type')} for s in parser.sections() if source == self.draft or s != selected.get('managed_remote')]
                revision = hashlib.sha256(text.encode()).hexdigest()
            enabled = values['EVERSPARK_STORAGE_BACKEND'] == 'rclone' and bool(active and active.is_file()) and bool(values['IMAGE_FORGE_RCLONE_REMOTE'] or values['CONCEPT_FORGE_RCLONE_REMOTE'])
            # Existing CLI configuration remains usable without re-importing credentials.
            if not selected:
                selected = {'image_sources': [values['IMAGE_FORGE_RCLONE_REMOTE']] if values['IMAGE_FORGE_RCLONE_REMOTE'] else [],
                            'concept_source': values['CONCEPT_FORGE_RCLONE_REMOTE']}
            return {'enabled': enabled, 'imported': bool(remotes), 'remotes': remotes,
                    'revision': revision, 'selection': selected, 'binary': values['RCLONE_BIN']}

    def import_file(self, text):
        parse_rclone(text)
        with self.lock:
            _atomic_write(self.draft, text.lstrip('\ufeff').encode())
            return self.status()

    def source(self, revision):
        status = self.status()
        if not revision or revision != status['revision']:
            raise ValueError('Configuration changed; reload before saving')
        values = self.values()
        return self.draft if self.draft.is_file() else Path(values['RCLONE_CONFIG'])

    def executable(self, binary):
        candidate = binary or self.values()['RCLONE_BIN'] or shutil.which('rclone')
        if not candidate and os.name == 'nt' and Path('C:/rclone/rclone.exe').is_file():
            candidate = 'C:/rclone/rclone.exe'
        if not candidate or any(ord(c) < 32 for c in candidate) or not (shutil.which(candidate) or Path(candidate).is_file()):
            raise ValueError('rclone was not found. Select its executable path.')
        return str(candidate)

    def validate_path(self, path, parser):
        if not isinstance(path, str) or ':' not in path or any(ord(c) < 32 for c in path):
            raise ValueError('Select a valid cloud directory')
        remote, relative = path.split(':', 1)
        if remote not in parser.sections() or relative.startswith(('/', '\\')) or '\\' in relative or any(p in {'.', '..'} for p in relative.split('/')):
            raise ValueError('Select a directory from an imported connection')
        return path.rstrip('/')

    def listing(self, source, path, binary):
        try:
            result = self.run([self.executable(binary), 'lsjson', path, '--dirs-only', '--max-depth', '1',
                               '--config', str(source), '--contimeout', '5s', '--timeout', '10s', '--retries', '1'],
                              capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('Cloud directory request failed or timed out; check the connection') from exc
        if result.returncode:
            # rclone stderr may contain credential values; never send it to the browser.
            raise ValueError('Could not access this cloud directory; check credentials and path')
        try:
            entries = json.loads(result.stdout)
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError()
            return [e['Name'] for e in entries if e.get('IsDir') and isinstance(e.get('Name'), str)
                    and e['Name'] not in {'.', '..'} and '/' not in e['Name'] and '\\' not in e['Name']]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError('Invalid cloud directory response') from exc

    def browse(self, body):
        with self.lock:
            source = self.source(body.get('revision'))
            parser = parse_rclone(source.read_text(encoding='utf-8'))
            path = self.validate_path(body.get('path'), parser)
            return {'path': path, 'directories': self.listing(source, path, str(body.get('binary', '')).strip())}

    def save(self, body):
        with self.lock:
            source = self.source(body.get('revision'))
            text = source.read_text(encoding='utf-8')
            parser = parse_rclone(text)
            images = body.get('image_sources', [])
            if not isinstance(images, list) or len(images) > 8:
                raise ValueError('Select at most eight image model directories')
            images = list(dict.fromkeys(self.validate_path(p, parser) for p in images))
            source_types = body.get('image_source_types', {})
            if not isinstance(source_types, dict) or len(source_types) > 8:
                raise ValueError('Invalid image source types')
            if any(path not in images or not isinstance(kind, str) or kind not in IMAGE_TYPES
                   for path, kind in source_types.items()):
                raise ValueError('Choose a valid model type for each selected image directory')
            concept = body.get('concept_source', '')
            if not isinstance(concept, str):
                raise ValueError('Select a valid cloud directory')
            concept = self.validate_path(concept, parser) if concept else ''
            if not images and not concept:
                raise ValueError('Select at least one model directory')
            binary = self.executable(str(body.get('binary', '')).strip())
            for path in dict.fromkeys([*images, *([concept] if concept else [])]):
                self.listing(source, path, binary)
            previous = self.status()['selection'].get('managed_remote')
            # Only remove our own previous section in the active file. Imported
            # files are user-owned and must retain even similarly named remotes.
            if source != self.draft and previous and previous in parser:
                if any(path.split(':', 1)[0] == previous for path in [*images, concept]):
                    raise ValueError('Select a directory from an imported connection')
                text = re.sub(r'(?ms)^\[' + re.escape(previous) + r'\][^\n]*\n.*?(?=^\[|\Z)', '', text)
                parser.remove_section(previous)
            image_remote = images[0] if images else ''
            managed = ''
            if len(images) > 1:
                managed = MANAGED
                suffix = 1
                while managed in parser:
                    managed = f'{MANAGED}-{suffix}'
                    suffix += 1
                upstreams = ' '.join(json.dumps(p + ':ro', ensure_ascii=False) for p in images)
                text = text.rstrip() + f'\n\n[{managed}]\ntype = union\nupstreams = {upstreams}\nsearch_policy = epall\n'
                image_remote = managed + ':'
            if len(text.encode('utf-8')) > 45000:
                raise ValueError('Generated rclone configuration exceeds 45 KB')
            destination = self.directory / 'rclone.conf'
            values = {'EVERSPARK_STORAGE_BACKEND': 'rclone', 'RCLONE_CONFIG': str(destination),
                      'RCLONE_BIN': binary, 'IMAGE_FORGE_RCLONE_REMOTE': image_remote,
                      'CONCEPT_FORGE_RCLONE_REMOTE': concept}
            selected = {'image_sources': images, 'image_source_types': source_types,
                        'concept_source': concept, 'managed_remote': managed}
            self.commit(values, text, selected)
            return self.status()

    def commit(self, values, text, selected):
        with self.guard():
            self._commit(values, text, selected)

    def _commit(self, values, text, selected):
        # Retain every unrelated environment value and original rclone connection.
        env_path = self.root / '.env'
        env = parse_env(env_path) if env_path.is_file() else {}
        env.update(values)
        mapping_path = self.directory / 'model_paths.json'
        mapping = json.loads(mapping_path.read_text(encoding='utf-8')) if mapping_path.exists() else {}
        if not isinstance(mapping, dict):
            raise ValueError('Invalid saved directory mappings')
        previous_selection = self.status()['selection']
        if previous_selection.get('image_sources') != selected['image_sources']:
            mapping['image_manual'] = {}
        if previous_selection.get('concept_source') != selected['concept_source']:
            mapping['concept_manual'] = []
        mapping['image_source_types'] = selected.get('image_source_types', {})
        paths = [self.directory / 'rclone.conf', env_path, self.selection, mapping_path]
        previous = {p: p.read_bytes() if p.exists() else None for p in paths}
        old_env = {key: os.environ.get(key) for key in values}
        try:
            _atomic_write(paths[0], text.encode())
            _atomic_write(env_path, _render_env(env))
            _atomic_write(self.selection, json.dumps(selected).encode())
            _atomic_write(mapping_path, json.dumps(mapping).encode())
            os.environ.update(values)
            self.apply(values)
        except Exception:
            for p, content in previous.items():
                if content is None:
                    p.unlink(missing_ok=True)
                else:
                    _atomic_write(p, content)
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            raise
        self.draft.unlink(missing_ok=True)
