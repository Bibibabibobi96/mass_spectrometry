from __future__ import annotations

import csv
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.source_zvz_affine import (
    POLICY_ID as IDENTIFY_POLICY_ID,
    derive_three_zone_working_point,
    identify,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    build_resolved_region_field_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    ContractError,
    _resolve_pa_cache_generation_binding,
    _validate_post_pulse_variation_axis,
    validate_active_post_pulse_restart_working_point,
)


GEOMETRY = {
    "role": "oa_tof_resolved_contract_do_not_edit",
    "geometry_mm": {"L_flight": 600.0, "L_stage1": 120.0, "L_stage2": 96.1563},
    "geometry_derivation": {"accelerator": {
        "source_center_from_repeller_mm": 1.5,
        "focus_drift_after_grid2_mm": 42.75,
    }},
    "electrodes_V": {"midgrid": 1700.0, "entgrid": 0.0, "backplate": 2650.0},
    "single_flight_layout_derivation": {
        "layout_profile_id": "test", "architecture_generation_id": "test",
    },
}
TOPOLOGY = {
    "topology_id": "three_zone_accelerator_ideal_v1",
    "planes_global_z_mm": {
        "repeller": -63.0, "intermediate1": -59.75,
        "intermediate2": -54.65, "exit": -42.75,
    },
    "potentials_v": {
        "repeller": 2115.3846153846152, "intermediate1": 1865.3846153846152,
        "intermediate2": 1619.0, "exit": 0.0,
    },
}


