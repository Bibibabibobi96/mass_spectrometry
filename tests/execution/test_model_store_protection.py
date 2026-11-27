"""Model geometry action protects the exact Store product, without a legacy ledger."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from msplatform.backends.simion.model_execution import _protect_model_geometry
from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.owner import standalone_native_store
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.storage.store import ArtifactStore


class ModelStoreProtectionTests(unittest.TestCase):
    def test_geometry_is_claimed_and_unlisted_member_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ArtifactStore(root/'store')
            with store.inplace_asset('native_stage','geometry') as (identity,asset,_,seal):
                run=asset/'runs'/'20261127_140000__test__python__geometry';run.mkdir(parents=True)
                (run/'.run_terminal_publication.lock').touch()
                payload=run/'geometry.pa0';payload.write_bytes(b'inert geometry')
                config=run/'run_config.json';config.write_text(json.dumps({'schema_version':1,'run_id':run.name,
                    'project':'fixture','mode':'software','inputs':{},'capacity_ledger_lifecycle':{'schema_version':1,
                    'enabled':False,'artifact_root':str(store.root),'light_evidence_budget_bytes':1024}}),encoding='utf-8')
                manifest=run/'run_manifest.json'
                document=build_run_manifest(config,'success',output_paths=[payload],extra_fields={'products':{
                    'geometry':{'schema_version':1,'kind':'geometry_artifact','status':'complete','metadata':{},
                                'data':{'raw':file_record(payload)}}}})
                manifest.write_text(json.dumps(document),encoding='utf-8');seal()
            geometry=open_artifact({'manifest':file_record(manifest),'product_id':'geometry'},expected_kind='geometry_artifact')
            with standalone_native_store(store,task_key='model-test',budget=10000) as scope:
                session=SimpleNamespace(context=SimpleNamespace(workspace=root))
                _protect_model_geometry(session,geometry,required_paths=[payload])
                with self.assertRaisesRegex(ValueError,'not bound'):
                    _protect_model_geometry(session,geometry,required_paths=[run/'not-listed.pa0'])
                store.collect(10**6)
                self.assertTrue(payload.exists())
                work=store.root/store.run_status(scope['parent_run_id'])['work_path']
                (work/'result.json').write_text('{}',encoding='utf-8')
            store.collect(10**6)
            with store.claim_verified(identity): self.assertEqual(payload.read_bytes(),b'inert geometry')
