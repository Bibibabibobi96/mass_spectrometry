"""Real provider source and interface reject boolean resolved schema versions."""
import json
from pathlib import Path
import unittest

from msplatform.components.catalog import _from_provider, resolve_component
from msplatform.contracts.machine_contracts import ContractError
from msplatform.examples import load_example
from tests.components.multi_reflection_tof.analysis.test_mr_provider_trial_transport import _plans
from tests.components.multi_reflection_tof.test_support.mr_geometry_inputs import geometry_authority

ROOT = Path(__file__).resolve().parents[2]

class ProviderSchemaVersionTests(unittest.TestCase):
    def test_existing_providers_refuse_boolean_resolved_version(self):
        case = load_example('rf_oatof_functional_v1')
        parts = {name: resolve_component(request) for name, request in case.component_requests.items()}
        _, _, contract = _plans()
        authority = geometry_authority(contract)
        common = {'accelerator_requirements': authority['accelerator_requirements'],
                  'geometry_profile': authority['geometry_profile']}
        profile = authority['geometry_profile_id']
        parts['oa'] = resolve_component({'provider_id': 'orthogonal_accelerator',
            'design': {'requirements': common['accelerator_requirements'], 'geometry_profile': common['geometry_profile']},
            'geometry_profile_id': profile})
        parts['mr'] = resolve_component({'provider_id': 'multi_reflection_tof',
            'design': {'contract': contract, **common}, 'geometry_profile_id': profile})
        baseline = json.loads((ROOT / 'src/msplatform/components/ion_processor/config/baseline.json').read_text(encoding='utf-8'))
        baseline['physical_design_selection'] = {'native_grid_mm': .1, 'native_aux_segments': 60}
        parts['ip'] = resolve_component({'provider_id': 'ion_processor', 'design': {'baseline': baseline}})
        cone = json.loads((ROOT / 'src/msplatform/components/dual_cone_tandem_quadrupole/config/baseline.json').read_text(encoding='utf-8'))
        parts['cone'] = resolve_component({'provider_id': 'dual_cone_tandem_quadrupole', 'design': cone})
        self.assertEqual(len(parts), 6)
        for name, item in parts.items():
            with self.subTest(provider=name):
                _from_provider(item.provider_id, item.resolved_design, item.assembly_interface, source_design=item.source_design)
                changed = item.resolved_design
                changed['schema_version'] = True
                with self.assertRaises((ValueError, ContractError)):
                    _from_provider(item.provider_id, changed, item.assembly_interface, source_design=item.source_design)

        source = parts['cone'].source_design
        source['schema_version'] = True
        with self.assertRaises((ValueError, ContractError)):
            _from_provider(parts['cone'].provider_id, parts['cone'].resolved_design,
                parts['cone'].assembly_interface, source_design=source)
