"""Provider-owned RF scientific drive, with native validation at the SIMION boundary."""
import copy
import unittest

from common.contracts import test_ip_mr_model as fixture_models
from msplatform.backends.simion.electrode_contract import scientific_multipole_drive as native_drive
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
from msplatform.components.rf_multipole.drive import scientific_multipole_drive as component_drive


class RfComponentDriveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_models.RfIpMrModelTests.setUpClass()
        cls.fixture = fixture_models.RfIpMrModelTests
        cls.resolved = cls.fixture.compiled.components_resolved['multipole']
        cls.mapping = cls.fixture.compiled.frontend_geometry['electrode_bindings']['multipole']

    def test_native_number_permutation_preserves_scientific_values(self):
        original = component_drive(self.resolved)
        self.assertEqual(native_drive(self.resolved, self.mapping), original)
        values = list(reversed(list(self.mapping.values())))
        permuted = dict(zip(self.mapping, values))
        self.assertEqual(native_drive(self.resolved, permuted), original)
        incomplete = dict(self.mapping)
        incomplete.pop(next(iter(incomplete)))
        with self.assertRaises(ValueError):
            native_drive(self.resolved, incomplete)

    def test_carrier_static_and_rf_group_values(self):
        from msplatform.backends.simion.electrode_contract import scientific_multipole_voltages
        from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
        carrier, groups = scientific_multipole_voltages(self.resolved, self.mapping)
        drives = component_drive(self.resolved)
        for row in build_electrode_topology(self.resolved):
            group = row['electrode_group_id']
            solver = self.mapping[group]
            drive = drives[group]
            if drive['kind'] == 'static':
                self.assertEqual(carrier[solver], drive['voltage_v'])
                self.assertNotIn(solver, groups)
            else:
                self.assertEqual(carrier[solver], drive['common_mode_v'] + drive['dc_v'])
                self.assertEqual(groups[solver], row['voltage_source']['rf_group'])
    def test_actual_source_amplitude_phase_and_model_consumer(self):
        source = copy.deepcopy(self.resolved)
        source['drive']['phase_rad'] += 0.25
        source['drive']['rf_amplitude_V_zero_to_peak_per_group'] += 2.0
        groups = component_drive(source)
        self.assertEqual(groups, native_drive(source, self.mapping))
        from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
        for electrode in build_electrode_topology(source):
            actual = groups[electrode['electrode_group_id']]
            authority = electrode['voltage_source']
            if authority['kind'] == 'static':
                value = source
                for token in authority['pointer'].split('/')[1:]:
                    value = value[int(token)] if isinstance(value, list) else value[token]
                self.assertEqual(actual, {'kind': 'static', 'voltage_v': float(value)})
            else:
                polarity = 1 if authority['rf_group'] == 1 else -1
                self.assertEqual(actual['polarity'], polarity)
                value = source
                for token in authority['dc_amplitude_pointer'].split('/')[1:]:
                    value = value[int(token)] if isinstance(value, list) else value[token]
                self.assertEqual(actual['dc_v'], polarity * float(value))
        for row in groups.values():
            if row['kind'] == 'rf':
                self.assertEqual(row['phase_rad'], source['drive']['phase_rad'])
                self.assertEqual(row['rf_amplitude_v'], source['drive']['rf_amplitude_V_zero_to_peak_per_group'])
        result = compile_prepared_model(self.fixture.compiled, self.fixture.compiled.components_resolved,
                                        drive=self.fixture.drive, physics=RF_IP_PHYSICS)
        self.assertEqual(result.document['drive']['groups']['multipole'], component_drive(self.resolved))