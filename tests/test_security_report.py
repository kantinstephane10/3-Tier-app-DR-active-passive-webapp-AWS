import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = load('security_report', 'security-report.py')
scan = load('security_scan', 'security-scan.py')


class SecurityReportTests(unittest.TestCase):
    def write(self, root, phase, findings):
        (root / f'{phase}.json').write_text(json.dumps({'phase': phase, 'findings': findings}))

    def test_table_sorted_by_severity_and_escaped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root, 'source', [
                {'tool': 'trivy', 'check_id': 'AWS-0178', 'severity': 'MEDIUM', 'title': 'Flow logs', 'file': 'a.tf', 'line': 3},
                {'tool': 'trivy', 'check_id': 'AWS-0104', 'severity': 'CRITICAL', 'title': '<script>x</script>', 'file': 'b.tf', 'line': 9,
                 'url': 'https://avd.aquasec.com/misconfig/aws-0104'}])
            (root / 'summary.json').write_text(json.dumps({'phases': ['source'], 'counts': {'CRITICAL': 1, 'MEDIUM': 1}, 'critical_count': 1}))
            report.main(root)
            page = (root / 'index.html').read_text()
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)
            self.assertLess(page.index('AWS-0104'), page.index('AWS-0178'))
            self.assertIn('href="https://avd.aquasec.com/misconfig/aws-0104"', page)
            findings, summary = report.load(root)
            text = report.console_table(findings, summary)
            self.assertIn('CRITICAL=1', text)
            self.assertLess(text.index('AWS-0104'), text.index('AWS-0178'))

    def test_empty_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root, 'source', [])
            report.main(root)
            self.assertIn('No findings.', (root / 'index.html').read_text())

    def test_gitleaks_secret_never_reaches_report(self):
        findings = scan.summarize_gitleaks([{'RuleID': 'aws-access-token', 'Description': 'AWS key', 'File': 'x.tf',
                                             'StartLine': 4, 'Secret': 'AKIAEXAMPLESECRET', 'Match': 'key = AKIAEXAMPLESECRET'}])
        self.assertEqual(findings[0]['severity'], 'CRITICAL')
        self.assertNotIn('AKIAEXAMPLESECRET', json.dumps(findings))


if __name__ == '__main__':
    unittest.main()
