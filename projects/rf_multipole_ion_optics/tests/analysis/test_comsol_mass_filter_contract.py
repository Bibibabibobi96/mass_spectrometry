from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.core.paired_mass_scan import generate_paired_case_tables
from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    evaluate_comsol as module,
)
from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    prepare_comsol_scan,
)


PROJECT_ROOT = Path(__file__).parents[2]


class ComsolMassFilterContractTests(unittest.TestCase):
    def test_case_mapping_reaches_actual_manifest_output_array(self) -> None:
        import subprocess

        runner = PROJECT_ROOT / "workflows/mass_filter_reference/run_comsol.ps1"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "case_outputs.ps1"
            script.write_text(
                r"""param([string]$Runner,[string]$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Actual runner parse failed.'}
$assign=@($ast.FindAll({param($n)$n-is[System.Management.Automation.Language.AssignmentStatementAst]-and$n.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$n.Left.VariablePath.UserPath-eq'cases'-and$n.Operator-eq'PlusEquals'},$true))
$loop=@($ast.FindAll({param($n)$n-is[System.Management.Automation.Language.ForEachStatementAst]-and$n.Variable.VariablePath.UserPath-eq'case'-and$n.Condition.Extent.Text-eq'$cases'-and@($n.Body.FindAll({param($x)$x-is[System.Management.Automation.Language.AssignmentStatementAst]-and$x.Left.Extent.Text-eq'$outputs'},$true)).Count-eq1},$true))
if($assign.Count-ne1-or$loop.Count-ne1){throw 'Actual case/output boundaries are ambiguous.'}
$cases=@()
foreach($mass in @(96.0,101.5)){
 $caseResultDir=Join-Path $Root ('mass_'+$mass);$null=New-Item -ItemType Directory $caseResultDir
 $caseConfigPath=Join-Path $Root ('case_'+$mass+'.json')
 Invoke-Expression $assign[0].Extent.Text
}
$outputs=@();Invoke-Expression $loop[0].Extent.Text
foreach($case in $cases){
 if(-not$case.Contains('release_source_mapping')){throw 'Actual case omits release mapping.'}
 if(@($outputs|Where-Object{$_-eq$case.release_source_mapping}).Count-ne1){throw 'Mapping is absent or duplicated in actual manifest output array.'}
 if($case.release_source_mapping-ne(Join-Path (Split-Path $case.particle_state) 'release_source_mapping.json')){throw 'Mapping bound to another case.'}
}
if($outputs.Count-ne8){throw 'Existing three outputs and mapping must remain for both cases.'}
@{cases=$cases;outputs=$outputs}|ConvertTo-Json -Depth 8
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script), "-Runner", str(runner), "-Root", str(root)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(result.stdout)
            self.assertEqual(len(document["cases"]), 2)
            self.assertEqual(len(document["outputs"]), 8)

    def test_paired_case_tables_preserve_source_and_change_only_mass(self) -> None:
        source = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "particles" / "official_fixed_100.ion"
        source_rows = list(csv.reader(source.read_text(encoding="utf-8").splitlines()))
        with tempfile.TemporaryDirectory() as temporary:
            cases = generate_paired_case_tables(Path(source), Path(temporary), [96.0, 101.5, 106.0], 100)
            self.assertEqual(len(cases), 3)
            for case in cases:
                rows = list(csv.reader(Path(case["particle_table"]).read_text(encoding="utf-8").splitlines()))
                self.assertEqual(len(rows), 100)
                self.assertTrue(all(float(row[1]) == case["mass_Th"] for row in rows))
                self.assertEqual([row[:1] + row[2:] for row in rows], [row[:1] + row[2:] for row in source_rows])

    def test_comsol_functional_aggregate_uses_frozen_mass_contract(self) -> None:
        mode_path = PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        transmissions = [0.0, 0.2, 0.92, 1.0, 0.72, 0.24, 0.04]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for mass, transmission in zip(
                mode["mass_scan_spec"]["paired_source_masses_Th"],
                transmissions,
            ):
                summary = root / f"mass_{mass:g}.json"
                summary.write_text(json.dumps({
                    "mode": "mass_filter_reference", "mass_Th": mass, "particles": 100,
                    "hits": round(25 * transmission), "transmission": transmission,
                }), encoding="utf-8")
                cases.append({"solver_summary": str(summary)})
            scan = root / "scan.json"
            scan.write_text(json.dumps({"cases": cases}), encoding="utf-8")
            response, metrics = module.analyze(scan, mode_path)
            self.assertEqual(
                [row["mass_Th"] for row in response],
                mode["mass_scan_spec"]["paired_source_masses_Th"],
            )
            self.assertEqual(metrics["status"], "PASS")
            self.assertEqual(metrics["sampled_response_analysis"]["status"], "computed")
            self.assertEqual(metrics["sampled_response_analysis"]["mass_samples_Th"],
                             mode["mass_scan_spec"]["paired_source_masses_Th"])
            self.assertFalse(metrics["sampled_response_analysis"]["resolution_claim_allowed"])
            # The same consumer rejects out-of-domain solver responses before publishing.
            last_summary = json.loads(summary.read_text(encoding="utf-8"))
            last_summary["transmission"] = 1.01
            summary.write_text(json.dumps(last_summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "within \\[0, 1\\]"):
                module.analyze(scan, mode_path)

    def test_comsol_case_preparation_derives_n1000_from_source(self) -> None:
        source_100 = (
            PROJECT_ROOT / "variants" / "quadrupole" / "config" / "particles" / "official_fixed_100.ion"
        )
        mode = (
            PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_1000 = root / "source_n1000.ion"
            source_1000.write_text(
                source_100.read_text(encoding="utf-8") * 10,
                encoding="utf-8",
            )
            metadata = prepare_comsol_scan.generate(
                source_1000,
                mode,
                root / "cases",
                root / "cases.json",
            )
        self.assertEqual(metadata["particles_per_mass"], 1000)
        self.assertTrue(
            all(case["particles"] == 1000 for case in metadata["cases"])
        )

    def test_matlab_builder_superposes_differential_and_static_fields(self) -> None:
        builder = (
            PROJECT_ROOT
            / "comsol"
            / "solve_deterministic_rf_quadrupole_particles.m"
        ).read_text(encoding="utf-8")
        mass_task = (
            PROJECT_ROOT / "comsol" / "mass_filter_reference" / "run_scan.m"
        ).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("'mass_filter_reference'", builder)
        self.assertIn("requireExistingFile(inputs,'resolved_design')", builder)
        self.assertIn("drive=resolved.drive", builder)
        self.assertIn("V_dc+V_rf*sin", builder)
        self.assertIn("Vdiff", builder)
        self.assertIn("Vstatic", builder)
        self.assertIn("-d(Vdiff,x))-axial_scale*d(Vstatic,x)", builder)
        self.assertIn("p.set('axial_scale','1')", builder)
        self.assertIn("staticElectrodes=resolved.static_electrodes_V", builder)
        self.assertIn("caseConfig.workflow_id,'mass_filter_reference'", mass_task)
        self.assertIn(
            "solve_deterministic_rf_quadrupole_particles(caseConfig)", mass_task
        )

    def test_matlab_exports_raw_metadata_while_python_owns_aggregate_metrics(self) -> None:
        builder = (
            PROJECT_ROOT / "comsol" / "solve_deterministic_rf_quadrupole_particles.m"
        ).read_text(encoding="utf-8")
        interface_runner = (
            PROJECT_ROOT / "workflows/interface_readiness/run_comsol.ps1"
        ).read_text(encoding="utf-8")
        mass_runner = (
            PROJECT_ROOT / "workflows/mass_filter_reference/run_comsol.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("solver_raw_metadata.json", builder)
        self.assertNotIn("solver_summary.json", builder)
        for forbidden in (
            "summarizeCensusEnergy",
            "mean_output_energy_eV",
            "output_energy_standard_deviation_eV",
            "sum(hit)",
            "mean(hit)",
        ):
            self.assertNotIn(forbidden, builder)
        for runner in (interface_runner, mass_runner):
            self.assertIn("analyze_comsol_particle_state_metrics", runner)

    def test_comsol_runners_freeze_the_governed_resolved_design(self) -> None:
        transport_runner = (
            PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1"
        ).read_text(encoding="utf-8")
        mass_runner = (
            PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_comsol.ps1"
        ).read_text(encoding="utf-8")
        for runner in (transport_runner, mass_runner):
            self.assertIn("resolved_design", runner)
            self.assertNotIn("resolve_family_operating_contract", runner)
            self.assertNotIn("family_operating_contract", runner)
        self.assertIn("'--source-format','ion11'", "".join(transport_runner.split()))
        self.assertIn("common.contracts.particle_state", transport_runner)

    def test_mass_filter_functional_pass_does_not_claim_formal_eligibility(self) -> None:
        runner = (
            PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_comsol.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("formal_gate_passed=$false", runner)
        self.assertNotIn(
            "$runConfiguration.formal_gate_passed=($metricDocument.status-eq 'PASS')",
            runner,
        )

    def test_comsol_mass_runner_has_no_cross_source_dependency(self) -> None:
        runner = (
            PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_comsol.ps1"
        ).read_text(encoding="utf-8")
        parameter_block = runner[: runner.index("Set-StrictMode")]
        self.assertIn("[string]$SourceIonPath", parameter_block)
        self.assertIn(
            "role='rf_quadrupole_comsol_mass_filter_run_config'",
            runner,
        )
        for forbidden in (
            "SimionRunId",
            "L1RunId",
            "simion_response",
            "l1_response",
            "mass-response__l0-l1-simion-comsol",
        ):
            self.assertNotIn(forbidden, runner)
        evaluator = (
            PROJECT_ROOT
            / "workflows"
            / "mass_filter_reference"
            / "evaluate_comsol.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("evaluate_simion", evaluator)
        self.assertNotIn("theory_masses", evaluator)
        self.assertNotIn("simion", evaluator.lower())

    def test_mass_comparison_requires_all_source_run_ids(self) -> None:
        runner = (
            PROJECT_ROOT
            / "workflows"
            / "mass_filter_reference"
            / "compare_responses.ps1"
        ).read_text(encoding="utf-8")
        parameter_block = runner[: runner.index("Set-StrictMode")]
        for required in ("ComsolRunId", "SimionRunId", "L1RunId"):
            self.assertIn(
                f"[Parameter(Mandatory = $true)][string]${required}",
                parameter_block,
            )
        self.assertNotIn("$Mode", parameter_block)
        self.assertIn("Copy-PortableRunManifestClosure", runner)
        self.assertIn("Invoke-IsolatedFrozenPythonModule", runner)
        self.assertIn("$comsolSourceParticles", runner)
        self.assertIn("$simionSourceParticles", runner)
        self.assertIn(
            "'--comsol-source-particles',$comsolSourceParticles",
            runner,
        )
        self.assertIn(
            "'--simion-source-particles',$simionSourceParticles",
            runner,
        )

    def test_project_comsol_runner_and_builder_retain_only_specialized_modes(self) -> None:
        runner = (
            PROJECT_ROOT / "workflows/interface_readiness/run_comsol.ps1"
        ).read_text(encoding="utf-8")
        builder = (
            PROJECT_ROOT / "comsol/solve_deterministic_rf_quadrupole_particles.m"
        ).read_text(encoding="utf-8")
        dedicated = (
            PROJECT_ROOT / "comsol/prepare_interface_readiness_run.m"
        ).read_text(encoding="utf-8")
        for source in (runner, builder):
            self.assertNotIn("[ValidateSet('transport_no_collision'", source)
            self.assertNotIn("'axial_acceleration_reference'", source)
            self.assertNotIn("'exit_aperture_plate_acceleration_reference'", source)
        self.assertIn("'transport_interface_readiness'", runner)
        self.assertIn("'transport_interface_readiness'", dedicated)
        self.assertNotIn("'transport_interface_readiness'", builder)
        self.assertNotIn("'mass_filter_reference'", builder)


if __name__ == "__main__":
    unittest.main()
