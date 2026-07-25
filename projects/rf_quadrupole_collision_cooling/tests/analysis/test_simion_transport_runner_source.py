from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.multipole.particle_source_preflight import COLUMNS
from common.multipole.verify_resolved_design import verify as verify_resolved_design
from projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.particle_source_policy import (
    generate_interface_bundle as generate_bundle,
)
from projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
MASS_RUNNER = (
    PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_simion.ps1"
)
RUN_CONFIG_CONTRACT = PROJECT_ROOT / "runtime" / "simion_run_config.ps1"
SHARED_LUA = REPO_ROOT / "common" / "multipole" / "simion_transport.lua"
EXECUTION_PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"
RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"
SOURCE_FAMILY = PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
INTERFACE_CONTRACT = PROJECT_ROOT / "config" / "interface_contract.json"
SOLVER_NUMERICS = PROJECT_ROOT / "config" / "simion_solver_numerics.json"


def write_canonical_source(path: Path) -> None:
    resolved = json.loads(RESOLVED.read_text(encoding="utf-8"))
    speed = math.sqrt(2.0 * 2.0 * ELEMENTARY_CHARGE_C / (100.0 * AMU_KG))
    vx, vy = 100.0, -50.0
    vz = math.sqrt(speed * speed - vx * vx - vy * vy)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for particle_id in range(1, 101):
            writer.writerow(
                {
                    "particle_id": particle_id,
                    "birth_time_s": 0,
                    "x_mm": 0.1,
                    "y_mm": -0.2,
                    "z_mm": resolved["interfaces_mm"]["entrance"][
                        "particle_plane_z_mm"
                    ],
                    "vx_m_s": format(vx, ".17g"),
                    "vy_m_s": format(vy, ".17g"),
                    "vz_m_s": format(vz, ".17g"),
                    "mass_amu": 100,
                    "charge_state": 1,
                }
            )


