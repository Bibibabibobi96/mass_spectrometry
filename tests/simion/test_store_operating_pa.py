"""Store-owned operating PA composition over exact source records."""
import os
from pathlib import Path
import struct
import tempfile
import unittest

from msplatform.backends.simion.operating_pa_cache import compose_operating_pa_group
from msplatform.backends.simion.standalone_pa_composition import HEADER, PaHeader
from msplatform.execution.owner import standalone_native_store
from msplatform.execution.native_artifact_controls import current_native_artifact_scope
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore


@unittest.skipUnless(os.name == 'nt', 'Windows OS file identity guard required')
class StoreOperatingPATests(unittest.TestCase):
    def test_composition_hit_missing_rebuild_and_bound_sources(self):
        with tempfile.TemporaryDirectory(prefix='operating-store-') as directory:
            root = Path(directory)
            header = PaHeader(-2, 1, 100., 2, 2, 1, 0, .1, .1, .1)
            base = root/'base.pa'; response = root/'response.pa'
            base.write_bytes(header.pack() + struct.pack('<4d', 1., 2., 3., 4.))
            response.write_bytes(header.pack() + struct.pack('<4d', 2., 4., 6., 8.))
            before = (base.read_bytes(), response.read_bytes())
            members = [dict(output_name='one.pa', base_pa=base, target_voltage_vector_v=[5.],
                responses=[dict(coordinate='c1', path=response, basis_normalization_v=10., applied_voltage_delta_v=5.)])]
            records = [file_record(base,'solver_native_binary'), file_record(response,'solver_native_binary')]
            store = ArtifactStore(root/'store')
            with standalone_native_store(store, task_key='composition-a', budget=1024*1024) as scope:
                first = compose_operating_pa_group(members, pa_format_version=2020, source_records=records)
                second = compose_operating_pa_group(members, pa_format_version=2020, source_records=records)
                self.assertEqual((first['cache_disposition'], second['cache_disposition']), ('miss','hit'))
                self.assertEqual(first['asset_id'], second['asset_id'])
                self.assertEqual(struct.unpack('<4d', (Path(first['directory'])/'one.pa').read_bytes()[HEADER.size:]),
                                 (2., 4., 6., 8.))
                (current_native_artifact_scope()['work_directory']/'summary.json').write_text('{}', encoding='utf8')
            self.assertEqual(store.inspect_run(scope['parent_run_id']), Path(scope['published_path']))
            (Path(first['directory'])/'one.pa').unlink()
            with standalone_native_store(store, task_key='composition-b', budget=1024*1024):
                rebuilt = compose_operating_pa_group(members, pa_format_version=2020, source_records=records)
                self.assertEqual(rebuilt['cache_disposition'], 'miss')
                self.assertNotEqual(first['asset_id'], rebuilt['asset_id'])
                (current_native_artifact_scope()['work_directory']/'summary.json').write_text('{}', encoding='utf8')
            self.assertEqual(before, (base.read_bytes(), response.read_bytes()))
            with standalone_native_store(store, task_key='composition-c', budget=1024*1024):
                with self.assertRaisesRegex(ValueError, 'manifest-bound source records'):
                    compose_operating_pa_group(members, pa_format_version=2020, source_records=records[:1])
                (current_native_artifact_scope()['work_directory']/'summary.json').write_text('{}', encoding='utf8')

    def test_budget_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory(prefix='operating-store-') as directory:
            root = Path(directory)
            base = root/'base.pa'
            base.write_bytes(PaHeader(-2,1,100.,2,2,1,0,.1,.1,.1).pack()+struct.pack('<4d',1.,2.,3.,4.))
            members = [dict(output_name='one.pa', base_pa=base, responses=[], target_voltage_vector_v=[0.])]
            store = ArtifactStore(root/'store')
            with self.assertRaisesRegex(ValueError, 'growth exceeds reserved budget'):
                with standalone_native_store(store, task_key='too-small', budget=1):
                    compose_operating_pa_group(members, pa_format_version=2020,
                                               source_records=[file_record(base,'solver_native_binary')])
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT status FROM run_execution').fetchone()[0], 'failed')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
