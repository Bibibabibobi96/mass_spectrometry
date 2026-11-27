"""RF borrowed-family ownership: tiny software fixtures, not native qualification."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.native_source_guard import guard_native_source
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from tests.contracts.test_support.rf_ip_inert_field import prepare_inert_field
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model


@unittest.skipUnless(os.name == 'nt' and os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'), 'shared Windows host ledger required')
class RfFamilyGuardTests(unittest.TestCase):
    def test_borrowed_family_producer_held_and_mismatch_rejected(self):
        from tests.contracts.test_joint_ip_model import JointIpModelTests
        case=JointIpModelTests(methodName='runTest');case.setUp()
        self.addCleanup(case.doCleanups)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            model=compile_prepared_model(case.compiled,case.compiled.components_resolved,drive=case.drive,physics=RF_IP_PHYSICS)
            reference, _, _, store=prepare_inert_field(root,model,case.compiled)
            original=open_artifact(reference,expected_kind='field_bundle')
            bindings=original.metadata['native_assets']; keys={'field_native_receipts'}
            for row in bindings.values(): keys.update(row['family']);keys.add(row['surface_witnesses'])
            with store.inplace_asset('native_stage','reused-rf-family',run_id='20261127_130000__test__python__reused-rf') as (selected_id,asset,_,seal):
                run=asset/'runs'/'20261127_130000__test__python__reused-rf';run.mkdir(parents=True)
                config=run/'run_config.json';config.write_text(json.dumps({'schema_version':1,'run_id':run.name,
                    'project':'fixture','mode':'software','inputs':{},'capacity_ledger_lifecycle':{
                    'schema_version':1,'enabled':False,'artifact_root':str(store.root),'light_evidence_budget_bytes':1024}}),encoding='utf-8')
                data={};outputs=[]
                for key, record in original.data_records.items():
                    if key in keys: data[key]=record
                    else:
                        target=run/(key+'.dat');target.write_bytes(original.data_path(key).read_bytes())
                        data[key]=file_record(target,record.get('retention_role'));outputs.append(target)
                document=build_run_manifest(config,'success',output_paths=outputs)
                document['outputs']=[data[key] for key in data if key not in keys]
                document['inputs'].update({key:data[key] for key in keys})
                metadata=dict(original.metadata,family_producer_reference=reference,fields_reused=True,refine_calls=0)
                document['products']={'fields':{'schema_version':1,'kind':'field_bundle','status':'complete',
                                               'metadata':metadata,'data':data}}
                manifest=run/'run_manifest.json';manifest.write_text(json.dumps(document),encoding='utf-8')
                selected={'manifest':file_record(manifest),'product_id':'fields'}
                seal()
            producer_path=original.manifest_location
            with guard_native_source(selected,expected_kind='field_bundle',expected_artifact_root=root/'study'/'artifacts',artifact_store=store):
                store.collect(10**8)
                self.assertTrue(producer_path.is_file())
                with self.assertRaises(PermissionError): original.data_path(next(iter(keys))).unlink()
            with store._db() as db:
                self.assertEqual(db.execute('SELECT state FROM assets WHERE id=?',(selected_id,)).fetchone()[0],'ready')
            bad_id='20261127_130001__test__python__wrong-family'
            with store.inplace_asset('native_stage','wrong-rf-family',run_id=bad_id) as (_,asset,_,seal):
                bad_run=asset/'runs'/bad_id;bad_run.mkdir(parents=True)
                config=bad_run/'run_config.json';config.write_text(json.dumps({'schema_version':1,'run_id':bad_id,
                    'project':'fixture','mode':'software','inputs':{},'capacity_ledger_lifecycle':{
                    'schema_version':1,'enabled':False,'artifact_root':str(store.root),'light_evidence_budget_bytes':1024}}),encoding='utf-8')
                bad=build_run_manifest(config,'success',output_paths=[])
                bad['products']={'fields':{'schema_version':1,'kind':'field_bundle','status':'complete',
                    'metadata':dict(metadata,native_assets={'wrong':next(iter(bindings.values()))}), 'data':data}}
                bad_manifest=bad_run/'run_manifest.json';bad_manifest.write_text(json.dumps(bad),encoding='utf-8')
                bad_reference={'manifest':file_record(bad_manifest),'product_id':'fields'}
                seal()
            with self.assertRaisesRegex(ValueError,'producer closure differs'):
                with guard_native_source(bad_reference,expected_kind='field_bundle',expected_artifact_root=root/'study'/'artifacts',artifact_store=store):
                    self.fail('wrong family binding accepted')
            original.data_path(next(iter(keys))).write_bytes(b'tampered')
            with self.assertRaises((OSError,ValueError)):
                with guard_native_source(selected,expected_kind='field_bundle',expected_artifact_root=root/'study'/'artifacts',artifact_store=store):
                    self.fail('damaged borrowed source accepted')
