"""The tracking execution retains real optional surface evidence."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion import rf_tracking_execution
from msplatform.io.manifest_records import file_record, verify_record


class TrackingSurfaceInputsTests(unittest.TestCase):
    def test_admitted_empty_surface_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roles = dict(rf='rf', ip='ip', analyzer='analyzer', detector='detector')
            records = {}
            for name in roles.values():
                for suffix in ('_collision', '_witness', '_surface'):
                    path = root / (name + suffix)
                    path.write_text('original', encoding='utf-8')
                    records[name + suffix] = file_record(path)
            state = root / 'detector_surface_state.json'
            state.write_text('{"mode":"empty"}', encoding='utf-8')
            records['detector_surface_state'] = file_record(state)
            records.pop('detector_surface')
            for key in ('clock_authority', 'instrument_epoch'):
                path = root / key
                path.write_text('clock', encoding='utf-8')
                records[key] = file_record(path)
            source = SimpleNamespace(reference={'manifest': 'fixture'}, data_records=records,
                                     data_path=lambda key: Path(records[key]['path']))
            model = SimpleNamespace(document={'identity': 1})
            admission = dict(model=model, priority={'roles': roles}, immutable_input_records=[])

            def admit(_):
                if 'detector_surface_state' in records:
                    verify_record('state', records['detector_surface_state'])
                return admission

            compiled = SimpleNamespace(frontend_geometry={})
            with patch('msplatform.backends.simion.ip_mr_tracking_admission.admit_ip_mr_tracking_fields', side_effect=admit), \
                 patch('msplatform.backends.simion.tracking_execution._execute_tracking_bound_source', side_effect=lambda *a, **k: k), \
                 patch.object(rf_tracking_execution, '_clock_reference', return_value={}), \
                 patch.object(rf_tracking_execution, 'model_geometry', return_value=compiled):
                result = rf_tracking_execution.execute_ip_mr_tracking(None, source=source, model=model,
                    document={'native_frame_id': 'world'})
                family = result['frontend']['detector']['family_records']
                self.assertEqual([r['path'] for r in family], [records['detector_collision']['path'], str(state)])
                removed = records.pop('detector_surface_state')
                with self.assertRaisesRegex(ValueError, 'surface evidence missing'):
                    rf_tracking_execution.execute_ip_mr_tracking(None, source=source, model=model,
                        document={'native_frame_id': 'world'})
                records['detector_surface_state'] = removed
                state.write_text('tampered', encoding='utf-8')
                with self.assertRaisesRegex(AssertionError, 'changed'):
                    rf_tracking_execution.execute_ip_mr_tracking(None, source=source, model=model,
                        document={'native_frame_id': 'world'})
