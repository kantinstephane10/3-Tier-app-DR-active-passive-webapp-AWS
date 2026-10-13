import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deploy
import security

class DeliveryTests(unittest.TestCase):
    def config(self, mode='active'):
        return {'mode':mode, 'artifactBucket':'kt-orders-example',
                'kmsKeyArn':'arn:aws:kms:us-east-1:123456789012:key/test-key',
                'application':'kt-orders', 'appDeploymentGroup':'app', 'webDeploymentGroup':'web',
                'migrationRunnerId':'i-0123456789abcdef0', 'smokeUrl':'https://primary.example.invalid'}

    def test_severity_mapping(self):
        self.assertEqual(security.severity('high'),'HIGH')
        self.assertEqual(security.severity('moderate'),'MEDIUM')
        self.assertEqual(security.severity('unknown'),'CRITICAL')
        with self.assertRaises(ValueError): security.severity('unrecognized')

    def test_configuration_rejects_placeholders_and_http(self):
        config=self.config(); deploy.validate(config,'us-east-1')
        config['artifactBucket']='REPLACE-ME'
        with self.assertRaises(ValueError): deploy.validate(config,'us-east-1')
        config=self.config();config['smokeUrl']='http://primary.example.invalid'
        with self.assertRaises(ValueError): deploy.validate(config,'us-east-1')

    def run_deployment(self, root, mode):
        (root/'deploy').mkdir();(root/'dist').mkdir()
        (root/'deploy/regions.json').write_text(json.dumps({'us-east-1':self.config(mode)}))
        hashes={}
        for tier in ['app','web']:
            data=f'{tier}-fixture'.encode();(root/f'dist/{tier}.zip').write_bytes(data);hashes[tier]=hashlib.sha256(data).hexdigest()
        content=json.dumps({'release':'test-1','sha256':hashes}).encode();(root/'dist/manifest.json').write_bytes(content)
        def aws(region,*args):
            if args[1]=='get-bucket-versioning':return{'Status':'Enabled'}
            if args[1]=='put-object':return{'VersionId':'version-1'}
            if args[1]=='create-deployment':return{'deploymentId':'d-test'}
            return{}
        with patch.object(deploy,'ROOT',root),patch('sys.argv',['deploy.py','us-east-1']),patch.dict(os.environ,{'APPROVED_MANIFEST_SHA':hashlib.sha256(content).hexdigest()}),patch.object(deploy,'aws',side_effect=aws) as cloud,patch.object(deploy,'migrate') as migrate,patch.object(deploy,'smoke'):
            deploy.main()
        return cloud,migrate

    def test_standby_skips_migration_and_deploys_app_before_web(self):
        with tempfile.TemporaryDirectory() as temp:
            cloud,migrate=self.run_deployment(Path(temp),'standby')
            migrate.assert_not_called()
            groups=[call.args[call.args.index('--deployment-group-name')+1] for call in cloud.call_args_list if 'create-deployment' in call.args]
            self.assertEqual(groups,['app','web'])

    def test_active_runs_migration_once(self):
        with tempfile.TemporaryDirectory() as temp:
            _,migrate=self.run_deployment(Path(temp),'active');migrate.assert_called_once()

    def test_changed_manifest_blocks_cloud_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'deploy').mkdir();(root/'dist').mkdir()
            (root/'deploy/regions.json').write_text(json.dumps({'us-east-1':self.config()}));(root/'dist/manifest.json').write_text('{}')
            with patch.object(deploy,'ROOT',root),patch('sys.argv',['deploy.py','us-east-1']),patch.dict(os.environ,{'APPROVED_MANIFEST_SHA':'0'*64}),patch.object(deploy,'aws') as cloud:
                with self.assertRaisesRegex(RuntimeError,'Manifest changed'):deploy.main()
                cloud.assert_not_called()

if __name__=='__main__':unittest.main()
