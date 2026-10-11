import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check-plan.py'


def check(actions):
    plan = {'resource_changes': [{'address': f'aws_instance.r{i}', 'change': {'actions': a}} for i, a in enumerate(actions)]}
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'plan.json'
        path.write_text(json.dumps(plan))
        return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)


class CheckPlanTests(unittest.TestCase):
    def test_create_and_update_pass(self):
        self.assertEqual(check([['create'], ['update'], ['no-op']]).returncode, 0)

    def test_delete_is_blocked(self):
        result = check([['create'], ['delete']])
        self.assertEqual(result.returncode, 1)
        self.assertIn('aws_instance.r1', result.stdout)

    def test_replacement_is_blocked(self):
        self.assertEqual(check([['create', 'delete']]).returncode, 1)
        self.assertEqual(check([['delete', 'create']]).returncode, 1)


if __name__ == '__main__':
    unittest.main()
