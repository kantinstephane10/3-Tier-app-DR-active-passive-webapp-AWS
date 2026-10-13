import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f'scripts/{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

deploy=module('deploy')
security=module('security')
CONFIG={'artifactBucket':'test-release-bucket','kmsKeyArn':'arn:aws:kms:us-east-1:123456789012:key/test-key','appInstanceIds':['i-aaaaaaaaaaaaaaaaa'],'webInstanceIds':['i-bbbbbbbbbbbbbbbbb']}

class DeploymentTests(unittest.TestCase):
    def test_explicit_target_inventory(self):
        deploy.validate(CONFIG,'us-east-1')
        for changes in [{'appInstanceIds':[]},{'webInstanceIds':CONFIG['appInstanceIds']},{'appInstanceIds':['not-an-instance']},{'kmsKeyArn':'arn:aws:kms:us-west-2:123456789012:key/test-key'}]:
            with self.assertRaises(ValueError):deploy.validate(CONFIG|changes,'us-east-1')

    def test_aws_service_allowlist_rejects_infrastructure_operations(self):
        with patch.object(deploy.subprocess,'run') as run:
            for service in ['rds','autoscaling','ec2','elbv2','secretsmanager']:
                with self.assertRaises(ValueError):deploy.aws('us-east-1',service,'create-resource')
            run.assert_not_called()

    def test_ssm_failure_stops_polling(self):
        with patch.object(deploy,'aws',side_effect=[{'Command':{'CommandId':'cmd'}},{'CommandInvocations':[{'Status':'Failed'}]}]),patch.object(deploy.time,'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'ended: Failed'):deploy.run_command('us-east-1','i-aaaaaaaaaaaaaaaaa','false')
            sleep.assert_not_called()

    def fixture(self,path):
        (path/'dist').mkdir();(path/'deploy').mkdir();(path/'scripts').mkdir()
        (path/'deploy/targets.json').write_text(json.dumps({'us-east-1':CONFIG}))
        installer=b'set -eu\necho release\n';(path/'scripts/install-release.sh').write_bytes(installer)
        hashes={}
        for tier in ['app','web']:
            value=f'{tier}-archive'.encode();(path/f'dist/{tier}.zip').write_bytes(value);hashes[tier]=hashlib.sha256(value).hexdigest()
        manifest={'release':'test-release','installerSha256':hashlib.sha256(installer).hexdigest(),'sha256':hashes}
        content=json.dumps(manifest).encode();(path/'dist/manifest.json').write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def test_changed_approved_content_blocks_cloud_calls(self):
        for file in ['dist/manifest.json','scripts/install-release.sh','dist/app.zip','dist/web.zip']:
            with self.subTest(file=file),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);approved=self.fixture(root)
                with (root/file).open('ab') as output:output.write(b'changed')
                with patch.object(deploy,'ROOT',root),patch.dict(os.environ,{'APPROVED_MANIFEST_SHA':approved}),patch('sys.argv',['deploy.py','us-east-1']),patch.object(deploy,'aws') as aws:
                    with self.assertRaises(RuntimeError):deploy.main()
                    aws.assert_not_called()

    def run_release(self,fail=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);approved=self.fixture(root);calls=[];commands=[]
            def aws(region,*args):
                calls.append(args)
                if args[1]=='get-bucket-versioning':return {'Status':'Enabled'}
                if args[1]=='put-object':return {'VersionId':'version-1'}
                raise AssertionError(args)
            def command(region,instance,body):
                commands.append((instance,body))
                if fail and body.startswith('set -eu'):raise RuntimeError('host failed')
                return 'command-id'
            with patch.object(deploy,'ROOT',root),patch.dict(os.environ,{'APPROVED_MANIFEST_SHA':approved}),patch('sys.argv',['deploy.py','us-east-1']),patch.object(deploy,'aws',side_effect=aws),patch.object(deploy,'run_command',side_effect=command):
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'host failed'):deploy.main()
                else:deploy.main()
            report=json.loads((root/'reports/deployment.json').read_text())
            return calls,commands,report

    def test_release_targets_app_then_web_and_only_uploads_existing_bucket(self):
        calls,commands,report=self.run_release()
        installs=[instance for instance,body in commands if body.startswith('set -eu')]
        self.assertEqual(installs,CONFIG['appInstanceIds']+CONFIG['webInstanceIds'])
        self.assertEqual([args[:2] for args in calls],[('s3api','get-bucket-versioning'),('s3api','put-object'),('s3api','put-object')])
        self.assertEqual(report['status'],'succeeded')
        self.assertTrue(all('sha256sum -c -' in body for instance,body in commands if body.startswith('set -eu')))

    def test_failed_app_stops_before_web_deployment(self):
        calls,commands,report=self.run_release(True)
        self.assertEqual([instance for instance,body in commands if body.startswith('set -eu')],CONFIG['appInstanceIds'])
        self.assertEqual(report['status'],'failed')

class SecurityPolicyTests(unittest.TestCase):
    def test_only_critical_requires_gate_and_unknown_is_conservative(self):
        for input_value,expected in [('low','LOW'),('moderate','MEDIUM'),('HIGH','HIGH'),('critical','CRITICAL'),('unknown','CRITICAL')]:
            self.assertEqual(security.severity(input_value),expected)
        with self.assertRaises(ValueError):security.severity('nonsense')

    def test_scanner_execution_errors_cannot_be_waived(self):
        result=subprocess.CompletedProcess(['trivy'],2,stdout='',stderr='failed')
        with patch.object(security.subprocess,'run',return_value=result):
            with self.assertRaisesRegex(RuntimeError,'incomplete scans cannot be waived'):security.command(['trivy'])

if __name__=='__main__':unittest.main()
