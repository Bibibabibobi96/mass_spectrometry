"""One explicit negative ion retains the historical synthetic row through tracking."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from msplatform.backends.simion.rf_tracking_program import render_rf_controls
from msplatform.backends.simion.tracking_collection import collect_tracking_logs
from msplatform.backends.simion.tracking_execution import plan_tracking_execution
from tests.contracts.test_simion_rf_tracking import rf_tracking_case
from tests.contracts.test_support.terminal_evidence_fixture import terminal_wire_lines


class NegativeIonTrackingTests(unittest.TestCase):
    def test_negative_ion_single_species_planner_and_collector(self):
        _, model, packet, clocks, propagation, numerics = rf_tracking_case()
        row = copy.deepcopy(packet['rows'][1])
        self.assertEqual((row['particle_id'], row['mass_amu'], row['charge_state'], row['particle_weight']),
                         (91, 200., -2, 4.))
        packet['rows'] = [row]
        packet['mother']['records'] = {91: packet['mother']['records'][91]}
        packet['mother']['fates'] = [item for item in packet['mother']['fates'] if item['particle_id'] == 91]
        packet['realization']['spec'] = {'particle_count': 1,
            'species': {'species_kind': 'ion', 'mass_amu': 200., 'charge_state': -2}}
        plan = plan_tracking_execution(model, particles=packet, clock_records=clocks,
            propagation=propagation, observations={'plane_observations': []}, numerics=numerics)
        self.assertEqual((plan['rows'][0]['particle_id'], plan['rows'][0]['charge_state']), (91, -2))
        controls = render_rf_controls(model, plan, assets={}, native_sources={})
        metadata = copy.deepcopy(controls['build_metadata'])
        metadata['terminal_evidence'] = {'schema_version': 1, 'native_run': 'negative-ion-fixture'}
        state = dict(event='source_release', reason='none', particle_id=91, ion=1,
                     instrument_time_us=row['instrument_time_us'], mass_amu=200., charge_state=-2, instance=1)
        state.update({axis+'_mm': row['position_'+axis+'_mm'] for axis in 'xyz'})
        state.update({'v'+axis+'_mm_per_us': row['velocity_'+axis+'_m_s']/1000 for axis in 'xyz'})
        lines = ['RF_DYNAMICS_V1: {"grouped":0,"repulsion":"none","relativity":0,"segment_global":1}']
        lines.extend(terminal_wire_lines(row, 1, 'negative-ion-fixture', 2., 1))
        lines.extend(['RF_NATIVE_STATE_V1: '+json.dumps(state),
                      'RF_NATIVE_STATE_V1: '+json.dumps(dict(state, event='terminal', reason='unknown', instrument_time_us=2.)),
                      'status,Fly completed. 1 splats'])
        with TemporaryDirectory() as directory:
            log = Path(directory) / 'native.log'
            log.write_text('\n'.join(lines)+'\n', encoding='utf8')
            collected = collect_tracking_logs([log], source_rows={91: row}, source_provenance=plan['source_provenance'],
                flight=plan['flight'], batches=[{'source_row_range': [1, 1], 'expected_particle_ids': [91],
                                                 'build_metadata': metadata}])
        terminal = collected['native_terminals'][0]
        self.assertEqual((terminal['particle_id'], terminal['mass_amu'], terminal['charge_state']), (91, 200., -2))
        self.assertEqual(collected['original_mother']['mother_records'][0]['particle_weight'], 4.)


if __name__ == '__main__':
    unittest.main()
