"""Static checks for the Wehnelt MATLAB resolved-contract boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MATLAB = REPO_ROOT / "src/msplatform/backends/comsol/matlab"
ACTIVE_SCRIPTS = (
    MATLAB / "phase1_geometry_coil_transverse.m",
    MATLAB / "phase2_electrostatics_coil_transverse.m",
    MATLAB / "phase4_thermal_emission_coil_transverse.m",
)


class MatlabContractBindingTests(unittest.TestCase):
    """Keep all active stages fail-closed and contract-driven."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {
            path.name: path.read_text(encoding="utf-8") for path in ACTIVE_SCRIPTS
        }
        cls.combined = "\n".join(cls.sources.values())
        cls.binding = (
            MATLAB / "wehnelt_contract_parameter_bindings.m"
        ).read_text(encoding="utf-8")
        cls.loader = (MATLAB / "load_wehnelt_contract.m").read_text(
            encoding="utf-8"
        )
        cls.resolver = (
            REPO_ROOT
            / "src/msplatform/components/transverse_helical_filament_wehnelt_electron_gun/resolve_contract.py"
        ).read_text(encoding="utf-8")

    def test_every_stage_requires_and_loads_resolved_contract(self) -> None:
        for name, source in self.sources.items():
            with self.subTest(name=name):
                self.assertIn("resolvedContractPath", source)
                self.assertIn("load_wehnelt_contract", source)
                self.assertIn("no defaults exist", source)
                self.assertIn("apply_wehnelt_contract_parameters", source)

    def test_geometry_and_physics_use_named_contract_parameters(self) -> None:
        required = (
            "set('rmaj', 'coil_rmaj')",
            "set('pos', {'coil_xmin' '0' 'coil_zc'})",
            "set('V0', 'V_wehnelt')",
            "set('hmax', 'mesh_coil_hmax')",
            "set('T', 'filament_T')",
            "particleProperties.set('mp'",
            "particleProperties.set('Z', particle.charge_state)",
            "wall.set('WallCondition', terminalOutcomes.wall_condition)",
            "range(particle_t_start,particle_t_step,particle_t_end)",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.combined)

    def test_active_scripts_do_not_duplicate_physical_defaults(self) -> None:
        forbidden = (
            "'0.3[mm]'",
            "'0.05[mm]'",
            "'-0.5[V]'",
            "'70[V]'",
            "'2700[K]'",
            "'0.03[mm]'",
            "'0.005[mm]'",
            "'range(0,0.1[ns],40[ns])'",
            "KE_eV > 60",
            "KE_eV < 75",
            "coil_turns*coil_pitch",
            "z_weh_top+gap2",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.combined)

    def test_parameter_binding_exposes_derived_coordinates_and_modes(self) -> None:
        required = (
            "derived.wehnelt_cavity_ceiling_z_mm",
            "derived.anode_bottom_z_mm",
            "derived.vacuum_domain_top_z_mm",
            "numerical.mesh.filament_surface_hmax_mm",
            "numerical.particle_time_ns.step",
            "metric.usable_energy_min_eV",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.binding)
        self.assertIn("physical.usable_final_state_metric", self.binding)
        self.assertNotIn("collection_metric", self.binding)

    def test_loader_enforces_execution_mode_and_particle_count(self) -> None:
        required = (
            "minimumCount = contract.evidence.minimum_particle_count",
            "strcmp(contract.numerical.execution_mode, 'full')",
            "sampling.seed_control",
            "~sampling.reproducible_particle_realization",
            "~emission.beam_current_supported",
            "~terminal.wall_loss_attribution_supported",
            "contract.physical.usable_final_state_metric",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.loader)

    def test_build_only_returns_before_electrostatic_and_particle_solvers(self) -> None:
        for name in (
            "phase2_electrostatics_coil_transverse.m",
            "phase4_thermal_emission_coil_transverse.m",
        ):
            source = self.sources[name]
            guard = source.index("if strcmp(executionMode, 'build_only')")
            guarded_return = source.index("return;", guard)
            solver_run = source.index(".runAll;", guarded_return)
            with self.subTest(name=name):
                self.assertLess(guard, guarded_return)
                self.assertLess(guarded_return, solver_run)

    def test_particle_postprocessing_enforces_full_finite_position_rule(self) -> None:
        source = self.sources["phase4_thermal_emission_coil_transverse.m"]
        required = (
            "qx_end = pd.p(end,:,1)",
            "qy_end = pd.p(end,:,2)",
            "qz_end = pd.p(end,:,3)",
            "isfinite(qx_end) & isfinite(qy_end) & isfinite(qz_end)",
            "finiteVelocity = isfinite(vx) & isfinite(vy) & isfinite(vz)",
            "KEv = KE_eV(validEnergy)",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, source)
        self.assertNotIn("valid = ~isnan(qz_end)", source)
        self.assertNotIn("me_ =", source)
        self.assertNotIn("qe =", source)
        self.assertNotIn("self-absorbed", source)
        self.assertNotIn("passed anode", source)
        self.assertIn("unclassified; no wall-loss", source)
        self.assertIn("contract.physical.filament.material_identity", source)
        self.assertIn("particle.mass_kg", source)
        self.assertIn("particle.charge_C", source)
        self.assertIn("contract.physical.usable_final_state_metric", source)
        self.assertNotIn("collection_metric", source)
        self.assertNotIn("collection efficiency", source.lower())

    def test_required_particle_dataset_is_not_optional_plotting_work(self) -> None:
        source = self.sources["phase4_thermal_emission_coil_transverse.m"]
        dataset_index = source.index(
            "pdset1 = model.result.dataset.create('pdset1', 'Particle');"
        )
        plotting_try_index = source.index("try", dataset_index)
        extraction_index = source.index(
            "pd = mphparticle(model, 'dataset', 'pdset1');"
        )
        self.assertLess(dataset_index, plotting_try_index)
        self.assertLess(plotting_try_index, extraction_index)

    def test_frozen_resolver_uses_core_without_legacy_json_dependencies(self) -> None:
        self.assertIn("from msplatform.contracts.particle_physics import (", self.resolver)
        self.assertNotIn("common.contracts.strict_json", self.resolver)
        self.assertNotIn("common.contracts.particle_physics", self.resolver)


if __name__ == "__main__":
    unittest.main()
