"""COMSOL native scope uses frozen Assembly provenance, not instance names."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from msplatform import assembly, components
from msplatform.backends.comsol.assembly_native_scope import require_supported_artifact, require_supported_plan
from msplatform.backends.comsol.geometry_execution import resolve_geometry_request
from msplatform.io.manifest_records import file_record


class ComsolNativeScopeTests(unittest.TestCase):
    def test_selected_project_identity_and_unknown_fail_closed(self):
        require_supported_plan({'components': {'single_reflection_oa_tof': {'project_id': 'single_reflection_tof'}}})
        for plan in ({}, {'components': {}}, {'components': {'renamed': {}}},
                     {'components': {'renamed': {'project_id': 'single_reflection_oa_tof_mass_analyzer'}}}):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                require_supported_plan(plan)

    def test_frozen_geometry_provenance_and_projection(self):
        path = Path(__file__).resolve().parents[2] / 'src/msplatform/examples/oa_split_tof_native_small_v1.json'
        study = json.loads(path.read_text(encoding='utf-8'))
        instrument = assembly.assemble(study['recipe'], {k: components.resolve_component(v) for k,v in study['component_requests'].items()})
        result = resolve_geometry_request(instrument, outer_box_mm={'min': [-400,-400,-100], 'max': [400,400,920]},
                                          geometry_validation={'position_mm': 1e-6, 'normal_abs': 1e-6})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); proj = root/'projection.json'; config = root/'config.json'; manifest = root/'manifest.json'
            proj.write_text(json.dumps(result['projection']), encoding='utf-8')
            parameters = {'action': 'build_comsol_geometry', 'assembly': result['assembly'], 'projection': result['projection']}
            config.write_text(json.dumps({'parameters': parameters}), encoding='utf-8')
            projection_record = file_record(proj, 'required_evidence')
            def save():
                config_record = file_record(config, 'required_evidence')
                manifest.write_text(json.dumps({'run_config': config_record, 'inputs': {}, 'outputs': [projection_record]}), encoding='utf-8')
            save()
            artifact = SimpleNamespace(kind='geometry_artifact', data_records={'projection': projection_record},
                                       manifest_location=manifest, data_path=lambda name: proj)
            require_supported_artifact(artifact)
            mismatched = copy.deepcopy(parameters)
            mismatched['projection']['outer_box_mm']['max'][0] += 1
            config.write_text(json.dumps({'parameters': mismatched}), encoding='utf-8'); save()
            with self.assertRaisesRegex(ValueError, 'projection differ'):
                require_supported_artifact(artifact)
            altered = copy.deepcopy(parameters)
            altered['assembly']['composition_plan']['components']['tof']['project_id'] = 'single_reflection_oa_tof_mass_analyzer'
            config.write_text(json.dumps({'parameters': altered}), encoding='utf-8'); save()
            with self.assertRaisesRegex(ValueError, 'retired composite'):
                require_supported_artifact(artifact)
            altered['assembly']['composition_plan']['components']['tof'].pop('project_id')
            config.write_text(json.dumps({'parameters': altered}), encoding='utf-8'); save()
            with self.assertRaisesRegex(ValueError, 'project identities'):
                require_supported_artifact(artifact)
