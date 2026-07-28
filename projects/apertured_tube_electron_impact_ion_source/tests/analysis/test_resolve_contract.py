"""Contract tests for the electron-impact ion-source resolver."""

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
    load_json,
    resolve_contract,
    validate_baseline,
    validate_modes,
    write_json,
)


class ResolveContractTests(unittest.TestCase):
    """Reject ambiguous inputs and preserve deterministic resolution."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline_path = PROJECT_ROOT / "config" / "baseline.json"
        cls.modes_path = PROJECT_ROOT / "config" / "numerical_modes.json"
        cls.baseline = load_json(cls.baseline_path)
        cls.modes = load_json(cls.modes_path)

    def run_resolver_module(self, arguments: list[str]) -> subprocess.CompletedProcess:
        """Run the package entry with bounded, diagnosable subprocess behavior."""

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
            self.fail(f"resolver entry timed out after {exc.timeout}s: {command}")

    def test_current_contract_resolves_for_build_smoke(self) -> None:
        resolved = resolve_contract(
            copy.deepcopy(self.baseline),
            copy.deepcopy(self.modes),
            "build_only_smoke",
            1,
        )
        self.assertEqual(resolved["selected_mode_id"], "build_only_smoke")
        self.assertFalse(resolved["evidence"]["candidate_evidence_allowed"])
        self.assertEqual(resolved["evidence"]["requested_particle_count"], 1)

    def test_current_contract_resolves_for_functional_n100(self) -> None:
        resolved = resolve_contract(
            copy.deepcopy(self.baseline),
            copy.deepcopy(self.modes),
            "functional_reference",
            100,
        )
        self.assertTrue(resolved["evidence"]["candidate_evidence_allowed"])
        self.assertEqual(resolved["evidence"]["minimum_particle_count"], 100)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "unknown numerical mode"):
            resolve_contract(self.baseline, self.modes, "fast_guess", 100)

    def test_unknown_baseline_key_is_rejected(self) -> None:
        baseline = copy.deepcopy(self.baseline)
        baseline["geometry_mm"]["radius"] = baseline["geometry_mm"].pop(
            "tube_bore_radius"
        )
        with self.assertRaisesRegex(ContractError, "keys mismatch"):
            validate_baseline(baseline)

    def test_identity_mismatch_is_rejected(self) -> None:
        baseline = copy.deepcopy(self.baseline)
        baseline["project_id"] = "another_project"
        with self.assertRaisesRegex(ContractError, "identity mismatch"):
            validate_baseline(baseline)

    def test_aperture_outside_tube_is_rejected(self) -> None:
        baseline = copy.deepcopy(self.baseline)
        baseline["geometry_mm"]["electrode_aperture_radius"] = 5.0
        with self.assertRaisesRegex(ContractError, "inside the tube bore"):
            validate_baseline(baseline)

    def test_heavy_ion_release_is_rejected(self) -> None:
        baseline = copy.deepcopy(self.baseline)
        baseline["ionization"]["release_ionized_particle"] = True
        with self.assertRaisesRegex(ContractError, "heavy-ion release"):
            validate_baseline(baseline)

    def test_nonpositive_density_is_rejected(self) -> None:
        baseline = copy.deepcopy(self.baseline)
        baseline["gas"]["neutral_number_density_per_m3"] = 0.0
        with self.assertRaisesRegex(ContractError, "must be >"):
            validate_baseline(baseline)

    def test_unknown_mode_definition_is_rejected(self) -> None:
        modes = copy.deepcopy(self.modes)
        modes["modes"]["experimental"] = copy.deepcopy(
            modes["modes"]["functional_reference"]
        )
        with self.assertRaisesRegex(ContractError, "fixed and exhaustive"):
            validate_modes(modes)

    def test_time_step_larger_than_end_is_rejected(self) -> None:
        modes = copy.deepcopy(self.modes)
        modes["modes"]["build_only_smoke"]["time_ns"]["step"] = 51.0
        with self.assertRaisesRegex(ContractError, "must not exceed"):
            validate_modes(modes)

    def test_n_below_100_cannot_be_functional_evidence(self) -> None:
        with self.assertRaisesRegex(ContractError, "below the functional minimum"):
            resolve_contract(self.baseline, self.modes, "functional_reference", 99)

    def test_low_n_build_smoke_never_becomes_evidence(self) -> None:
        resolved = resolve_contract(
            self.baseline, self.modes, "build_only_smoke", 2
        )
        self.assertFalse(resolved["evidence"]["candidate_evidence_allowed"])
        self.assertEqual(resolved["evidence"]["scope"], "build_smoke_only")

    def test_functional_mode_requires_declared_n(self) -> None:
        with self.assertRaisesRegex(ContractError, "requires an evidence particle"):
            resolve_contract(self.baseline, self.modes, "functional_reference", None)

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

    def test_module_entry_rejects_unknown_mode(self) -> None:
        completed = self.run_resolver_module(
            [
                "--baseline",
                "config/baseline.json",
                "--modes",
                "config/numerical_modes.json",
                "--mode",
                "unregistered",
            ]
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown numerical mode", completed.stdout)


if __name__ == "__main__":
    unittest.main()
