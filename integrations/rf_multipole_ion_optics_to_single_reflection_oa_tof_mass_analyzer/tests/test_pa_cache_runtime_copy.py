"""Exercise the production PA family copier without SIMION or large payloads."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "runtime" / "run_single_flight.ps1"
REPO = Path(__file__).resolve().parents[3]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class PaCacheRuntimeCopyTests(unittest.TestCase):
    def test_optional_mode_shapes_copy_the_complete_family(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("  function Copy-RfPaCacheFamilyToRuntime {")
        function = source[start:source.index("  $formalDir =", start)]
        assignment_start = source.index("    $runtimeProjectionIds =", start)
        assignment = source[assignment_start:source.index(
            "    Copy-RfPaCacheFamilyToRuntime", assignment_start
        )]
        # The false branch formerly emitted no objects, producing $null and
        # StrictMode's missing Count error before any flight could start.
        for case, argument, projection, expected_count in (
            ("omitted", "", "$false", 0),
            ("null", "-PaPlusSolutionIds $null", "$false", 0),
            ("empty", "-PaPlusSolutionIds @()", "$false", 0),
            ("runtime_empty", "-PaPlusSolutionIds $runtimeProjectionIds", "$false", 0),
            ("single", "-PaPlusSolutionIds 44", "$true", 1),
            ("multiple", "-PaPlusSolutionIds @(44,45)", "$true", 2),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                cache, runtime = root / "cache", root / "runtime"
                cache.mkdir()
                runtime.mkdir()
                names = ["main.pa0", "main.pa#", "main.pa_", "main.pa+", "main.pa44", "main.pa45"]
                for name in names:
                    (cache / name).write_bytes(name.encode("ascii"))
                def quote(path: Path) -> str:
                    return "'" + str(path).replace("'", "''") + "'"
                script = (
                    "$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest\n"
                    + function
                    + "\nfunction Set-RfMaterializedCacheFileWritable { param($Path) }\n"
                    + f"$runtimeDir={quote(runtime)}\n"
                    + f"$postPulseHandoffMinimal={projection}\n"
                    + "$domainSplitFineBuild=[pscustomobject]@{name='accelerator_main'}\n"
                    + ("$postPulsePaPlusSolutionIds=@(44,45)\n" if expected_count == 2
                       else "$postPulsePaPlusSolutionIds=@(44)\n")
                    + assignment
                    + f"if ($runtimeProjectionIds.Count -ne {expected_count}) {{ throw 'mode count differs' }}\n"
                    + f"Copy-RfPaCacheFamilyToRuntime -CacheDirectory {quote(cache)} -Pattern 'main.pa*' {argument}\n"
                )
                result = subprocess.run(
                    ["pwsh", "-NoLogo", "-NoProfile", "-Command", script],
                    capture_output=True, text=True, timeout=30, cwd=REPO,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(sorted(p.name for p in runtime.iterdir()), sorted(names))
                for name in names:
                    self.assertEqual((runtime / name).read_bytes(), (cache / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
