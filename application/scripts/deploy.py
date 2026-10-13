#!/usr/bin/env python3
"""Jenkins-owned rolling EC2 deployment; SSM is command transport, S3 is storage."""
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
# Freeze group changes during a bounded rolling deployment, then restore prior settings.
PROCESSES = ['Launch', 'Terminate', 'HealthCheck', 'ReplaceUnhealthy',
             'AZRebalance', 'AlarmNotification', 'ScheduledActions']

def aws(region, *args, allow_missing=False):
    result = subprocess.run(['aws', '--region', region, '--output', 'json', *args], capture_output=True, text=True)
    if result.returncode:
        if allow_missing and args[:2] == ('ssm', 'get-parameter') and 'ParameterNotFound' in result.stderr:
            return None
        if args[:2] == ('ssm', 'put-parameter') and 'ParameterAlreadyExists' in result.stderr:
            raise RuntimeError('An existing regional deployment lease blocks this build; recover the recorded deployment before retrying')
        raise RuntimeError(f'AWS operation failed: {args[0]}/{args[1]} (inspect AWS/SSM status; credentials are not logged)')
    return json.loads(result.stdout or '{}')

def validate(config, region):
    if config['mode'] not in ['active', 'standby']:
        raise ValueError('Mode must be active or standby')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{2,62}', config['artifactBucket']):
        raise ValueError('Configure the regional artifact bucket')
    if not re.fullmatch(rf'arn:aws:kms:{region}:\d{{12}}:key/[a-zA-Z0-9-]+', config['kmsKeyArn']):
        raise ValueError('Configure the regional KMS key ARN')
    for tier in ['app', 'web']:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,255}', config[f'{tier}AsgName']):
            raise ValueError('Invalid ASG name')
        if not re.fullmatch(rf'arn:aws:elasticloadbalancing:{region}:\d{{12}}:targetgroup/[a-zA-Z0-9-]+/[a-f0-9]{{16}}', config[f'{tier}TargetGroupArn']):
            raise ValueError('Configure the regional target group ARN')
        if not re.fullmatch(r'/[a-zA-Z0-9/_-]+', config[f'{tier}ReleaseParameter']):
            raise ValueError('Configure the release parameter')
    if config['appAsgName'] == config['webAsgName'] or config['appReleaseParameter'] == config['webReleaseParameter']:
        raise ValueError('App and web must use distinct groups and release parameters')
    if not re.fullmatch(r'/[a-zA-Z0-9/_-]+', config['deploymentLeaseParameter']) or config['deploymentLeaseParameter'] in [config['appReleaseParameter'], config['webReleaseParameter']]:
        raise ValueError('Configure a distinct deployment lease parameter')
    if config['mode'] == 'active' and not re.fullmatch(r'i-[a-f0-9]{8,17}', config.get('migrationRunnerId') or ''):
        raise ValueError('Active mode requires a migration runner')
    if config.get('publicUrl'):
        parsed = urlsplit(config['publicUrl'])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Optional public URL must use HTTPS')

