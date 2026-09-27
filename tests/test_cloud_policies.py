import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import cloud_policies


class CloudPolicyTests(unittest.TestCase):
    def setUp(self):
        self.digest = hashlib.sha256(b'policy source').hexdigest()
        self.state = {'schemaVersion':2,'deployment':1,'policies':[{
            'id':'sentinel-jev','version':1,'effect':'enforce','sha256':self.digest,
            'artifactUrl':'/enforcement/v1/artifacts/'+self.digest}]}

    def test_rejects_empty_unexpected_or_foreign_artifact(self):
        for bad in [{**self.state,'policies':[]}, {**self.state,'deployment':True},
                    {**self.state,'policies':[{**self.state['policies'][0],'artifactUrl':'https://elsewhere.example/policy'}]}]:
            with self.assertRaises(ValueError): cloud_policies.validate_state(bad)
        self.assertEqual(cloud_policies.validate_state(self.state)['version'],1)

    def test_only_successfully_evaluated_cloud_source_is_reported(self):
        value={"deployment":2,"sha256":"abc","path":"unused","effect":"enforce"}
        with patch.object(cloud_policies,"_applied_snapshot",None):
            cloud_policies.mark_evaluated(value,{"error":True,"cloud_policy":{"sha256":"abc"}})
            self.assertIsNone(cloud_policies.last_evaluated_deployment())
            cloud_policies.mark_evaluated(value,{"cloud_policy":{"sha256":"different"}})
            self.assertIsNone(cloud_policies.last_evaluated_deployment())
            cloud_policies.mark_evaluated(value,{"cloud_policy":{"sha256":"abc"}})
            self.assertEqual(cloud_policies.last_evaluated_deployment(),2)
            cloud_policies.mark_evaluated({**value,"deployment":1},{"cloud_policy":{"sha256":"abc"}})
            self.assertEqual(cloud_policies.last_evaluated_deployment(),2)

    def test_modified_source_is_rejected(self):
        cloud_policies.verify_source(b'policy source',self.digest)
        with self.assertRaises(ValueError):cloud_policies.verify_source(b'tampered source',self.digest)

    def test_policy_process_receives_no_cloud_or_model_credentials(self):
        with patch.dict(os.environ,{'JEV_API_KEY':'private','FAILPROOFAI_POLICY_TOKEN':'private','SENTINEL_API_TOKEN':'private'}):
            env=cloud_policies.runtime_environment(None)
            self.assertNotIn('JEV_API_KEY',env)
            self.assertNotIn('FAILPROOFAI_POLICY_TOKEN',env)
            self.assertNotIn('SENTINEL_API_TOKEN',env)

    def test_observe_records_cloud_verdict_but_enforce_uses_cloud_source(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'policies/sentinel-policies.mjs').read_text()
        # Isolated synthetic test: a distinct threshold proves which source ran.
        source=source.replace('j.prohibited >= 0.7','j.prohibited >= 0.8')
        context={'eventType':'UserPromptSubmit','payload':{'judgment':{
            'prohibited':0.75,'missing_context':0.01,'safe_reframing':0.01}}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.mjs';path.write_text(source)
            for mode in ['observe','enforce']:
                env=cloud_policies.runtime_environment({'path':str(path),'effect':mode,'id':'sentinel-jev','version':99,'deployment':99,'sha256':'test-only'})
                result=subprocess.run(['node',str(root/'policy_runtime.mjs')],input=json.dumps(context),text=True,capture_output=True,env=env,check=True)
                value=json.loads(result.stdout)
                if mode=='observe':
                    self.assertEqual(value['decision'],'deny')
                    self.assertEqual(value['observed'][0]['decision'],'allow')
                else:self.assertEqual(value['decision'],'allow')
                self.assertEqual(value['cloud_policy']['version'],99)


class CloudFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_cloud_key_cannot_silently_use_bundled_source(self):
        with patch.dict(os.environ,{'SENTINEL_REQUIRE_CLOUD_POLICY':'1'},clear=True):
            with self.assertRaises(RuntimeError):await cloud_policies.snapshot()

    async def test_failed_refresh_does_not_reuse_expired_snapshot(self):
        with patch.dict(os.environ,{'FAILPROOFAI_POLICY_TOKEN':'test','FAILPROOFAI_CLOUD_URL':'https://example.test','FAILPROOFAI_MACHINE_ID':'test'}), \
             patch.object(cloud_policies,'_cached',{'version':1}), \
             patch.object(cloud_policies,'_checked_at',0), \
             patch.object(cloud_policies.httpx,'AsyncClient',side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):await cloud_policies.snapshot()


if __name__ == '__main__':unittest.main()
