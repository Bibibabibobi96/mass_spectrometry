"""COMSOL source preparation checks the actual declared outer solver volume."""

from __future__ import annotations
import copy
import csv
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from projects.rf_multipole_ion_optics.runtime import (
    particle_source_preflight as source_api,
)
from projects.rf_multipole_ion_optics.runtime.runtime_profile import (
    resolve_runtime_profile,
)
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.compile_design_request import (
    compile_design_request,
    apply_typed_operating_mode,
)

REPO = Path(__file__).resolve().parents[4]


class ComsolSourceDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = resolve_runtime_profile(
            REPO,
            "rf_multipole_ion_optics",
            "octupole_no_acceleration_full_length_volume_snapshot_n100",
        )
        cls.resolved = cls.runtime["design_profile_resolution"]["resolved_design"]
        cls.source = Path(cls.runtime["particle_source"]["path"])
        cls.receipt = Path(
            cls.runtime["particle_source"]["volume_snapshot_receipt"]["path"]
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_finite_consumer_passes_comsol_policy_to_real_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolved = root / "resolved.json"
            resolved.write_text(json.dumps(self.resolved), encoding="utf-8")
            metadata = root / "absent/metadata.json"
            script = root / "arguments.ps1"
            script.write_text("""param($Owner,$Source,$Resolved,$Output)
$ErrorActionPreference='Stop'
$particleSource=$Source;$resolved=$Resolved;$sourceMetadata=$Output
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$assignment=$ast.Find({param($node)
 $node-is[Management.Automation.Language.AssignmentStatementAst]-and
 $node.Left.Extent.Text-eq'$preflightArguments'-and
 $node.Operator-eq[Management.Automation.Language.TokenKind]::Equals
},$true)
if($null-eq$assignment){throw 'Actual finite source argument construction is missing.'}
Invoke-Expression $assignment.Extent.Text
ConvertTo-Json -InputObject @($preflightArguments) -Compress
""", encoding="utf-8")
            args = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                 str(REPO / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"),
                 str(self.source), str(resolved), str(metadata)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(args.returncode, 0, args.stdout + args.stderr)
            actual = subprocess.run(
                [sys.executable, *json.loads(args.stdout),
                 "--volume-snapshot-receipt", str(self.receipt)],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertNotEqual(actual.returncode, 0)
            self.assertIn("outside numerical_domain: z_mm=", actual.stderr)
            self.assertFalse(metadata.parent.exists())

    def test_actual_registered_volume_fails_before_output(self):
        with self.assertRaisesRegex(
            ValueError, "COMSOL source particle .* outside numerical_domain: z_mm="
        ):
            source_api.validate_source(
                self.source,
                self.resolved,
                solver="comsol",
                volume_snapshot_receipt_path=self.receipt,
            )

    def test_existing_unselected_or_simion_preflight_does_not_gain_comsol_policy(self):
        for solver in (None, "simion"):
            with self.subTest(solver=solver):
                metadata = source_api.validate_source(
                    self.source,
                    self.resolved,
                    solver=solver,
                    volume_snapshot_receipt_path=self.receipt,
                )
                self.assertEqual(metadata["particle_count"], 100)
                self.assertNotIn("comsol_domain_validation", metadata)

    def test_provider_accepts_bounded_upstream_extension_without_source_change(self):
        design = resolve_design_profile(REPO, "rf_multipole_ion_optics", self.runtime["design_profile_id"])
        request = json.loads(Path(design["paths"]["design_request"]).read_text(encoding="utf-8"))
        request["geometry_mm"]["numerical_domain"]["z_min_mm"] = -3.0
        request = apply_typed_operating_mode(
            request,
            json.loads(Path(design["paths"]["operating_mode_registry"]).read_text(encoding="utf-8")),
            design["profile"]["mode_id"],
        )
        resolved = compile_design_request(
            request, expected_identity=self.resolved["identity"]
        )
        original = self.source.read_bytes()
        metadata = source_api.validate_source(
            self.source,
            resolved,
            solver="comsol",
            volume_snapshot_receipt_path=self.receipt,
        )
        self.assertEqual(metadata["comsol_domain_validation"]["particle_count"], 100)
        self.assertEqual(metadata["comsol_domain_validation"]["z_min_mm"], -3.0)
        self.assertNotEqual(
            resolved["resolved_sha256"], self.resolved["resolved_sha256"]
        )
        self.assertEqual(self.source.read_bytes(), original)

    def planar(self, root, x, y, z, resolved=None):
        source = root / "source.csv"
        with source.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=source_api.COLUMNS)
            writer.writeheader()
            writer.writerow(
                dict(
                    particle_id=1,
                    birth_time_s=0,
                    x_mm=x,
                    y_mm=y,
                    z_mm=z,
                    vx_m_s=0,
                    vy_m_s=0,
                    vz_m_s=math.sqrt(4 * ELEMENTARY_CHARGE_C / (100 * AMU_KG)),
                    mass_amu=100,
                    charge_state=1,
                )
            )
        return source_api.validate_source(
            source,
            resolved or self.resolved,
            solver="comsol",
            expected_kinetic_energy_ev=2,
        )

    def test_outer_radius_not_working_region_radius(self):
        z = self.resolved["geometry_mm"]["observations"]["release_plane_z_mm"]
        with tempfile.TemporaryDirectory() as directory:
            metadata = self.planar(Path(directory), 4, 0, z)
        self.assertEqual(metadata["comsol_domain_validation"]["radius_mm"], 21)

    def test_cylinder_rejects_outside_actual_radius(self):
        z = self.resolved["geometry_mm"]["observations"]["release_plane_z_mm"]
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "outside numerical_domain: x_mm="),
        ):
            self.planar(Path(directory), 21.0001, 0, z)

    def test_cylinder_accepts_exact_outer_boundary(self):
        z = self.resolved["geometry_mm"]["observations"]["release_plane_z_mm"]
        with tempfile.TemporaryDirectory() as directory:
            metadata = self.planar(Path(directory), 21, 0, z)
        self.assertEqual(metadata["comsol_domain_validation"]["shape"], "cylinder")

    def test_rectangular_reference_keeps_box_corners(self):
        resolved = copy.deepcopy(self.resolved)
        resolved["geometry_mm"]["enclosure"] = dict(
            model="rectangular_reference_enclosure_v1",
            outer_half_width_mm=21,
            vacuum_z_min_mm=-2.5,
            vacuum_z_max_mm=82.1,
            working_region_radius_mm=3.6,
        )
        resolved["interfaces_mm"] = dict(
            entrance=dict(release_plane_z_mm=0),
            exit=dict(
                handoff_plane_z_mm=80.6, census_plane_z_mm=81.1, aperture_radius_mm=3.6
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            metadata = self.planar(Path(directory), 20, 20, 0, resolved)
        self.assertEqual(metadata["comsol_domain_validation"]["shape"], "box")

    def test_cli_rejects_actual_volume_before_metadata_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolved = root / "resolved.json"
            output = root / "not-created/metadata.json"
            resolved.write_text(json.dumps(self.resolved), encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(source_api.__file__)),
                    "--source",
                    str(self.source),
                    "--resolved-design",
                    str(resolved),
                    "--volume-snapshot-receipt",
                    str(self.receipt),
                    "--solver",
                    "comsol",
                    "--output",
                    str(output),
                ],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside numerical_domain: z_mm=", result.stderr)
            self.assertFalse(output.parent.exists())


    def source_receipt_boundary(self, mode):
        PROJECT = REPO / "projects/rf_multipole_ion_optics"
        resolved = resolve_runtime_profile(
            REPO,
            "rf_multipole_ion_optics",
            "octupole_no_acceleration_full_length_volume_snapshot_n100",
        )
        receipt = self.root / "receipt.json"
        receipt.write_bytes(
            Path(
                resolved["particle_source"]["volume_snapshot_receipt"]["path"]
            ).read_bytes()
        )
        resolved["particle_source"]["volume_snapshot_receipt"]["path"] = str(receipt)
        if mode == "tampered":
            receipt.write_text(
                receipt.read_text(encoding="utf-8") + " ", encoding="utf-8"
            )
        if mode == "missing":
            receipt.unlink()
        if mode == "undeclared":
            resolved["particle_source"].pop("volume_snapshot_receipt")
        snapshot = self.root / "resolved_runtime.json"
        snapshot.write_text(json.dumps(resolved), encoding="utf-8")
        design = self.root / "resolved_design.json"
        # Reuse the existing explicit upstream-domain fixture. The registered
        # unchanged default remains rejected by its existing separate test.
        selected = resolve_design_profile(REPO, "rf_multipole_ion_optics", resolved["design_profile_id"])
        request = json.loads(Path(selected["paths"]["design_request"]).read_text(encoding="utf-8"))
        request["geometry_mm"]["numerical_domain"]["z_min_mm"] = -3.0
        request = apply_typed_operating_mode(
            request,
            json.loads(Path(selected["paths"]["operating_mode_registry"]).read_text(encoding="utf-8")),
            selected["profile"]["mode_id"],
        )
        fixture_design = compile_design_request(
            request, expected_identity=resolved["design_profile_resolution"]["resolved_design"]["identity"]
        )
        design.write_text(
            json.dumps(fixture_design),
            encoding="utf-8",
        )

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        script = self.root / "source_prepare.ps1"
        body = "\n$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n$repoRoot=@@REPO@@;$runner=@@RUNNER@@;$testRoot=@@ROOT@@\n. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')\n$inputDir=Join-Path $testRoot 'inputs';New-Item -ItemType Directory -Path $inputDir -Force|Out-Null\n$compiledRuntime=Get-Content -LiteralPath @@IR@@ -Raw -Encoding UTF8|ConvertFrom-Json -Depth 100\n$particleSourceInput=@@SOURCE@@;$sourceFamilyInput=$null;$OperatingPointId='fixture'\nif(@@CONFLICT@@){$sourceFamilyInput=Join-Path $testRoot 'family.json';'{}'|Set-Content -LiteralPath $sourceFamilyInput -Encoding utf8}\n$codeRoot=$repoRoot;$resolved=@@DESIGN@@;$python=@@PYTHON@@\n$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)\nif($errors.Count){throw 'production runner parse failed'}\n$start=@($ast.FindAll({param($node)$node-is[System.Management.Automation.Language.AssignmentStatementAst]-and$node.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$node.Left.VariablePath.UserPath-eq'particleSource'},$true))[0].Extent.StartOffset\n$end=@($ast.FindAll({param($node)$node-is[System.Management.Automation.Language.AssignmentStatementAst]-and$node.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$node.Left.VariablePath.UserPath-eq'sourceMeta'},$true))[0].Extent.EndOffset\n$source=Get-Content -LiteralPath $runner -Raw -Encoding UTF8\nInvoke-Expression $source.Substring($start,$end-$start)\nif(-not$sourceMeta.source_volume_snapshot){throw 'actual preflight missed snapshot semantics'}\nif(-not$volumeSnapshotReceipt-or-not(Test-Path -LiteralPath $volumeSnapshotReceipt)){throw 'frozen receipt absent'}\nif([string]$volumeReceiptIdentity.sha256-ne[string]$compiledRuntime.particle_source.volume_snapshot_receipt.sha256){throw 'receipt identity differs'}\nWrite-Output 'ACTUAL_COMSOL_SOURCE_PREPARE=PASS SNAPSHOT=true'\n"
        replacements = {
            "REPO": quote(REPO),
            "RUNNER": quote(PROJECT / "runtime/run_finite_3d_transport.ps1"),
            "ROOT": quote(self.root),
            "IR": quote(snapshot),
            "SOURCE": quote(resolved["particle_source"]["path"]),
            "DESIGN": quote(design),
            "CONFLICT": "$true" if mode == "conflict" else "$false",
            "PYTHON": quote(sys.executable),
        }
        for key, value in replacements.items():
            body = body.replace("@@" + key + "@@", value)
        script.write_text(body, encoding="utf-8")
        return subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script)],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
        )

    def test_actual_comsol_source_prepare_freezes_and_consumes_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.root = Path(temporary)
            execution = self.source_receipt_boundary("valid")
        self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
        self.assertIn("ACTUAL_COMSOL_SOURCE_PREPARE=PASS", execution.stdout)

    def test_actual_comsol_source_prepare_rejects_missing_changed_or_conflicting_receipt(
        self,
    ):
        for mode in ("missing", "tampered", "undeclared", "conflict"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as temporary:
                    self.root = Path(temporary)
                    execution = self.source_receipt_boundary(mode)
                self.assertNotEqual(
                    execution.returncode, 0, execution.stdout + execution.stderr
                )
                expected = {
                    "missing": "Run input is missing",
                    "tampered": "Resolved COMSOL volume receipt differs from its frozen identity",
                    "undeclared": "source plane differs from resolved design",
                    "conflict": "volume-source receipt cannot be combined with an energy override",
                }
                self.assertIn(expected[mode], execution.stdout + execution.stderr)


if __name__ == "__main__":
    unittest.main()
