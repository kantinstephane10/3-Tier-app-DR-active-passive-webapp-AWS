#!/usr/bin/env python3
"""Run scanners; publish metadata only, never source, secrets or Terraform values."""
import argparse
import collections
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/security'

def run_json(command, path, allowed=(0,)):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    # Scanner diagnostics can contain source/values. Keep them private, not in Jenkins logs.
    if result.returncode not in allowed:
        raise RuntimeError(f'{command[0]} scan failed (exit {result.returncode}); no risk waiver is permitted for incomplete scans')
    return json.loads(path.read_text())

def summarize_trivy(document):
    if not isinstance(document, dict) or not isinstance(document.get('Results'), list) or 'SchemaVersion' not in document:
        raise ValueError('Invalid Trivy report')
    findings = []
    for result in document.get('Results', []):
        for finding in result.get('Misconfigurations', []):
            if finding.get('Status') == 'PASS':
                continue
            severity = finding.get('Severity', 'UNKNOWN').upper()
            if severity not in ('UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'):
                raise ValueError('Invalid severity')
            cause = finding.get('CauseMetadata') or {}
            # Unknown/unrated findings require critical review; never silently downgrade them.
            # Location and rule text only: code snippets can contain values and are never copied.
            findings.append({'tool': 'trivy', 'check_id': finding.get('ID', 'unknown'),
                             'severity': 'CRITICAL' if severity == 'UNKNOWN' else severity,
                             'title': finding.get('Title', ''), 'resolution': finding.get('Resolution', ''),
                             'file': result.get('Target', ''), 'line': cause.get('StartLine') or '',
                             'resource': cause.get('Resource', ''), 'url': finding.get('PrimaryURL', '')})
    return findings

def summarize_gitleaks(report):
    if not isinstance(report, list):
        raise ValueError('Invalid Gitleaks report')
    # Secret, Match and Line fields are deliberately not copied.
    return [{'tool': 'gitleaks', 'check_id': item['RuleID'], 'severity': 'CRITICAL',
             'title': item.get('Description', 'Possible secret'), 'resolution': 'Revoke and rotate the credential, then remove it from Git history.',
             'file': item.get('File', ''), 'line': item.get('StartLine') or '',
             'resource': (item.get('Commit') or '')[:12], 'url': ''} for item in report]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['source', 'plan'])
    args = parser.parse_args()
    os.umask(0o077)
    REPORTS.mkdir(parents=True, exist_ok=True)
    if args.phase == 'source':
        for file in REPORTS.glob('*.json'):
            file.unlink()
    findings = []
    with tempfile.TemporaryDirectory(prefix='.security-private-', dir=ROOT) as temp:
        temp = Path(temp)
        if args.phase == 'source':
            if subprocess.run(['git', 'rev-parse', '--is-shallow-repository'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip() != 'false':
                raise RuntimeError('Full Git history is required; disable shallow checkout')
            for mode in ('git', 'dir'):
                path = temp / f'gitleaks-{mode}.json'
                report = run_json(['gitleaks', mode, '--no-banner', '--redact=100', '--exit-code=10',
                                   '--config', str(ROOT / 'security/gitleaks.toml'), '--report-format=json',
                                   '--report-path', str(path), str(ROOT)], path, (0, 10))
                findings.extend(summarize_gitleaks(report))
        target = ROOT if args.phase == 'source' else ROOT / 'environments/lab/plan.json'
        path = temp / 'trivy.json'
        report = run_json(['trivy', 'config', '--config', str(ROOT / 'security/trivy.yaml'),
                           '--ignorefile', '/dev/null', '--exit-code=0', '--format=json',
                           '--output', str(path), str(target)], path)
        findings.extend(summarize_trivy(report))
    output = {'phase': args.phase, 'scan_complete': True, 'findings': findings,
              'counts': dict(collections.Counter(f['severity'] for f in findings))}
    (REPORTS / f'{args.phase}.json').write_text(json.dumps(output, indent=2) + '\n')
    phases = [json.loads(path.read_text()) for path in sorted(REPORTS.glob('*.json')) if path.name != 'summary.json']
    all_findings = [f for phase in phases for f in phase['findings']]
    summary = {'scan_complete': True, 'phases': [p['phase'] for p in phases],
               'counts': dict(collections.Counter(f['severity'] for f in all_findings)),
               'critical_count': sum(f['severity'] == 'CRITICAL' for f in all_findings)}
    (REPORTS / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
