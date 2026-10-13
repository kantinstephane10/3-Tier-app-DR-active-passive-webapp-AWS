#!/usr/bin/env python3
"""Build two EC2 CodeDeploy revisions. Dependencies are built once in CI."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
DIST.mkdir(exist_ok=True)
release = os.environ.get('RELEASE_ID', 'local')
if not release.replace('-', '').isalnum() or len(release) > 100:
    raise ValueError('Invalid release ID')
if not (ROOT / 'node_modules/pg/package.json').is_file():
    raise RuntimeError('Run npm ci --omit=dev --ignore-scripts before bundling')
for tier in ['app', 'web']:
    stage = DIST / f'stage-{tier}'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    shutil.copy(ROOT / f'deploy/{tier}/appspec.yml', stage / 'appspec.yml')
    shutil.copytree(ROOT / f'deploy/{tier}/hooks', stage / 'hooks')
    for hook in (stage / 'hooks').glob('*.sh'):
        hook.chmod(0o755)
    if tier == 'web':
        shutil.copytree(ROOT / 'public', stage / 'public')
    else:
        app = stage / 'application'
        app.mkdir()
        for directory in ['src', 'db', 'public', 'node_modules']:
            shutil.copytree(ROOT / directory, app / directory,
                            ignore=shutil.ignore_patterns('@electric-sql'))
        for filename in ['package.json', 'package-lock.json']:
            shutil.copy(ROOT / filename, app / filename)
        (app / 'deploy').mkdir()
        for filename in ['kantin-api.service', 'kantin-worker.service']:
            shutil.copy(ROOT / 'deploy' / filename, app / 'deploy' / filename)
        (app / 'release.json').write_text(json.dumps({'release': release}) + '\n')
    archive = DIST / f'{tier}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(stage.rglob('*')):
            if file.is_file():
                bundle.write(file, file.relative_to(stage).as_posix())
    shutil.rmtree(stage)
    print(tier, archive.stat().st_size, 'bytes')
manifest = {'release': release, 'sha256': {tier: hashlib.sha256((DIST / f'{tier}.zip').read_bytes()).hexdigest() for tier in ['app', 'web']}}
(DIST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
