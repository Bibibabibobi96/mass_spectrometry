"""Focused actual execute_tracking dispatch with explicit source/owner doubles."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.simion import tracking_execution as subject
from msplatform.backends.simion import rf_tracking_execution as executor
from msplatform.backends.simion import artifacts as artifacts_module
from msplatform.results import artifacts as results_module

class Session:
    def run_process(self, *, immutable_input_records):
        raise AssertionError('dispatch test must not start a process')

class SampledTrackingDispatchTests(unittest.TestCase):
    def test_actual_dispatch_and_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.json';path.write_text('{}',encoding='utf8')
            model=object();clock={'clock_epoch_id':'epoch','authority_sha256':'a'*64}
            doc={'model_identity_sha256':'b'*64,'drive':{'clock':clock}}
            meta=dict(backend='simion',field_status='available',source_status='not_requested',
                field_representation='assembly_sampled_basis_with_collision_geometry',
                model_identity_sha256=doc['model_identity_sha256'],clock=clock)
            source=SimpleNamespace(kind='field_bundle',metadata=meta,data_path=lambda name:path)
            geometry=SimpleNamespace(frontend_geometry={'role':'simion_ip_mr_complete_geometry'})
            marker=object();particles={'original':'cohort'};propagation={'scope':'continuous_assembly'}
            observations={'plane_observations':[]};numerics={'unchanged':True};hs1={'explicit':'gas'}
            def call(**changes):
                options=dict(fields_reference={'manifest':'fixture'},particles=particles,propagation=propagation,
                    observations=observations,numerics=numerics,limits={},hs1_request=hs1)
                options.update(changes);return subject.execute_tracking(Session(),**options)
            with patch.object(results_module,'open_artifact',return_value=source), \
                 patch.object(artifacts_module,'CompiledPreparedModel',return_value=model), \
                 patch.object(subject,'require_prepared_model',return_value=doc), \
                 patch.object(subject,'model_geometry',return_value=geometry), \
                 patch.object(executor,'execute_ip_mr_tracking',return_value=marker) as run:
                self.assertIs(call(),marker)
                kw=run.call_args.kwargs
                self.assertIs(kw['source'],source);self.assertIs(kw['model'],model)
                self.assertIs(kw['particles'],particles);self.assertIs(kw['propagation'],propagation)
                self.assertIs(kw['observations'],observations);self.assertIs(kw['hs1_request'],hs1)
                with self.assertRaisesRegex(ValueError,'already owns'):
                    call(scalar_field_basis={'unexpected':'override'})
                geometry.frontend_geometry['role']='simion_rf_ip_geometry'
                with self.assertRaisesRegex(ValueError,'matching complete geometry'):call()
                geometry.frontend_geometry['role']='simion_ip_mr_complete_geometry'
                meta['field_representation']='wrong'
                with self.assertRaisesRegex(ValueError,'published sampled FieldBundle'):call()
                meta['field_representation']='assembly_sampled_basis_with_collision_geometry';meta['clock']={}
                with self.assertRaisesRegex(ValueError,'model/clock identity'):call()
                self.assertEqual(run.call_count,1)
