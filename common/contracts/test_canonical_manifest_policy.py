"""Actual installed-owner policy/publication/projection regression."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from msplatform.backends.simion.native_completion import retention_api as native_policy
from msplatform.execution.retention import retention_api as generic_policy
from msplatform.execution.manifest_publication import publish_run_manifest
from msplatform.execution.manifest_verification import main as verify_main
from msplatform.io.manifest_records import verified_successful_run_reference

class CanonicalManifestPolicyTests(unittest.TestCase):
    def test_completed_failed_trace_requires_explicit_native_policy(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d); (run/'logs').mkdir()
            trace=run/'logs/simion__batch01.trace.log'; trace.write_text('status,Fly completed.\n',encoding='utf-8')
            (run/'retention_actions.json').write_text(json.dumps(dict(schema_version=1,role='artifact_retention_actions',retention_class='compact',status='complete',preserved=[dict(path='logs/simion__batch01.trace.log',bytes=trace.stat().st_size,retention_role='dense_trajectory',action='retained_completed_native_trace_for_recovery')])),encoding='utf-8')
            config=run/'run_config.json';config.write_text(json.dumps(dict(schema_version=2,run_id='20261017_120000__test__python__manifest-read-reuse',project='fixture',mode='test',inputs={},artifact_retention=dict(policy_version=1,**{'class':'compact'},reason=None))),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'explicit completion policy'):
                publish_run_manifest(config,'failed',retention_api=generic_policy)
            self.assertFalse((run/'run_manifest.json').exists())
            publish_run_manifest(config,'failed',retention_api=native_policy,output_paths=[trace])
            argv=['verify',str(run/'run_manifest.json'),'--require-status','failed']
            with patch('sys.argv',argv),contextlib.redirect_stdout(io.StringIO()):
                verify_main(retention_api=native_policy)
            with patch('sys.argv',argv),self.assertRaisesRegex(ValueError,'explicit completion policy'):
                verify_main(retention_api=generic_policy)
            trace.write_text('status,Fly incomplete.\n',encoding='utf-8')
            with patch('sys.argv',argv),self.assertRaises(AssertionError):
                verify_main(retention_api=native_policy)

    def test_consumed_projection_and_shared_reference_ignore_only_unconsumed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);a=run/'a.txt';b=run/'b.txt';a.write_text('a');b.write_text('b')
            c=run/'run_config.json';c.write_text(json.dumps(dict(schema_version=1,run_id='20261017_120000__test__python__manifest-read-reuse',project='fixture',mode='test',inputs={})))
            publish_run_manifest(c,'success',retention_api=generic_policy,output_paths=[a,b]);b.unlink()
            self.assertEqual(verified_successful_run_reference(run,'a.txt',project='fixture',mode='test'),a.resolve())
            argv=['verify',str(run/'run_manifest.json'),'--consumer-projection-id','fixture_v1','--consumed-output',str(a)]
            with patch('sys.argv',argv),contextlib.redirect_stdout(io.StringIO()):verify_main()
            with patch('sys.argv',['verify',str(run/'run_manifest.json')]),self.assertRaises(AssertionError):verify_main()
            a.write_text('x')
            with patch('sys.argv',argv),self.assertRaisesRegex(AssertionError,'SHA-256 changed'):verify_main()


    def test_admitted_candidate_schema2_binds_native_policy_for_both_publishers(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import finalize_candidate_run, _write_manifest
        for direct in (False, True):
            with self.subTest(direct=direct), tempfile.TemporaryDirectory() as directory:
                run=Path(directory)/'20261110_120000__test__python__candidate-manifest-policy'
                (run/'logs').mkdir(parents=True)
                (run/'inputs').mkdir()
                request=run/'inputs/execution_request.json'
                request.write_text('{}',encoding='utf-8')
                trace=run/'logs/simion__batch01.trace.log'
                trace.write_text('status,Fly completed.\n',encoding='utf-8')
                original=trace.read_bytes()
                (run/'retention_actions.json').write_text(json.dumps(dict(schema_version=1,role='artifact_retention_actions',retention_class='compact',status='complete',preserved=[dict(path='logs/simion__batch01.trace.log',bytes=len(original),retention_role='dense_trajectory',action='retained_completed_native_trace_for_recovery')])),encoding='utf-8')
                config=dict(schema_version=2,run_id=run.name,project='single_reflection_oa_tof_mass_analyzer',mode='design_candidate',inputs=dict(execution_request=str(request)),input_sha256={},parameters=dict(lifecycle_stage='run_package_initialized'),capacity_ledger_lifecycle=dict(enabled=True),artifact_retention=dict(policy_version=1,**{'class':'compact'},reason=None))
                (run/'run_config.json').write_text(json.dumps(config),encoding='utf-8')
                (run/'candidate_workflow_plan.json').write_text(json.dumps(dict(stages=[dict(stage_id='materialize')])),encoding='utf-8')
                (run/'summary.json').write_text(json.dumps(dict(status='interrupted')),encoding='utf-8')
                if direct:
                    manifest=_write_manifest(run,'failed')
                else:
                    summary,manifest=finalize_candidate_run(run,'failed',[dict(stage_id='materialize',status='failed')],'materialize')
                    self.assertEqual(json.loads((run/'summary.json').read_text()),summary)
                self.assertEqual(manifest['status'],'failed')
                self.assertFalse(manifest['formal_eligible'])
                self.assertFalse(manifest['promotion_authorized'])
                self.assertEqual(json.loads((run/'run_manifest.json').read_text()),manifest)
                self.assertEqual(trace.read_bytes(),original)
                self.assertFalse((run/'.run_terminal_publication.json').exists())
                with patch('sys.argv',['verify',str(run/'run_manifest.json'),'--require-status','failed']),contextlib.redirect_stdout(io.StringIO()):
                    verify_main(retention_api=native_policy)
