#!/usr/bin/env python3
"""Deploy application files to explicit, already-configured EC2 instances."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SERVICES = {'s3api', 'ssm'}

def aws(region, *args):
    if args[0] not in ALLOWED_SERVICES:
        raise ValueError('This deployment can only upload release files or execute SSM commands')
    result = subprocess.run(['aws', '--region', region, '--output', 'json', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'AWS operation failed: {args[0]}/{args[1]} (credentials/output are not logged)')
    return json.loads(result.stdout or '{}')

def validate(config, region):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{2,62}', config['artifactBucket']):
        raise ValueError('Configure the existing artifact bucket')
    if not re.fullmatch(rf'arn:aws:kms:{region}:\d{{12}}:key/[a-zA-Z0-9-]+', config['kmsKeyArn']):
        raise ValueError('Configure the existing regional KMS key ARN')
    targets=[]
    for tier in ['app','web']:
        ids=config[f'{tier}InstanceIds']
        if not isinstance(ids,list) or not ids or any(not isinstance(i,str) or not re.fullmatch(r'i-[a-f0-9]{8,17}',i) for i in ids):
            raise ValueError('Configure explicit existing EC2 instance IDs')
        targets.extend(ids)
    if len(set(targets)) != len(targets):
        raise ValueError('App/web instance lists must be distinct and contain no duplicates')

def run_command(region, instance, command):
    response=aws(region,'ssm','send-command','--instance-ids',instance,'--document-name','AWS-RunShellScript',
                 '--parameters',json.dumps({'commands':[command],'executionTimeout':['600']}),'--timeout-seconds','60')
    command_id=response['Command']['CommandId']
    for _ in range(138):
        results=aws(region,'ssm','list-command-invocations','--command-id',command_id,'--details')['CommandInvocations']
        if results:
            state=results[0]['Status']
            if state=='Success':return command_id
            if state not in ['Pending','InProgress','Delayed']:raise RuntimeError(f'SSM command {command_id} ended: {state}')
        time.sleep(5)
    raise RuntimeError(f'SSM command {command_id} timed out')

def install_command(tier,revision,installer):
    arguments=[tier,revision['bucket'],revision['key'],revision['version'],revision['sha256'],revision['release']]
    encoded=base64.b64encode(installer).decode()
    digest=hashlib.sha256(installer).hexdigest()
    # The installer is application code, not host/DB/infrastructure provisioning.
    return '\n'.join([
        'set -eu','set +x','umask 077','deploy_tmp=$(mktemp -d)',
        'trap \'rm -rf "$deploy_tmp"\' EXIT',
        f"printf '%s' '{encoded}' | base64 -d > \"$deploy_tmp/install.sh\"",
        f"printf '%s  %s\\n' '{digest}' \"$deploy_tmp/install.sh\" | sha256sum -c -",
        'bash "$deploy_tmp/install.sh" '+' '.join(shlex.quote(a) for a in arguments)])

def main():
    region=sys.argv[1]
    if region not in ['us-east-1','us-west-2']:raise ValueError('Unsupported region')
    config=json.loads((ROOT/'deploy/targets.json').read_text())[region]
    validate(config,region)
    content=(ROOT/'dist/manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest()!=os.environ['APPROVED_MANIFEST_SHA']:
        raise RuntimeError('Manifest changed after the security decision')
    manifest=json.loads(content);release=manifest['release']
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,99}',release):raise ValueError('Invalid release')
    installer=(ROOT/'scripts/install-release.sh').read_bytes()
    if hashlib.sha256(installer).hexdigest()!=manifest['installerSha256']:
        raise RuntimeError('Installer changed after the security decision')
    for tier in ['app','web']:
        if hashlib.sha256((ROOT/f'dist/{tier}.zip').read_bytes()).hexdigest()!=manifest['sha256'][tier]:
            raise RuntimeError('Bundle checksum mismatch')
    if aws(region,'s3api','get-bucket-versioning','--bucket',config['artifactBucket']).get('Status')!='Enabled':
        raise RuntimeError('Existing artifact bucket must have versioning enabled')
    for tier in ['app','web']:
        for instance in config[f'{tier}InstanceIds']:
            check=f'test -r /etc/kantin-orders/{tier}.env && command -v aws >/dev/null && command -v python3 >/dev/null'
            if tier=='app':check+=' && test -x /usr/local/bin/node && systemctl cat kantin-api.service >/dev/null && systemctl cat kantin-worker.service >/dev/null'
            else:check+=' && nginx -t'
            run_command(region,instance,check)
    uploaded={}
    for tier in ['app','web']:
        file=ROOT/f'dist/{tier}.zip'
        if hashlib.sha256(file.read_bytes()).hexdigest()!=manifest['sha256'][tier]:raise RuntimeError('Bundle checksum mismatch')
        key=f'releases/{release}/{tier}.zip'
        response=aws(region,'s3api','put-object','--bucket',config['artifactBucket'],'--key',key,'--body',str(file),'--server-side-encryption','aws:kms','--ssekms-key-id',config['kmsKeyArn'])
        version=response.get('VersionId','')
        if not re.fullmatch(r'[a-zA-Z0-9._-]+',version):raise RuntimeError('Upload must return an immutable S3 version')
        uploaded[tier]={'bucket':config['artifactBucket'],'key':key,'version':version,'sha256':manifest['sha256'][tier],'release':release}
    report={'region':region,'release':release,'status':'running','instances':[]}
    path=ROOT/'reports/deployment.json';path.parent.mkdir(exist_ok=True)
    try:
        for tier in ['app','web']:
            for instance in config[f'{tier}InstanceIds']:
                command_id=run_command(region,instance,install_command(tier,uploaded[tier],installer))
                report['instances'].append({'tier':tier,'instanceId':instance,'commandId':command_id})
                print(f'{tier} {instance}: deployed {release}',flush=True)
                path.write_text(json.dumps(report,indent=2)+'\n')
        report['status']='succeeded'
    except Exception:
        report['status']='failed'
        # Each failed host installer attempts to restore its prior local release.
        # Already-successful hosts are not silently redeployed after a build failure.
        raise
    finally:path.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
