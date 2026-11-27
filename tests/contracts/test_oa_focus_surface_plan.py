"""OA focus mirrored geometry plans retain their explicit empty-surface identity."""
import json
import tempfile
import unittest
from pathlib import Path

from msplatform.backends.simion.model import model_geometry
from msplatform.backends.simion.native_plans import plan_geometry_build, plan_model_preparation
from msplatform.backends.simion.resources import STRUCTURAL_SEEDS
from msplatform.backends.simion.rf_field_execution import _field_contract
from msplatform.workflows.oa_focus_model_projection import project_focus_model


class FocusSurfacePlanTests(unittest.TestCase):
    def test_author_model_plans_real_empty_surface_evidence(self):
        root = Path(__file__).resolve().parents[2] / 'src/msplatform/components/orthogonal_accelerator'
        campaign = root / 'config/two_zone_component_focus_campaign.json'
        author = json.loads(campaign.read_text(encoding='utf8'))
        profile = json.loads((root / 'component_contract.json').read_text(encoding='utf8'))['geometry_profiles'][author['geometry_profile_id']]
        clock = dict(clock_epoch_id='focus_test', authority_sha256='A' * 64, phase_reference_instrument_time_us=0.)
        projection = project_focus_model(campaign, geometry_profile=profile, mesh_mm_per_gu=[.25, .25, .1], clock=clock)
        compiled = model_geometry(projection['model'])
        self.assertEqual(_field_contract(compiled.frontend_geometry)[0], 'producer_owned_oa_mirror_empty_surface_family')
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            size, sha = STRUCTURAL_SEEDS[1]
            seed = dict(path=str(temp / 'seed.iob'), bytes=size, sha256=sha)
            plan = plan_geometry_build(compiled, run_directory=temp, seed_record=seed, native_path_resource=temp / 'native.lua')
            operation = next(row for row in plan.operations if row['operation_id'] == 'geometry_oa')
            self.assertTrue(operation['outputs'][2].endswith('_surface_state.json'))
            self.assertTrue(operation['optional_surface'].endswith('.pa-surf'))
            self.assertNotIn(operation['optional_surface'], operation['outputs'])
            audit = plan.materializations[str(temp / 'inputs/oa_build.lua')]
            self.assertIn('surface_state', audit)
            self.assertIn('fractional_surface', audit)
            def record(name):
                return dict(path=str(temp / name), bytes=1, sha256='A' * 64)
            assets = {'oa': dict(raw_record=record('oa.pa#'), surface_records=[],
                                 witness_record=record('witness.csv'), state_record=record('state.json'))}
            model_plan = plan_model_preparation(projection['model'], geometry_assets=assets,
                run_directory=temp, seed_record=seed, native_path_resource=temp / 'native.lua')
            destinations = [item['destination'] for item in model_plan.input_copies]
            self.assertTrue(any(path.endswith('_surface_state.json') for path in destinations))
            self.assertFalse(any(path.endswith('.pa-surf') for path in destinations))


if __name__ == '__main__':
    unittest.main()