class SimionTransportRunnerSourceTests(unittest.TestCase):
    def test_resolved_design_logical_hash_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            document = json.loads(RESOLVED.read_text(encoding="utf-8"))
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(verify_resolved_design(path), document["resolved_sha256"])
            document["drive"]["phase_rad"] = 0.25
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "recomputed logical design hash"):
                verify_resolved_design(path)

    def test_dedicated_runners_cover_shared_lua_required_config_fields(self) -> None:
        lua = SHARED_LUA.read_text(encoding="utf-8")
        required_fields = set(
            re.findall(r"assert\(run_config\.([a-z0-9_]+)", lua)
        )
        self.assertIn("waveform", required_fields)
        self.assertIn("parent_resolved_design_sha256", required_fields)
        self.assertGreater(len(required_fields), 10)
        helper = RUN_CONFIG_CONTRACT.read_text(encoding="utf-8")
        for token in (
            "function New-RfSimionCoreRunConfig",
            "function ConvertTo-RfSimionLuaConfig",
            "function Assert-RfSimionLuaConfigContract",
            "'parent_resolved_design_sha256'",
            "Generated SIMION run config lacks required fields",
        ):
            self.assertIn(token, helper)
        for runner_path in (RUNNER, MASS_RUNNER):
            runner = runner_path.read_text(encoding="utf-8")
            for token in (
                "New-RfSimionCoreRunConfig",
                "ConvertTo-RfSimionLuaConfig",
                "Invoke-RfSimionCoreRun",
                "Copy-VerifiedRunInput",
                "Write-RunDirectoryChecksumInventory",
                "parent_resolved_design_sha256 = $coreConfig.parent_resolved_design_sha256",
                "waveform = $coreConfig.waveform",
            ):
                self.assertIn(token, runner)
            for forbidden in (
                "return {",
                "Copy-Item",
                "gem2pa",
                "Start-Process -FilePath $simion",
            ):
                self.assertNotIn(forbidden, runner)

    def test_waveform_contract_accepts_only_exact_governed_enum(self) -> None:
        command = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "$resolved=Get-Content -LiteralPath $env:RF_RESOLVED_JSON "
            "-Raw -Encoding UTF8|ConvertFrom-Json; "
            "Get-VerifiedRfSimionWaveform -ResolvedDesign $resolved"
        )
        cases = (
            ({"drive": {"waveform": "sine"}}, True, "sine"),
            ({"drive": {"waveform": "cosine"}}, True, "cosine"),
            ({"drive": {}}, False, "drive.waveform is missing"),
            ({"drive": {"waveform": "sinusoidal"}}, False, "exactly sine or cosine"),
            ({"drive": {"waveform": "SINE"}}, False, "exactly sine or cosine"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (payload, accepted, message) in enumerate(cases):
                resolved_path = root / f"resolved_{index}.json"
                resolved_path.write_text(json.dumps(payload), encoding="utf-8")
                environment = os.environ.copy()
                environment.update(
                    {
                        "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
                        "RF_RESOLVED_JSON": str(resolved_path),
                    }
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    encoding="utf-8",
                    env=environment,
                    timeout=30,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                output = result.stdout if accepted else result.stderr
                self.assertIn(message, output)

    def test_core_compiler_fails_closed_on_hash_numeric_and_mapping_drift(self) -> None:
        prefix = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "$r=Get-Content $env:RF_RESOLVED_JSON -Raw|ConvertFrom-Json; "
            "$i=Get-Content $env:RF_INTERFACE_JSON -Raw|ConvertFrom-Json; "
            "$n=Get-Content $env:RF_NUMERICS_JSON -Raw|ConvertFrom-Json; "
            "$steps=40; "
            "$quality=10; "
        )
        suffix = (
            "$core=New-RfSimionCoreRunConfig -ResolvedDesign $r "
            "-InterfaceContract $i -SolverNumerics $n "
            "-RfStepsPerPeriod $steps "
            "-TrajectoryQuality $quality -ModeName transport_interface_readiness "
            "-OperatingPoint official_100amu_2eV -IobPath C:\\tmp\\a.iob "
            "-Fly2Path C:\\tmp\\a.fly2 -SourceStatesLua C:\\tmp\\s.lua "
            "-ParticleStateCsv C:\\tmp\\p.csv -TrajectoryCsv C:\\tmp\\t.csv "
            "-SummaryJson C:\\tmp\\q.json; "
            "ConvertTo-RfSimionLuaConfig -CoreConfig $core "
            "-SharedProgramPath $env:RF_SHARED_LUA|Out-Null"
        )
        cases = (
            ("", True, ""),
            (
                "$r.PSObject.Properties.Remove('resolved_sha256'); ",
                False,
                "resolved_sha256 is missing",
            ),
            ("$r.resolved_sha256='xyz'; ", False, "64 hexadecimal"),
            (
                "$r.drive.PSObject.Properties.Remove('frequency_Hz'); ",
                False,
                "RF frequency is missing",
            ),
            ("$r.drive.frequency_Hz=$null; ", False, "RF frequency is missing"),
            ("$r.drive.frequency_Hz=0; ", False, "RF frequency must be positive"),
            ("$r.drive.frequency_Hz='NaN'; ", False, "RF frequency must be finite"),
            (
                "$r.drive.frequency_Hz=[double]::PositiveInfinity; ",
                False,
                "RF frequency must be finite",
            ),
            ("$n.simion_cell_mm=0; ", False, "simion_cell_mm must be positive"),
            ("$i.planes.handoff.z_mm=90.3; ", False, "handoff plane mapping differs"),
            ("$steps=0; ", False, "rf_steps_per_period must be positive"),
            ("$steps=99; ", False, "not allowed by the solver numerics contract"),
            (
                "$quality=11; ",
                False,
                "trajectory_quality differs from the solver numerics contract",
            ),
        )
        environment = os.environ.copy()
        environment.update(
            {
                "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
                "RF_RESOLVED_JSON": str(RESOLVED),
                "RF_INTERFACE_JSON": str(INTERFACE_CONTRACT),
                "RF_NUMERICS_JSON": str(SOLVER_NUMERICS),
                "RF_SHARED_LUA": str(SHARED_LUA),
            }
        )
        for mutation, accepted, message in cases:
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    prefix + mutation + suffix,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                encoding="utf-8",
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode == 0, accepted, result.stderr)
            if not accepted:
                self.assertIn(message, result.stderr)

    def test_full_lua_contract_reports_late_terminate_field_before_launch(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
                "RF_SHARED_LUA": str(SHARED_LUA),
            }
        )
        command = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "Assert-RfSimionLuaConfigContract "
            "-LuaConfig 'return { waveform=[[sine]], }' "
            "-SharedProgramPath $env:RF_SHARED_LUA"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            env=environment,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("parent_resolved_design_sha256", result.stderr)

    def test_active_profiles_use_single_purpose_project_runners(self) -> None:
        profiles = {
            item["profile_id"]: item
            for item in json.loads(EXECUTION_PROFILES.read_text(encoding="utf-8"))[
                "profiles"
            ]
        }
        interface = profiles["transport_interface_readiness_candidate"]
        interface_steps = {step["step_id"]: step for step in interface["steps"]}
        self.assertEqual(
            set(interface["required_bindings"]),
            {
                "comsol_particle_source_path",
                "simion_particle_source_path",
                "particle_bundle_metadata_path",
                "particle_source_family_path",
                "particle_distribution_path",
                "simion_solver_numerics_contract_path",
                "operating_point_id",
            },
        )
        self.assertEqual(
            interface_steps["simion_run"]["entrypoint"],
            "workflows/interface_readiness/run_simion.ps1",
        )
        self.assertNotIn(
            "workflows/no_collision_transport/run_simion.ps1",
            json.dumps(interface),
        )
        mass_filter = profiles["mass_filter_simion_functional_reference"]
        mass_steps = {step["step_id"]: step for step in mass_filter["steps"]}
        self.assertEqual(
            mass_filter["required_bindings"],
            [
                "mass_filter_base_source_ion11_path",
                "simion_solver_numerics_contract_path",
                "run_id",
            ],
        )
        self.assertEqual(
            mass_steps["simion_mass_response"]["entrypoint"],
            "workflows/mass_filter_reference/run_simion.ps1",
        )

    def test_runner_uses_current_canonical_source_cli_as_an_argument_array(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        parameter_block = source[: source.index("Set-StrictMode")]
        for forbidden in (
            "$Mode",
            "$SourceAxialOffsetMm",
            "mass_filter_reference",
        ):
            self.assertNotIn(forbidden, source)
        for required in (
            "[Parameter(Mandatory=$true)][string]$ParticleTablePath",
            "[Parameter(Mandatory=$true)][string]$ParticleBundleMetadataPath",
            "[Parameter(Mandatory=$true)][string]$SourceFamilyPath",
            "[Parameter(Mandatory=$true)][string]$ParticleDistributionPath",
        ):
            self.assertIn(required, parameter_block)
        self.assertIn("$mode = 'transport_interface_readiness'", source)
        invocation = source[source.index("$sourceProjectionArguments = @(") :]
        for token in (
            "'-m','common.multipole.simion_particle_source'",
            "'--particles',$particlePath",
            "'--resolved-design',$frozenResolved",
            "'--source-family',$frozenSourceFamily",
            "'--operating-point',$OperatingPoint",
            "'--expected-source-family-sha256',$sourceFamilySha",
            "'--fly2',$flyPath",
            "'--source-states-lua',$sourceStatesLua",
            "& $python @sourceProjectionArguments",
        ):
            self.assertIn(token, invocation)
        self.assertNotIn(
            "common.multipole.simion_particle_source --ion-table", source
        )
        self.assertIn("particle_source_metadata.json", source)
        self.assertIn("'--source',$particlePath", source)
        self.assertIn("particle_source_sha256", source)
        for field in (
            "source_ion11",
            "source_canonical10",
            "consumed_particle_table",
            "particle_bundle_metadata",
            "source_sample_family_sha256",
            "latent_sha256",
            "coordinate_mapping_version",
            "ion11_sha256",
            "canonical10_sha256",
            "n1000_parent",
        ):
            self.assertIn(field, source)

    def test_bundle_binding_recomputes_both_representations(self) -> None:
        distribution = PROJECT_ROOT / "config" / "official_particle_source.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = generate_bundle(
                SOURCE_FAMILY, distribution, RESOLVED, root
            )
            canonical = root / "official_100amu_2eV_n100_canonical.csv"
            result = resolve_binding(
                root / "paired_particle_bundle.json",
                SOURCE_FAMILY,
                distribution,
                RESOLVED,
                "official_100amu_2eV",
                100,
                "canonical10",
                canonical,
            )
            entries = {
                entry["representation"]: entry
                for entry in metadata["artifacts"]
                if entry["operating_point_id"] == "official_100amu_2eV"
                and entry["particle_count"] == 100
            }
            self.assertEqual(result["representation"], "canonical10")
            self.assertEqual(result["consumed_sha256"], entries["canonical10"]["sha256"])
            self.assertEqual(result["ion11_sha256"], entries["ion11"]["sha256"])
            self.assertEqual(
                result["source_sample_family_sha256"],
                metadata["sample_family_sha256"],
            )
            self.assertEqual(result["representation_equivalence"], "PASS")
            self.assertEqual(result["n1000_parent"], entries["canonical10"]["n1000_parent"])
            n1000 = resolve_binding(
                root / "paired_particle_bundle.json",
                SOURCE_FAMILY,
                distribution,
                RESOLVED,
                "official_100amu_2eV",
                1000,
                "canonical10",
                root / "official_100amu_2eV_n1000_canonical.csv",
            )
            self.assertEqual(n1000["particle_count"], 1000)
            self.assertIsNone(n1000["n1000_parent"])
            with self.assertRaisesRegex(ValueError, "differs from its bundle artifact"):
                resolve_binding(
                    root / "paired_particle_bundle.json",
                    SOURCE_FAMILY,
                    distribution,
                    RESOLVED,
                    "official_100amu_2eV",
                    100,
                    "canonical10",
                    root / "official_100amu_2eV_n100.ion",
                )

    def test_real_python_cli_preserves_canonical_coordinate_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "inputs with spaces [poison]"
            root.mkdir()
            particles = root / "particles.csv"
            fly2 = root / "particles.fly2"
            states = root / "source states.lua"
            write_canonical_source(particles)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "common.multipole.simion_particle_source",
                    "--particles",
                    str(particles),
                    "--resolved-design",
                    str(RESOLVED),
                    "--source-family",
                    str(SOURCE_FAMILY),
                    "--operating-point",
                    "official_100amu_2eV",
                    "--expected-source-family-sha256",
                    hashlib.sha256(SOURCE_FAMILY.read_bytes()).hexdigest(),
                    "--fly2",
                    str(fly2),
                    "--source-states-lua",
                    str(states),
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            fly_text = fly2.read_text(encoding="ascii")
            state_text = states.read_text(encoding="ascii")
            self.assertEqual(fly_text.count("standard_beam {"), 100)
            self.assertIn("position=vector(-2.22044604925e-16,0.2,0.1)", fly_text)
            self.assertIn("[1]={t=0,x=-2.22044604925e-16,y=0.2,z=0.1", state_text)
            self.assertIn("vy=0.05,vz=0.1,ke=2", state_text)

    def test_pre_solver_failure_finishes_failed_run_without_simion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            particles = root / "empty canonical.csv"
            particles.write_text(",".join(COLUMNS) + "\n", encoding="utf-8")
            artifact_root = root / "artifacts"
            run_id = "20260725_120000__test__simion__source-preflight"
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(RUNNER),
                    "-RunId",
                    run_id,
                    "-ParticleTablePath",
                    str(particles),
                    "-ParticleBundleMetadataPath",
                    str(root / "missing bundle.json"),
                    "-SourceFamilyPath",
                    str(SOURCE_FAMILY),
                    "-ParticleDistributionPath",
                    str(PROJECT_ROOT / "config" / "official_particle_source.json"),
                    "-SolverNumericsContractPath",
                    str(PROJECT_ROOT / "config" / "simion_solver_numerics.json"),
                    "-OperatingPoint",
                    "official_100amu_2eV",
                    "-ArtifactRootPath",
                    str(artifact_root),
                    "-PythonExe",
                    sys.executable,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            process_diagnostics = (
                f"returncode={result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
            self.assertNotEqual(result.returncode, 0, process_diagnostics)
            self.assertNotIn("STATUS=PASS", result.stdout)
            self.assertIn("bundle metadata is missing", result.stderr.lower())
            run = artifact_root / "runs" / run_id
            for filename in ("run_config.json", "summary.json", "run_manifest.json"):
                self.assertTrue(
                    (run / filename).is_file(),
                    f"missing failed-run {filename}\n{process_diagnostics}",
                )
            summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            manifest = json.loads(
                (run / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "failed")
            self.assertIn("bundle metadata is missing", summary["reason"].lower())
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse(any((run / "simion").glob("*.pa0")))

    def test_execution_failure_and_physical_decision_are_separate(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("SIMION transport execution integrity failed", source)
        self.assertIn("$physicalDecision = if", source)
        self.assertIn("physical_decision=$physicalDecision", source)
        self.assertIn("EXECUTION=PASS DECISION=$physicalDecision", source)
        self.assertIn("Write-VerifiedRunManifest", source)
        integrity = source[
            source.index("if ($summary.particles -ne $expectedParticles")
            : source.index("$physicalDecision = if")
        ]
        self.assertNotIn("summary.transmission", integrity)
        self.assertNotIn("-ge 0.8", source)
        self.assertIn(
            "$summary.transmission -ge $minimumTransmission",
            source,
        )
        self.assertEqual(source.count("transport_interface_readiness.json"), 1)
        self.assertIn(
            "-LiteralPath $frozenMode -Raw -Encoding UTF8 | ConvertFrom-Json",
            source,
        )
        self.assertIn("minimum_transmission = $minimumTransmission", source)
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertLess(source.index("try {"), source.index("$sourceParticlePath"))


if __name__ == "__main__":
    unittest.main()
