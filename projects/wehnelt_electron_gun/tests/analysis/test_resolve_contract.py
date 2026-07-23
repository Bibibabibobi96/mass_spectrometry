"""Contract tests for the Wehnelt electron-gun resolver."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from analysis.resolve_contract import (
    ContractError,
    contract_sha256,
    derive_geometry,
    load_json,
    resolve_contract,
    validate_baseline,
    validate_modes,
    write_json,
)


class ResolveContractTests(unittest.TestCase):
    """Preserve the current physics while rejecting ambiguous contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline_path = PROJECT_ROOT / "config" / "baseline.json"
        cls.modes_path = PROJECT_ROOT / "config" / "numerical_modes.json"
        cls.baseline = load_json(cls.baseline_path)
        cls.modes = load_json(cls.modes_path)

    def run_resolver_module(
        self, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        """Run the package entry with bounded subprocess behavior."""

        command = [sys.executable, "-m", "analysis.resolve_contract", *arguments]
        try:
            return subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f"resolver timed out after {exc.timeout}s: {command}")

    def test_current_build_smoke_resolves_with_source_identity(self) -> None:
        resolved = resolve_contract(
            copy.deepcopy(self.baseline),
            copy.deepcopy(self.modes),
            "build_only_smoke",
            1,
        )
        self.assertEqual(resolved["selected_mode_id"], "build_only_smoke")
        self.assertFalse(resolved["evidence"]["candidate_evidence_allowed"])
        self.assertEqual(
            resolved["source_identity"]["baseline_sha256"],
            contract_sha256(self.baseline),
        )

    def test_current_physical_values_and_coordinates_are_preserved(self) -> None:
        derived = derive_geometry(self.baseline)
        self.assertEqual(derived["coil_length_mm"], 1.0)
        self.assertEqual(derived["wehnelt_cavity_ceiling_z_mm"], 1.5)
        self.assertEqual(derived["anode_bottom_z_mm"], 14.0)
        self.assertEqual(derived["vacuum_domain_top_z_mm"], 18.0)
        self.assertEqual(self.baseline["electrodes_V"]["wehnelt"], -0.5)
        self.assertEqual(self.baseline["filament"]["temperature_K"], 2700.0)

    def test_functional_reference_requires_n100(self) -> None:
        with self.assertRaisesRegex(ContractError, "below the functional minimum"):
            resolve_contract(self.baseline, self.modes, "functional_reference", 99)
        resolved = resolve_contract(
            self.baseline, self.modes, "functional_reference", 100
        )
        self.assertTrue(resolved["evidence"]["candidate_evidence_allowed"])

    def test_unknown_mode_and_unknown_key_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "unknown numerical mode"):
            resolve_contract(self.baseline, self.modes, "quick", 1)
        changed = copy.deepcopy(self.baseline)
        changed["geometry_mm"]["shortcut_radius"] = 1.0
        with self.assertRaisesRegex(ContractError, "keys mismatch"):
            validate_baseline(changed)

    def test_identity_and_coordinate_changes_are_rejected(self) -> None:
        changed = copy.deepcopy(self.baseline)
        changed["project_id"] = "another_project"
        with self.assertRaisesRegex(ContractError, "identity mismatch"):
            validate_baseline(changed)
        changed = copy.deepcopy(self.baseline)
        changed["coordinate_convention"]["beam_axis"] = "+x"
        with self.assertRaisesRegex(ContractError, "coordinate convention"):
            validate_baseline(changed)

    def test_invalid_radial_geometry_and_electrode_order_are_rejected(self) -> None:
        changed = copy.deepcopy(self.baseline)
        changed["geometry_mm"]["wehnelt_aperture_radius"] = 2.0
        with self.assertRaisesRegex(ContractError, "radial geometry"):
            validate_baseline(changed)
        changed = copy.deepcopy(self.baseline)
        changed["electrodes_V"]["wehnelt"] = 1.0
        with self.assertRaisesRegex(ContractError, "electrode ordering"):
            validate_baseline(changed)

    def test_filament_must_fit_inside_cavity(self) -> None:
        changed = copy.deepcopy(self.baseline)
        changed["filament"]["axis_center_z_mm"] = 1.4
        validate_baseline(changed)
        with self.assertRaisesRegex(ContractError, "does not fit"):
            derive_geometry(changed)

    def test_invalid_mesh_and_time_modes_are_rejected(self) -> None:
        changed = copy.deepcopy(self.modes)
        changed["modes"]["build_only_smoke"]["mesh"][
            "filament_surface_hmin_mm"
        ] = 0.04
        with self.assertRaisesRegex(ContractError, "hmin"):
            validate_modes(changed)
        changed = copy.deepcopy(self.modes)
        changed["modes"]["functional_reference"]["particle_time_ns"]["step"] = 41.0
        with self.assertRaisesRegex(ContractError, "step <= end"):
            validate_modes(changed)

    def test_build_smoke_is_always_evidence_ineligible(self) -> None:
        resolved = resolve_contract(
            self.baseline, self.modes, "build_only_smoke", 5
        )
        self.assertFalse(resolved["evidence"]["candidate_evidence_allowed"])
        self.assertEqual(resolved["evidence"]["scope"], "build_smoke_only")

    def test_deterministic_round_trip(self) -> None:
        resolved = resolve_contract(
            self.baseline, self.modes, "build_only_smoke", 1
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            write_json(path, resolved)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), resolved)

    def test_module_entry_checks_tracked_resolved_contract(self) -> None:
        completed = self.run_resolver_module(
            [
                "--baseline",
                "config/baseline.json",
                "--modes",
                "config/numerical_modes.json",
                "--mode",
                "build_only_smoke",
                "--evidence-particle-count",
                "1",
                "--check",
                "config/resolved_model.json",
            ]
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_module_entry_rejects_stale_resolved_contract(self) -> None:
        stale = resolve_contract(
            self.baseline, self.modes, "build_only_smoke", 1
        )
        stale["derived_geometry_mm"]["anode_bottom_z_mm"] += 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stale.json"
            write_json(path, stale)
            completed = self.run_resolver_module(
                [
                    "--baseline",
                    "config/baseline.json",
                    "--modes",
                    "config/numerical_modes.json",
                    "--mode",
                    "build_only_smoke",
                    "--evidence-particle-count",
                    "1",
                    "--check",
                    str(path),
                ]
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("stale resolved contract", completed.stdout)


if __name__ == "__main__":
    unittest.main()
