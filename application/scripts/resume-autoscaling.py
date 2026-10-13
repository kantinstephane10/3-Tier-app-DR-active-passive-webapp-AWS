#!/usr/bin/env python3
"""Recover only the ASG processes recorded by this exact Jenkins release."""
import json
from pathlib import Path
import re
import sys
from deploy import aws, PROCESSES, ROOT

def recover(region, release):
    if region not in ['us-east-1', 'us-west-2'] or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,99}', release):
        raise ValueError('Invalid region/release')
    config = json.loads((ROOT / 'deploy/regions.json').read_text())[region]
    parameter = config['deploymentLeaseParameter']
    state = aws(region, 'ssm', 'get-parameter', '--name', parameter, allow_missing=True)
    if state is None:
        return
    lease = json.loads(state['Parameter']['Value'])
    if lease['release'] != release or lease['region'] != region:
        raise RuntimeError('A different deployment owns the lease; do not resume or clear it from this build')
    expected = {config['appAsgName'], config['webAsgName']}
    for group, processes in lease['restoreProcesses'].items():
        if group not in expected or any(p not in PROCESSES for p in processes):
            raise ValueError('Recovery metadata does not match the deployment configuration')
    for group, processes in lease['restoreProcesses'].items():
        if processes:
            aws(region, 'autoscaling', 'resume-processes', '--auto-scaling-group-name', group, '--scaling-processes', *processes)
    # Agent loss may leave release work unfinished. Recovery deliberately retains the
    # lease until an operator checks targets and restores/accepts release pointers.
    print('Recorded ASG settings restored. Inspect the incomplete release before clearing the regional deployment lease.')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: resume-autoscaling.py REGION RELEASE')
    recover(sys.argv[1], sys.argv[2])
