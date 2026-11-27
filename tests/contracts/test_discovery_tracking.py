"""Software evidence for detector-blind discovery admission; no native Fly."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from msplatform.backends.simion.tracking_execution import resolve_discovery_selection


class DiscoverySelectionTests(unittest.TestCase):
    def test_published_pilot_is_reopened_and_tamper_rejected(self):
        from msplatform.backends.simion import model as model_module
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        from tests.contracts.test_split_tof_simion import SplitTofSimionTests
        from msplatform.analysis.pulse_selection import _capture_bounds

        models = []
        original = model_module.compile_prepared_model
        def capture(*args, **kwargs):
            model = original(*args, **kwargs)
            models.append(model)
            return model
        with patch.object(model_module, 'compile_prepared_model', side_effect=capture):
            SplitTofSimionTests('test_split_two_component_geometry_uses_real_provider_snapshots').test_split_two_component_geometry_uses_real_provider_snapshots()
        model = next(value for value in models if model_module.model_geometry(value).frontend_geometry.get('role') == 'simion_split_oa_tof_geometry')
        doc = model.document
        geometry = model_module.model_geometry(model, downstream_drive=True).frontend_geometry
        bounds = _capture_bounds(geometry)
        pulse = doc['drive']['pulse']
        times = [pulse['time_us'], pulse['time_us'] + 1.]
        author = dict(mode='discover', width_us=pulse['width_us'], candidate_times_us=times)
        phase = dict(phase='discovery', author=author)
        field = dict(bytes=7, sha256='c' * 64)
        source = dict(state_kind='source_birth', mother_particle_ids=[1], execution_particle_ids=[1],
            mother_records=[dict(particle_id=1, particle_birth_time_us=times[0]-1.)],
            mother_fates=[], clock_authority_sha256=doc['drive']['clock']['authority_sha256'])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            def publish(name, *, missing=False, incomplete=False):
                run = root/name; run.mkdir()
                records = {}
                def put(key, value):
                    path = run/(key+'.json'); path.write_text(json.dumps(value), encoding='utf-8')
                    records[key] = file_record(path, 'required_evidence')
                put('compiled_model', doc)
                put('source_provenance', source)
                put('observations', dict(pulse_discovery=phase, observation_times_us=times))
                rows = [dict(particle_id=1, candidate_time_us=t, instrument_time_us=t,
                    **{a+'_mm': bounds[a]['center_mm'] for a in 'xyz'},
                    vx_mm_per_us=0., vy_mm_per_us=0., vz_mm_per_us=1.) for t in times]
                put('collection', dict(role='simion_tracking_collection', native_complete=not incomplete,
                    pulse_discovery=phase, effective_flight={'pulse': {'mode': 'held_off'}},
                    clock_epoch_id=doc['drive']['clock']['clock_epoch_id'],
                    model_identity_sha256=doc['model_identity_sha256'],
                    source_provenance_record=records['source_provenance'],
                    field_reference={'manifest': field, 'product_id': 'field'},
                    canonical_events=[dict(event='source_release', particle_id=1, instrument_time_us=times[0]-1.)],
                    native_terminals=[dict(particle_id=1, instrument_time_us=times[-1]+1.)],
                    native_shared_states=[] if missing else rows))
                manifest = dict(schema_version=1,role='simulation_run_manifest',run_id=name,
                    project='instrument_assembly',mode='fixture',status='success',inputs=records,outputs=[],
                    products={'trajectory':dict(schema_version=1,kind='trajectory_result',status='complete',
                        metadata={'backend':'simion'},data=records)})
                publish_terminal_state(run, {'status':'success'}, manifest)
                return {'manifest':file_record(run/'run_manifest.json'),'product_id':'trajectory'}, run
            ref, run = publish('pilot')
            selected = dict(phase='selected', author=author, pilot=ref)
            result = resolve_discovery_selection(selected, model, field_manifest_record=field,
                field_product_id='field', provenance=source)
            self.assertEqual(result['effective_pulse']['time_us'], times[0])
            for changed in (dict(field, bytes=8),):
                with self.assertRaises(ValueError):
                    resolve_discovery_selection(selected, model, field_manifest_record=changed, field_product_id='field', provenance=source)
            with self.assertRaises(ValueError):
                resolve_discovery_selection(selected, model, field_manifest_record=field, field_product_id='other', provenance=source)
            with self.assertRaises(ValueError):
                resolve_discovery_selection(selected, model, field_manifest_record=field, field_product_id='field',
                    provenance=dict(source, clock_authority_sha256='e'*64))
            with self.assertRaises(ValueError):
                resolve_discovery_selection(selected, model, field_manifest_record=field, field_product_id='field',
                    provenance=dict(source, mother_records=[dict(particle_id=2, particle_birth_time_us=times[0]-1.)]))
            missing, _ = publish('missing', missing=True)
            with self.assertRaisesRegex(ValueError, 'no supported eligible'):
                resolve_discovery_selection(dict(selected, pilot=missing), model,
                    field_manifest_record=field, field_product_id='field', provenance=source)
            incomplete, _ = publish('incomplete', incomplete=True)
            with self.assertRaises(ValueError):
                resolve_discovery_selection(dict(selected, pilot=incomplete), model,
                    field_manifest_record=field, field_product_id='field', provenance=source)
            (run/'collection.json').write_text('{}', encoding='utf-8')
            with self.assertRaises((AssertionError, ValueError)):
                resolve_discovery_selection(selected, model, field_manifest_record=field, field_product_id='field', provenance=source)

    def test_bound_pilot_selection_and_missing_or_mismatched_evidence(self):
        author = dict(mode='discover', width_us=2., candidate_times_us=[10., 11.])
        pilot_author = dict(phase='discovery', author=author)
        discovery = dict(phase='selected', author=author, pilot={'fixture': 'inert'})
        document = dict(model_identity_sha256='a' * 64, drive=dict(
            clock=dict(clock_epoch_id='epoch'), pulse=dict(mode='timed', time_us=10., width_us=2.)))
        geometry = dict(accelerator_projection=dict(bore_width_mm=10., repeller_front_z_mm=0.,
            grid1_z_mm=10., axis_x_mm=0., axis_y_mm=0.), composition_plan=dict(assembly_frame_id='world'))
        source = dict(state_kind='source_birth', mother_particle_ids=[1], execution_particle_ids=[1],
                      mother_records=[{'particle_id': 1, 'particle_birth_time_us': 0.}],
                      mother_fates=[], clock_authority_sha256='b' * 64)
        identity = dict(bytes=7, sha256='c' * 64)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            records = {name: {'path': str(root / (name + '.json')), 'bytes': 1, 'sha256': 'd' * 64}
                       for name in ('collection', 'observations', 'source_provenance', 'compiled_model')}
            collection = dict(role='simion_tracking_collection', native_complete=True,
                pulse_discovery=pilot_author, effective_flight={'pulse': {'mode': 'held_off'}},
                clock_epoch_id='epoch', model_identity_sha256='a' * 64,
                source_provenance_record=records['source_provenance'], field_reference={'manifest': identity, 'product_id': 'field'},
                canonical_events=[dict(event='source_release', particle_id=1, instrument_time_us=0.)],
                native_terminals=[dict(particle_id=1, instrument_time_us=20.)], native_shared_states=[
                    dict(particle_id=1, candidate_time_us=t, instrument_time_us=t, x_mm=0., y_mm=0.,
                         z_mm=5., vx_mm_per_us=0., vy_mm_per_us=0., vz_mm_per_us=1.) for t in (10., 11.)])
            values = dict(collection=collection, observations=dict(pulse_discovery=pilot_author,
                observation_times_us=[10., 11.]), source_provenance=source, compiled_model=document)
            for name, value in values.items():
                (root / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')
            class Pilot:
                data_records = records
                metadata = {'backend': 'simion'}
                def data_path(self, key):
                    return root / (key + '.json')
            class Geometry:
                frontend_geometry = geometry
            # This double exercises scientific admission only; publication and guards have separate owners.
            with patch('msplatform.results.artifacts.open_artifact', return_value=Pilot()), \
                 patch('msplatform.backends.simion.tracking_execution.require_prepared_model', return_value=document), \
                 patch('msplatform.backends.simion.tracking_execution.model_geometry', return_value=Geometry()):
                result = resolve_discovery_selection(discovery, object(), field_manifest_record=identity, field_product_id='field', provenance=source)
                self.assertEqual(result['effective_pulse'], dict(mode='timed', time_us=10., width_us=2.))
                self.assertEqual(result['decision']['selection']['selected']['eligible_ids'], [1])
                with self.assertRaises(ValueError):
                    resolve_discovery_selection(discovery, object(), field_manifest_record=dict(identity, bytes=8), field_product_id='field', provenance=source)
                with self.assertRaises(ValueError):
                    resolve_discovery_selection(discovery, object(), field_manifest_record=identity, field_product_id='other', provenance=source)
                with self.assertRaises(ValueError):
                    resolve_discovery_selection(discovery, object(), field_manifest_record=identity, field_product_id='field',
                        provenance=dict(source, clock_authority_sha256='e' * 64))
                collection['native_shared_states'] = []
                (root / 'collection.json').write_text(json.dumps(collection), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'no supported eligible'):
                    resolve_discovery_selection(discovery, object(), field_manifest_record=identity, field_product_id='field', provenance=source)
                collection['native_complete'] = False
                (root / 'collection.json').write_text(json.dumps(collection), encoding='utf-8')
                with self.assertRaises(ValueError):
                    resolve_discovery_selection(discovery, object(), field_manifest_record=identity, field_product_id='field', provenance=source)


if __name__ == '__main__':
    unittest.main()
