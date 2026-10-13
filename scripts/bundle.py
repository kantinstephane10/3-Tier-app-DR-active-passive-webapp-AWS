#!/usr/bin/env python3
"""Build two EC2 release archives for the Jenkins rollout."""
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
    if tier == 'web':
        shutil.copytree(ROOT / 'public', stage / 'public')
        (stage / 'public/release.json').write_text(json.dumps({'release': release}) + '\n')
    else:
        app = stage / 'application'
        app.mkdir()
        for directory in ['src', 'public', 'node_modules']:
            shutil.copytree(ROOT / directory, app / directory)
        for filename in ['package.json', 'package-lock.json']:
            shutil.copy(ROOT / filename, app / filename)
        (app / 'release.json').write_text(json.dumps({'release': release}) + '\n')
    archive = DIST / f'{tier}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(stage.rglob('*')):
            if file.is_file():
                bundle.write(file, file.relative_to(stage).as_posix())
    shutil.rmtree(stage)
    print(tier, archive.stat().st_size, 'bytes')
manifest = {'release': release, 'installerSha256': hashlib.sha256((ROOT / 'scripts/install-release.sh').read_bytes()).hexdigest(), 'sha256': {tier: hashlib.sha256((DIST / f'{tier}.zip').read_bytes()).hexdigest() for tier in ['app', 'web']}}
(DIST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
