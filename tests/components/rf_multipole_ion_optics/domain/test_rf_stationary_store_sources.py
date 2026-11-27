"""Store source identity and lifetime for the RF saved-field entry point."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.native_artifact_controls import current_native_artifact_scope
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.rf_stationary import saved_comsol, simion_samples


class SavedStoreSourceTests(unittest.TestCase):
    def test_simion_controller_must_be_exact_source_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);store=ArtifactStore(root/'store')
            with store.inplace_asset('native_stage','simion-source') as (identity,asset,_,seal):
                run=asset/'runs'/'20261127_120000__sim__simion__rf-parent'
                (run/'results').mkdir(parents=True)
                controller=run/'results'/'controller.pa';controller.write_bytes(b'inert pa')
                config=run/'run_config.json';config.write_text(json.dumps({'schema_version':1,'run_id':run.name,
                    'project':'rf_multipole_ion_optics','mode':'resolved_design_transport','inputs':{}}),encoding='utf-8')
                manifest=run/'run_manifest.json';manifest.write_text(json.dumps(build_run_manifest(config,'success',output_paths=[controller])),encoding='utf-8')
                seal()
            budget=root/'budget.json';budget.write_text('{}',encoding='utf-8')
            plan=root/'plan.json';plan.write_text('{}',encoding='utf-8')
            design=root/'design.json';design.write_text('{}',encoding='utf-8')
            request=root/'request.json'
            data={'schema_version':1,'role':'multipole_stationary_simion_sampling_request',
                'resolved_design':str(design),'sampling_plan':str(plan),'controller_pa':str(controller),
                'producer_manifest':str(manifest),'origin_mm':[0,0,0],'cell_mm':[1,1,1],
                'electrode_ids_by_group':{'1':[1],'2':[2]}}
            request.write_text(json.dumps(data),encoding='utf-8')
            def produce(**_):
                store.collect(10**6)
                self.assertTrue(controller.is_file())
                work=current_native_artifact_scope()['work_directory']
                (work/'samples.csv').write_text('inert',encoding='utf-8')
                return {'status':'success'}
            with patch('msplatform.workflows.rf_stationary._budget',return_value=(
                    {'limits':{'transient_run_directory_bytes':10000}},file_record(budget))), \
                 patch('msplatform.workflows.rf_stationary._simion_samples_guarded',side_effect=produce):
                self.assertEqual(simion_samples(request_path=request,budget=budget,run_id='fixture',
                    source_id='fixture',context=SimpleNamespace(),artifact_store=store)['status'],'success')
                store.collect(10**6)
                with store.claim_verified(identity): self.assertEqual(controller.read_bytes(),b'inert pa')
                other=run/'results'/'unlisted.pa';other.write_bytes(b'unlisted')
                data['controller_pa']=str(other);request.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises((ValueError,OSError)):
                    simion_samples(request_path=request,budget=budget,run_id='other',source_id='fixture',
                        context=SimpleNamespace(),artifact_store=store)

    def test_saved_source_is_claimed_until_publication_and_required_after_gc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / 'store')
            with store.inplace_asset('native_stage', 'rf-source') as (identity, asset, _, seal):
                run = asset / 'runs' / '20261127_120000__sim__comsol__rf-parent'
                (run / 'inputs').mkdir(parents=True)
                (run / 'results').mkdir()
                design = run / 'inputs' / 'resolved.json'; design.write_text('{}', encoding='utf-8')
                model = run / 'results' / 'finite_3d_transport.mph'; model.write_bytes(b'inert model')
                config = run / 'run_config.json'
                config.write_text(json.dumps({'schema_version':1,'run_id':run.name,
                    'project':'rf_multipole_ion_optics','mode':'resolved_design_transport',
                    'inputs':{'multipole_resolved_design':str(design)}}),encoding='utf-8')
                manifest=run/'run_manifest.json'
                manifest.write_text(json.dumps(build_run_manifest(config,'success',output_paths=[model])),encoding='utf-8')
                seal()
            budget=root/'budget.json';budget.write_text('{}',encoding='utf-8')
            plan=root/'plan.json';plan.write_text('{}',encoding='utf-8')
            def produce(**kwargs):
                self.assertEqual(Path(kwargs['model']['path']),model)
                store.collect(10**6)
                self.assertTrue(model.is_file())
                work=current_native_artifact_scope()['work_directory']
                (work/'samples.csv').write_text('inert result',encoding='utf-8')
                return {'status':'success'}
            with patch('msplatform.workflows.rf_stationary._budget',return_value=(
                    {'limits':{'transient_run_directory_bytes':10000}},file_record(budget))), \
                 patch('msplatform.workflows.rf_stationary._saved_comsol_guarded',side_effect=produce):
                self.assertEqual(saved_comsol(parent_manifest=manifest,sampling_plan=plan,budget=budget,
                    run_id='saved-fixture',source_id='fixture',context=SimpleNamespace(),artifact_store=store)['status'],'success')
            store.collect(10**6)
            with store.claim_verified(identity):
                self.assertEqual(model.read_bytes(),b'inert model')
            model.write_bytes(b'tampered')
            with self.assertRaises((ValueError,OSError)):
                saved_comsol(parent_manifest=manifest,sampling_plan=plan,budget=budget,
                    run_id='another',source_id='fixture',context=SimpleNamespace(),artifact_store=store)


if __name__ == '__main__':
    unittest.main()
