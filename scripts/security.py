#!/usr/bin/env python3
import collections
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def command(args, allowed=(0,)):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode not in allowed:
        raise RuntimeError(f'{args[0]} execution failed; incomplete scans cannot be waived')
    return result

def severity(value):
    value = str(value).upper()
    value = {'MODERATE': 'MEDIUM', 'INFO': 'LOW'}.get(value, value)
    if value == 'UNKNOWN':
        return 'CRITICAL'
    if value not in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
        raise ValueError('Unrecognized security severity')
    return value

def main():
    os.umask(0o077)
    reports = ROOT / 'reports/security'
    reports.mkdir(parents=True, exist_ok=True)
    for file in reports.glob('*.json'):
        file.unlink()
    if command(['git', 'rev-parse', '--is-shallow-repository']).stdout.strip() != 'false':
        raise RuntimeError('Disable shallow Git checkout')
    findings = []
    with tempfile.TemporaryDirectory(prefix='.security-private-', dir=ROOT) as temp:
        temp = Path(temp)
        for mode in ['git', 'dir']:
            path = temp / f'gitleaks-{mode}.json'
            command(['gitleaks', mode, '--no-banner', '--redact=100', '--exit-code=10',
                     '--config', str(ROOT / 'security/gitleaks.toml'), '--report-format=json',
                     '--report-path', str(path), str(ROOT)], (0, 10))
            result = json.loads(path.read_text())
            if not isinstance(result, list):
                raise ValueError('Invalid Gitleaks report')
            findings.extend({'tool': 'gitleaks', 'id': f['RuleID'], 'severity': 'CRITICAL'} for f in result)
        path = temp / 'trivy.json'
        command(['trivy', 'fs', '--config', str(ROOT / 'security/trivy.yaml'), '--ignorefile', '/dev/null',
                 '--scanners', 'vuln,misconfig', '--format', 'json', '--exit-code', '0', '--output', str(path), '.'])
        report = json.loads(path.read_text())
        if 'SchemaVersion' not in report or not isinstance(report.get('Results'), list):
            raise ValueError('Invalid Trivy report')
        for result in report['Results']:
            for finding in result.get('Vulnerabilities', []):
                findings.append({'tool': 'trivy', 'id': finding['VulnerabilityID'], 'package': finding['PkgName'], 'severity': severity(finding['Severity'])})
            for finding in result.get('Misconfigurations', []):
                if finding.get('Status') != 'PASS':
                    findings.append({'tool': 'trivy', 'id': finding['ID'], 'severity': severity(finding['Severity'])})
        audit = json.loads(command(['npm', 'audit', '--omit=dev', '--json'], (0, 1)).stdout)
        if audit.get('error') or not isinstance(audit.get('vulnerabilities'), dict):
            raise ValueError('npm audit failed')
        for name, finding in audit['vulnerabilities'].items():
            findings.append({'tool': 'npm-audit', 'id': name, 'package': name, 'severity': severity(finding['severity'])})
    summary = {'scanComplete': True, 'criticalCount': sum(f['severity'] == 'CRITICAL' for f in findings),
               'counts': dict(collections.Counter(f['severity'] for f in findings))}
    (reports / 'findings.json').write_text(json.dumps(findings, indent=2) + '\n')
    (reports / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
