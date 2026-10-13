import hashlib
import importlib.util
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
spec=importlib.util.spec_from_file_location('resume',Path(__file__).resolve().parents[1]/'scripts/resume-autoscaling.py')
resume=importlib.util.module_from_spec(spec);spec.loader.exec_module(resume)

class DeliveryTests(unittest.TestCase):
    def config(self, mode='active'):
        return {'mode':mode,'artifactBucket':'kt-orders-example',
                'kmsKeyArn':'arn:aws:kms:us-east-1:123456789012:key/test-key',
                'appAsgName':'app','webAsgName':'web',
                'appTargetGroupArn':'arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/app/0123456789abcdef',
                'webTargetGroupArn':'arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/web/0123456789abcdef',
                'appReleaseParameter':'/example/app','webReleaseParameter':'/example/web',
                'deploymentLeaseParameter':'/example/lease',
                'migrationRunnerId':'i-0123456789abcdef0','publicUrl':None}

    def fixture(self, root, mode):
        (root/'deploy').mkdir();(root/'dist').mkdir()
        (root/'deploy/regions.json').write_text(json.dumps({'us-east-1':self.config(mode)}))
        hashes={}
        for tier in ['app','web']:
            data=f'{tier}-fixture'.encode();(root/f'dist/{tier}.zip').write_bytes(data);hashes[tier]=hashlib.sha256(data).hexdigest()
        content=json.dumps({'release':'test-1','sha256':hashes}).encode();(root/'dist/manifest.json').write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def run_deployment(self, root, mode='active', fail_roll=False, previous=True, fail_smoke=False, expected=None):
        digest=self.fixture(root,mode)
        prior={'bucket':'kt-orders-example','key':'releases/old/app.zip','version':'old-version','sha256':'a'*64,'release':'old'} if previous else None
        groups={tier:{'Instances':[{'InstanceId':f'i-{tier}1'},{'InstanceId':f'i-{tier}2'}],
                      'SuspendedProcesses':[{'ProcessName':'ScheduledActions'}]} for tier in ['app','web']}
        events=[]
        def aws(region,*args,**kwargs):
            events.append(args)
            if args[1]=='get-bucket-versioning':return{'Status':'Enabled'}
            if args[1]=='put-object':return{'VersionId':'version-1'}
            return{}
        def roll(region,config,tier,instance,revision,group,rollback=False):
            events.append(('roll',tier,instance,revision['release'],rollback))
            if fail_roll and not rollback:raise RuntimeError('Installation failed')
            return 'command-1'
        def run(region,instance,command,timeout=600):
            events.append(('command',instance,command))
            if fail_smoke and 'kantin-smoke' in command:raise RuntimeError('Smoke failed')
            return 'command-1'
        with patch.object(deploy,'ROOT',root),patch('sys.argv',['deploy.py','us-east-1']),patch.dict(os.environ,{'APPROVED_MANIFEST_SHA':expected or digest}),patch.object(deploy,'aws',side_effect=aws),patch.object(deploy,'inventory',side_effect=lambda region,config,tier:groups[tier]),patch.object(deploy,'current_revision',return_value=prior),patch.object(deploy,'roll_instance',side_effect=roll),patch.object(deploy,'run_command',side_effect=run):
            if fail_roll or fail_smoke or expected:
                with self.assertRaises(RuntimeError):deploy.main()
            else:deploy.main()
        return events

    def test_severity_mapping(self):
        self.assertEqual(security.severity('high'),'HIGH');self.assertEqual(security.severity('moderate'),'MEDIUM');self.assertEqual(security.severity('unknown'),'CRITICAL')
        with self.assertRaises(ValueError):security.severity('unrecognized')

    def test_configuration_rejects_placeholders_and_http(self):
        config=self.config();deploy.validate(config,'us-east-1');config['artifactBucket']='REPLACE-ME'
        with self.assertRaises(ValueError):deploy.validate(config,'us-east-1')
        config=self.config();config['publicUrl']='http://example.invalid'
        with self.assertRaises(ValueError):deploy.validate(config,'us-east-1')

    def test_standby_skips_migration_and_rolls_app_before_web(self):
        with tempfile.TemporaryDirectory() as temp:events=self.run_deployment(Path(temp),'standby')
        self.assertFalse(any('kantin-migrate' in e[-1] for e in events if e[0]=='command'))
        self.assertEqual([e[1] for e in events if e[0]=='roll'],['app','app','web','web'])
        self.assertFalse(any(e[0]=='deploy' for e in events))

    def test_active_migrates_once_before_app_update(self):
        with tempfile.TemporaryDirectory() as temp:events=self.run_deployment(Path(temp))
        migrations=[i for i,e in enumerate(events) if e[0]=='command' and 'kantin-migrate' in e[-1]]
        self.assertEqual(len(migrations),1);self.assertLess(migrations[0],next(i for i,e in enumerate(events) if e[0]=='roll'))

    def test_changed_manifest_blocks_all_cloud_mutations(self):
        with tempfile.TemporaryDirectory() as temp:events=self.run_deployment(Path(temp),expected='0'*64)
        self.assertEqual(events,[])

    def test_failure_restores_pointer_rolls_back_and_resumes_only_added_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);events=self.run_deployment(root,fail_roll=True)
            report=json.loads((root/'reports/deployment.json').read_text())
        self.assertEqual(report['status'],'failed');self.assertEqual(report['rollbackErrors'],[])
        self.assertTrue(any(e[0]=='roll' and e[-1] is True and e[3]=='old' for e in events))
        for e in events:
            if len(e)>1 and e[1]=='resume-processes':self.assertNotIn('ScheduledActions',e)

    def test_smoke_failure_restores_both_tiers(self):
        with tempfile.TemporaryDirectory() as temp:events=self.run_deployment(Path(temp),fail_smoke=True)
        self.assertEqual({e[1] for e in events if e[0]=='roll' and e[-1] is True},{'app','web'})

    def test_first_release_failure_is_reported_without_fake_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);events=self.run_deployment(root,fail_roll=True,previous=False)
            report=json.loads((root/'reports/deployment.json').read_text())
        self.assertIn('first deployment',report['rollbackErrors'][0])
        self.assertTrue(any(len(e)>1 and e[1]=='resume-processes' for e in events))

    def test_removal_of_last_healthy_target_is_blocked(self):
        config=self.config();group={'Instances':[{'InstanceId':'i-one'},{'InstanceId':'i-two'}]}
        states=[{'Target':{'Id':'i-one','Port':8080},'TargetHealth':{'State':'healthy'}},
                {'Target':{'Id':'i-two','Port':8080},'TargetHealth':{'State':'unhealthy'}}]
        revision={'bucket':'kt-orders-example','key':'releases/new/app.zip','version':'v1','sha256':'a'*64,'release':'new'}
        with patch.object(deploy,'target_states',return_value=states),patch.object(deploy,'aws') as cloud:
            with self.assertRaisesRegex(RuntimeError,'last healthy'):deploy.roll_instance('us-east-1',config,'app','i-one',revision,group)
            cloud.assert_not_called()

    def test_register_target_runs_even_when_remote_install_fails(self):
        config=self.config();group={'Instances':[{'InstanceId':'i-one'},{'InstanceId':'i-two'}]}
        states=[{'Target':{'Id':i,'Port':8080},'TargetHealth':{'State':'healthy'}} for i in ['i-one','i-two']]
        revision={'bucket':'kt-orders-example','key':'releases/new/app.zip','version':'v1','sha256':'a'*64,'release':'new'}
        with patch.object(deploy,'target_states',return_value=states),patch.object(deploy,'aws',return_value={}) as cloud,patch.object(deploy,'run_command',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):deploy.roll_instance('us-east-1',config,'app','i-one',revision,group)
            self.assertEqual(cloud.call_args_list[-1].args[2],'register-targets')

    def test_recovery_cannot_resume_a_different_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,'active')
            state={'Parameter':{'Value':json.dumps({'region':'us-east-1','release':'someone-else','restoreProcesses':{'app':['Launch']}})}}
            with patch.object(resume,'ROOT',root),patch.object(resume,'aws',return_value=state) as cloud:
                with self.assertRaisesRegex(RuntimeError,'different deployment'):resume.recover('us-east-1','test-1')
                self.assertEqual(cloud.call_count,1)

    def test_recovery_restores_settings_but_retains_interrupted_release_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,'active')
            state={'Parameter':{'Value':json.dumps({'region':'us-east-1','release':'test-1','restoreProcesses':{'app':['Launch']}})}}
            with patch.object(resume,'ROOT',root),patch.object(resume,'aws',side_effect=[state,{}]) as cloud:
                resume.recover('us-east-1','test-1')
                self.assertEqual(cloud.call_count,2);self.assertEqual(cloud.call_args.args[2],'resume-processes')

if __name__=='__main__':unittest.main()
