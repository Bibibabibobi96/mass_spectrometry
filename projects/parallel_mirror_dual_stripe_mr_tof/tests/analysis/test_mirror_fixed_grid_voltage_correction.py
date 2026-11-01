from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_grid_voltage_correction import (
    NATIVE_GAMMA_OPERATOR_ID,
    SAMPLED_GAMMA_OPERATOR_ID,
    _bounded_physical_gate_secant,
    _l1_gamma_operator_id,
    _measured_chord_gamma_root,
    _native_gamma_trace,
    _source_fixed_grid_gamma_trace,
    _source_gamma_operator_id,
    _solve_corrected_l0_slice,
    constrained_secant_update,
    decompose_l0_l1_correction,
    rank_one_secant_update,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)

RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_mirror_fixed_grid_voltage_correction.ps1"


class FixedGridVoltageCorrectionTests(unittest.TestCase):
    def test_runner_uses_ledger_lifecycle_and_one_capacity_session(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "-CapacityLedgerLifecycleEnabled", "Enter-ArtifactWorkflowCapacitySession",
            "Update-ArtifactWorkflowCapacitySession", "Exit-ArtifactWorkflowCapacitySession",
        ):
            self.assertIn(token, source)
        self.assertNotIn("Invoke-ArtifactCapacityGate", source)

    def test_measured_chord_gamma_root_stays_between_physical_l0_endpoints(self) -> None:
        proposal, slopes, fraction = _measured_chord_gamma_root(
            base_voltages=np.asarray([1.0, 2.0, 3.0, 4.0]),
            secant_voltages=np.asarray([2.0, 4.0, 6.0, 8.0]),
            base_slopes=np.asarray([4e-8, -2e-8, 1e-8]),
            secant_slopes=np.asarray([5e-8, 1e-8, -3e-8]),
            base_gamma=-0.25,
            secant_gamma=0.75,
            slope_gate=5e-8,
            lower_bounds=np.zeros(4),
            upper_bounds=np.full(4, 10.0),
        )
        self.assertEqual(fraction, 0.25)
        np.testing.assert_allclose(proposal, [1.25, 2.5, 3.75, 5.0])
        np.testing.assert_allclose(slopes, [4.25e-8, -1.25e-8, 0.0])

    def test_secant_base_uses_the_source_corrections_frozen_gamma_operator(self) -> None:
        source = {"fixed_grid_mean_directional_trace_half": -4.12e-4}
        self.assertEqual(_source_fixed_grid_gamma_trace(source), -4.12e-4)
        with self.assertRaisesRegex(CandidateContractError, "authoritative"):
            _source_fixed_grid_gamma_trace({})

    @staticmethod
    def operator_source(operator: str, *, chord: bool = False) -> dict:
        if chord:
            inputs = {
                "source_correction_sha256": "1" * 64,
                "base_l1_sha256": "2" * 64,
                "secant_l1_sha256": "3" * 64,
                "secant_l1_probe_sha256": "4" * 64 if operator == NATIVE_GAMMA_OPERATOR_ID else None,
            }
            status = "secant_proposal_only__independent_fixed_grid_validation_required"
        else:
            inputs = {"fixed_l1_sha256": "1" * 64}
            if operator == NATIVE_GAMMA_OPERATOR_ID:
                inputs.update(native_l1_sha256="A" * 64, native_l1_probe_sha256="b" * 64)
            status = "no_local_gamma_bracket__additional_fixed_grid_secant_required"
        return {"fixed_grid_gamma_operator_id": operator, "status": status, "inputs": inputs}

    def test_gamma_operator_identity_is_explicit_and_matches_producer_shape(self) -> None:
        for operator in (NATIVE_GAMMA_OPERATOR_ID, SAMPLED_GAMMA_OPERATOR_ID):
            for status in (
                "no_local_gamma_bracket__additional_fixed_grid_secant_required",
                "gamma_root_outside_local_trust_region__additional_fixed_grid_secant_required",
                "proposal_only__independent_fixed_grid_validation_required",
            ):
                source = self.operator_source(operator)
                source["status"] = status
                with self.subTest(operator=operator, status=status):
                    self.assertEqual(_source_gamma_operator_id(source), operator)
            with self.subTest(operator=operator, chord=True):
                self.assertEqual(_source_gamma_operator_id(self.operator_source(operator, chord=True)), operator)

    def test_gamma_operator_rejects_missing_partial_conflicting_and_invalid_identity(self) -> None:
        sampled = self.operator_source(SAMPLED_GAMMA_OPERATOR_ID)
        native = self.operator_source(NATIVE_GAMMA_OPERATOR_ID)
        cases = []
        for value in (None, "unknown", {}, []):
            source = copy.deepcopy(sampled)
            source["fixed_grid_gamma_operator_id"] = value
            cases.append(source)
        source = copy.deepcopy(sampled)
        del source["fixed_grid_gamma_operator_id"]
        cases.extend((source, {"inputs": {}}, {"inputs": {"native_l1_sha256": "A" * 64}}))
        for key in ("native_l1_sha256", "native_l1_probe_sha256"):
            source = copy.deepcopy(native)
            del source["inputs"][key]
            cases.append(source)
            for value in (None, "", "A", "g" * 64, 5):
                source = copy.deepcopy(native)
                source["inputs"][key] = value
                cases.append(source)
            source = copy.deepcopy(sampled)
            source["inputs"][key] = None
            cases.append(source)
        source = copy.deepcopy(native)
        source["fixed_grid_gamma_operator_id"] = SAMPLED_GAMMA_OPERATOR_ID
        cases.append(source)
        for operator, value in ((NATIVE_GAMMA_OPERATOR_ID, None), (SAMPLED_GAMMA_OPERATOR_ID, "A" * 64)):
            source = self.operator_source(operator, chord=True)
            source["inputs"]["secant_l1_probe_sha256"] = value
            cases.append(source)
        source = self.operator_source(SAMPLED_GAMMA_OPERATOR_ID, chord=True)
        del source["inputs"]["secant_l1_probe_sha256"]
        cases.append(source)
        source = self.operator_source(NATIVE_GAMMA_OPERATOR_ID, chord=True)
        source["inputs"]["native_l1_sha256"] = "A" * 64
        cases.append(source)
        for key in ("source_correction_sha256", "base_l1_sha256", "secant_l1_sha256"):
            source = self.operator_source(NATIVE_GAMMA_OPERATOR_ID, chord=True)
            source["inputs"][key] = "not-a-sha256"
            cases.append(source)
        source = copy.deepcopy(sampled)
        source["inputs"]["fixed_l1_sha256"] = None
        cases.append(source)
        source = copy.deepcopy(sampled)
        source["status"] = "unknown"
        cases.append(source)
        for index, source in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(CandidateContractError):
                _source_gamma_operator_id(source)

    def test_powershell_endpoint_selection_uses_python_classifier_and_propagates_failure(self) -> None:
        repo = RUNNER.parents[3]
        self.assertTrue((repo / "common/contracts").is_dir())
        with tempfile.TemporaryDirectory(prefix="gamma-operator-") as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            for name in ("native_transverse_l1.json", "native_transverse_l1_probe_contract.json",
                         "fixed_operating_field_l1.json"):
                (results / name).write_text("{}", encoding="utf-8")
            invalid = self.operator_source(SAMPLED_GAMMA_OPERATOR_ID)
            del invalid["fixed_grid_gamma_operator_id"]
            partial = self.operator_source(NATIVE_GAMMA_OPERATOR_ID)
            del partial["inputs"]["native_l1_probe_sha256"]
            sources = [self.operator_source(SAMPLED_GAMMA_OPERATOR_ID),
                       self.operator_source(NATIVE_GAMMA_OPERATOR_ID), invalid, partial]
            paths = []
            for index, source in enumerate(sources):
                run = root / f"source_{index}"
                path = run / "results/fixed_grid_multifidelity_voltage_correction.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(source), encoding="utf-8")
                paths.append(str(run))
            request = root / "request.json"
            request.write_text(json.dumps(paths), encoding="utf-8")
            script = root / "select.ps1"
            script.write_text(r'''param($Runner,$Python,$RequestPath,$Secant)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner parse failed'}
$functions=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Resolve-FixedGridSecantL1Inputs'},$true))
if($functions.Count-ne1){throw 'One actual endpoint selector required'}
. ([scriptblock]::Create($functions[0].Extent.Text))
$callers=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.IfStatementAst] -and $node.Extent.Text.Contains('$secantInputs = Resolve-FixedGridSecantL1Inputs')},$true))
if($callers.Count-ne1){throw 'One actual selector-to-argv call site required'}
$rows=@(foreach($path in (Get-Content -LiteralPath $RequestPath -Raw|ConvertFrom-Json)){
 $sourceCorrection=$path;$secantFixed=$Secant;$arguments=@('unchanged-prefix')
 try {
  . ([scriptblock]::Create($callers[0].Extent.Text))
  @{ok=$true;arguments=@($arguments)}
 } catch {@{ok=$false;message=$_.Exception.Message;arguments=@($arguments)}}
})
$rows|ConvertTo-Json -Depth 10
''', encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script), str(RUNNER), sys.executable, str(request), str(root)],
                cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False,
                timeout=120,  # Four pure classifier imports plus one pwsh startup; no solver.

            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = json.loads(result.stdout)
            self.assertEqual(len(rows), 4)
            for index, filename in ((0, "fixed_operating_field_l1.json"), (1, "native_transverse_l1.json")):
                self.assertTrue(rows[index]["ok"])
                arguments = rows[index]["arguments"]
                self.assertEqual(arguments[0], "unchanged-prefix")
                self.assertEqual(arguments.count("--secant-l1"), 1)
                self.assertEqual(Path(arguments[arguments.index("--secant-l1") + 1]), results / filename)
                self.assertEqual(Path(arguments[arguments.index("--source-correction") + 1]),
                                 Path(paths[index]) / "results/fixed_grid_multifidelity_voltage_correction.json")
            self.assertNotIn("--secant-l1-probe", rows[0]["arguments"])
            native_arguments = rows[1]["arguments"]
            self.assertEqual(native_arguments.count("--secant-l1-probe"), 1)
            self.assertEqual(Path(native_arguments[native_arguments.index("--secant-l1-probe") + 1]),
                             results / "native_transverse_l1_probe_contract.json")
            for row in rows[2:]:
                self.assertFalse(row["ok"])
                self.assertEqual(row["arguments"], ["unchanged-prefix"])
                self.assertIn("Source gamma operator validation failed before endpoint selection", row["message"])

    def test_gamma_operator_classifier_fails_closed_on_mixed_endpoint(self) -> None:
        native = {"role": "mrtof_native_simion_transverse_l1_analysis"}
        sampled = {"role": "mrtof_fixed_operating_field_l1_analysis"}
        self.assertEqual(_l1_gamma_operator_id(native, True), NATIVE_GAMMA_OPERATOR_ID)
        self.assertEqual(_l1_gamma_operator_id(sampled, False), SAMPLED_GAMMA_OPERATOR_ID)
        with self.assertRaisesRegex(CandidateContractError, "requires its frozen probe"):
            _l1_gamma_operator_id(native, False)
        with self.assertRaisesRegex(CandidateContractError, "cannot carry a native probe"):
            _l1_gamma_operator_id(sampled, True)
        for endpoint in ({}, {"role": "unknown"}):
            for has_probe in (False, True):
                with self.subTest(endpoint=endpoint, has_probe=has_probe), self.assertRaisesRegex(
                    CandidateContractError, "role is unsupported",
                ):
                    _l1_gamma_operator_id(endpoint, has_probe)

    def test_diagnostic_secant_shrinks_to_the_physical_l0_gate(self) -> None:
        voltage, slopes, delta_e, shrink_count = _bounded_physical_gate_secant(
            source_voltages=np.zeros(4),
            tangent_per_e=np.asarray([4.0, 0.0, 0.0, 1.0]),
            direction=1.0,
            initial_e_step_v=0.5,
            shrink_factor=0.5,
            maximum_shrinks=3,
            lower_bounds_v=np.full(4, -10.0),
            upper_bounds_v=np.full(4, 10.0),
            maximum_voltage_step_v=10.0,
            slope_gate_per_v=5e-8,
            slope_model=lambda trial: np.asarray([4e-8 + abs(trial[3]) * 4e-8, 0.0, 0.0]),
        )
        self.assertEqual(shrink_count, 1)
        self.assertEqual(delta_e, 0.25)
        np.testing.assert_allclose(voltage, [1.0, 0.0, 0.0, 0.25])
        self.assertAlmostEqual(float(np.max(np.abs(slopes))), 5e-8)

    def test_independent_corrected_l0_slice_closes_three_equations(self) -> None:
        def linear_slopes(_basis, voltages, _energies, _step):
            return np.asarray(voltages[:3], dtype=float) - np.asarray([1.0, -2.0, 3.0])

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "mirror_fixed_grid_voltage_correction.normalized_slopes",
            side_effect=linear_slopes,
        ):
            trial = _solve_corrected_l0_slice(
                object(), (3900.0, 4000.0, 4100.0), 1.0, np.zeros(3),
                np.full(4, -10.0), np.full(4, 10.0), np.zeros(3),
                1e-4, 1e-12, 120, 1e-10, 4.0,
            )
        np.testing.assert_allclose(trial, [1.0, -2.0, 3.0, 4.0], atol=1e-10)

    def test_native_l1_trace_requires_the_frozen_native_probe_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe_path = root / "native_probe.json"
            probe_path.write_text(json.dumps({
                "role": "mrtof_native_simion_transverse_l1_probe",
                "status": "prepared",
                "nominal_energy_ev": 4000.0,
            }), encoding="utf-8")
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            probe["_path"] = str(probe_path)
            native = {
                "role": "mrtof_native_simion_transverse_l1_analysis",
                "status": "native_l1_diagnostic_complete",
                "source_native_l1_probe_contract_sha256": file_sha256(probe_path),
                "nominal_energy_ev": 4000.0,
                "directions": {
                    "-1": {"stable": True, "trace_half": -0.001},
                    "1": {"stable": True, "trace_half": 0.003},
                },
            }
            self.assertAlmostEqual(_native_gamma_trace(native, probe, 4000.0), 0.001)
            native["source_native_l1_probe_contract_sha256"] = "0" * 64
            with self.assertRaisesRegex(CandidateContractError, "identity"):
                _native_gamma_trace(native, probe, 4000.0)

    def test_l0_is_closed_before_l1_moves_along_null_space(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 2.0, 0.0, -1.0],
            [0.0, 0.0, 4.0, 0.5],
        ])
        gamma = np.array([0.5, -0.25, 0.75, 1.0])
        slopes = np.array([0.1, -0.2, 0.3])
        trace = -0.4
        result = decompose_l0_l1_correction(jacobian, gamma, slopes, trace)
        delta = np.asarray(result["voltage_correction_v"])
        np.testing.assert_allclose(slopes + jacobian @ delta, 0.0, atol=1e-12)
        self.assertAlmostEqual(trace + float(gamma @ delta), 0.0, places=12)
        self.assertEqual(result["l0_jacobian_rank"], 3)
        self.assertEqual(result["l0_family_nullity"], 1)
        self.assertEqual(result["augmented_jacobian_rank"], 4)

    def test_rank_deficient_l0_fails_closed(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "rank three"):
            decompose_l0_l1_correction(
                [[1.0, 0.0, 0.0, 0.0]] * 3,
                [0.0, 0.0, 0.0, 1.0],
                [0.0, 0.0, 0.0],
                0.0,
            )

    def test_gamma_stationary_on_l0_family_fails_closed(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        with self.assertRaisesRegex(CandidateContractError, "stationary"):
            decompose_l0_l1_correction(
                jacobian,
                [1.0, 1.0, 1.0, 0.0],
                [0.0, 0.0, 0.0],
                0.1,
            )

    def test_rank_one_secant_update_satisfies_matrix_chord(self) -> None:
        jacobian = np.array([
            [1.0, 2.0, 0.0, -1.0],
            [0.0, 1.0, 3.0, 0.5],
            [2.0, 0.0, -1.0, 1.0],
        ])
        step = np.array([2.0, -1.0, 0.5, 3.0])
        observed = np.array([0.25, -0.5, 1.5])
        updated = rank_one_secant_update(jacobian, step, observed)
        np.testing.assert_allclose(updated @ step, observed, atol=1e-12)
        self.assertEqual(np.linalg.matrix_rank(updated), 3)

    def test_rank_one_secant_update_supports_gradient(self) -> None:
        gradient = np.array([1.0, -2.0, 0.5, 4.0])
        step = np.array([1.0, 2.0, -1.0, 0.25])
        updated = rank_one_secant_update(gradient, step, np.asarray(0.75))
        self.assertAlmostEqual(float(updated @ step), 0.75, places=12)

    def test_rank_one_secant_update_rejects_zero_chord(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "zero"):
            rank_one_secant_update(np.eye(3, 4), np.zeros(4), np.ones(3))

    def test_constrained_update_preserves_first_chord_and_adds_second(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        first = np.array([1.0, 2.0, 0.0, 0.0])
        second = np.array([0.5, -1.0, 2.0, 1.0])
        first_response = jacobian @ first
        second_response = np.array([0.2, -0.3, 0.4])
        updated = constrained_secant_update(
            jacobian, [first], second, second_response,
        )
        np.testing.assert_allclose(updated @ first, first_response, atol=1e-12)
        np.testing.assert_allclose(updated @ second, second_response, atol=1e-12)

    def test_constrained_update_rejects_redundant_direction(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "no independent"):
            constrained_secant_update(
                np.eye(3, 4), [[1.0, 0.0, 0.0, 0.0]],
                [2.0, 0.0, 0.0, 0.0], [1.0, 2.0, 3.0],
            )

    def test_constrained_update_preserves_two_chords_and_adds_third(self) -> None:
        jacobian = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        first = np.array([1.0, 0.5, 0.0, 0.0])
        second = np.array([0.0, 1.0, 2.0, 0.0])
        third = np.array([0.25, -0.5, 1.0, 2.0])
        first_response = jacobian @ first
        second_response = jacobian @ second
        third_response = np.array([-0.2, 0.4, 0.7])
        updated = constrained_secant_update(
            jacobian, [first, second], third, third_response,
        )
        np.testing.assert_allclose(updated @ first, first_response, atol=1e-12)
        np.testing.assert_allclose(updated @ second, second_response, atol=1e-12)
        np.testing.assert_allclose(updated @ third, third_response, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
