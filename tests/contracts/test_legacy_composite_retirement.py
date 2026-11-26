"""Historical composite data remains readable but cannot start new native owners."""
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform import assembly, components, examples
from msplatform.backends import simion
from msplatform.backends.simion.compiler import compile_geometry as historical_compile
from msplatform.contracts.machine_contracts import ContractError


class LegacyCompositeRetirementTests(unittest.TestCase):
    def test_public_execution_rejects_before_owner_and_pure_history_is_readable(self):
        # Import before stubbing model validation so module-level bindings stay real.
        import msplatform.backends.simion.field_execution  # noqa: F401
        case = examples.load_example('rf_oatof_functional_v1')
        parts = {name: components.resolve_component(request) for name, request in case.component_requests.items()}
        design = assembly.assemble(case.recipe, parts)
        old = historical_compile(dict(composition_plan=design.composition_plan, components_resolved=design.components_resolved),
                                 numerics=case.geometry_numerics)
        self.assertTrue(old.frontend_geometry['composition_plan']['scope']['instance_ids'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiled = root/'compiled.json'
            compiled.write_text(json.dumps(asdict(old)), encoding='utf8')
            fake = SimpleNamespace(kind='field_bundle', metadata=dict(backend='simion', field_status='available', source_status='not_requested'),
                                   data_path=lambda key: compiled)
            context = SimpleNamespace(tools={'simion':Path(sys.executable)})
            stage = dict(runtime={})
            document = dict(geometry=dict(frontend_geometry=old.frontend_geometry))
            with patch('msplatform.execution.owner.run_managed_stage') as owner, \
                 patch('msplatform.backends.simion.operations.artifact_reader.open_artifact', return_value=fake), \
                 patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
                 patch('msplatform.backends.simion.field_closure.load_field_model', return_value=SimpleNamespace(model=SimpleNamespace(document=document))), \
                 patch('msplatform.backends.simion.artifacts.CompiledPreparedModel', return_value=object()), \
                 patch('msplatform.backends.simion.model.require_prepared_model', return_value=document):
                with self.assertRaisesRegex(ContractError, 'historical read-only'):
                    simion.compile_geometry(design, numerics=case.geometry_numerics)
                with self.assertRaisesRegex(ContractError, 'historical read-only'):
                    simion.build_geometry(old, context=context)
                with self.assertRaisesRegex(ContractError, 'historical read-only'):
                    simion.prepare_model({}, drive={}, physics={}, context=context)
                with self.assertRaisesRegex(ContractError, 'historical read-only'):
                    simion.solve_fields({}, numerics={}, context=context)
                with self.assertRaisesRegex(ContractError, 'historical read-only'):
                    simion.track({}, {}, propagation={}, observations={}, numerics={}, context=context)
                owner.assert_not_called()

    def test_mass_scan_legacy_execution_rejected_before_any_native_io(self):
        from msplatform.backends.simion.mass_spectrum import run_mixed_species_fly
        from msplatform.workflows.single_reflection_mass_spectrum_study import run, _run_action
        from unittest.mock import Mock
        session = Mock()
        with self.assertRaisesRegex(ValueError, 'mass_scan'):
            run_mixed_species_fly(session, operation_id='', simion_executable=Path('x'), artifact_project_root=Path('x'),
                project_id='', combined_ion=Path('x'), total_particles=1, max_tof_us=1., output_csv=Path('x'),
                summary_path=Path('x'), runtime_receipt=Path('x'), limits={}, immutable_input_records=[])
        with self.assertRaisesRegex(ValueError, 'mass_scan'):
            _run_action(session, requested={}, original={}, stage={}, partial_parent=None)
        with self.assertRaisesRegex(ValueError, 'mass_scan'):
            run(None, run_id='', mode_config=Path('x'), resolved_geometry=Path('x'), particle_count_policy=Path('x'),
                formal_mph=Path('x'), formal_asset_manifest=Path('x'), simion_executable=Path('x'),
                artifact_project_root=Path('x'), project_config=Path('x'), formal_assets=Path('x'), baseline=Path('x'),
                formal_mode=Path('x'), solver_numerics=Path('x'))
        session.assert_not_called()
        session.run_process.assert_not_called()


if __name__ == '__main__': unittest.main()
