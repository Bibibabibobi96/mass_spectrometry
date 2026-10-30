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
        definition = self.runtime["design_profile_resolution"]["input_definitions"]
        request = copy.deepcopy(definition["design_request"])
        request["geometry_mm"]["numerical_domain"]["z_min_mm"] = -3.0
        request = apply_typed_operating_mode(
            request,
            definition["operating_mode_registry"],
            "no_acceleration_full_length",
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


if __name__ == "__main__":
    unittest.main()
