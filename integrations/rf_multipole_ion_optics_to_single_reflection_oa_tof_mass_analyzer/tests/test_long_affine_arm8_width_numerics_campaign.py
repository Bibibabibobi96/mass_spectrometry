from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    FULL_ID,
    build_resolved_region_field_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    validate_full_domain_affine_width_numerics_campaign,
)


ROOT = Path(__file__).resolve().parents[3]
INTEGRATION = ROOT / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
CAMPAIGN = INTEGRATION / "config/diagnostics/canonical_long_affine_arm8_width_numerics_n1000_campaign.json"
RESTART_CAMPAIGN = INTEGRATION / "config/diagnostics/canonical_long_affine_arm8_width_numerics_restart_n1000_campaign.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class LongAffineArm8WidthNumericsCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = load(CAMPAIGN)
        self.restart_campaign = load(RESTART_CAMPAIGN)
        self.registry = load(INTEGRATION / "config/simion_single_flight.json")
        self.policy = load(INTEGRATION / "config/execution_policy.json")

    def test_schema_and_exact_five_cell_matrix(self) -> None:
        validate_schema(self.campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        self.assertEqual(self.campaign["status"], "archived_invalid")
        self.assertEqual(
            self.campaign["preregistration"]["status"],
            "REGISTERED_EXECUTION_REQUIRES_EXPLICIT_AUTHORIZATION",
        )
        self.assertIn("3+2", self.restart_campaign["claim_limit"])
        validate_full_domain_affine_width_numerics_campaign(
            self.campaign, self.registry, self.policy, ROOT
        )
        validate_schema(
            self.restart_campaign,
            "rf_multipole_oatof_experiment_campaign.schema.json",
        )
        self.assertEqual(
            self.restart_campaign["status"], "authorized"
        )
        validate_full_domain_affine_width_numerics_campaign(
            self.restart_campaign, self.registry, self.policy, ROOT
        )
        self.assertEqual(
            [(item["profile_id"], item["rf_steps_per_period"])
             for item in self.registry["time_integration_profiles"]],
            [("dt160", 160), ("dt320", 320)],
        )
        self.assertNotIn("rf_steps_per_period", self.registry)
        self.assertNotIn("trajectory_quality", self.registry)

    def test_matrix_rejects_missing_cell_and_wrong_resource_gate(self) -> None:
        missing = copy.deepcopy(self.campaign)
        missing["experiments"].pop()
        with self.assertRaises(ContractError):
            validate_full_domain_affine_width_numerics_campaign(
                missing, self.registry, self.policy, ROOT
            )
        wrong_policy = copy.deepcopy(self.policy)
        wrong_policy["stage_limits"]["single_flight_transport"][
            "minimum_system_available_memory_bytes"
        ] = 8 * 1024**3
        with self.assertRaises(ContractError):
            validate_full_domain_affine_width_numerics_campaign(
                self.campaign, self.registry, wrong_policy, ROOT
            )

    def test_exact_pulse_family_has_no_continuous_compatibility_fallback(self) -> None:
        wrong_release = copy.deepcopy(self.restart_campaign)
        wrong_release["experiments"][0]["source_release_mode"] = "continuous_frontend"
        with self.assertRaises(ContractError):
            validate_full_domain_affine_width_numerics_campaign(
                wrong_release, self.registry, self.policy, ROOT
            )
        wrong_source = copy.deepcopy(self.restart_campaign)
        wrong_source["experiments"][1]["pre_pulse_source_state"]["sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            validate_full_domain_affine_width_numerics_campaign(
                wrong_source, self.registry, self.policy, ROOT
            )
        resurrected = copy.deepcopy(self.campaign)
        resurrected["status"] = "authorized"
        with self.assertRaises(ContractError):
            validate_full_domain_affine_width_numerics_campaign(
                resurrected, self.registry, self.policy, ROOT
            )

    def test_resolved_geometry_translates_to_existing_arm8_contract(self) -> None:
        geometry = load(
            ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        port = load(
            ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json"
        )
        profiles = load(INTEGRATION / "config/single_flight_layout_profiles.json")
        compiled, _, _ = compile_geometry_and_port(
            geometry, port,
            select_profile(profiles, "symmetric_10ev_source_z22_finite_interval_theory"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            geometry_path = root / "resolved_oatof_geometry.json"
            contract_path = root / "resolved_region_field_contract.json"
            geometry_path.write_text(json.dumps(compiled), encoding="utf-8")
            contract = build_resolved_region_field_contract(
                geometry_path, contract_path, FULL_ID
            )
            self.assertEqual(
                contract["role"], "rf_oatof_resolved_region_field_contract"
            )
            self.assertFalse(contract["semantic"]["real_pa_field_blending_allowed"])
            self.assertEqual(
                contract["semantic"]["planes_mm"]["reflectron_backplate"],
                compiled["geometry_mm"]["L_flight"]
                + compiled["geometry_mm"]["L_stage1"]
                + compiled["geometry_mm"]["L_stage2"],
            )
            stale = copy.deepcopy(compiled)
            stale["electrodes_V"]["grid1"] += 1
            geometry_path.write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_resolved_region_field_contract(geometry_path, contract_path, FULL_ID)

    def test_runner_uses_profile_authorities_without_new_physics_renderer(self) -> None:
        runner = (INTEGRATION / "runtime/run_single_flight.ps1").read_text(encoding="utf-8")
        adapter = (INTEGRATION / "workflows/family_source_closure/adapter.ps1").read_text(
            encoding="utf-8"
        )
        builder = (INTEGRATION / "runtime/build_single_flight_program.py").read_text(encoding="utf-8")
        self.assertIn("$timeIntegrationProfiles", runner)
        self.assertIn('single_flight_rf_steps={0}" -f $rfStepsPerPeriod', runner)
        self.assertNotIn("$settings.rf_steps_per_period", runner)
        self.assertNotIn("PulseResolutionArm8GlobalFieldContract", runner)
        self.assertIn("Campaign status permits validation only", adapter)
        self.assertIn("resolved_region_field_hook_lua", builder)
        self.assertNotIn("full_domain_piecewise_field_lua", builder)


if __name__ == "__main__":
    unittest.main()
