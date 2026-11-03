#!/usr/bin/env python3
"""Package checked-out sibling repositories without local secrets or databases."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

root = Path(__file__).resolve().parents[3]
if len(sys.argv) != 2:
    raise SystemExit('Usage: snapshot-source.py /absolute/path/to/new-source.tar.gz')
target = Path(sys.argv[1]).resolve()
manifest = {}
with tarfile.open(target, 'x:gz') as archive:
    for repo in ['tg_flow_bot', 'tg_flow_frontend', 'tg_flow_storage']:
        directory = root / repo
        files = subprocess.check_output([
            'git', '-C', str(directory), 'ls-files', '--cached', '--others',
            '--exclude-standard', '-z',
        ]).decode().split('\0')
        hashes = {}
        for name in sorted(set(files)):
            if not name:
                continue
            relative = Path(repo) / name
            path = root / relative
            if not path.is_file() or any(part in relative.parts for part in (
                'envs', '.venv', 'node_modules', '.git', '__pycache__',
            )):
                continue
            if (path.name == '.env' or
                path.name.startswith('.env.') and path.name != '.env.example' or
                '.sqlite3' in path.name):
                continue
            archive.add(path, arcname='src/' + str(relative), recursive=False)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[repo] = {
            'commit': subprocess.check_output([
                'git', '-C', str(directory), 'rev-parse', 'HEAD',
            ]).decode().strip(),
            'working_tree_sha256': hashes,
        }
    for name in ['README.md', 'MCP_AND_CLI.md', 'AGENTS.md']:
        archive.add(root / name, arcname='src/' + name)
    encoded = (json.dumps(manifest, indent=2) + '\n').encode()
    info = tarfile.TarInfo('source-manifest.json')
    info.size = len(encoded)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(encoded))
print('Created source snapshot:', target)
