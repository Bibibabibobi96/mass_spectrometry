"""One public OA focus Store chain; vendor leaves are inert, not SIMION evidence."""
import copy
from contextlib import nullcontext
import hashlib
import json
import os
from dataclasses import replace
from functools import partial
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.recipes import load_recipe
from msplatform.workflows.tracing import run_recipe
from tests.contracts.test_support.oa_focus_study import make_focus_recipe


class PublicOaFocusStoreTests(unittest.TestCase):
    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
    def test_public_focus_store_owner_chain_and_cold_analysis(self):
        from tests.contracts.test_execution_runtime import NormalOwnerTests
        from tests.contracts.test_support.oa_focus_inert import run_leaf
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger
        from msplatform.execution import run_session
        from msplatform.storage import ArtifactStore
        from msplatform.workflows.oa_focus_store_analysis import publish_focus_analysis
        with (nullcontext(tempfile.mkdtemp(prefix='oa-focus-store-inert-', dir=os.environ['OA_FOCUS_TEST_EVIDENCE_ROOT']))
              if os.environ.get('OA_FOCUS_TEST_EVIDENCE_ROOT') else tempfile.TemporaryDirectory(prefix='oa-focus-store-inert-')) as directory:
            root=Path(directory); helper=NormalOwnerTests(); context=helper._context(root)
            capacity=root/'capacity.json';capacity.write_text(json.dumps(helper._policy()))
            binary=root/'inert-simion.exe';binary.write_bytes(b'INERT_NOT_SIMION')
            plane=root/'examples/test_plane/testplanelib.lua';plane.parent.mkdir(parents=True)
            plane.write_text('-- INERT TestPlane fixture',encoding='utf-8')
            stage=dict(limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=128*1024**2,
                process_tree_working_set_bytes=1024**3,minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=128*1024**2,automatic_retry_count=0),
                artifact_retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert OA focus'))
            stages={name:copy.deepcopy(stage) for name in ('build_geometry','prepare_model','solve_fields','track')}
            stages['solve_fields']['limits']['reserved_run_payload_bytes']=0
            policy=root/'stages.json';policy.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages=stages)))
            context=replace(context,capacity_policy_path=capacity,stage_policy_path=policy,tools={'simion':binary})
            artifact_root=context.workspace/'artifacts';artifact_root.mkdir(parents=True);initialize_capacity_ledger(artifact_root,objects=[])
            author,_,_=make_focus_recipe(root/'author')
            # Explicit synthetic small cohort; only this test's campaign copy is changed.
            campaign=author.parent/'focus_campaign.json';payload=json.loads(campaign.read_text())
            payload['release_spec']['particle_count']=3
            raw=(json.dumps(payload,indent=2)+'\n').encode();campaign.write_bytes(raw)
            study_path=author.parent/'study.json';study=json.loads(study_path.read_text())
            study['model_input_sources']['oa_focus_campaign']['sha256']=hashlib.sha256(raw).hexdigest()
            study_bytes=(json.dumps(study,indent=2)+'\n').encode();study_path.write_bytes(study_bytes)
            text=author.read_text();import re
            author.write_text(re.sub(r'(?m)^sha256 = "[a-fA-F0-9]{64}"',
                'sha256 = "'+hashlib.sha256(study_bytes).hexdigest()+'"',text,count=1))
            actual=run_session.run_observed_process
            with patch('msplatform.backends.simion.tracking_execution.windows_binary_version',return_value='inert'), \
                 patch('msplatform.execution.run_session.run_observed_process',side_effect=partial(run_leaf,actual)) as observed:
                result=run_recipe(author,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
                before=observed.call_count
                repeated=run_recipe(author,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
                self.assertEqual(observed.call_count,before)
                self.assertTrue(all(row['reused'] for row in repeated['provenance']['stages'].values()))
            self.assertEqual(result['run_state']['execution_status'],'succeeded')
            self.assertEqual(repeated['run_state']['execution_status'],'succeeded')
            store=ArtifactStore(root/'store')
            report=publish_focus_analysis(store=store,source_run_id=result['run_id'],budget_bytes=64*1024**2,
                exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            self.assertIsNotNone(report)
            self.assertEqual(load_recipe(author).to_dict()['study']['document']['release']['release_spec']['particle_count'],3)
