from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.multipole.particle_source_preflight import COLUMNS
from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    generate_bundle,
)
from projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
RUNNER = PROJECT_ROOT / "tests" / "simion" / "run_transport_candidate.ps1"
EXECUTION_PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"
RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"
SOURCE_FAMILY = PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
RUN_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


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
            },
        )
        self.assertEqual(
            interface_steps["simion_run"]["entrypoint"],
            "tests/simion/run_transport_candidate.ps1",
        )
        self.assertNotIn(
            "../../common/multipole/run_simion_finite_3d_transport.ps1",
            json.dumps(interface),
        )
        mass_filter = profiles["mass_filter_simion_functional_reference"]
        mass_steps = {step["step_id"]: step for step in mass_filter["steps"]}
        self.assertEqual(
            mass_filter["required_bindings"],
            ["mass_filter_base_source_ion11_path", "run_id"],
        )
        self.assertEqual(
            mass_steps["simion_mass_response"]["entrypoint"],
            "tests/simion/run_mass_filter_candidate.ps1",
        )

    def test_runner_uses_current_canonical_source_cli_as_an_argument_array(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        parameter_block = source[: source.index("Set-StrictMode")]
        for forbidden in (
            "$Mode",
            "$SourceAxialOffsetMm",
            "mass_filter_reference",
            "generate_mass_scan_particle_table",
            "render_ion11_simion_source",
            "analyze_simion_mass_scan",
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
                    "-ArtifactRootPath",
                    str(artifact_root),
                    "-PythonExe",
                    str(RUN_PYTHON),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            run = artifact_root / "runs" / run_id
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
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertLess(source.index("try {"), source.index("$sourceParticlePath"))


if __name__ == "__main__":
    unittest.main()
