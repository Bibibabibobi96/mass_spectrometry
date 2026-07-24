import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import csv_columns
from common.contracts.particle_physics import kinetic_energy_ev
from projects.rf_quadrupole_collision_cooling.analysis import analyze_s3_end_to_end as analyze
from projects.rf_quadrupole_collision_cooling.analysis import build_simion_input_from_canonical as adapter


def canonical_row(particle_id: int) -> dict[str, object]:
    return {
        "particle_id": particle_id, "parent_particle_id": "", "generation": 0,
        "species_id": "ion_100amu_q1", "particle_weight": 1,
        "source_component_id": "s3", "target_component_id": "oatof_analyzer",
        "state_event": "local_accelerator_exit", "frame_id": "oatof_global",
        "clock_epoch_id": "instrument_clock_epoch.v1", "instrument_time_us": 36.75,
        "lineage_age_us": 36.0, "particle_age_us": 36.0,
        "last_component_elapsed_time_us": 7.0, "lineage_birth_time_us": 0.75,
        "particle_birth_time_us": 0.75, "mass_to_charge_Th": 100,
        "mass_amu": 100, "charge_state": 1, "position_x_mm": -47,
        "position_y_mm": 0.2, "position_z_mm": 4.87, "velocity_x_m_s": 4000,
        "velocity_y_m_s": 300, "velocity_z_m_s": 58000,
        "kinetic_energy_eV": kinetic_energy_ev(100, 4000, 300, 58000),
        "phase_reference_id": "rf_drive.v1", "phase_rad": 2.7,
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class S3EndToEndTests(unittest.TestCase):
    def test_runner_freezes_dependencies_and_source_before_execution(self) -> None:
        runner = (
            Path(__file__).parents[1]
            / "cross_solver"
            / "run_s3_end_to_end.ps1"
        ).read_text(encoding="utf-8")
        selection = runner.index("$dependencyConsumer = 's3_end_to_end'")
        snapshot = runner.index("Copy-RfFrozenDependency")
        naming = runner.index(
            "$frozenArtifactNaming,'run',$RunId"
        )
        source_containment = runner.index(
            "Resolve-RfDirectChildDirectory -ParentRoot $runsRoot"
        )
        manifest_freeze = runner.index(
            "Copy-RfStableFile -SourceRunRoot $source"
        )
        manifest_verify = runner.index(
            "$frozenManifestVerifier,$sourceManifestPath"
        )
        config_copy = runner.index(
            "Copy-RfManifestBoundFile -SourceRunRoot $source"
        )
        adapter = runner.index(
            "$frozenAdapter,'--source',$sourceCanonical"
        )
        program = runner.index(
            "$frozenProgramBuilder,'--formal',$frozenFormalLua"
        )
        simion = runner.index("Start-Process -FilePath $SimionExe")
        diagnostics = runner.index(
            "$frozenSolverDiagnostics,'analyze-simion-log'"
        )
        analyzer = runner.index(
            "$frozenAnalyzer,'--source-summary',$sourceSummary"
        )
        self.assertLess(selection, snapshot)
        self.assertLess(snapshot, naming)
        self.assertLess(naming, source_containment)
        self.assertLess(source_containment, manifest_freeze)
        self.assertLess(manifest_freeze, manifest_verify)
        self.assertLess(manifest_verify, config_copy)
        self.assertLess(config_copy, adapter)
        self.assertLess(adapter, program)
        self.assertLess(program, simion)
        self.assertLess(simion, diagnostics)
        self.assertLess(diagnostics, analyzer)

        for dependency_id in (
            "rf_dependency_contract_snapshot",
            "rf_s3_simion_input_adapter",
            "rf_s3_end_to_end_analyzer",
            "rf_oatof_handoff_builder",
            "oatof_resolved_geometry",
            "oatof_handoff_pulse_program_builder",
            "oatof_formal_lua",
            "oatof_handoff_pulse_extension_lua",
            "oatof_solver_diagnostics",
            "common_verify_run_manifest",
            "common_write_run_manifest",
        ):
            self.assertIn(f"'{dependency_id}'", runner)
        self.assertIn("$dependencySnapshotPaths = @{}", runner)
        self.assertIn("$dependencyCompatibilityPaths = @{}", runner)
        self.assertIn("$manifestToolRoot = $snapshotRoot", runner)
        self.assertIn("$snapshotReady = $false", runner)
        self.assertIn("if ($snapshotReady)", runner)
        self.assertIn("$env:PYTHONPATH = $SnapshotRoot", runner)
        self.assertIn("$env:PYTHONNOUSERSITE = '1'", runner)
        self.assertIn("Push-Location -LiteralPath $SnapshotRoot", runner)
        self.assertIn(
            "--require-mode','rf_to_oatof_s3_shared_clock_pulse_capture_n100'",
            runner,
        )
        self.assertIn("Get-RfManifestOutputRecord", runner)
        self.assertIn("Copy-RfManifestBoundFile", runner)
        self.assertIn(
            "$frozenManifestVerifier,$formalManifestPath",
            runner,
        )
        self.assertIn(
            "Get-S3FormalAssetRecords -ChecksumPath $checksumPath",
            runner,
        )
        self.assertIn(
            "Copy-RfManifestBoundFile `\n      "
            "-SourceRunRoot $formalDir",
            runner,
        )
        self.assertNotIn("Get-ChildItem -LiteralPath $formalDir", runner)
        self.assertNotIn("New-Item -ItemType HardLink", runner)
        self.assertNotIn(
            "Join-Path $repoRoot 'projects\\oa_tof", runner
        )
        self.assertNotIn(
            "Join-Path $repoRoot 'common\\contracts\\verify_run_manifest.py'",
            runner,
        )
        self.assertNotIn("& $package.python $frozen", runner)
        self.assertNotIn("New-RfRunPackage", runner)
        self.assertNotIn(
            "Complete-RfFailedRun -Python", runner
        )
        self.assertNotIn("-FrozenRepoRoot $repoRoot", runner)

    def test_dependency_contract_is_frozen_before_closure_selection(self) -> None:
        runner = (
            Path(__file__).parents[1]
            / "cross_solver"
            / "run_s3_end_to_end.ps1"
        ).read_text(encoding="utf-8")
        stable_copy = runner.index(
            "$dependencyContractIdentity = Copy-RfStableFile"
        )
        frozen_parse = runner.index(
            "Get-Content -LiteralPath $dependencyContract"
        )
        selection = runner.index("$selectedDependencies = @(")
        self_identity = runner.index(
            "if ([string]$dependency.id -eq "
            "'rf_dependency_contract_snapshot')"
        )
        identity_hash = runner.index(
            "$dependencyContractIdentity.sha256", self_identity
        )
        ordinary_copy = runner.index(
            "$identity = Copy-RfFrozenDependency", self_identity
        )
        self.assertLess(stable_copy, frozen_parse)
        self.assertLess(frozen_parse, selection)
        self.assertLess(selection, self_identity)
        self.assertLess(self_identity, identity_hash)
        self.assertLess(identity_hash, ordinary_copy)
        self.assertNotIn(
            "Get-Content -LiteralPath $dependencyContractSource",
            runner,
        )

    def test_snapshot_adapter_imports_nested_handoff_builder_under_poison(self) -> None:
        repository = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "runtime_snapshot"
            relative_files = (
                "projects/rf_quadrupole_collision_cooling/analysis/"
                "build_simion_input_from_canonical.py",
                "projects/rf_quadrupole_collision_cooling/analysis/"
                "build_oatof_handoff.py",
                "projects/rf_quadrupole_collision_cooling/analysis/"
                "migrate_legacy_component_particle_state.py",
                "projects/oa_tof/analysis/rf_handoff_adapter.py",
                "common/contracts/component_particle_state.py",
                "common/contracts/particle_physics.py",
                "common/contracts/rigid_transform.py",
                "common/contracts/schemas/component_particle_state.schema.json",
            )
            for relative in relative_files:
                source = repository / relative
                destination = snapshot / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

            poison = root / "poison"
            poison.mkdir()
            (poison / "build_oatof_handoff.py").write_text(
                "raise RuntimeError('LIVE_PROVIDER_POISON')\n",
                encoding="utf-8",
            )
            source = root / "source.csv"
            write_csv(source, csv_columns(), [canonical_row(1)])
            adapter_path = (
                snapshot
                / "projects/rf_quadrupole_collision_cooling/analysis/"
                "build_simion_input_from_canonical.py"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = (
                str(poison) + os.pathsep + str(snapshot)
            )
            environment["PYTHONNOUSERSITE"] = "1"
            subprocess.run(
                [
                    sys.executable,
                    str(adapter_path),
                    "--source",
                    str(source),
                    "--canonical-output",
                    str(root / "canonical.csv"),
                    "--ion-output",
                    str(root / "input.ion"),
                    "--row-map-output",
                    str(root / "row_map.csv"),
                    "--metadata-output",
                    str(root / "metadata.json"),
                ],
                check=True,
                cwd=snapshot,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            analysis_dir = adapter_path.parent
            provenance = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib,sys;"
                        f"sys.path.insert(0,{str(analysis_dir)!r});"
                        "import build_simion_input_from_canonical;"
                        "import build_oatof_handoff;"
                        "print(pathlib.Path(build_oatof_handoff.__file__).resolve())"
                    ),
                ],
                check=True,
                cwd=snapshot,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                Path(provenance.stdout.strip()).resolve(),
                (analysis_dir / "build_oatof_handoff.py").resolve(),
            )
            self.assertTrue((root / "metadata.json").is_file())

    def test_early_snapshot_failure_cannot_fall_back_to_live_manifest(self) -> None:
        runner = (
            Path(__file__).parents[1]
            / "cross_solver"
            / "run_s3_end_to_end.ps1"
        ).read_text(encoding="utf-8")
        not_ready = runner.index("$snapshotReady = $false")
        copy = runner.index("Copy-RfFrozenDependency")
        ready = runner.index("$snapshotReady = $true")
        catch = runner.index("} catch {")
        guard = runner.index("if ($snapshotReady)", catch)
        no_manifest = runner.index("manifest_written = $false", guard)
        self.assertLess(not_ready, copy)
        self.assertLess(copy, ready)
        self.assertLess(ready, catch)
        self.assertLess(catch, guard)
        self.assertLess(guard, no_manifest)
        self.assertNotIn("-FrozenRepoRoot $repoRoot", runner)
        self.assertNotIn("Complete-RfFailedRun -Python", runner)

    def test_canonical_adapter_preserves_state_and_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "source.csv"
            write_csv(source, csv_columns(), [canonical_row(8), canonical_row(2)])
            canonical = root / "canonical.csv"; ion = root / "input.ion"
            mapping = root / "map.csv"; metadata = root / "metadata.json"
            result = adapter.build(source, canonical, ion, mapping, metadata)
            self.assertEqual(result["particles"], 2)
            self.assertFalse(result["transform"]["position_projection_applied"])
            self.assertTrue(ion.read_text(encoding="utf-8").splitlines()[0].startswith(
                "36.75,100,1,-47,0.2,4.87,"))
            with mapping.open(encoding="utf-8") as handle:
                self.assertEqual(list(csv.DictReader(handle))[0]["particle_id"], "2")

    def test_s3_audit_requires_identity_clock_and_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); canonical = root / "canonical.csv"
            write_csv(canonical, csv_columns(), [canonical_row(2)])
            ion = root / "input.ion"; mapping = root / "map.csv"; metadata = root / "meta.json"
            adapter.build(canonical, root / "copy.csv", ion, mapping, metadata)
            summary = root / "summary.json"
            summary.write_text(json.dumps({"status": "success", "source_particles": 100,
                                           "oatof_entry_crossings": 61,
                                           "active_at_pulse": 31}), encoding="utf-8")
            downstream = root / "downstream.csv"
            fields = ["Ion", "MassAmu", "ChargeState", "X0Mm", "Y0Mm", "Z0Mm",
                      "TofUs", "InstrumentTimeUs", "XMm", "YMm", "Hit"]
            write_csv(downstream, fields, [{"Ion": 1, "MassAmu": 100,
                                            "ChargeState": 1, "X0Mm": -47, "Y0Mm": 0.2,
                                            "Z0Mm": 4.87, "TofUs": 10,
                                            "InstrumentTimeUs": 46.75, "XMm": 0,
                                            "YMm": 0, "Hit": "True"}])
            stdout = root / "stdout.log"
            stdout.write_text(
                "handoff_pulse_contract mode=1 time_us=36.112 width_us=1\n", encoding="utf-8")
            result = analyze.analyze(
                summary, canonical, ion, mapping, downstream, stdout, 36.112, 1.0)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["census"]["detector_hit"], 1)
            self.assertFalse(result["s3_stage_passed"])


if __name__ == "__main__":
    unittest.main()
