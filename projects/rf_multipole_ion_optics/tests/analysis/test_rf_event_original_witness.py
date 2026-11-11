"""Compare installed RF event/ION11 owners with an actual old software capture."""
from __future__ import annotations

import base64
import csv
import errno
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from msplatform.backends.simion import rf_ion11_source as source
from msplatform.components.rf_multipole import event_table
from msplatform.contracts import particle_physics

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/rf_event_old_capture.json"


class OriginalRFEventWitnessTests(unittest.TestCase):
    def test_full_old_api_and_cli_witness(self):
        self.assertIs(event_table.kinetic_energy_ev, particle_physics.kinetic_energy_ev)
        self.assertFalse(hasattr(source, "read_canonical_rf_source_expectations"))
        capture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        expected = {row["case"]: row for row in capture["records"]}
        self.assertTrue(all(row["matches_expected"] and row["inputs_unchanged"] for row in expected.values()))
        with tempfile.TemporaryDirectory(prefix="rf_event_original_witness_") as temporary:
            root = Path(temporary)
            for item in capture["inputs"]:
                data = bytes.fromhex(item["raw_hex"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                path = root / Path(item["path"]).name
                path.write_bytes(data)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            old_source = {int(key): value for key, value in expected["canonical_valid"]["value"].items()}
            operations = {
                "ion11_valid_offset": lambda: source.read_ion11_source_states(root / "source.ion", 7.0),
                "ion11_bom": lambda: source.read_ion11_source_states(root / "source_bom.ion", 7.0),
                "canonical_valid": lambda: event_table.read_canonical_rf_source_expectations(root / "source.csv"),
                "canonical_explicit_mass": lambda: event_table.read_canonical_rf_source_expectations(root / "fallback.csv", 28.0),
                "canonical_missing_file": lambda: event_table.read_canonical_rf_source_expectations(root / "absent.csv"),
            }
            for name in ("ion_bad_count", "ion_bad_mass", "ion_bad_energy", "ion_bad_number"):
                operations[name] = lambda name=name: source.read_ion11_source_states(root / (name + ".ion"))
            for name in ("canonical_duplicate", "canonical_missing_mass", "canonical_bad_mass"):
                operations[name] = lambda name=name: event_table.read_canonical_rf_source_expectations(root / (name + ".csv"))
            operations["event_valid"] = lambda: event_table.validate_rf_event_table(root / "state_valid.csv", old_source, 1.1e6, 0.)
            operations["event_valid_explicit_columns_enums"] = lambda: event_table.validate_rf_event_table(
                root / "state_valid.csv", old_source, 1.1e6, 0., columns=event_table.PARTICLE_STATE_COLUMNS, enums=event_table.ENUMS)
            for name, planes in (("event_valid_planes", (9, 12)), ("event_bad_rod_plane", (10, 12)), ("event_bad_handoff_plane", (9, 13))):
                operations[name] = lambda planes=planes: event_table.validate_rf_event_table(root / "state_planes.csv", old_source, 1.1e6, 0., *planes)
            for name in ("duplicate", "missing_terminal", "unknown_id", "invalid_status", "nonfinite", "bad_phase", "negative_energy", "source_drift", "bad_header"):
                operations["event_" + name] = lambda name=name: event_table.validate_rf_event_table(root / ("state_" + name + ".csv"), old_source, 1.1e6, 0.)
            self.assertEqual(set(operations), {name for name in expected if not name.startswith("cli_")})
            for name, call in operations.items():
                record = expected[name]
                with self.subTest(case=name):
                    if record["expected"] == "success":
                        self.assertEqual(json.loads(json.dumps(call())), record["value"])
                    else:
                        with self.assertRaises(Exception) as caught:
                            call()
                        error = caught.exception
                        self.assertEqual(type(error).__module__ + "." + type(error).__qualname__, record["exception_type"])
                        if name == "canonical_missing_file":
                            self.assertEqual(error.errno, errno.ENOENT)
                            self.assertEqual(Path(error.filename), root / "absent.csv")
                        else:
                            self.assertEqual(str(error), record["exception_message"])
            for label, state, particles, format_name, extra in (
                ("canonical", "state_valid.csv", "source.csv", "canonical", []),
                ("ion11", "state_ion11.csv", "source.ion", "ion11", ["--axial-offset-mm", "7"]),
                ("bad_header", "state_bad_header.csv", "source.csv", "canonical", []),
            ):
                old = [row for row in expected.values() if row["case"].startswith("cli_" + label + "_")]
                self.assertEqual(len(old), 2)
                command = [sys.executable, "-B", "-X", "utf8", "-m", "msplatform.workflows.rf_event_table_validation",
                           "--state", str(root / state), "--particles", str(root / particles), "--source-format", format_name,
                           "--frequency-hz", "1100000", "--phase-rad", "0", "--solver", "fixture", *extra]
                result = subprocess.run(command, cwd=Path(__file__).resolve().parents[4], capture_output=True, timeout=30, check=False)
                for record in old:
                    self.assertEqual(result.returncode, record["returncode"])
                    self.assertEqual(result.stdout.hex(), record["stdout_hex"])
                    # The migrated module has a new traceback location; preserve the final error exactly.
                    last = result.stderr.decode("utf-8").splitlines()[-1] if result.stderr else ""
                    self.assertEqual(last, record["stderr_last_line"])
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_canonical_nonfinite_expected_source_values_are_rejected(self):
        capture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw = {Path(item["path"]).name: bytes.fromhex(item["raw_hex"]) for item in capture["inputs"]}
        with tempfile.TemporaryDirectory(prefix="rf_nonfinite_source_") as temporary:
            root = Path(temporary)
            state = root / "state.csv"
            state.write_bytes(raw["state_valid.csv"])
            rows = list(csv.DictReader(raw["source.csv"].decode("utf-8-sig").splitlines()))
            for field, expected_field in (("x_mm", "transverse_x_mm"), ("birth_time_s", "time_us"),
                                          ("vx_m_s", "velocity_x_m_s"), ("mass_amu", "kinetic_energy_eV")):
                with self.subTest(field=field):
                    row = dict(rows[0])
                    row[field] = "nan"
                    source_path = root / (field + ".csv")
                    with source_path.open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(row), lineterminator="\n")
                        writer.writeheader()
                        writer.writerow(row)
                    sources = event_table.read_canonical_rf_source_expectations(source_path)
                    with self.assertRaisesRegex(AssertionError, "source " + expected_field):
                        event_table.validate_rf_event_table(state, sources, 1.1e6, 0.)
                    if field == "x_mm":
                        command = [sys.executable, "-B", "-X", "utf8", "-m", "msplatform.workflows.rf_event_table_validation",
                                   "--state", str(state), "--particles", str(source_path), "--source-format", "canonical",
                                   "--frequency-hz", "1100000", "--phase-rad", "0", "--solver", "fixture"]
                        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[4],
                                                capture_output=True, text=True, encoding="utf-8", timeout=30)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("particle 7 source transverse_x_mm", result.stderr)
                        self.assertNotIn('"source_identity": "PASS"', result.stdout)

    def test_cli_help_keeps_original_description(self):
        result = subprocess.run([sys.executable, "-B", "-m", "msplatform.workflows.rf_event_table_validation", "--help"],
                                cwd=Path(__file__).resolve().parents[4], capture_output=True,
                                text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RF event-table protocol, distinct from neutral transfer-state snapshots.", result.stdout)

    def test_actual_cross_solver_contract_branch_uses_frozen_sources(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell unavailable for frozen RF contract execution")
        repo = Path(__file__).resolve().parents[4]
        runner = repo / "projects/rf_multipole_ion_optics/workflows/cross_solver/compare_cross_solver.ps1"
        content = runner.read_text(encoding="utf-8")
        start = content.index("    foreach($entry in @([pscustomobject]@{Solver='COMSOL';State=")
        end = content.index("    $base+=", start)
        origin_check = """
foreach($name in @('msplatform.workflows.rf_event_table_validation','msplatform.components.rf_multipole.event_table','msplatform.backends.simion.rf_ion11_source')){
 $row=@($contractExecution.frozen_modules|Where-Object name -eq $name)
 if($row.Count-ne1-or-not([IO.Path]::GetFullPath([string]$row[0].origin).StartsWith([IO.Path]::GetFullPath([string]$frozenPackage.code_root)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase))){throw 'Frozen origin differs: '+$name}
}
"""
        branch = base64.b64encode((content[start:end] + origin_check).encode("utf-8")).decode("ascii")
        capture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        with tempfile.TemporaryDirectory(prefix="rf_cross_contract_frozen_") as directory:
            root = Path(directory)
            for item in capture["inputs"]:
                (root / Path(item["path"]).name).write_bytes(bytes.fromhex(item["raw_hex"]))
            for name, state in (("comsol", "state_ion11.csv"), ("simion", "state_valid.csv")):
                target = root / name / "results"
                target.mkdir(parents=True)
                shutil.copyfile(root / state, target / "particle_state.csv")
            # This real branch uses its original zero axial offset. The captured
            # ION11 fixture used +7 mm, so express that same source at zero here.
            comsol_state = root / "comsol/results/particle_state.csv"
            with comsol_state.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                columns = reader.fieldnames
                rows = list(reader)
            for row in rows:
                row["axial_z_mm"] = str(float(row["axial_z_mm"]) - 7.)
            with comsol_state.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            helper = repo / "projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1"
            execution = repo / "src/msplatform/execution/resources/frozen_python_package.ps1"
            command = f"""$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$repoRoot={quote(repo)};$projectRoot=Join-Path $repoRoot 'projects/rf_multipole_ion_optics';$python={quote(sys.executable)}
. {quote(helper)} -ExecutionResourcePath {quote(execution)}
$frozenPackage=New-FrozenPythonPackage -SourceRoot $repoRoot -CodeRoot {quote(root / 'code')} -Python $python -PythonModules @('src/msplatform/workflows/rf_transport_comparison.py')
. (Get-FrozenPythonPackageFile -Package $frozenPackage -RelativePath 'src/msplatform/execution/resources/frozen_python_package.ps1')
$cr={quote(root / 'comsol')};$sr={quote(root / 'simion')};$FrequencyHz=1100000;$PhaseRad=0
$identity=@{{ion11_path={quote(root / 'source.ion')};canonical10_path={quote(root / 'source.csv')}}}
$actual=[scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{branch}')))
& $actual
foreach($relative in @('src/msplatform/workflows/rf_event_table_validation.py','src/msplatform/components/rf_multipole/event_table.py','src/msplatform/backends/simion/rf_ion11_source.py')){{
 $target=[IO.Path]::GetFullPath((Join-Path {quote(root / 'code')} $relative));$bytes=[IO.File]::ReadAllBytes($target);Remove-Item -LiteralPath $target
 try{{& $actual;throw 'Missing frozen module accepted'}}catch{{
  if($_.Exception.Message-ne'COMSOL particle-state contract failed.'-or$null-eq$_.Exception.InnerException-or-not$_.Exception.InnerException.Message.Contains($target)){{throw}}
 }}finally{{[IO.File]::WriteAllBytes($target,$bytes)}}
}}
Write-Output 'RF_CROSS_FROZEN_CONTRACT=PASS'
"""
            result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("RF_CROSS_FROZEN_CONTRACT=PASS", result.stdout)

    def test_retired_old_modules_have_no_live_alias(self):
        repo = Path(__file__).resolve().parents[4]
        retired = (
            ("common.contracts.particle_state", "common/contracts/particle_state.py"),
            ("projects.rf_multipole_ion_optics.analysis.rf_event_table_validation", "projects/rf_multipole_ion_optics/analysis/rf_event_table_validation.py"),
            ("projects.rf_multipole_ion_optics.simion.ion11_source_adapter", "projects/rf_multipole_ion_optics/simion/ion11_source_adapter.py"),
        )
        for module, relative in retired:
            with self.subTest(module=module):
                self.assertFalse((repo / relative).exists())
                result = subprocess.run([sys.executable, "-B", "-c", "import importlib,sys; importlib.import_module(sys.argv[1])", module],
                                        cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ModuleNotFoundError", result.stderr)
                self.assertIn(module, result.stderr)


if __name__ == "__main__":
    unittest.main()
