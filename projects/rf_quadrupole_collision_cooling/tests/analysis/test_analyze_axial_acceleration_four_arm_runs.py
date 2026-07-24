from __future__ import annotations

import csv
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_state import (
    PARTICLE_STATE_COLUMNS,
    canonical_sources,
)
from common.contracts.write_run_manifest import file_record
from projects.rf_quadrupole_collision_cooling.analysis.analyze_axial_acceleration_four_arm_runs import (
    analyze_four_arm_runs,
)
from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    generate_bundle,
)
from projects.rf_quadrupole_collision_cooling.analysis.validate_axial_acceleration_four_arm_experiment import (
    _compile_profile,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT_ROOT / "config" / "axial_acceleration_four_arm_experiment.json"
SOURCE_FAMILY = PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
DISTRIBUTION = PROJECT_ROOT / "config" / "official_particle_source.json"
RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"
RUN_IDS = {
    "A": "20260724_180001__sim__comsol__four-arm-a__n100",
    "B": "20260724_180002__sim__comsol__four-arm-b__n100",
    "C": "20260724_180003__sim__comsol__four-arm-c__n100",
    "D": "20260724_180004__sim__comsol__four-arm-d__n100",
}


class FourArmPostRunAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle_temporary = tempfile.TemporaryDirectory()
        cls.bundle_root = Path(cls.bundle_temporary.name)
        generate_bundle(
            SOURCE_FAMILY, DISTRIBUTION, RESOLVED, cls.bundle_root
        )
        cls.bundle_metadata = cls.bundle_root / "paired_particle_bundle.json"
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.metadata = json.loads(cls.bundle_metadata.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.bundle_temporary.cleanup()

    def _artifact(self, arm: dict) -> dict:
        selector = self.contract["source_selectors"][arm["source_selector"]]
        return next(
            item
            for item in self.metadata["artifacts"]
            if item["operating_point_id"] == selector["operating_point_id"]
            and item["particle_count"] == selector["particle_count"]
            and item["representation"] == selector["representation"]
        )

    def _write_state(
        self,
        path: Path,
        source_path: Path,
        resolved: dict,
        arm_id: str,
        *,
        lose_particle: bool,
    ) -> None:
        sources = canonical_sources(source_path)
        frequency = float(resolved["drive"]["frequency_Hz"])
        phase = float(resolved["drive"]["phase_rad"])
        detector = float(
            resolved["interfaces_mm"]["exit"]["particle_plane_z_mm"]
        )
        arm_offset = {"A": 0.0, "B": 0.3, "C": 0.2, "D": 0.1}[arm_id]
        rows: list[dict[str, object]] = []
        for particle_id, source in sources.items():
            radius = math.hypot(
                source["transverse_x_mm"], source["transverse_y_mm"]
            )
            divergence = math.degrees(
                math.atan2(
                    math.hypot(
                        source["velocity_x_m_s"], source["velocity_y_m_s"]
                    ),
                    source["velocity_axial_m_s"],
                )
            )
            rf_phase = (
                2 * math.pi * frequency * source["time_us"] * 1e-6 + phase
            ) % (2 * math.pi)
            common = {
                "particle_id": particle_id,
                "time_us": source["time_us"],
                "rf_phase_rad": rf_phase,
                "transverse_x_mm": source["transverse_x_mm"],
                "transverse_y_mm": source["transverse_y_mm"],
                "velocity_axial_m_s": source["velocity_axial_m_s"],
                "velocity_x_m_s": source["velocity_x_m_s"],
                "velocity_y_m_s": source["velocity_y_m_s"],
                "radial_position_mm": radius,
                "divergence_angle_deg": divergence,
                "max_rod_radius_mm": radius,
            }
            rows.append(
                {
                    **common,
                    "event": "source",
                    "status": "alive",
                    "terminal_reason": "none",
                    "elapsed_time_us": 0.0,
                    "axial_z_mm": source["axial_z_mm"],
                    "kinetic_energy_eV": source["kinetic_energy_eV"],
                }
            )
            lost = lose_particle and particle_id == 100
            rows.append(
                {
                    **common,
                    "event": "terminal",
                    "status": "lost" if lost else "transmitted",
                    "terminal_reason": (
                        "radial_escape" if lost else "acceptance_detector"
                    ),
                    "time_us": source["time_us"] + 30.0 + arm_offset,
                    "elapsed_time_us": 30.0 + arm_offset,
                    "axial_z_mm": detector,
                    "kinetic_energy_eV": (
                        source["kinetic_energy_eV"] + arm_offset
                    ),
                    "radial_position_mm": radius + arm_offset * 0.01,
                    "divergence_angle_deg": divergence + arm_offset,
                }
            )
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=PARTICLE_STATE_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)

    def _write_run(
        self,
        parent: Path,
        arm: dict,
        *,
        lose_particle: bool = False,
        wrong_binding: bool = False,
    ) -> Path:
        arm_id = arm["arm_id"]
        root = parent / RUN_IDS[arm_id]
        inputs = root / "inputs"
        results = root / "results"
        inputs.mkdir(parents=True)
        results.mkdir()
        artifact = self._artifact(arm)
        source = inputs / "particle_source.csv"
        shutil.copy2(self.bundle_root / artifact["relative_path"], source)
        family = inputs / "particle_source_family.json"
        shutil.copy2(SOURCE_FAMILY, family)
        resolved_document = _compile_profile(arm["design_profile_id"])
        resolved = inputs / "multipole_resolved_design.json"
        resolved.write_text(
            json.dumps(resolved_document, indent=2) + "\n", encoding="utf-8"
        )
        profile = inputs / "design_profile_resolution.json"
        profile.write_text(
            json.dumps(
                {"profile": {"design_profile_id": arm["design_profile_id"]}}
            ),
            encoding="utf-8",
        )
        selector = self.contract["source_selectors"][arm["source_selector"]]
        point = selector["operating_point_id"]
        family_sha = self.metadata["inputs"]["source_family_sha256"]
        binding = {
            "operating_point_id": point,
            "source_family_sha256": family_sha,
        }
        source_metadata = inputs / "particle_source_metadata.json"
        source_metadata.write_text(
            json.dumps(
                {
                    "source_sha256": artifact["sha256"],
                    "operating_point_binding": binding,
                }
            ),
            encoding="utf-8",
        )
        evidence = None
        if arm["evidence_contract"] is not None:
            evidence = inputs / "evidence_contract.json"
            repository_root = Path(__file__).resolve().parents[4]
            shutil.copy2(repository_root / arm["evidence_contract"], evidence)
        state = results / "particle_state__primary.csv"
        self._write_state(
            state,
            source,
            resolved_document,
            arm_id,
            lose_particle=lose_particle,
        )
        metrics = results / "finite_3d_transport_metrics.json"
        metrics.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "multipole_finite_3d_transport_metrics",
                    "primary_case_id": arm["primary_case_id"],
                }
            ),
            encoding="utf-8",
        )
        config = {
            "schema_version": 1,
            "role": "multipole_resolved_comsol_run_config",
            "run_id": root.name,
            "project": self.contract["project_id"],
            "mode": self.contract["comparison_contract"][
                "post_run_acceptance"
            ]["run_mode"],
            "inputs": {
                "design_profile_resolution": str(profile.resolve()),
                "multipole_resolved_design": str(resolved.resolve()),
                "particle_source": str(source.resolve()),
                "particle_source_metadata": str(source_metadata.resolve()),
                "particle_source_family": str(family.resolve()),
                **(
                    {"evidence_contract": str(evidence.resolve())}
                    if evidence is not None
                    else {"evidence_contract": None}
                ),
            },
            "parameters": {
                "design_profile_id": arm["design_profile_id"],
                "operating_point_id": point,
            },
            "provenance": {
                "parent_resolved_design_sha256": resolved_document[
                    "resolved_sha256"
                ],
                "particle_source_sha256": artifact["sha256"],
                "source_family_sha256": family_sha,
                "operating_point_id": (
                    "wrong_operating_point" if wrong_binding else point
                ),
                "particle_source_operating_point_binding": binding,
            },
            "formal_gate_passed": False,
        }
        config_path = root / "run_config.json"
        config_path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        manifest = {
            "schema_version": 1,
            "role": "simulation_run_manifest",
            "run_id": root.name,
            "project": config["project"],
            "mode": config["mode"],
            "status": "success",
            "run_config": file_record(config_path),
            "inputs": {
                name: file_record(Path(value))
                for name, value in config["inputs"].items()
                if isinstance(value, str)
            },
            "outputs": [file_record(state), file_record(metrics)],
            "formal_eligible": False,
        }
        (root / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return root

    def _refresh_manifest_input(self, run: Path, name: str) -> None:
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
        manifest["inputs"][name] = file_record(Path(config["inputs"][name]))
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def _runs(
        self,
        parent: Path,
        *,
        lost_arm: str | None = None,
        wrong_binding_arm: str | None = None,
    ) -> dict[str, Path]:
        return {
            arm["arm_id"]: self._write_run(
                parent,
                arm,
                lose_particle=arm["arm_id"] == lost_arm,
                wrong_binding=arm["arm_id"] == wrong_binding_arm,
            )
            for arm in self.contract["arms"]
        }

    def test_accepts_complete_four_arm_population_and_reports_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_four_arm_runs(
                CONTRACT,
                self.bundle_metadata,
                self._runs(Path(directory)),
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["full_four_arm_id_set"], "PASS")
        self.assertFalse(result["common_survivor_filtering"])
        self.assertEqual(
            [item["direction"] for item in result["comparisons"]],
            ["B_minus_A", "C_minus_D"],
        )
        self.assertTrue(
            all(
                item["paired_particle_count"] == 100
                and len(item["per_particle_delta"]) == 100
                for item in result["comparisons"]
            )
        )
        self.assertFalse(result["C_D_equivalence_claim_allowed"])
        self.assertIsNone(result["C_D_equivalence_tolerance"])
        self.assertEqual(
            set(result["comparisons"][0]["descriptive_delta"]),
            {
                item["output_name"]
                for item in self.contract["comparison_contract"][
                    "post_run_acceptance"
                ]["descriptive_aggregations"]
            },
        )

    def test_rejects_loss_instead_of_intersecting_survivors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory), lost_arm="D")
            with self.assertRaisesRegex(ValueError, "failed acceptance detector"):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_rejects_manifest_valid_but_wrong_operating_point_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory), wrong_binding_arm="B")
            with self.assertRaisesRegex(ValueError, "source/profile binding differs"):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_rejects_output_changed_after_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory))
            state = runs["C"] / "results" / "particle_state__primary.csv"
            state.write_text(
                state.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(AssertionError, "byte count changed"):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_rejects_manifest_role_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory))
            manifest_path = runs["A"] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["role"] = "not_a_simulation_run_manifest"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest is not success"):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_rejects_required_evidence_omitted_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory))
            manifest_path = runs["C"] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["inputs"]["evidence_contract"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "does not freeze input evidence_contract"
            ):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_rejects_accelerated_resolved_invariant_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory))
            resolved_path = (
                runs["D"] / "inputs" / "multipole_resolved_design.json"
            )
            resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
            resolved["axial_drive"]["predicted_output_energy_eV"] += 0.25
            resolved_path.write_text(json.dumps(resolved), encoding="utf-8")
            self._refresh_manifest_input(
                runs["D"], "multipole_resolved_design"
            )
            with self.assertRaisesRegex(
                ValueError, "accelerated-arm frozen resolved field differs"
            ):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_rejects_resolved_invariant_missing_from_both_arms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = self._runs(Path(directory))
            for arm_id in ("C", "D"):
                resolved_path = (
                    runs[arm_id]
                    / "inputs"
                    / "multipole_resolved_design.json"
                )
                resolved = json.loads(
                    resolved_path.read_text(encoding="utf-8")
                )
                del resolved["axial_drive"]["predicted_energy_gain_eV"]
                resolved_path.write_text(json.dumps(resolved), encoding="utf-8")
                self._refresh_manifest_input(
                    runs[arm_id], "multipole_resolved_design"
                )
            with self.assertRaisesRegex(
                ValueError, "lacks finite resolved field"
            ):
                analyze_four_arm_runs(CONTRACT, self.bundle_metadata, runs)

    def test_metrics_output_path_is_contract_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = self._runs(root)
            contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
            contract["comparison_contract"]["post_run_acceptance"][
                "metrics_output"
            ] = "results/different_metrics.json"
            contract_path = root / "experiment.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "transport metrics is missing"
            ):
                analyze_four_arm_runs(
                    contract_path, self.bundle_metadata, runs
                )


if __name__ == "__main__":
    unittest.main()