class FullIdealWorkingPointTest(unittest.TestCase):
    def test_adapter_validates_frozen_pa_generation_binding_before_runner_dispatch(self) -> None:
        adapter = (
            Path(__file__).resolve().parents[1]
            / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Frozen PA cache generation binding is missing or stale.",
            adapter,
        )
        self.assertLess(
            adapter.index("Frozen PA cache generation binding is missing or stale."),
            adapter.index("& $runtime.implementation.single_flight_runner @runnerArguments"),
        )

    def test_runner_reparses_pa_generation_binding_from_frozen_path_after_runtime_imports(self) -> None:
        runner = (
            Path(__file__).resolve().parents[1]
            / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "-LiteralPath $frozenPaCacheGenerationBindingPath -Raw -Encoding UTF8",
            runner,
        )

    def test_working_point_voltage_is_not_a_frontend_pa_identity_axis(self) -> None:
        """Voltage-only theory changes reuse the geometry/basis PA generation."""
        root = Path(__file__).resolve().parents[1]
        runner = (root / "runtime" / "run_single_flight.ps1").read_text(
            encoding="utf-8"
        )
        identity_start = runner.index("$frontendCacheIdentity = [ordered]@{")
        identity_end = runner.index("$frontendCacheKey =", identity_start)
        frontend_identity = runner[identity_start:identity_end]
        self.assertIn("frontend_gem_sha256=$frontendHash", frontend_identity)
        self.assertNotIn("source_zvz", frontend_identity)
        self.assertNotIn("working_point", frontend_identity)
        self.assertNotIn("resolved_region_field", frontend_identity)

        downstream_start = runner.index("$identity = [ordered]@{")
        downstream_end = runner.index(
            "$key = Get-RfContentIdentitySha256", downstream_start
        )
        downstream_identity = runner[downstream_start:downstream_end]
        self.assertIn("pa_build_geometry_sha256", downstream_identity)
        self.assertNotIn("oatof_geometry_sha256", downstream_identity)

        artifacts = (root / "runtime" / "run_artifacts.ps1").read_text(
            encoding="utf-8"
        )
        flight_tube_scope_start = artifacts.index(
            "function Get-RfFlightTubePaBuildGeometryIdentity"
        )
        flight_tube_scope_end = artifacts.index(
            "function Assert-RfCacheEntryPath", flight_tube_scope_start
        )
        flight_tube_scope = artifacts[flight_tube_scope_start:flight_tube_scope_end]
        self.assertIn("flight_tube_r", flight_tube_scope)
        self.assertIn("cell_axial_mm", flight_tube_scope)
        self.assertNotIn("electrodes_V", flight_tube_scope)

        frontend = (root / "runtime" / "single_flight_frontend.py").read_text(
            encoding="utf-8"
        )
        topology_validation = frontend[
            frontend.index("accelerator_topology = oatof.get"):
            frontend.index("geometry = oatof[\"geometry_mm\"]")
        ]
        self.assertIn("potential_values", topology_validation)
        self.assertNotIn("lines.append", topology_validation)

    def test_flight_tube_pa_identity_excludes_working_point_voltages(self) -> None:
        """Voltage-only source-z--vz changes reuse the grounded shield PA."""
        pwsh = shutil.which("pwsh")
        self.assertIsNotNone(pwsh)
        artifacts = (
            Path(__file__).resolve().parents[1] / "runtime" / "run_artifacts.ps1"
        )
        script = f"""
. '{artifacts}'
$geometry = [pscustomobject]@{{flight_tube_r=350.0;flight_tube_wall=10.0;shield_endcap_thickness=10.0;shield_outer_z_min=-102.99;L_flight=600.0}}
$build = [pscustomobject]@{{cell_axial_mm=1.0;cell_radial_mm=1.0;max_gib=0.1}}
$baseline = Get-RfContentIdentitySha256 -Identity (Get-RfFlightTubePaBuildGeometryIdentity -Geometry $geometry -Build $build)
$workingPointVoltageOnly = [pscustomobject]@{{repeller=2114.46;grid1=1864.46;intermediate2=1593.63;backplate=2651.80}}
$theory = Get-RfContentIdentitySha256 -Identity (Get-RfFlightTubePaBuildGeometryIdentity -Geometry $geometry -Build $build)
$changedGeometry = [pscustomobject]@{{flight_tube_r=351.0;flight_tube_wall=10.0;shield_endcap_thickness=10.0;shield_outer_z_min=-102.99;L_flight=600.0}}
$changedMesh = [pscustomobject]@{{cell_axial_mm=0.5;cell_radial_mm=1.0;max_gib=0.1}}
$geometryKey = Get-RfContentIdentitySha256 -Identity (Get-RfFlightTubePaBuildGeometryIdentity -Geometry $changedGeometry -Build $build)
$meshKey = Get-RfContentIdentitySha256 -Identity (Get-RfFlightTubePaBuildGeometryIdentity -Geometry $geometry -Build $changedMesh)
if ($baseline -ne $theory -or $baseline -eq $geometryKey -or $baseline -eq $meshKey) {{ throw 'flight-tube PA identity scope mismatch' }}
'FLIGHT_TUBE_PA_IDENTITY_SCOPE=PASS'
"""
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=Path(__file__).resolve().parents[3], text=True,
            encoding="utf-8", errors="replace", capture_output=True,
            check=False, timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("FLIGHT_TUBE_PA_IDENTITY_SCOPE=PASS", completed.stdout)

    def test_exact_pa_generation_binding_requires_existing_cache_and_unique_roles(self) -> None:
        binding = {
            "binding_mode": "require_exact_schema_v3_generations_v1",
            "cache_generations": [{
                "role": "simion_single_flight_frontend_pa_cache",
                "cache_key": "a" * 64,
                "generation_sha256": "b" * 64,
                "payload_sha256": "C" * 64,
            }],
        }
        self.assertEqual(
            _resolve_pa_cache_generation_binding({
                "single_flight_pa_cache_policy": "require_existing",
                "single_flight_pa_cache_generation_binding": binding,
            }),
            binding,
        )
        with self.assertRaisesRegex(ContractError, "require_existing"):
            _resolve_pa_cache_generation_binding({
                "single_flight_pa_cache_policy": "build_and_publish_if_missing",
                "single_flight_pa_cache_generation_binding": binding,
            })
        duplicate = copy.deepcopy(binding)
        duplicate["cache_generations"].append(copy.deepcopy(binding["cache_generations"][0]))
        with self.assertRaisesRegex(ContractError, "roles must be unique"):
            _resolve_pa_cache_generation_binding({
                "single_flight_pa_cache_policy": "require_existing",
                "single_flight_pa_cache_generation_binding": duplicate,
            })

    def test_final_working_point_pair_uses_one_exact_pa_generation_set(self) -> None:
        campaign_path = (
            Path(__file__).resolve().parents[1] / "config" / "diagnostics"
            / "connector_gap_102p4_post_pulse_full_ideal_working_point_pair_n116_v15.json"
        )
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        baseline, theory = campaign["experiments"]
        self.assertEqual(
            baseline["single_flight_pa_cache_policy"], "require_existing"
        )
        self.assertEqual(
            theory["single_flight_pa_cache_policy"], "require_existing"
        )
        self.assertEqual(
            baseline["single_flight_pa_cache_generation_binding"],
            theory["single_flight_pa_cache_generation_binding"],
        )
        self.assertEqual(
            {entry["role"] for entry in baseline[
                "single_flight_pa_cache_generation_binding"]["cache_generations"]},
            {
                "simion_single_flight_frontend_pa_cache",
                "simion_accelerator_overlay_pa_cache",
                "simion_oatof_flight_tube_pa_cache",
            },
        )

    def _post_pulse_theory_experiment(self) -> dict[str, object]:
        return {
            "single_flight_time_integration_profile_id": "dt40",
            "single_flight_accelerator_field_profile_id": "full_domain_three_zone_piecewise_ideal_field",
            "single_flight_source_zvz_affine_policy": "source_zvz_affine_identify_and_bind_v1",
            "single_flight_source_zvz_theory_working_point": {
                "policy_id": "source_zvz_three_zone_theory_working_point_v1",
                "first_zone_drop_v": 250.0,
                "nominal_energy_per_charge_v": 2000.0,
                "reflectron_stage1_voltage_v": 1701.7426470171729,
            },
        }

    def test_post_pulse_theory_axis_allows_only_full_ideal_and_working_point(self) -> None:
        authority = {
            "post_pulse_variation_axis": (
                "accelerator_field_profile_id_and_source_zvz_theory_working_point"
            )
        }
        experiment = self._post_pulse_theory_experiment()
        self.assertEqual(
            _validate_post_pulse_variation_axis(
                experiment=experiment,
                authority=authority,
                producer_time_profile="dt40",
                producer_field_profile="accelerator_real_three_zone_pa_real_reflectron",
            ),
            "full_domain_three_zone_piecewise_ideal_field_"
            "source_zvz_three_zone_theory_working_point_v1",
        )
        for field, value, message in (
            ("single_flight_accelerator_field_profile_id", "unsupported_three_zone_field", "requires a supported three-zone field profile"),
            ("single_flight_source_zvz_affine_policy", None, "requires source z--vz binding"),
            ("single_flight_source_zvz_theory_working_point", None, "authority is missing"),
        ):
            invalid = copy.deepcopy(experiment)
            invalid[field] = value
            with self.assertRaisesRegex(ContractError, message):
                _validate_post_pulse_variation_axis(
                    experiment=invalid,
                    authority=authority,
                    producer_time_profile="dt40",
                    producer_field_profile="accelerator_real_three_zone_pa_real_reflectron",
                )
        for field_profile in (
            "accelerator_real_three_zone_pa_real_reflectron",
            "accelerator_ideal_three_zone_real_reflectron",
            "accelerator_real_three_zone_ideal_reflectron",
            "three_zone_explicit_region_modes",
        ):
            field_variant = copy.deepcopy(experiment)
            field_variant["single_flight_accelerator_field_profile_id"] = field_profile
            self.assertEqual(
                _validate_post_pulse_variation_axis(
                    experiment=field_variant,
                    authority=authority,
                    producer_time_profile="dt40",
                    producer_field_profile="accelerator_real_three_zone_pa_real_reflectron",
                ),
                field_profile + "_source_zvz_three_zone_theory_working_point_v1",
            )
        cross_dt = copy.deepcopy(experiment)
        cross_dt["single_flight_time_integration_profile_id"] = "dt40"
        self.assertEqual(
            _validate_post_pulse_variation_axis(
                experiment=cross_dt,
                authority=authority,
                producer_time_profile="dt160",
                producer_field_profile="accelerator_real_three_zone_pa_real_reflectron",
            ),
            "full_domain_three_zone_piecewise_ideal_field_"
            "source_zvz_three_zone_theory_working_point_v1",
        )
        # The restart boundary is directional but not tied to one preferred
        # producer/consumer pair: either registered profile may consume the
        # frozen pulse state without re-integrating the producer stage.
        reverse_dt = copy.deepcopy(experiment)
        reverse_dt["single_flight_time_integration_profile_id"] = "dt160"
        self.assertEqual(
            _validate_post_pulse_variation_axis(
                experiment=reverse_dt,
                authority=authority,
                producer_time_profile="dt40",
                producer_field_profile="accelerator_real_three_zone_pa_real_reflectron",
            ),
            "full_domain_three_zone_piecewise_ideal_field_"
            "source_zvz_three_zone_theory_working_point_v1",
        )
        with self.assertRaisesRegex(ContractError, "requires its declared variation axis"):
            _validate_post_pulse_variation_axis(
                experiment=experiment,
                authority={"post_pulse_variation_axis": "accelerator_field_profile_id"},
                producer_time_profile="dt40",
                producer_field_profile="accelerator_real_three_zone_pa_real_reflectron",
            )

    def test_active_post_pulse_restart_requires_theory_working_point(self) -> None:
        valid = self._post_pulse_theory_experiment()
        valid.update({
            "source_release_mode": "pre_pulse_restart",
            "post_pulse_restart_reuse_authority": {
                "post_pulse_variation_axis": (
                    "accelerator_field_profile_id_and_source_zvz_theory_working_point"
                )
            },
        })
        validate_active_post_pulse_restart_working_point(valid)
        missing = copy.deepcopy(valid)
        del missing["single_flight_source_zvz_theory_working_point"]
        with self.assertRaisesRegex(ContractError, "theory working point"):
            validate_active_post_pulse_restart_working_point(missing)
        inherited = copy.deepcopy(valid)
        inherited["post_pulse_restart_reuse_authority"][
            "post_pulse_variation_axis"
        ] = "accelerator_field_profile_id"
        with self.assertRaisesRegex(ContractError, "theory variation axis"):
            validate_active_post_pulse_restart_working_point(inherited)

    def test_non_post_pulse_modes_remain_independent(self) -> None:
        validate_active_post_pulse_restart_working_point({
            "source_release_mode": "continuous_frontend",
        })

    def _state(self, root: Path) -> Path:
        path = root / "state.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "particle_id", "mass_amu", "charge_state", "position_z_mm", "velocity_z_m_s"
            ])
            writer.writeheader()
            for index, z in enumerate((-61.9, -61.5, -61.1, -60.7, -60.3), start=1):
                writer.writerow({"particle_id": index, "mass_amu": 100.0, "charge_state": 1,
                                 "position_z_mm": z, "velocity_z_m_s": -2.0 + 90.0 * (z + 61.1)})
        return path

    def test_source_zvz_feature_is_independent_of_full_ideal_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geometry_path = root / "geometry.json"
            geometry_path.write_text(json.dumps(GEOMETRY), encoding="utf-8")
            identified = identify(source_state_path=self._state(root))
            self.assertEqual(identified["policy_id"], IDENTIFY_POLICY_ID)
            self.assertAlmostEqual(
                identified["source_state"]["ols_slope_vz_m_per_s_per_mm"], 90.0
            )
            validate_schema(identified, "rf_oatof_source_zvz_affine_receipt.schema.json")
            # Full ideal is separately usable and receives no z--vz-derived voltage change.
            contract = build_resolved_region_field_contract(
                geometry_path, root / "region.json",
                "full_domain_three_zone_piecewise_ideal_field",
                accelerator_topology=TOPOLOGY,
            )
            validate_schema(contract, "rf_oatof_resolved_region_field_contract.schema.json")
            self.assertNotIn("full_ideal_working_point", contract["semantic"])

    def test_source_zvz_accepts_continuous_multipole_source_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "particle_source.csv"
            source.write_text(
                "particle_id,z_mm,vz_m_s,mass_amu,charge_state\n"
                "1,-1.5,10,100,1\n"
                "2,-1.0,20,100,1\n"
                "3,-0.5,30,100,1\n",
                encoding="utf-8",
            )
            identified = identify(source_state_path=source)
            self.assertAlmostEqual(
                identified["source_state"]["ols_slope_vz_m_per_s_per_mm"],
                20.0,
            )

    def test_rejects_degenerate_source_without_consulting_field_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self._state(root)
            state.write_text(
                "particle_id,mass_amu,charge_state,position_z_mm,velocity_z_m_s\n1,100,1,-61,0\n2,100,1,-61,1\n3,100,1,-61,2\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "degenerate"):
                identify(source_state_path=state)

    def test_working_point_is_derived_from_source_geometry_and_native_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geometry = dict(GEOMETRY)
            geometry["accelerator_topology"] = TOPOLOGY
            receipt = identify(source_state_path=self._state(root))
            request = {
                "first_zone_drop_v": 250.0,
                "nominal_energy_per_charge_v": 2000.0,
                "reflectron_stage1_voltage_v": 1700.0,
            }
            working_point = derive_three_zone_working_point(
                source_receipt=receipt, resolved_geometry=geometry,
                resolved_geometry_input_sha256="A" * 64,
                theory_request=request,
            )
            self.assertEqual(
                working_point["source_state_sha256"], receipt["source_state"]["sha256"]
            )
            self.assertEqual(
                working_point["resolved_geometry_input_sha256"], "A" * 64
            )
            validate_schema(working_point, "rf_oatof_theory_working_point.schema.json")
            self.assertLess(abs(working_point["verification"]["reflectron_d1_mm_per_sqrt_v"]), 1e-10)
            self.assertNotEqual(
                working_point["accelerator_topology"]["potentials_v"], TOPOLOGY["potentials_v"]
            )

    def test_all_three_field_profiles_consume_identical_theory_potentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geometry = copy.deepcopy(GEOMETRY)
            geometry["accelerator_topology"] = copy.deepcopy(TOPOLOGY)
            working_point = derive_three_zone_working_point(
                source_receipt=identify(source_state_path=self._state(root)),
                resolved_geometry=geometry,
                resolved_geometry_input_sha256="B" * 64,
                theory_request={
                    "first_zone_drop_v": 250.0,
                    "nominal_energy_per_charge_v": 2000.0,
                    "reflectron_stage1_voltage_v": 1700.0,
                },
            )
            geometry["accelerator_topology"] = working_point["accelerator_topology"]
            geometry["electrodes_V"].update({
                "repeller": working_point["accelerator_topology"]["potentials_v"]["repeller"],
                "grid1": working_point["accelerator_topology"]["potentials_v"]["intermediate1"],
                "grid2": 0.0,
                "midgrid": working_point["reflectron"]["stage1_voltage_v"],
                "backplate": working_point["reflectron"]["backplate_voltage_v"],
            })
            geometry_path = root / "geometry.json"
            geometry_path.write_text(json.dumps(geometry), encoding="utf-8")
            profiles = (
                "accelerator_ideal_three_zone_real_reflectron",
                "accelerator_real_three_zone_pa_real_reflectron",
                "full_domain_three_zone_piecewise_ideal_field",
            )
            contracts = [build_resolved_region_field_contract(
                geometry_path, root / (profile + ".json"), profile,
                accelerator_topology=working_point["accelerator_topology"],
            ) for profile in profiles]
            topologies = [contract["semantic"]["accelerator_topology"] for contract in contracts]
            self.assertEqual(topologies[0], topologies[1])
            self.assertEqual(topologies[1], topologies[2])
            self.assertEqual(
                geometry["electrodes_V"]["backplate"],
                working_point["reflectron"]["backplate_voltage_v"],
            )
            self.assertNotEqual(
                contracts[0]["semantic"]["region_modes"],
                contracts[1]["semantic"]["region_modes"],
            )

    def test_changed_source_relation_rederives_working_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geometry = copy.deepcopy(GEOMETRY)
            geometry["accelerator_topology"] = copy.deepcopy(TOPOLOGY)
            state = self._state(root)
            request = {
                "first_zone_drop_v": 250.0,
                "nominal_energy_per_charge_v": 2000.0,
                "reflectron_stage1_voltage_v": 1700.0,
            }
            first = derive_three_zone_working_point(
                source_receipt=identify(source_state_path=state),
                resolved_geometry=geometry,
                resolved_geometry_input_sha256="C" * 64,
                theory_request=request,
            )
            with state.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row["velocity_z_m_s"] = str(-2.0 + 130.0 * (float(row["position_z_mm"]) + 61.1))
            with state.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            second = derive_three_zone_working_point(
                source_receipt=identify(source_state_path=state),
                resolved_geometry=geometry,
                resolved_geometry_input_sha256="C" * 64,
                theory_request=request,
            )
            self.assertNotEqual(first["source_state_sha256"], second["source_state_sha256"])
            self.assertNotEqual(
                first["accelerator_topology"]["potentials_v"],
                second["accelerator_topology"]["potentials_v"],
            )
