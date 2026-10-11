import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

spec = importlib.util.spec_from_file_location('security_scan', Path(__file__).resolve().parents[1] / 'scripts/security-scan.py')
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

def trivy(severity):
    return {'SchemaVersion': 2, 'Results': [{'Misconfigurations': [
        {'ID': 'TEST-CHECK', 'Severity': severity, 'Status': 'FAIL', 'Code': 'secret-value'}]}]}

class SecurityPolicyTests(unittest.TestCase):
    def execute(self, root, phase, responses):
        with patch.object(scan, 'ROOT', root), patch.object(scan, 'REPORTS', root / 'reports'), \
             patch('sys.argv', ['security-scan.py', phase]), \
             patch.object(scan, 'run_json', side_effect=responses), \
             patch.object(scan.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'false\n')):
            scan.main()
        return json.loads((root / 'reports/summary.json').read_text())

    def test_noncritical_does_not_require_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.execute(root, 'source', [[], [], trivy('HIGH')])
            self.assertEqual(result['critical_count'], 0)
            self.assertEqual(result['counts']['HIGH'], 1)
            self.assertNotIn('secret-value', (root / 'reports/source.json').read_text())

    def test_critical_plan_aggregates_source_and_requires_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.execute(root, 'source', [[], [], trivy('MEDIUM')])
            result = self.execute(root, 'plan', [trivy('CRITICAL')])
            self.assertEqual(result['critical_count'], 1)
            self.assertEqual(result['counts']['MEDIUM'], 1)

    def test_secret_is_critical_and_redacted_from_published_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.execute(root, 'source', [[{'RuleID': 'test-secret', 'Secret': 'credential-value'}], [], trivy('LOW')])
            self.assertEqual(result['critical_count'], 1)
            self.assertNotIn('credential-value', (root / 'reports/source.json').read_text())

    def test_unknown_is_not_silently_downgraded(self):
        self.assertEqual(scan.summarize_trivy(trivy('UNKNOWN'))[0]['severity'], 'CRITICAL')

    def test_invalid_report_stops_build(self):
        with self.assertRaises(ValueError):
            scan.summarize_trivy({})

    def test_scanner_error_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(scan.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, '', 'private secret')):
                with self.assertRaisesRegex(RuntimeError, 'no risk waiver'):
                    scan.run_json(['trivy'], Path(temp) / 'missing.json')

if __name__ == '__main__':
    unittest.main()
