from __future__ import annotations

import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.verify_single_flight_pa_cache_readiness import (
    LOCAL_ROLE,
    MAIN_ROLE,
    main,
    verify_readiness,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    resolve_three_zone_pa_plus_solution_model,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import (
    frontend_electrodes,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _family(prefix: str, mode_ids: tuple[int, ...]) -> list[str]:
    return [f"{prefix}.pa#", f"{prefix}.pa+", f"{prefix}.pa0"] + [
        f"{prefix}.pa{mode}" for mode in mode_ids
    ]


def _main_contract(shape: str) -> dict:
    electrodes = frontend_electrodes(ring_count=2, three_zone=True)
    planes = {
        "repeller": 0.0,
        "intermediate1": 1.0,
        "intermediate2": 2.0,
        "exit": 3.0,
    }
    ring_z_mm = [1.5, 2.5]
    model = resolve_three_zone_pa_plus_solution_model(
        electrodes,
        planes_global_z_mm=planes,
        ring_z_mm=ring_z_mm,
    )
    return {
        "cross_section": shape,
        "cell_mm_xyz": {"x": 0.5, "y": 0.5, "z": 0.1},
        "domain_policy": {"policy_id": "full_accelerator_v1"},
        "accelerator_port_aperture": {
            "reference_aperture_mm": {"width": 1.0, "height": 1.0}
        },
        "electrodes": electrodes,
        "axial_planes_global_z_mm": planes,
        "ring_placement": {"ring_z_mm": ring_z_mm},
        "pa_plus_solution_model": model,
    }


class SingleFlightPaCacheReadinessTests(unittest.TestCase):
    def _campaign(self, root: Path) -> tuple[Path, Path, Path]:
        rows = []
        profiles = []
        for shape, realization in (("square", "square_3d"), ("cylindrical", "cylindrical_3d")):
            profile_id = f"profile_{shape}"
            profiles.append({"layout_profile_id": profile_id, "accelerator_realization_id": realization})
            for height in (1.0, 1.5, 2.0, 2.5):
                rows.append({"experiment_id": f"{shape}_{height}", "values": {
                    "single_flight_layout_profile_id": profile_id,
                    "accelerator_entrance_local_aperture_mm": {"width": 1.0, "height": height},
                }})
        campaign = root / "campaign.json"
        layouts = root / "layouts.json"
        configuration = root / "single_flight.json"
        _write_json(campaign, {"experiments": {"shared": {
            "single_flight_frontend_grid_profile_id": "active_main"
        }, "rows": rows}})
        _write_json(layouts, {"profiles": profiles})
        _write_json(configuration, {
            "role": "rf_oatof_simion_single_flight_configuration",
            "clock_basis": "canonical_instrument_time_us",
            "default_frontend_grid_profile_id": "active_main",
            "frontend_grid_profiles": [{
                "profile_id": "active_main",
                "field_overlay_id": "accelerator_entrance_local_aperture",
                "cell_mm_xyz": {"x": 0.25, "y": 0.25, "z": 0.1},
                "accelerator_main_cell_mm_xyz": {"x": 0.5, "y": 0.5, "z": 0.1},
                "accelerator_main_domain": {"policy_id": "full_accelerator_v1"},
                "accelerator_main_reference_aperture_mm": {"width": 1.0, "height": 1.0},
                "role": "test",
            }],
            "default_oatof_numerical_profile_id": "oatof",
            "oatof_numerical_profiles": [{
                "profile_id": "oatof", "reflectron_cell_mm": {"axial": 1.0, "radial": 1.0}, "role": "test",
            }],
            "default_trajectory_quality_profile_id": "trajectory",
            "trajectory_quality_profiles": [{
                "profile_id": "trajectory", "trajectory_quality": 1, "role": "test",
            }],
            "default_time_integration_profile_id": "time",
            "time_integration_profiles": [{
                "profile_id": "time", "rf_steps_per_period": 1, "role": "test",
            }],
            "post_pulse_observation_window_us": 1.0,
        })
        return campaign, layouts, configuration

    def _publish(
        self, cache: Path, runs: Path, *, key: str, role: str, run_id: str,
        files: list[str], identity: dict, contract_name: str, contract: dict,
    ) -> None:
        generation = "a" * 64
        root = cache / role / key / "generations" / generation
        root.mkdir(parents=True)
        for name in files:
            (root / name).touch()
        _write_json(root / "cache_manifest.json", {
            "schema_version": 3, "role": role, "cache_key": key,
            "provider_run_id": run_id, "identity": identity,
            "files": [{"name": name} for name in files],
        })
        _write_json(root.parent.parent / "current_generation.json", {
            "schema_version": 1, "cache_key": key,
            "generation_sha256": generation,
            "generation_relative_path": f"generations/{generation}",
        })
        _write_json(runs / run_id / "inputs" / contract_name, contract)

    def _ready_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        campaign, layouts, configuration = self._campaign(root)
        cache = root / "cache"
        runs = root / "runs"
        main_keys = {"square": "1" * 64, "cylindrical": "2" * 64}
        main_contracts = {shape: _main_contract(shape) for shape in main_keys}
        for shape, key in main_keys.items():
            model = main_contracts[shape]["pa_plus_solution_model"]
            mode_ids = tuple(model["mode_ids"])
            self._publish(
                cache, runs, key=key, role=MAIN_ROLE, run_id=f"main-{shape}",
                files=_family("accelerator_main", mode_ids), identity={
                    "critical_options": {"pa_plus_solution_model": model}
                },
                contract_name="accelerator_main_contract.json",
                contract=main_contracts[shape],
            )
            for index, height in enumerate((1.0, 1.5, 2.0, 2.5)):
                key = ("3" if shape == "square" else "4") * 63 + str(index)
                self._publish(
                    cache, runs, key=key, role=LOCAL_ROLE, run_id=f"local-{shape}-{height}",
                    files=_family("accelerator_entrance_local", mode_ids),
                    identity={"inputs": {"accelerator_main_cache_key": main_keys[shape]}, "critical_options": {
                        "boundary_mode": "accelerator_main_electrode_basis_dirichlet_v1",
                        "replacement_semantics": "highest_priority_complete_local_replacement_v1",
                        "pa_plus_solution_model": model,
                    }},
                    contract_name="accelerator_entrance_local_contract.json", contract={
                        "cross_section": shape,
                        "accelerator_port_aperture": {"mechanical_aperture_mm": {"width": 1.0, "height": height}},
                    },
                )
        return campaign, layouts, configuration, cache

    def test_missing_cache_warns_without_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            campaign, layouts, configuration = self._campaign(root)
            receipt = verify_readiness(campaign, layouts, root / "cache", configuration)
        self.assertEqual(receipt["status"], "WARN")
        self.assertEqual(len(receipt["rows"]), 8)
        self.assertTrue(any(item.startswith("MAIN_CACHE_COUNT_INVALID") for item in receipt["warnings"]))

    def test_pre_pulse_campaign_requires_the_same_main_and_local_families(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            receipt = verify_readiness(
                INTEGRATION / "config/explorations/ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000.json",
                INTEGRATION / "config/single_flight_layout_profiles.json",
                Path(raw) / "cache",
                INTEGRATION / "config/simion_single_flight.json",
            )
        self.assertEqual(len(receipt["rows"]), 8)
        self.assertTrue(all(not row["ready"] for row in receipt["rows"]))
        self.assertTrue(
            any(item.startswith("MAIN_CACHE_COUNT_INVALID") for item in receipt["warnings"])
        )
        self.assertFalse(
            any(item.startswith("FIELD_BEARING_EXECUTION_PROFILE_MISSING") for item in receipt["warnings"])
        )

    def test_complete_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign, layouts, configuration, cache = self._ready_fixture(Path(raw))
            receipt = verify_readiness(campaign, layouts, cache, configuration)
        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(all(item["ready"] for item in receipt["rows"]))

    def test_local_mode_namespace_must_match_its_main(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign, layouts, configuration, cache = self._ready_fixture(Path(raw))
            manifest_path = next(
                cache.glob(f"{LOCAL_ROLE}/*/generations/*/cache_manifest.json")
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["identity"]["critical_options"]["pa_plus_solution_model"]["mode_ids"][-1] = 44
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt = verify_readiness(campaign, layouts, cache, configuration)
        self.assertEqual(receipt["status"], "WARN")
        self.assertFalse(receipt["rows"][0]["ready"])

    def test_require_ready_fails_after_warning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            campaign, layouts, configuration = self._campaign(root)
            with mock.patch("sys.argv", ["check", "--campaign", str(campaign), "--layout-profiles", str(layouts), "--single-flight-configuration", str(configuration), "--cache-root", str(root / "cache"), "--require-ready"]), mock.patch("sys.stdout", io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main()
        self.assertEqual(raised.exception.code, 1)

    def test_same_shape_old_numerical_main_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            campaign, layouts, configuration, cache = self._ready_fixture(root)
            self._publish(
                cache,
                root / "runs",
                key="9" * 64,
                role=MAIN_ROLE,
                run_id="old-square-main",
                files=_family("accelerator_main", tuple(range(36, 44))),
                identity={"critical_options": {"pa_plus_solution_model": _main_contract("square")["pa_plus_solution_model"]}},
                contract_name="accelerator_main_contract.json",
                contract={
                    **_main_contract("square"),
                    "cell_mm_xyz": {"x": 0.25, "y": 0.25, "z": 0.1},
                    "domain_policy": {
                        "policy_id": "coarse_boundary_supported_full_axial_core_v1",
                        "exit_axis_positive_extent_mm": 40.0,
                        "transverse_half_span_mm": 8.0,
                    },
                },
            )
            receipt = verify_readiness(campaign, layouts, cache, configuration)
        self.assertEqual(receipt["status"], "PASS")
        square_rows = [row for row in receipt["rows"] if row["shape"] == "square"]
        self.assertEqual({row["main_cache_key"] for row in square_rows}, {"1" * 64})

    def test_same_geometry_legacy_fourteen_mode_main_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            campaign, layouts, configuration, cache = self._ready_fixture(root)
            legacy_contract = _main_contract("square")
            legacy_model = {
                **legacy_contract["pa_plus_solution_model"],
                "model_id": "three_zone_linear_ring_pa_plus_v1",
                "mode_ids": list(range(36, 50)),
                "mode_count": 14,
            }
            legacy_contract["pa_plus_solution_model"] = legacy_model
            self._publish(
                cache,
                root / "runs",
                key="8" * 64,
                role=MAIN_ROLE,
                run_id="legacy-fourteen-mode-square-main",
                files=_family("accelerator_main", tuple(range(36, 50))),
                identity={"critical_options": {"pa_plus_solution_model": legacy_model}},
                contract_name="accelerator_main_contract.json",
                contract=legacy_contract,
            )
            receipt = verify_readiness(campaign, layouts, cache, configuration)
        self.assertEqual(receipt["status"], "PASS")
        square_rows = [row for row in receipt["rows"] if row["shape"] == "square"]
        self.assertEqual({row["main_cache_key"] for row in square_rows}, {"1" * 64})


if __name__ == "__main__":
    unittest.main()
