from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
FIXTURE = Path(__file__).with_name("test_dirichlet_patch_basis_fixture.lua")
BUILDER = Path(__file__).with_name("build_dirichlet_patch_basis.lua")
GEM2PA = Path(__file__).with_name("run_gem2pa.ps1")


@unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
class DirichletPatchBasisTest(unittest.TestCase):
    def run_simion(self, *arguments: object) -> str:
        result = subprocess.run(
            [str(SIMION), "--nogui", "--noprompt", "lua", *(str(value) for value in arguments)],
            cwd=ROOT,
            timeout=120,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def test_native_10000_v_donor_is_not_rescaled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-patch-") as directory:
            self.assertIn("PREPARED", self.run_simion(FIXTURE, "prepare", directory))
            compile_result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target.gem"),
                 "-OutputPaPath", str(Path(directory) / "target.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            self.assertIn("SIMION_GEM2PA=PASS", compile_result.stdout)
            output = self.run_simion(
                BUILDER,
                Path(directory) / "target.pa",
                Path(directory) / "donor.pa",
                "0,0,0",
                "1,1,1",
            )
            self.assertIn("native_basis_voltage=10000", output)
            self.assertIn("boundary_scale=1", self.run_simion(FIXTURE, "verify", directory))

    def test_optional_source_coefficient_scales_only_donor_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-scaled-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target.gem"),
                 "-OutputPaPath", str(Path(directory) / "target.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            self.run_simion(
                BUILDER,
                Path(directory) / "target.pa",
                f"{Path(directory) / 'donor.pa'},0.5",
                "0,0,0",
                "1,1,1",
            )
            self.assertIn("boundary_scale=0.5", self.run_simion(FIXTURE, "verify_scaled", directory))
    def test_x_mirror_plane_is_not_overwritten_by_dirichlet_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-mirror-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target_mirror.gem"),
                 "-OutputPaPath", str(Path(directory) / "target_mirror.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            output = self.run_simion(
                BUILDER, Path(directory) / "target_mirror.pa", Path(directory) / "donor.pa",
                "0,0,0", "0,0,0", "x_mirror_five_faces",
            )
            self.assertIn("boundary_mode=x_mirror_five_faces", output)
            self.assertIn("boundary_mode=x_mirror_five_faces", self.run_simion(FIXTURE, "verify_mirror", directory))

    def test_explicit_stopping_keeps_mirror_edges_and_physical_voltage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-dirichlet-stopping-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target_mirror.gem"),
                 "-OutputPaPath", str(Path(directory) / "target_mirror.pa")],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            output = self.run_simion(
                BUILDER, Path(directory) / "target_mirror.pa", Path(directory) / "donor.pa",
                "0,0,0", "0,0,0", "x_mirror_five_faces", "1e-5",
            )
            self.assertIn("refine_convergence=1e-05", output.lower())
            self.assertIn("boundary_mode=x_mirror_five_faces", self.run_simion(FIXTURE, "verify_mirror", directory))

    def test_invalid_stopping_is_rejected_before_opening_arrays(self) -> None:
        for value in ("0", "-1", "nan", "inf", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(subprocess.CalledProcessError) as failure:
                    self.run_simion(BUILDER, "absent-target.pa", "absent-source.pa",
                                    "0,0,0", "0,0,0", "six_faces", value)
                message = (failure.exception.stdout or "") + (failure.exception.stderr or "")
                self.assertIn("convergence", message.lower())

    def test_parent_refine_cli_accepts_explicit_stopping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion-parent-stopping-") as directory:
            self.run_simion(FIXTURE, "prepare", directory)
            target = Path(directory) / "target.pa"
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(GEM2PA),
                 "-SimionExe", str(SIMION), "-GemPath", str(Path(directory) / "target.gem"),
                 "-OutputPaPath", str(target)],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "refine", "--convergence=1e-5", str(target)],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
            )
            self.assertIn("Refine completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
