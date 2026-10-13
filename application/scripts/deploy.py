#!/usr/bin/env python3
"""Deploy prebuilt, hash-checked revisions to existing EC2 Auto Scaling groups."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit
from smoke import smoke

ROOT = Path(__file__).resolve().parents[1]

def aws(region, *args):
    result = subprocess.run(['aws', '--region', region, '--output', 'json', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'AWS operation failed: {args[0]}/{args[1]} (inspect AWS deployment/SSM status; credentials are not logged)')
    return json.loads(result.stdout or '{}')

def validate(config, region):
    if config['mode'] not in ['active', 'standby']:
        raise ValueError('Mode must be active or standby')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{2,62}', config['artifactBucket']):
        raise ValueError('Configure the regional artifact bucket')
    if not re.fullmatch(rf'arn:aws:kms:{region}:\d{{12}}:key/[a-zA-Z0-9-]+', config['kmsKeyArn']):
        raise ValueError('Configure the regional KMS key ARN')
    for field in ['application', 'appDeploymentGroup', 'webDeploymentGroup']:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', config[field]):
            raise ValueError('Invalid CodeDeploy name')
    if config['mode'] == 'active' and not re.fullmatch(r'i-[a-f0-9]{8,17}', config.get('migrationRunnerId') or ''):
        raise ValueError('Active mode requires a migration runner')
    parsed = urlsplit(config['smokeUrl'])
    if parsed.scheme != 'https' or not parsed.hostname or 'REPLACE' in config['smokeUrl'] or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Configure a regional HTTPS smoke URL')

def migrate(region, config, key, version, digest):
    cmd = '/usr/local/bin/kantin-migrate ' + ' '.join(shlex.quote(s) for s in [config['artifactBucket'], key, version, digest])
    result = aws(region, 'ssm', 'send-command', '--instance-ids', config['migrationRunnerId'], '--document-name', 'AWS-RunShellScript', '--parameters', json.dumps({'commands': [cmd], 'executionTimeout': ['300']}), '--timeout-seconds', '60')
    command_id = result['Command']['CommandId']
    for attempt in range(72):
        status = aws(region, 'ssm', 'list-command-invocations', '--command-id', command_id, '--details')['CommandInvocations']
        if status:
            state = status[0]['Status']
            if state == 'Success':
                return
            if state not in ['Pending', 'InProgress', 'Delayed']:
                raise RuntimeError(f'Migration SSM command {command_id} ended: {state}')
        time.sleep(5)
    raise RuntimeError(f'Migration SSM command {command_id} timed out')

def main():
    region = sys.argv[1]
    if region not in ['us-east-1', 'us-west-2']:
        raise ValueError('Unexpected region')
    config = json.loads((ROOT / 'deploy/regions.json').read_text())[region]
    validate(config, region)
    manifest_bytes = (ROOT / 'dist/manifest.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != os.environ['APPROVED_MANIFEST_SHA']:
        raise RuntimeError('Manifest changed after the security decision')
    manifest = json.loads(manifest_bytes)
    release = manifest['release']
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,100}', release):
        raise ValueError('Invalid release')
    if aws(region, 's3api', 'get-bucket-versioning', '--bucket', config['artifactBucket']).get('Status') != 'Enabled':
        raise RuntimeError('Artifact bucket versioning is required')
    uploaded = {}
    for tier in ['app', 'web']:
        file = ROOT / f'dist/{tier}.zip'
        if hashlib.sha256(file.read_bytes()).hexdigest() != manifest['sha256'][tier]:
            raise RuntimeError('Bundle checksum mismatch')
        key = f'releases/{release}/{tier}.zip'
        result = aws(region, 's3api', 'put-object', '--bucket', config['artifactBucket'], '--key', key, '--body', str(file), '--server-side-encryption', 'aws:kms', '--ssekms-key-id', config['kmsKeyArn'])
        version = result.get('VersionId')
        if not version:
            raise RuntimeError('Upload did not return an immutable S3 version')
        uploaded[tier] = {'bucket': config['artifactBucket'], 'key': key, 'bundleType': 'zip', 'version': version}
    if config['mode'] == 'active':
        migrate(region, config, uploaded['app']['key'], uploaded['app']['version'], manifest['sha256']['app'])
    deployments = []
    for tier in ['app', 'web']:
        revision = {'revisionType': 'S3', 's3Location': uploaded[tier]}
        result = aws(region, 'deploy', 'create-deployment', '--application-name', config['application'], '--deployment-group-name', config[f'{tier}DeploymentGroup'], '--revision', json.dumps(revision), '--description', release, '--auto-rollback-configuration', json.dumps({'enabled': True, 'events': ['DEPLOYMENT_FAILURE', 'DEPLOYMENT_STOP_ON_ALARM']}))
        deployment_id = result['deploymentId']
        print(f'{region} {tier}: {deployment_id}', flush=True)
        aws(region, 'deploy', 'wait', 'deployment-successful', '--deployment-id', deployment_id)
        deployments.append({'tier': tier, 'deploymentId': deployment_id, 'revision': uploaded[tier]})
    report = {'region': region, 'mode': config['mode'], 'release': release, 'deployments': deployments}
    path = ROOT / 'reports/deployment.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n')
    smoke(config['smokeUrl'], region, release, config['mode'] == 'active')

if __name__ == '__main__':
    main()
