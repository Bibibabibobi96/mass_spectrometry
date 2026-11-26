"""Plan6 recorded-birth preparation software fixture; no native solver."""
import copy
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.simion.model import compile_prepared_model
from msplatform.components.rf_multipole.source_validation import load_validated_source
from msplatform.io.manifest_records import file_record
from msplatform.workflows.single_reflection_flight.prepare import prepare, validate_preparation_request
from tests.contracts.test_platform_api import split_example
from tests.workflows.single_reflection.test_single_reflection_preparation import scientific_preparation_fixture


class RecordedBirthV12Tests(unittest.TestCase):
    def test_plan6_freezes_real_recorded_source_and_rejects_clock_change(self):
        case, _, _, compiled = split_example()
        with TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'fixture').mkdir()
            old_path, _, old = scientific_preparation_fixture(root/'fixture',recorded_birth=True)
            source = copy.deepcopy(old['source'])
            for name in ('particle_source','metadata','clock_authority','instrument_epoch'):
                source[name]['path'] = str((old_path.parent/source[name]['path']).resolve())
            with Path(source['particle_source']['path']).open(encoding='utf-8-sig') as stream:
                raw_rows=list(csv.DictReader(stream))
            ids=[int(row['particle_id']) for row in raw_rows]
            source.update(species_id='ion',particle_ids=ids,instrument_origin_us=7.5)
            metadata, _ = load_validated_source(Path(source['particle_source']['path']), compiled.components_resolved['multipole'])
            metadata_path = root/'metadata.json'
            metadata_path.write_text(json.dumps(metadata), encoding='utf8')
            source['metadata'] = file_record(metadata_path)
            drive=copy.deepcopy(case.drive);drive.pop('clock_authority')
            epoch=json.loads(Path(source['clock_authority']['path']).read_text(encoding='utf8'))
            drive['clock'].update(clock_epoch_id=epoch['clock_epoch_id'],authority_sha256=source['instrument_epoch']['sha256'])
            model=compile_prepared_model(compiled,compiled.components_resolved,drive=drive,physics=case.physics)
            model_path=root/'model.json';model_path.write_text(json.dumps(model.document),encoding='utf8')
            fields_manifest=root/'fields.json';fields_manifest.write_text('{}',encoding='utf8')
            reference=dict(manifest=file_record(fields_manifest),product_id='fields')
            fields=SimpleNamespace(reference=reference,data_path=lambda key:model_path,
                metadata=dict(backend='simion',field_status='available',source_status='not_requested',
                              model_identity_sha256=model.document['model_identity_sha256'],clock=model.document['drive']['clock']))
            request=dict(schema_version=12,role='split_oa_tof_recorded_birth_preparation_request',fields_reference=reference,
                source=source,propagation=dict(schema_version=1,scope='continuous_assembly',stop=None,consumed_plane_events=[],
                end_policy=dict(maximum_particle_age_us=200.)),numerics=case.numerics['simion'])
            author=root/'request.json';author.write_text(json.dumps(request),encoding='utf8')
            run=root/'run';(run/'inputs').mkdir(parents=True)
            self.assertEqual(validate_preparation_request(request),12)
            with patch('msplatform.results.artifacts.open_artifact',return_value=fields):
                result=prepare(author,run)
            self.assertEqual(result['particle_count'],len(ids))
            self.assertEqual((run/'inputs/particle_source.csv').read_bytes(),Path(source['particle_source']['path']).read_bytes())
            provenance=json.loads((run/'inputs/source_provenance.json').read_text(encoding='utf8'))
            self.assertEqual(provenance['model_identity_sha256'],model.document['model_identity_sha256'])
            from msplatform.workflows.single_reflection_flight.recorded_birth import track_recorded_birth
            manifest=run/'run_manifest.json'
            manifest.write_text(json.dumps(dict(role='simulation_run_manifest',status='success',
                inputs=result['input_records'],outputs=list(result['outputs'].values()))),encoding='utf8')
            selected=SimpleNamespace(reference=reference,data_path=lambda key:model_path)
            with patch('msplatform.workflows.single_reflection_flight.recorded_birth.require_completed_terminal_publication'), \
                 patch('msplatform.workflows.single_reflection_flight.recorded_birth.open_artifact',return_value=selected), \
                 patch('msplatform.backends.simion.track',return_value='fixture-result') as track:
                actual=track_recorded_birth(preparation_manifest=file_record(manifest),fields=reference,
                    species_id='ion',expected_particle_ids=ids,observations={'plane_observations':[]},context=None)
            self.assertEqual(actual,'fixture-result')
            packet=track.call_args.args[1]
            self.assertEqual([row['particle_id'] for row in packet['rows']],ids)
            self.assertEqual(packet['clock']['clock_epoch_id'],epoch['clock_epoch_id'])
            self.assertAlmostEqual(packet['rows'][0]['particle_birth_time_us'], 7.5 + float(raw_rows[0]['birth_time_s'])*1e6)
            self.assertEqual(packet['recorded_source']['instrument_origin_us'],7.5)
            self.assertEqual(track.call_args.kwargs['birth_source_authority']['manifest']['path'],str(manifest))
            with patch('msplatform.workflows.single_reflection_flight.recorded_birth.require_completed_terminal_publication'), \
                 patch('msplatform.workflows.single_reflection_flight.recorded_birth.open_artifact',return_value=selected), \
                 patch('msplatform.backends.simion.track') as refused:
                with self.assertRaisesRegex(ValueError, 'original mother'):
                    track_recorded_birth(preparation_manifest=file_record(manifest),fields=reference,
                        species_id='other',expected_particle_ids=ids,observations={'plane_observations':[]},context=None)
                refused.assert_not_called()
            other = copy.deepcopy(reference); other['manifest']['sha256'] = 'b'*64
            with patch('msplatform.workflows.single_reflection_flight.recorded_birth.require_completed_terminal_publication'), \
                 patch('msplatform.workflows.single_reflection_flight.recorded_birth.open_artifact',
                       return_value=SimpleNamespace(reference=other,data_path=lambda key:model_path)), \
                 patch('msplatform.backends.simion.track') as refused:
                with self.assertRaisesRegex(ValueError, 'FieldBundle differs'):
                    track_recorded_birth(preparation_manifest=file_record(manifest),fields=other,
                        species_id='ion',expected_particle_ids=ids,observations={'plane_observations':[]},context=None)
                refused.assert_not_called()
            altered=copy.deepcopy(request);altered['source']['particle_ids'][0]=2**31
            with self.assertRaises(ValueError):validate_preparation_request(altered)
            for invalid in (float('nan'), float('inf'), True):
                altered=copy.deepcopy(request);altered['source']['instrument_origin_us']=invalid
                with self.assertRaises(ValueError):validate_preparation_request(altered)
            altered=copy.deepcopy(request);del altered['source']['instrument_origin_us']
            with self.assertRaises(ValueError):validate_preparation_request(altered)
            altered=copy.deepcopy(request);altered['source']['particle_ids'].reverse()
            bad_author=root/'bad-ids.json';bad_author.write_text(json.dumps(altered),encoding='utf8')
            bad_run=root/'bad-ids-run';(bad_run/'inputs').mkdir(parents=True)
            with patch('msplatform.results.artifacts.open_artifact',return_value=fields), \
                 self.assertRaisesRegex(ValueError, 'IDs differ'):
                prepare(bad_author,bad_run)
            altered=copy.deepcopy(request);altered['source']['instrument_epoch']['sha256']='0'*64
            bad_author=root/'bad-clock.json';bad_author.write_text(json.dumps(altered),encoding='utf8')
            bad_run=root/'bad-clock-run';(bad_run/'inputs').mkdir(parents=True)
            with patch('msplatform.results.artifacts.open_artifact',return_value=fields), \
                 self.assertRaisesRegex(AssertionError, 'SHA-256 changed'):
                prepare(bad_author,bad_run)


if __name__ == '__main__': unittest.main()
