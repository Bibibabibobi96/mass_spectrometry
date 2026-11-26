"""Explicit runtime carrier representation rejects published PA families."""
import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion.tracking_program import (
    DOWNSTREAM_STATIC_ASSET_REPRESENTATION,
    DOWNSTREAM_STATIC_ASSET_ROLE,
    _resolve_downstream_static_assets,
)


class AnalyticGroundTrackingTests(unittest.TestCase):
    def test_only_standalone_ground_with_surface_is_accepted(self):
        roles = {'flight_tube': 1, 'reflectron': 2, 'detector': 4}
        rows = []
        for role, index in roles.items():
            row = dict(role=role, instance_index=index, carrier_pa_basename=role+'.pa',
                       representation='standalone_voltageized_static_pa' if role == 'reflectron'
                       else 'analytic_zero_ground_standalone')
            if role != 'reflectron':
                row['family_members'] = [role+'.pa-surf']
            rows.append(row)
        contract = dict(schema_version=1, role=DOWNSTREAM_STATIC_ASSET_ROLE,
                        runtime_representation=DOWNSTREAM_STATIC_ASSET_REPRESENTATION,
                        receipt=dict(path='C:/receipt.json',bytes=1,sha256='a'*64), static_roles=rows)
        self.assertEqual(len(_resolve_downstream_static_assets(contract, roles)), 3)
        rows[0].update(representation='run_private_native_static_family',carrier_pa_basename='flight_tube.pa0',
                       family_members=['flight_tube.pa#','flight_tube.pa0','flight_tube.pa1','flight_tube.pa-surf'])
        self.assertEqual(len(_resolve_downstream_static_assets(contract, roles)), 3)
        rows[0]['family_members'] = []
        with self.assertRaisesRegex(ValueError, 'complete same-stem'):
            _resolve_downstream_static_assets(contract, roles)


    def test_borrowed_product_members_are_real_manifest_inputs(self):
        from msplatform.backends.simion.grounded_runtime import _bind_retained_field_inputs
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        from msplatform.results.artifacts import open_artifact

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'original'; source.mkdir()
            derived = root/'derived'; derived.mkdir()
            pa = source/'frontend.pa'; pa.write_bytes(b'original immutable PA')
            script = source/'build.lua'; script.write_bytes(b'original frozen builder')
            data = {'frontend':file_record(pa, 'solver_native_binary'),
                    'resource_build_flight_tube_variant.lua':file_record(script, 'required_evidence')}
            class Session:
                def __init__(self): self.inputs = {}
                def add_inputs(self, entries): self.inputs.update(entries)
            session = Session()
            _bind_retained_field_inputs(session, data)
            self.assertEqual(list(session.inputs.values()), list(data.values()))
            product = dict(schema_version=1,kind='field_bundle',status='complete',metadata={},data=data)
            manifest = dict(schema_version=2,role='simulation_run_manifest',run_id=derived.name,
                project='instrument_assembly',mode='fields_only',status='success',
                inputs=session.inputs,outputs=[],products={'fields':product})
            publish_terminal_state(derived, {'status':'success'}, manifest)
            result = open_artifact({'manifest':file_record(derived/'run_manifest.json'),
                                    'product_id':'fields'}, expected_kind='field_bundle')
            self.assertEqual(result.data_path('frontend'), pa)
            self.assertEqual(result.data_path('resource_build_flight_tube_variant.lua'), script)
            self.assertEqual(result.data_records['frontend']['retention_role'], 'solver_native_binary')
            broken = dict(manifest,inputs={})
            other = root/'unbound'; other.mkdir(); broken['run_id']=other.name
            publish_terminal_state(other, {'status':'success'}, broken)
            with self.assertRaisesRegex(ValueError, 'not bound'):
                open_artifact({'manifest':file_record(other/'run_manifest.json'),
                               'product_id':'fields'}, expected_kind='field_bundle')

    def test_original_borrowed_field_identity_is_required(self):
        from msplatform.backends.simion.grounded_runtime import verified_ground_origin
        shared = dict(model_identity_sha256='m', downstream_identity={'operator':'x'}, clock={'epoch':'e'})
        original = SimpleNamespace(metadata=dict(shared),data_records={'frontend':{}})
        meta = dict(shared,ground_representation='analytic_zero_on_native_geometry',
                    ground_source_reference={'manifest':{},'product_id':'fields'},
                    native_assets={'flight_tube':{'carrier':'tube','family':['tube_surface']},
                                   'detector':{'carrier':'det','family':['det_surface']}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root/'run_manifest.json'
            (root/'inputs').mkdir()
            (root/'inputs/execution_request.json').write_text(json.dumps(dict(payload=dict(
                action='prepare_grounded_runtime_fields', fields=meta['ground_source_reference']))))
            from msplatform.io.manifest_records import file_record
            manifest.write_text(json.dumps(dict(project='instrument_assembly', mode='fields_only', status='success',
                inputs={'execution_request': file_record(root/'inputs/execution_request.json')})))
            def log_path(key):
                path = root/(key+'.txt')
                mode = 'BUILD' if '_build_' in key else 'VERIFY'
                path.write_text('ANALYTIC_ZERO_GROUND_'+mode+'=PASS')
                return path
            derived = SimpleNamespace(metadata=meta,manifest_location=manifest,data_path=log_path,
                data_records={'frontend':{},'tube':{},'tube_surface':{},'det':{},'det_surface':{}})
            value = {'path':'C:/shared.pa','bytes':3,'sha256':'A'*64}
            with patch('msplatform.backends.simion.grounded_runtime._admit',return_value=(original,None,None)):
                with patch('msplatform.backends.simion.grounded_runtime.data_record',return_value=value):
                    self.assertIs(verified_ground_origin(derived),original)
                with patch('msplatform.backends.simion.grounded_runtime.data_record',side_effect=[value,dict(value,sha256='B'*64)]):
                    with self.assertRaisesRegex(ValueError,'borrowed record differs'):
                        verified_ground_origin(derived)



if __name__ == '__main__':
    unittest.main()
