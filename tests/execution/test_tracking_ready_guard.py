"""Ready tracking recovery holds the manifest-bound unit closure."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from msplatform.execution.native_source_guard import guard_tracking_recovery
from msplatform.backends.simion.tracking_units import inspect_tracking_recovery
from tests.contracts.test_support.tracking_recovery_store_fixture import create_stopped_tracking


@unittest.skipUnless(os.name=='nt' and os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'shared Windows host ledger required')
class ReadyTrackingGuardTests(unittest.TestCase):
    def test_ready_index_and_unit_records_stay_held(self):
        from tests.contracts.test_simion_tracking_execution import TrackingExecutionPlanTests
        case=TrackingExecutionPlanTests();case.setUp();plan=case.plan(unit_size=50)
        with tempfile.TemporaryDirectory() as directory:
            store,reference,context=create_stopped_tracking(Path(directory),plan,status='success')
            manifest=json.loads(Path(reference['path']).read_text(encoding='utf-8'))
            index=next(Path(row['path']) for row in manifest['outputs'] if Path(row['path']).name=='tracking_units.json')
            unit=json.loads(index.read_text(encoding='utf-8'))['units'][0]
            with guard_tracking_recovery(store,reference,raw_root=context.workspace/'artifacts'):
                self.assertEqual(inspect_tracking_recovery(plan,reference)['reused_unit_keys'],['unit_0001'])
                for path in (index,Path(unit['stdout_record']['path']),Path(unit['process_record']['path'])):
                    with self.assertRaises(PermissionError): path.unlink()
            Path(unit['stdout_record']['path']).unlink()
            with self.assertRaises((OSError,ValueError)):
                with guard_tracking_recovery(store,reference,raw_root=context.workspace/'artifacts'): pass
