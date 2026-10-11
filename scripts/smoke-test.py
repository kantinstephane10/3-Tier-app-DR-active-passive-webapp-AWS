"""Smoke test after APPLY: web -> internal ALB -> app in each region, then CloudFront over HTTPS."""
import json
import subprocess
import sys
import time
import urllib.request

PROBE = ('cloud-init status --wait >/dev/null; '
         'curl -fsS --retry 12 --retry-delay 10 --retry-all-errors http://127.0.0.1/health; echo; '
         'curl -fsS --retry 12 --retry-delay 10 --retry-all-errors http://127.0.0.1/')


def aws(*args):
    return json.loads(subprocess.check_output(['aws', *args, '--output', 'json'], text=True))


def web_instance(region, group):
    # Auto Scaling may still be launching instances right after apply.
    for _ in range(30):
        groups = aws('autoscaling', 'describe-auto-scaling-groups', '--region', region,
                     '--auto-scaling-group-names', group)['AutoScalingGroups']
        ready = [i['InstanceId'] for g in groups for i in g['Instances'] if i['LifecycleState'] == 'InService']
        if ready:
            return ready[0]
        time.sleep(20)
    raise SystemExit(f'No InService web instance in {group}')


def run_on_instance(region, instance_id):
    # The SSM agent can need a few minutes to register a new instance.
    for attempt in range(20):
        try:
            command_id = aws('ssm', 'send-command', '--region', region, '--instance-ids', instance_id,
                             '--document-name', 'AWS-RunShellScript', '--timeout-seconds', '900',
                             '--parameters', json.dumps({'commands': [PROBE]}))['Command']['CommandId']
            break
        except subprocess.CalledProcessError:
            if attempt == 19:
                raise
            time.sleep(15)
    for _ in range(90):
        time.sleep(10)
        try:
            result = aws('ssm', 'get-command-invocation', '--region', region,
                         '--command-id', command_id, '--instance-id', instance_id)
        except subprocess.CalledProcessError:
            continue
        if result['Status'] not in ('Pending', 'InProgress', 'Delayed'):
            return result
    raise SystemExit(f'SSM command {command_id} did not finish on {instance_id}')


def main():
    out = json.load(open(sys.argv[1]))
    for key, info in out['regional']['value'].items():
        result = run_on_instance(info['region'], web_instance(info['region'], info['autoscaling_groups']['web']))
        message = result.get('StandardOutputContent', '')
        if result['Status'] != 'Success' or 'healthy' not in message or 'Kantin Tongue' not in message:
            raise SystemExit(f"{key}: application smoke test failed ({result['Status']}): {message}")
        print(f"{key} ({info['region']}): web -> internal ALB -> app passed")
    url = (out.get('cloudfront_url') or {}).get('value')
    if url:
        # New distributions take several minutes to deploy to edge locations.
        for attempt in range(30):
            try:
                body = urllib.request.urlopen(url, timeout=20).read().decode()
                if 'Kantin Tongue' not in body:
                    raise ValueError('Unexpected body')
                print('CloudFront HTTPS smoke test passed')
                break
            except Exception:
                if attempt == 29:
                    raise
                time.sleep(30)


if __name__ == '__main__':
    main()