def run_command(region, instance, command, timeout=600):
    result = aws(region, 'ssm', 'send-command', '--instance-ids', instance,
                 '--document-name', 'AWS-RunShellScript', '--parameters',
                 json.dumps({'commands': [command], 'executionTimeout': [str(timeout)]}), '--timeout-seconds', '60')
    command_id = result['Command']['CommandId']
    for _ in range((timeout + 90) // 5):
        invocations = aws(region, 'ssm', 'list-command-invocations', '--command-id', command_id, '--details')['CommandInvocations']
        if invocations:
            state = invocations[0]['Status']
            if state == 'Success':
                return command_id
            if state not in ['Pending', 'InProgress', 'Delayed']:
                raise RuntimeError(f'SSM command {command_id} ended: {state}')
        time.sleep(5)
    raise RuntimeError(f'SSM command {command_id} timed out')

def validate_revision(revision):
    patterns = {'bucket': r'[a-z0-9.-]{3,63}', 'key': r'[a-zA-Z0-9/_-]+\.zip',
                'version': r'[a-zA-Z0-9._-]+', 'sha256': r'[a-f0-9]{64}', 'release': r'[a-zA-Z0-9][a-zA-Z0-9-]{0,99}'}
    for key, pattern in patterns.items():
        if not re.fullmatch(pattern, revision.get(key, '')):
            raise ValueError(f'Invalid release field: {key}')
    return revision

def install_command(tier, revision):
    validate_revision(revision)
    return '/usr/local/bin/kantin-release ' + ' '.join(shlex.quote(s) for s in [tier, revision['bucket'], revision['key'], revision['version'], revision['sha256'], revision['release']])

def inventory(region, config, tier):
    groups = aws(region, 'autoscaling', 'describe-auto-scaling-groups', '--auto-scaling-group-names', config[f'{tier}AsgName'])['AutoScalingGroups']
    if len(groups) != 1:
        raise RuntimeError('ASG was not found')
    group = groups[0]
    if config[f'{tier}TargetGroupArn'] not in group.get('TargetGroupARNs', []):
        raise RuntimeError('Target group is not attached to the expected ASG')
    instances = group['Instances']
    if len(instances) < 2 or len(instances) != group['DesiredCapacity'] or any(i['LifecycleState'] != 'InService' or i['HealthStatus'] != 'Healthy' for i in instances):
        raise RuntimeError('Deploy requires a stable ASG with at least two healthy InService instances')
    online = aws(region, 'ssm', 'describe-instance-information', '--filters', json.dumps([{'Key': 'InstanceIds', 'Values': [i['InstanceId'] for i in instances]}]))['InstanceInformationList']
    if {i['InstanceId'] for i in online if i['PingStatus'] == 'Online'} != {i['InstanceId'] for i in instances}:
        raise RuntimeError('Every target instance must be online in SSM')
    for instance in instances:
        command = f'test -x /usr/local/bin/kantin-release && test -r /etc/kantin-orders/{tier}.env'
        if tier == 'web':
            command += ' && test -x /usr/local/bin/kantin-configure-web && test -x /usr/local/bin/kantin-smoke'
        run_command(region, instance['InstanceId'], command, timeout=60)
    return group

def target_states(region, config, tier):
    return aws(region, 'elbv2', 'describe-target-health', '--target-group-arn', config[f'{tier}TargetGroupArn'])['TargetHealthDescriptions']

def roll_instance(region, config, tier, instance, revision, group, rollback=False):
    states = target_states(region, config, tier)
    match = next((s for s in states if s['Target']['Id'] == instance), None)
    if not match:
        raise RuntimeError('Target is not registered; stop and repair the group before deployment')
    members = {i['InstanceId'] for i in group['Instances']}
    healthy = {s['Target']['Id'] for s in states if s['Target']['Id'] in members and s['TargetHealth']['State'] == 'healthy'}
    if len(healthy - {instance}) < 1 and (not rollback or instance in healthy):
        raise RuntimeError('Rolling update would remove the last healthy ASG target')
    target = json.dumps([{'Id': instance, 'Port': match['Target']['Port']}])
    arn = config[f'{tier}TargetGroupArn']
    deregistered = False
    try:
        aws(region, 'elbv2', 'deregister-targets', '--target-group-arn', arn, '--targets', target)
        deregistered = True
        aws(region, 'elbv2', 'wait', 'target-deregistered', '--target-group-arn', arn, '--targets', target)
        command_id = run_command(region, instance, install_command(tier, revision))
    finally:
        if deregistered:
            aws(region, 'elbv2', 'register-targets', '--target-group-arn', arn, '--targets', target)
    aws(region, 'elbv2', 'wait', 'target-in-service', '--target-group-arn', arn, '--targets', target)
    return command_id

def current_revision(region, parameter):
    value = aws(region, 'ssm', 'get-parameter', '--name', parameter, allow_missing=True)
    return validate_revision(json.loads(value['Parameter']['Value'])) if value else None

def publish(region, parameter, revision):
    if revision is None:
        aws(region, 'ssm', 'delete-parameter', '--name', parameter)
    else:
        aws(region, 'ssm', 'put-parameter', '--name', parameter, '--type', 'String', '--overwrite', '--value', json.dumps(revision))

def main():
    region = sys.argv[1]
    if region not in ['us-east-1', 'us-west-2']:
        raise ValueError('Unexpected region')
    config = json.loads((ROOT / 'deploy/regions.json').read_text())[region]
    validate(config, region)
    content = (ROOT / 'dist/manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != os.environ['APPROVED_MANIFEST_SHA']:
        raise RuntimeError('Manifest changed after the security decision')
    manifest = json.loads(content)
    release = manifest['release']
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,99}', release):
        raise ValueError('Invalid release')
    if aws(region, 's3api', 'get-bucket-versioning', '--bucket', config['artifactBucket']).get('Status') != 'Enabled':
        raise RuntimeError('Artifact bucket versioning is required')
    lease = {'region': region, 'release': release, 'restoreProcesses': {}}
    lease_parameter = config['deploymentLeaseParameter']
    # Put without --overwrite acquires an atomic regional deployment lease.
    aws(region, 'ssm', 'put-parameter', '--name', lease_parameter, '--type', 'String', '--value', json.dumps(lease))
    suspended = {}
    published = []
    groups = {}
    previous = {}
    uploaded = {}
    affected = {'app': [], 'web': []}
    report = {'region': region, 'mode': config['mode'], 'release': release, 'status': 'running', 'instances': affected, 'revisions': uploaded, 'rollbackErrors': []}
    path = ROOT / 'reports/deployment.json'
    path.parent.mkdir(exist_ok=True)
    try:
        groups = {tier: inventory(region, config, tier) for tier in ['app', 'web']}
        previous = {tier: current_revision(region, config[f'{tier}ReleaseParameter']) for tier in groups}
        for tier in groups:
            file = ROOT / f'dist/{tier}.zip'
            if hashlib.sha256(file.read_bytes()).hexdigest() != manifest['sha256'][tier]:
                raise RuntimeError('Bundle checksum mismatch')
            key = f'releases/{release}/{tier}.zip'
            result = aws(region, 's3api', 'put-object', '--bucket', config['artifactBucket'], '--key', key, '--body', str(file), '--server-side-encryption', 'aws:kms', '--ssekms-key-id', config['kmsKeyArn'])
            uploaded[tier] = validate_revision({'bucket': config['artifactBucket'], 'key': key, 'version': result.get('VersionId', ''), 'sha256': manifest['sha256'][tier], 'release': release})
        # Persist recovery information before any group process is suspended.
        for tier, group in groups.items():
            existing = {p['ProcessName'] for p in group.get('SuspendedProcesses', [])}
            added = [p for p in PROCESSES if p not in existing]
            if added:
                suspended[tier] = added
                lease['restoreProcesses'][config[f'{tier}AsgName']] = added
        aws(region, 'ssm', 'put-parameter', '--name', lease_parameter, '--type', 'String', '--overwrite', '--value', json.dumps(lease))
        for tier, processes in suspended.items():
            aws(region, 'autoscaling', 'suspend-processes', '--auto-scaling-group-name', config[f'{tier}AsgName'], '--scaling-processes', *processes)
        if config['mode'] == 'active':
            rev = uploaded['app']
            command = '/usr/local/bin/kantin-migrate ' + ' '.join(shlex.quote(s) for s in [rev['bucket'], rev['key'], rev['version'], rev['sha256']])
            run_command(region, config['migrationRunnerId'], command, timeout=300)
        for tier, group in groups.items():
            published.append(tier)
            publish(region, config[f'{tier}ReleaseParameter'], uploaded[tier])
            for instance in group['Instances']:
                instance_id = instance['InstanceId']
                # Include the failing instance in rollback: it may have changed before health failed.
                affected[tier].append(instance_id)
                command_id = roll_instance(region, config, tier, instance_id, uploaded[tier], group)
                print(f'{region} {tier} {instance_id}: installed {release} (SSM {command_id})', flush=True)
                path.write_text(json.dumps(report, indent=2) + '\n')
        run_command(region, groups['web']['Instances'][0]['InstanceId'], '/usr/local/bin/kantin-smoke ' + ' '.join(shlex.quote(s) for s in [region, release, config['mode']]))
        if config.get('publicUrl') and config['mode'] == 'active':
            smoke(config['publicUrl'], region, release, True)
        report['status'] = 'succeeded'
    except Exception:
        report['status'] = 'failed'
        # Restore startup pointers first, then roll back web/app that were attempted.
        for tier in reversed(published):
            try:
                publish(region, config[f'{tier}ReleaseParameter'], previous[tier])
            except Exception as error:
                report['rollbackErrors'].append(f'{tier} pointer: {error}')
        for tier in ['web', 'app']:
            if affected[tier] and previous[tier] is None:
                report['rollbackErrors'].append(f'{tier}: first deployment has no published prior release; inspect and repair before retrying')
                continue
            for instance_id in reversed(affected[tier]):
                try:
                    roll_instance(region, config, tier, instance_id, previous[tier], groups[tier], rollback=True)
                except Exception as error:
                    report['rollbackErrors'].append(f'{tier} {instance_id}: {error}')
        raise
    finally:
        resume_errors = []
        for tier, processes in suspended.items():
            try:
                aws(region, 'autoscaling', 'resume-processes', '--auto-scaling-group-name', config[f'{tier}AsgName'], '--scaling-processes', *processes)
            except Exception:
                resume_errors.append(config[f'{tier}AsgName'])
        if not resume_errors:
            try:
                aws(region, 'ssm', 'delete-parameter', '--name', lease_parameter)
            except Exception:
                resume_errors.append('deployment lease cleanup failed')
        report['resumeErrors'] = resume_errors
        path.write_text(json.dumps(report, indent=2) + '\n')
        if resume_errors:
            raise RuntimeError('Manually restore recorded ASG processes: resume failed for ' + ', '.join(resume_errors))

if __name__ == '__main__':
    main()
