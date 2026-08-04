import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import csv_columns
from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    analyze_analyzer_transport as analyze,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    compare_simion_interface_transport as interface_compare,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    materialize_simion_grid2_state as grid2_state,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    compare_grid2_solver_propagation as propagation,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    write_oatof_simion_input as adapter,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    validate_oatof_formal_analyzer_release as formal_release,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


def canonical_row(particle_id: int) -> dict[str, object]:
    return {
        "particle_id": particle_id, "parent_particle_id": "", "generation": 0,
        "species_id": "ion_100amu_q1", "particle_weight": 1,
        "source_component_id": "pulse_capture",
        "target_component_id": "oatof_analyzer",
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


class AnalyzerTransportTests(unittest.TestCase):
    def test_compares_grid2_solver_difference_and_common_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "comsol.csv"
            simion = root / "simion.csv"
            write_csv(comsol, csv_columns(), [canonical_row(7)])
            write_csv(simion, grid2_state.TRACE_COLUMNS, [{
                "particle_id": 7, "instrument_time_us": 36.8,
                "x": -46.5, "y": 0.2, "z": 4.87,
                "vx": 4100, "vy": 300, "vz": 58000,
                "ax": 4, "ay": 0.3, "energy": 1700,
            }])
            row_map = root / "row_map.csv"
            write_csv(row_map, ["solver_row_index", "particle_id"], [{
                "solver_row_index": 1, "particle_id": 7,
            }])
            fields = ["Ion", "Hit", "InstrumentTimeUs", "XMm", "YMm", "RadiusMm", "TofUs"]
            simion_down = root / "simion_down.csv"
            comsol_down = root / "comsol_down.csv"
            write_csv(simion_down, fields, [{
                "Ion": 1, "Hit": "True", "InstrumentTimeUs": 70.0,
                "XMm": 48, "YMm": 1, "RadiusMm": 1, "TofUs": 30,
            }])
            write_csv(comsol_down, fields, [{
                "Ion": 1, "Hit": "True", "InstrumentTimeUs": 70.2,
                "XMm": 50, "YMm": 2, "RadiusMm": 2, "TofUs": 30.2,
            }])
            middle = root / "middle.json"
            middle.write_text(json.dumps({"simion_minus_comsol": {"mean_energy_eV": 1}}))
            result = propagation.compare(
                label="fixture", handoff_count=2,
                simion_grid2_path=simion, comsol_grid2_path=comsol,
                simion_downstream_path=simion_down, simion_row_map_path=row_map,
                comsol_downstream_path=comsol_down, comsol_row_map_path=row_map,
                middle_comparison_path=middle,
            )
            self.assertEqual(result["detector_identity"]["common_hit_particles"], 1)
            self.assertAlmostEqual(
                result["detector_paired_difference"]["position_vector_rms_difference_mm"],
                5 ** 0.5,
            )

    def test_materializes_simion_grid2_trace_as_canonical_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.csv"
            trace = root / "trace.csv"
            output = root / "grid2.csv"
            write_csv(template, csv_columns(), [canonical_row(7)])
            write_csv(trace, grid2_state.TRACE_COLUMNS, [{
                "particle_id": 7, "instrument_time_us": 37.0,
                "x": -45.0, "y": 0.1, "z": -0.129,
                "vx": 4200, "vy": 200, "vz": 60000,
                "ax": 4.0, "ay": 0.2, "energy": 1.0,
            }])
            self.assertEqual(grid2_state.materialize(template, trace, output), 1)
            with output.open(encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["state_event"], "local_accelerator_exit")
            self.assertEqual(row["position_x_mm"], "-45.0")
            self.assertEqual(row["velocity_z_m_s"], "60000")
            self.assertAlmostEqual(float(row["particle_age_us"]), 36.25)

    def test_compares_real_port_local_exit_by_particle_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            comsol = root / "comsol.csv"
            row = canonical_row(7)
            row["state_event"] = "oatof_entry"
            write_csv(source, csv_columns(), [row])
            exit_row = dict(row)
            exit_row["state_event"] = "local_accelerator_exit"
            write_csv(comsol, csv_columns(), [exit_row])
            row_map = root / "row_map.csv"
            write_csv(row_map, ["solver_row_index", "particle_id"], [
                {"solver_row_index": 1, "particle_id": 7}
            ])
            log = root / "simion.log"
            log.write_text(
                "TRACE: local_accelerator_exit ion=1 instrument_time_us=36.75 "
                "x_mm=-47 y_mm=0.2 z_mm=4.87 vx_mm_per_us=4 "
                "vy_mm_per_us=0.3 vz_mm_per_us=58\n",
                encoding="utf-8",
            )
            result, rows = interface_compare.compare(log, row_map, source, comsol)
            self.assertEqual(result["paired_particle_count"], 1)
            self.assertEqual(result["simion"]["particles"], 1)
            self.assertEqual(rows[0]["particle_id"], 7)

    def _formal_release_fixture(self, root: Path) -> tuple[Path, ...]:
        formal = root / "formal" / "simion"
        formal.mkdir(parents=True)
        iob = formal / "oatof_ideal_grounded.iob"
        con = formal / "oatof_ideal_grounded.con"
        program = formal / "oatof_ideal_grounded.lua"
        fly2 = formal / "oatof_ideal_grounded.fly2"
        ion = formal / "oatof_comsol_524amu_gaussian_N1000.ion"
        checksum = formal / "SHA256SUMS.csv"
        iob.write_bytes(b"iob")
        con.write_text("con\n", encoding="utf-8")
        program.write_text("formal program\n", encoding="utf-8")
        fly2.write_text("fly2\n", encoding="utf-8")
        ion.write_text("ion\n", encoding="utf-8")
        checksum.write_text("file,bytes,sha256\n", encoding="utf-8")

        def identity(path: Path, relative: str) -> dict[str, object]:
            return {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            }

        def stable_identity(path: Path, relative: str) -> dict[str, object]:
            record = identity(path, relative)
            record["relative_path"] = record.pop("path")
            return record

        delivery_path = formal / "run_manifest.json"
        release_id = "20260720_191743__sim__cross__coupled-baseline-validation__n1000"
        delivery = {
            "schema_version": 1,
            "role": "oa_tof_simion_formal_delivery_manifest",
            "status": "success",
            "release_id": release_id,
            "project": "single_reflection_oa_tof_mass_analyzer",
            "assets": {
                "bundle_001": identity(iob, iob.name),
                "bundle_002": identity(con, con.name),
                "bundle_003": identity(program, program.name),
                "bundle_004": identity(fly2, fly2.name),
                "bundle_005": identity(ion, ion.name),
            },
        }
        delivery_path.write_text(json.dumps(delivery), encoding="utf-8")

        validation_path = root / "formal_validation.json"
        baseline_path = root / "baseline.json"
        baseline_path.write_text('{"coordinate_convention":{"frame_id":"oatof_global"}}', encoding="utf-8")
        baseline_sha256 = identity(baseline_path, "")["sha256"]
        resolved_path = root / "resolved_geometry.json"
        resolved_path.write_text(
            json.dumps(
                {
                    "inputs": {"baseline_sha256": baseline_sha256},
                    "coordinate_convention": {"frame_id": "oatof_global"},
                }
            ),
            encoding="utf-8",
        )
        validation = {
            "schema_version": 5,
            "status": "formal_cross_solver_validation",
            "run_id": release_id,
            "physical_contract": "baseline.json",
            "physical_contract_sha256": baseline_sha256,
            "simion": {
                "iob_artifact_relative_path": "formal/simion/oatof_ideal_grounded.iob",
                "iob_sha256": identity(iob, "")["sha256"],
                "delivery_manifest_artifact_relative_path": "formal/simion/run_manifest.json",
                "delivery_manifest_sha256": identity(delivery_path, "")["sha256"],
            },
            "promotion_evidence": {
                "validation_run_manifest_sha256": "A" * 64,
            },
        }
        validation_path.write_text(json.dumps(validation), encoding="utf-8")

        asset_path = root / "formal" / "asset_manifest.json"
        asset = {
            "schema_version": 1,
            "role": "formal_asset_manifest",
            "project": "single_reflection_oa_tof_mass_analyzer",
            "release_id": release_id,
            "source_run": {
                "run_id": release_id,
                "run_manifest": {"sha256": "A" * 64},
            },
            "validation_contract": identity(
                validation_path, "projects/single_reflection_oa_tof_mass_analyzer/config/formal_validation.json"
            ),
            "assets": {
                "simion_delivery_manifest": identity(
                    delivery_path, "simion/run_manifest.json"
                ),
                "simion_iob": identity(iob, f"simion/{iob.name}"),
                "simion_con": identity(con, f"simion/{con.name}"),
                "simion_program": identity(program, f"simion/{program.name}"),
                "simion_fly2": identity(fly2, f"simion/{fly2.name}"),
                "shared_particle_table": identity(ion, f"simion/{ion.name}"),
                "simion_sha256_manifest": identity(
                    checksum, "simion/SHA256SUMS.csv"
                ),
            },
        }
        asset_path.write_text(json.dumps(asset), encoding="utf-8")
        stable_path = root / "simion_stable_entry.json"
        stable = {
            "schema_version": 2,
            "role": (
                "Stable runtime requirements and manifest bindings for the "
                "current formal SIMION delivery."
            ),
            "artifact_workspace_relative": "formal",
            "entries": [
                {
                    "id": "formal_vnext_fixture",
                    "manifests": {
                        "formal_asset_manifest": stable_identity(
                            asset_path, "asset_manifest.json"
                        ),
                        "simion_delivery_manifest": stable_identity(
                            delivery_path, "simion/run_manifest.json"
                        ),
                    },
                    "required_assets": {
                        "iob": "simion_iob",
                        "con": "simion_con",
                        "program": "simion_program",
                        "fly2": "simion_fly2",
                        "ion": "shared_particle_table",
                    },
                    "gui_requirements": {
                        "expected_instances": 4,
                        "trajectory_quality": 8,
                        "program_enabled": True,
                        "data_recording_enabled": True,
                    },
                }
            ],
        }
        stable_path.write_text(json.dumps(stable), encoding="utf-8")
        return (
            asset_path,
            validation_path,
            delivery_path,
            formal,
            stable_path,
            baseline_path,
            resolved_path,
            program,
        )

    def test_formal_release_uses_current_asset_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self._formal_release_fixture(Path(temp))
            result = formal_release.validate(*paths)
            self.assertEqual(result["status"], "PASS")

    def test_formal_release_accepts_identical_renamed_frozen_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self._formal_release_fixture(Path(temp))
            frozen_delivery = Path(temp) / "oatof_formal_release_manifest.json"
            shutil.copy2(paths[2], frozen_delivery)
            result = formal_release.validate(
                paths[0], paths[1], frozen_delivery, *paths[3:]
            )
            self.assertEqual(result["status"], "PASS")

    def test_formal_release_rejects_consumed_iob_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self._formal_release_fixture(Path(temp))
            (paths[3] / "oatof_ideal_grounded.iob").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "record identity differs"):
                formal_release.validate(*paths)

    def test_formal_release_rejects_frozen_lua_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self._formal_release_fixture(Path(temp))
            frozen_lua = Path(temp) / "frozen.lua"
            frozen_lua.write_text("drifted program\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Formal Lua differs"):
                formal_release.validate(*paths[:-1], frozen_lua)

    def test_runner_freezes_dependencies_and_source_before_execution(self) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "cross_solver"
            / "run_analyzer_transport.ps1"
        ).read_text(encoding="utf-8")
        selection = runner.index("$dependencyConsumer = 'analyzer_transport'")
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
            "$frozenAdapter,'--source',$adapterSourceCanonical"
        )
        program = runner.index(
            "$frozenProgramBuilder,'--formal',$frozenFormalLua"
        )
        simion = runner.index(
            "$processResult = Invoke-ResourceBudgetedProcess `\n"
            "      -ResolvedBudgetPath $budgetBinding.stage_budget"
        )
        diagnostics = runner.index(
            "$frozenSolverDiagnostics,'analyze-simion-log'"
        )
        analyzer = runner.index(
            "$frozenAnalyzer,'--source-summary',$analysisSourceSummary"
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
        self.assertIn("-FilePath $SimionExe", runner[simion:])
        self.assertIn(
            "$simionDefaultParticleCount = [Math]::Max(100, $analyzerParticleCount)",
            runner,
        )
        self.assertIn(
            "'--default-num-particles',([string]$simionDefaultParticleCount)",
            runner,
        )
        self.assertIn(
            "'simion_local_accelerator_exit'", runner
        )
        self.assertIn(
            "'rf_to_oatof_simion_interface_transport'", runner
        )
        self.assertIn(
            "'results\\simion_local_accelerator_exit.csv'", runner
        )
        self.assertIn(
            "if ($interfaceDiagnostic) {\n      $env:OATOF_ACCELERATOR_PA_OVERRIDE",
            runner,
        )

        for dependency_id in (
            "rf_analyzer_transport_simion_input_adapter",
            "rf_analyzer_transport_analyzer",
            "rf_oatof_formal_release_validator",
            "oatof_rf_handoff_adapter",
            "oatof_resolved_geometry",
            "oatof_formal_validation",
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
        self.assertIn("'rf_to_oatof_pulse_capture'", runner)
        self.assertIn("'rf_to_oatof_pre_pulse_interface_transport'", runner)
        self.assertIn("Get-RfManifestOutputRecord", runner)
        self.assertIn("Copy-RfManifestBoundFile", runner)
        self.assertIn("$frozenFormalReleaseValidator", runner)
        self.assertIn("--asset-manifest',$formalAssetManifestPath", runner)
        self.assertIn("--validation-contract',$frozenFormalValidation", runner)
        self.assertNotIn("$frozenManifestVerifier,$formalManifestPath", runner)
        self.assertIn(
            "Get-AnalyzerTransportFormalAssetRecords -ChecksumPath $checksumPath",
            runner,
        )
        self.assertIn(
            "Get-AnalyzerTransportReleaseAssetRecord",
            runner,
        )
        self.assertNotIn(
            "Get-RfManifestOutputRecord -Manifest $formalManifest",
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
            "Join-Path $repoRoot 'projects\\single_reflection_oa_tof_mass_analyzer",
            runner,
        )
        self.assertNotIn(
            "Join-Path $repoRoot 'common\\contracts\\verify_run_manifest.py'",
            runner,
        )
        self.assertNotIn("& $package.python $frozen", runner)
        self.assertEqual(runner.count("New-RfRunPackage"), 1)
        self.assertIn("-RetentionContractEnabled -RetentionClass compact", runner)
        self.assertNotIn(
            "Complete-RfFailedRun -Python", runner
        )
        self.assertNotIn("-FrozenRepoRoot $repoRoot", runner)

    def test_resolved_inventory_freezes_single_runtime_contract(self) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "cross_solver"
            / "run_analyzer_transport.ps1"
        ).read_text(encoding="utf-8")
        runtime = (
            INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
        ).read_text(encoding="utf-8")
        publication = runner.index(
            "$dependencyPublication = Publish-RfOatofDependencyInventory"
        )
        frozen_parse = runner.index(
            "$dependencyDocument = Get-Content -LiteralPath $dependencyContract"
        )
        selection = runner.index("$selectedDependencies = @(")
        ordinary_copy = runner.index("$identity = Copy-RfFrozenDependency")
        self.assertLess(publication, frozen_parse)
        self.assertLess(frozen_parse, selection)
        self.assertLess(selection, ordinary_copy)
        self.assertIn("$contractIdentity = Copy-RfStableFile", runtime)
        self.assertIn("resolved code inventory must contain exactly 53", runtime)
        self.assertIn("path = $contractRelative", runtime)
        self.assertNotIn("base = [ordered]@{", runtime)
        self.assertNotIn("overlay = [ordered]@{", runtime)
        self.assertNotIn("rf_dependency_contract_snapshot", runner)
        self.assertNotIn("rf_dependency_contract_snapshot", runtime)

    def test_early_snapshot_failure_cannot_fall_back_to_live_manifest(self) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "cross_solver"
            / "run_analyzer_transport.ps1"
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
            result = adapter.write_oatof_simion_input(
                source, canonical, ion, mapping, metadata
            )
            self.assertEqual(result["particles"], 2)
            self.assertEqual(result["role"], "oatof_simion_input_bundle")
            self.assertEqual(result["coordinate_frame_id"], "oatof_global")
            with ion.open(encoding="utf-8", newline="") as handle:
                first_ion = next(csv.reader(handle))
            self.assertEqual(
                [float(value) for value in first_ion[:6]],
                [36.75, 100.0, 1.0, -47.0, 0.2, 4.87],
            )
            with mapping.open(encoding="utf-8") as handle:
                self.assertEqual(list(csv.DictReader(handle))[0]["particle_id"], "8")

    def test_analyzer_audit_requires_identity_clock_and_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); canonical = root / "canonical.csv"
            write_csv(canonical, csv_columns(), [canonical_row(2)])
            ion = root / "input.ion"; mapping = root / "map.csv"; metadata = root / "meta.json"
            adapter.write_oatof_simion_input(
                canonical, root / "copy.csv", ion, mapping, metadata
            )
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
            self.assertFalse(result["analyzer_transport_stage_passed"])

    def test_analyzer_audit_keeps_blank_non_crossing_rows_in_census(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); canonical = root / "canonical.csv"
            write_csv(
                canonical, csv_columns(), [canonical_row(2), canonical_row(8)]
            )
            ion = root / "input.ion"; mapping = root / "map.csv"
            adapter.write_oatof_simion_input(
                canonical, root / "copy.csv", ion, mapping, root / "meta.json"
            )
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "source_particles": 100,
                        "oatof_entry_crossings": 61,
                        "active_at_pulse": 31,
                    }
                ),
                encoding="utf-8",
            )
            fields = [
                "Ion", "MassAmu", "ChargeState", "X0Mm", "Y0Mm", "Z0Mm",
                "TofUs", "InstrumentTimeUs", "XMm", "YMm", "Hit",
            ]
            downstream = root / "downstream.csv"
            write_csv(
                downstream,
                fields,
                [
                    {
                        "Ion": 1, "MassAmu": 100, "ChargeState": 1,
                        "X0Mm": -47, "Y0Mm": 0.2, "Z0Mm": 4.87,
                        "TofUs": 10, "InstrumentTimeUs": 46.75,
                        "XMm": 0, "YMm": 0, "Hit": "True",
                    },
                    {
                        "Ion": 2, "MassAmu": 100, "ChargeState": 1,
                        "X0Mm": -47, "Y0Mm": 0.2, "Z0Mm": 4.87,
                        "TofUs": "", "InstrumentTimeUs": "",
                        "XMm": "", "YMm": "", "Hit": "False",
                    },
                ],
            )
            stdout = root / "stdout.log"
            stdout.write_text(
                "handoff_pulse_contract mode=1 time_us=36.112 width_us=1\n",
                encoding="utf-8",
            )
            result = analyze.analyze(
                summary, canonical, ion, mapping, downstream, stdout, 36.112, 1.0
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["census"]["local_accelerator_exit"], 2)
            self.assertEqual(result["census"]["detector_crossing"], 1)
            self.assertEqual(result["census"]["detector_hit"], 1)

    def test_analyzer_audit_rejects_incomplete_or_invalid_crossing_state(self) -> None:
        base = {
            "TofUs": "", "InstrumentTimeUs": "", "XMm": "", "YMm": "",
            "Hit": "False",
        }
        self.assertFalse(analyze._is_detector_crossing(base))
        self.assertFalse(
            analyze._is_detector_crossing(
                {**base, "TofUs": "NaN", "InstrumentTimeUs": "NaN",
                 "XMm": "NaN", "YMm": "NaN"}
            )
        )
        for changed in (
            {"Hit": "True"},
            {"TofUs": "1"},
            {"TofUs": "Inf", "InstrumentTimeUs": "Inf",
             "XMm": "Inf", "YMm": "Inf"},
            {"Hit": "unknown"},
        ):
            with self.assertRaises(ValueError):
                analyze._is_detector_crossing({**base, **changed})


if __name__ == "__main__":
    unittest.main()
