import csv
import hashlib
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.multipole.particle_source_preflight import COLUMNS
from common.multipole.simion_particle_source import render_canonical_source


RUNNER = Path(__file__).resolve().parent / "run_simion_finite_3d_transport.ps1"
REPO_ROOT = Path(__file__).parents[2]


class SimionRunnerContractTests(unittest.TestCase):
    def test_runner_freezes_resolved_campaign_selection_before_solver_launch(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$ResolvedRuntimeProfilePath=''", source)
        self.assertIn(
            "Campaign transport requires the resolved runtime-profile snapshot.",
            source,
        )
        self.assertIn("resolved_runtime_profile.json", source)
        self.assertIn("campaign_sha256=[string]$campaignSelection.sha256", source)
        self.assertLess(
            source.index("Campaign authority changed before it was frozen."),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_runner_freezes_terminal_authority_and_consumes_resolved_snapshot(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "downstream_terminal_profiles.json",
            "common.multipole.downstream_terminal",
            "Downstream-terminal registry changed before it was frozen.",
            "Frozen resolved design differs from the resolved runtime snapshot.",
            "Resolved runtime-profile design identity is invalid.",
            "$design.axial_dc",
            "$design.downstream_terminal.surface_plane_z_mm",
            "handoff_aperture={shape=",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("Resolved runtime-profile design identity is invalid."),
            source.index("common.multipole.simion_geometry"),
        )

    def test_default_run_ids_delimit_the_design_profile_variable(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (RUNNER.parent / name).read_text(encoding="utf-8-sig")
            self.assertIn("$($DesignProfileId.Replace('_','-'))__resolved-l3", source)
            self.assertNotIn("$DesignProfileId__resolved-l3", source)

    def test_segmented_voltage_binding_uses_resolved_dynamic_electrodes(self) -> None:
        lua = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("adj_elect[electrode_id] = voltage", lua)
        self.assertIn("electrode_id <= 1000", lua)
        self.assertIn("$design.segmentation.segmented_rod_array", runner)
        self.assertIn("zero_axial_drop_rf_on", runner)
        self.assertNotIn("--segmented-rods", runner)

    def test_build_and_fly_are_serialized_without_nested_reentry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        watchdog = (RUNNER.parent / "resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Invoke-ResourceBudgetedProcess", source)
        self.assertIn("Start-Process @startArguments", watchdog)
        self.assertIn("$process.WaitForExit", watchdog)
        self.assertIn("Start-Sleep -Milliseconds 500", source)
        self.assertIn("'--nogui','--noprompt','fly'", source)
        self.assertNotIn("simion_run_fly.lua", source)

    def test_governed_profile_is_the_only_physical_entry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in ("ProjectId", "DesignProfileId", "ParticleSourcePath"):
            self.assertIn(token, source)
        for legacy in (
            "ProjectRoot",
            "ResolvedDesignPath",
            "ParticleMassAmu",
            "Adapter",
            "FieldScreenRunId",
            "AxialAccelerationContractPath",
            "EntranceConnectorLengthMm",
            "ExitConnectorLengthMm",
            "EndplateAcceleration",
        ):
            self.assertNotIn(legacy, source)
        self.assertIn("common.multipole.design_profile", source)
        self.assertIn("common.multipole.compile_design_request", source)
        self.assertIn("common.multipole.particle_source_preflight", source)

    def test_typed_mode_is_forwarded_to_both_solver_compilers(self) -> None:
        for runner_name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (RUNNER.parent / runner_name).read_text(encoding="utf-8")
            self.assertIn("$profile.profile.mode_id", source)
            self.assertIn("$profile.paths.operating_mode_registry", source)
            self.assertIn("--operating-mode-registry", source)
            self.assertIn("--mode-id", source)
            self.assertIn("operating_mode_registry=$modeRegistry", source)
            self.assertIn("operating_mode_id=$modeId", source)

    def test_tool_paths_are_numerical_runtime_parameters(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        template_support = (
            RUNNER.parent / "simion_layout_template_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[string]$SimionExe", source)
        self.assertNotIn("TemplateIob", source)
        self.assertIn(
            "common\\multipole\\simion_layout_template_support.ps1", source
        )
        self.assertIn("Resolve-MultipoleSimionLayoutTemplate", source)
        self.assertIn("common.multipole.simion_layout_template", template_support)
        self.assertIn("build_simion_runtime_iob.lua", source)
        self.assertIn("simion_layout_template_registry", source)
        self.assertIn("simion_layout_template_con", source)
        self.assertNotIn("C:\\Program Files\\SIMION-2020", source)

    def test_manifest_lifecycle_preserves_partial_outputs(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        support = (
            REPO_ROOT / "common/contracts/run_artifact_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertIn("Get-ChildItem -LiteralPath $directory -Recurse -File", support)
        self.assertIn("Write-VerifiedRunManifest", support)
        for output in (
            'simion_summary__$primaryName.json',
            'simion_summary__$controlName.json',
            'particle_states__$primaryName.csv',
            'particle_states__$controlName.csv',
            'trajectory_samples__$primaryName.csv',
            'trajectory_samples__$controlName.csv',
        ):
            self.assertIn(output, source)

    def test_census_and_handoff_are_exact_resolved_projections(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$interfaces.exit.handoff_plane_z_mm", source)
        self.assertIn("$interfaces.exit.census_plane_z_mm", source)
        self.assertIn("handoff_plane_mm=$handoffPlaneMm", source)
        self.assertIn("census_plane_mm=$censusPlaneMm", source)
        self.assertIn("numerical_census_marker_is_handoff=false", source)
        self.assertIn(
            "$surfaceToleranceMm=[Math]::Max(1e-6*$resolvedCellMmZ,1e-9)",
            source,
        )
        self.assertIn(
            "$censusPlaneMm-2*$resolvedCellMmZ-$surfaceToleranceMm",
            source,
        )
        program = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        self.assertIn("census_plane_mm = assert(run_config.census_plane_mm)", program)
        self.assertIn(
            "project_state_to_plane(handoff_state[particle], census_plane_mm)",
            program,
        )

    def test_gem_z_spacing_maps_to_the_flight_axis_controls(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("DefaultParameterSetName='IsotropicCell'", source)
        for axis in ("X", "Y", "Z"):
            self.assertIn(
                f"ParameterSetName='AnisotropicCell')]\n"
                f"  [ValidateScript({{[double]::IsFinite($_) -and $_ -gt 0}})][double]$CellMm{axis}",
                source,
            )
            self.assertIn(f"--cell-mm-{axis.lower()} $resolvedCellMm{axis}", source)
        self.assertIn("trajectory_plane_step_mm=$resolvedCellMmZ", source)
        self.assertIn('axial_axis="x"', source)
        self.assertIn("maps GEM +z to flight +x", source)

    def test_runner_accepts_small_positive_and_large_exploration_numerics(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        parameter_block = source[: source.index(")\n\nSet-StrictMode")] + ")\n'BOUND'\n"
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "parameter_probe.ps1"
            probe.write_text(parameter_block, encoding="utf-8")
            result = subprocess.run(
                [
                    "pwsh", "-NoProfile", "-NonInteractive", "-File", str(probe),
                    "-ProjectId", "probe", "-RuntimeProfileId", "probe",
                    "-DesignProfileId", "probe", "-ParticleSourcePath", "probe",
                    "-EngineeringBudgetPath", "probe", "-CellMm", "0.000001",
                    "-MaximumTimeUs", "0.000001", "-TrajectoryQuality", "10001",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOUND", result.stdout)

    def test_final_run_id_is_always_forwarded_to_budget_authorization(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("$runIdWasExplicit", source)
        self.assertIn("$budgetArguments+=@('--run-id',$RunId)", source)
        self.assertIn("authorized_run_id", source)
        self.assertLess(
            source.index("authorized_run_id"),
            source.index("New-RunPackage"),
        )

    def test_pa_grid_budget_is_audited_before_simion_starts(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "Get-SimionPaGridAudit",
            "maximum_pa_grid_points",
            "simion_grid_audit.json",
            "multipole_simion_pa_grid_audit",
            "SIMION PA grid point budget exceeded",
        ):
            self.assertIn(token, source)
        audit = source.index(
            "$gridAuditDocument=Get-SimionPaGridAudit -GemPath $gem"
        )
        persisted = source.index(
            "Set-Content -LiteralPath $gridAudit -Encoding UTF8",
            audit,
        )
        rejected = source.index("if($gridAuditDocument.status-eq'FAIL')", persisted)
        simion_start = source.index("Invoke-SimionStep 'gem2pa'")
        self.assertLess(audit, persisted)
        self.assertLess(persisted, rejected)
        self.assertLess(rejected, simion_start)
        self.assertIn("simion_grid_audit=$gridAudit", source)

    def test_pa_grid_budget_accepts_below_cap_and_rejects_over_cap(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("function Get-SimionPaGridAudit")
        end = source.index("\nfunction ConvertTo-TransportMetricCase", start)
        audit_function = source[start:end]
        with tempfile.TemporaryDirectory() as directory:
            gem = Path(directory) / "anisotropic.gem"
            gem.write_text(
                "pa_define(101, 41, 51, planar, non-mirrored)\n",
                encoding="ascii",
            )

            def audit(maximum: int | None) -> dict:
                maximum_argument = "$null" if maximum is None else str(maximum)
                command = (
                    f"{audit_function}\n"
                    f"Get-SimionPaGridAudit -GemPath '{gem}' "
                    f"-MaximumPaGridPoints {maximum_argument} | "
                    "ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    [
                        "pwsh",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            grid_points = 101 * 41 * 51
            below_cap = audit(grid_points + 1)
            self.assertEqual(below_cap["status"], "PASS")
            self.assertEqual(below_cap["grid_points"], grid_points)
            self.assertEqual(
                below_cap["maximum_pa_grid_points"],
                grid_points + 1,
            )
            over_cap = audit(grid_points - 1)
            self.assertEqual(over_cap["status"], "FAIL")
            self.assertEqual(over_cap["grid_points"], grid_points)
            unconfigured = audit(None)
            self.assertEqual(unconfigured["status"], "NOT_CONFIGURED")
            self.assertIsNone(unconfigured["maximum_pa_grid_points"])

    def test_rejected_handoff_writes_a_unique_terminal_event(self) -> None:
        program = (REPO_ROOT / "common" / "multipole" / "simion_transport.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "write_particle_state(ion_number, 'terminal', 'lost', "
            "'acceptance_aperture', handoff)",
            program,
        )
        self.assertIn("inside_handoff_aperture(handoff)", program)
        self.assertIn("terminal_written[ion_number] = true", program)
        self.assertIn("if terminal_written[particle] then return end", program)
        self.assertIn(
            "if previous_state[particle] then "
            "finalize_particle(particle, previous_state[particle]) end",
            program,
        )

    def test_raw_and_paired_transmission_cannot_diverge(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "SIMION paired metrics transmission differs from the raw handoff states.",
            source,
        )
        self.assertIn("$primaryHandoffTransmission", source)
        self.assertIn("$controlHandoffTransmission", source)

    def test_waveform_and_all_drive_scalars_come_from_resolved_design(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        lua = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        for field in (
            "waveform",
            "rf_amplitude_V_zero_to_peak_per_group",
            "dc_amplitude_V_per_group",
            "common_mode_offset_V",
            "frequency_Hz",
            "phase_rad",
        ):
            self.assertIn(field, source)
        self.assertIn("transport_waveform == 'sine'", lua)
        self.assertIn("transport_waveform == 'cosine'", lua)
        kernel = (RUNNER.parent / "simion_rf_drive.lua").read_text(encoding="utf-8")
        self.assertIn("RF drive waveform must be sine or cosine", kernel)
        self.assertIn("config.waveform == 'sine' and math.sin or math.cos", kernel)

    def test_mechanically_segmented_rods_always_receive_full_length_rf(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        comsol = (RUNNER.parent / "solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "$segmentedRodGeometry=($null-ne$design.segmentation.segmented_rod_array)",
            source,
        )
        self.assertIn("if($segmentedRodGeometry){", source)
        self.assertIn(
            "$segmented=($axialTopology-eq'segmented_rod_axial_acceleration')",
            source,
        )
        self.assertIn(
            "segmentedRodGeometry = isfield(design.segmentation,'segmented_rod_array');",
            comsol,
        )
        self.assertIn("if segmentedRodGeometry", comsol)
        self.assertIn(
            "segmentedAccelerationEnabled = strcmp("
            "axialTopology,'segmented_rod_axial_acceleration');",
            comsol,
        )

    def test_metrics_are_unqualified_without_explicit_evidence(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$qualification='UNQUALIFIED'", source)
        self.assertIn("evaluate_transport_evidence", source)
        self.assertIn("analyze_simion_axial_acceleration", source)
        self.assertIn("ConvertTo-TransportMetricCase $primary", source)
        self.assertIn(
            "$metricCase.transmission_fraction=[double]$CaseSummary.transmission",
            source,
        )
        self.assertNotIn("MinimumRfTransmission", source)
        self.assertNotIn("MinimumImprovementOverZeroRf", source)

    def test_validator_output_is_not_returned_as_case_data(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("--output $stateReport|Out-Null", source)
        self.assertIn("return Get-Content -LiteralPath $caseSummary", source)

    def test_reference_comsol_run_is_verified_before_simion(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "common.contracts.verify_run_manifest",
            "--require-status success",
            "--require-local-run-config",
            "--require-run-id $ReferenceComsolRunId",
            "--require-project $ProjectId",
            "--require-mode resolved_design_transport",
            "--require-design-profile-id $DesignProfileId",
            "--require-parent-resolved-design-sha256 $resolvedHash",
            "--require-particle-source-sha256",
            "reference_comsol_run_manifest.json",
            "reference_comsol_run_manifest_sha256",
            "reference_comsol_source_run_id",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("common.contracts.verify_run_manifest"),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_project_wrappers_are_thin_profile_consumers(self) -> None:
        projects = (
            "rf_quadrupole_ion_optics",
            "rf_hexapole_ion_optics",
            "rf_octupole_ion_optics",
        )
        for project in projects:
            project_root = REPO_ROOT / "projects" / project
            wrapper_path = (
                project_root
                / "workflows"
                / "no_collision_transport"
                / "run_simion.ps1"
                if project == "rf_quadrupole_ion_optics"
                else project_root / "analysis" / "run_simion_finite_3d_transport.ps1"
            )
            wrapper = wrapper_path.read_text(encoding="utf-8-sig")
            self.assertIn("RuntimeProfileId", wrapper)
            if project == "rf_quadrupole_ion_optics":
                self.assertNotIn("DesignProfileId", wrapper)
                self.assertNotIn("ParticleSourcePath", wrapper)
                self.assertIn("project_transport_launcher_support.ps1", wrapper)
            else:
                self.assertNotIn("DesignProfileId", wrapper)
                self.assertNotIn("ParticleSourcePath", wrapper)
                self.assertIn("project_transport_launcher_support.ps1", wrapper)
            self.assertNotIn("FieldScreenRunId", wrapper)
            self.assertNotIn("AxialAccelerationContractPath", wrapper)

    def test_5ev_projection_requires_and_consumes_explicit_operating_point(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$sourceProjectionArguments", runner)
        self.assertIn("--expected-source-family-sha256", runner)
        self.assertGreaterEqual(runner.count("--source-family"), 2)
        self.assertGreaterEqual(runner.count("--operating-point"), 2)
        project = REPO_ROOT / "projects" / "rf_quadrupole_ion_optics"
        resolved_path = project / "config" / "resolved_design_official.json"
        family_path = project / "config" / "interface_readiness_particle_source.json"
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        speed = math.sqrt(
            2.0 * 5.0 * ELEMENTARY_CHARGE_C / (100.0 * AMU_KG)
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=COLUMNS, lineterminator="\n"
                )
                writer.writeheader()
                for particle_id in range(1, 101):
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "birth_time_s": "0",
                            "x_mm": "0",
                            "y_mm": "0",
                            "z_mm": resolved["interfaces_mm"]["entrance"][
                                "release_plane_z_mm"
                            ],
                            "vx_m_s": "0",
                            "vy_m_s": "0",
                            "vz_m_s": format(speed, ".17g"),
                            "mass_amu": "100",
                            "charge_state": "1",
                        }
                    )
            with self.assertRaisesRegex(
                ValueError, "resolved closed interval"
            ):
                render_canonical_source(source, resolved_path)
            fly, states, count = render_canonical_source(
                source,
                resolved_path,
                source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(
                    family_path.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(count, 100)
            self.assertIn("ke=5", fly)
            self.assertIn("ke=5", states)
            with self.assertRaisesRegex(ValueError, "requires both"):
                render_canonical_source(
                    source,
                    resolved_path,
                    source_family_path=family_path,
                )
            with self.assertRaisesRegex(ValueError, "differs from the frozen"):
                render_canonical_source(
                    source,
                    resolved_path,
                    source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256="0" * 64,
                )

            class DriftingSourceFamily:
                def __init__(self) -> None:
                    self.read_count = 0

                def read_bytes(self) -> bytes:
                    self.read_count += 1
                    return (
                        family_path.read_bytes()
                        if self.read_count == 1
                        else b'{"schema_version":1,"operating_points":{}}'
                    )

            drifting_family = DriftingSourceFamily()
            _, _, drift_count = render_canonical_source(
                source,
                resolved_path,
                source_family_path=drifting_family,  # type: ignore[arg-type]
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(
                    family_path.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(drift_count, 100)
            self.assertEqual(drifting_family.read_count, 1)

            fly, states, count = render_canonical_source(
                source, resolved_path, source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                particle_id_min=21, particle_id_max=40,
            )
            self.assertEqual(count, 20)
            self.assertIn("[21]", states)
            self.assertIn("[40]", states)
            self.assertNotIn("[20]", states)
            self.assertEqual(fly.count("standard_beam"), 20)
            _, local_states, _ = render_canonical_source(
                source, resolved_path, source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                particle_id_min=21, particle_id_max=40, simion_particle_id_offset=20,
            )
            self.assertIn("[1]", local_states)
            self.assertIn("[20]", local_states)
            self.assertNotIn("[21]", local_states)
            with self.assertRaisesRegex(ValueError, "offset exceeds"):
                render_canonical_source(
                    source, resolved_path, source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                    particle_id_min=21, particle_id_max=40, simion_particle_id_offset=21,
                )
            with self.assertRaisesRegex(ValueError, "batch interval"):
                render_canonical_source(
                    source, resolved_path, source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                    particle_id_min=1,
                )

    def test_primary_only_case_set_skips_control_and_records_null_control(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('primary_and_zero_axial_control','primary_and_rf_off_energy_control','primary_only')]",
            runner,
        )
        self.assertIn("if($CaseSet-eq'primary_and_zero_axial_control')", runner)
        self.assertIn("elseif($CaseSet-eq'primary_and_rf_off_energy_control')", runner)
        self.assertIn("$control=Invoke-TransportCase $controlName 0 1", runner)
        self.assertIn("role='multipole_simion_rf_off_energy_control_metrics'", runner)
        self.assertIn("case_set=$CaseSet", runner)

    def test_parallel_batching_is_single_wave_and_revalidates_the_merged_state(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        support = (RUNNER.parent / "resource_budget_support.ps1").read_text(encoding="utf-8")
        self.assertIn("common.simion.particle_batching", runner)
        self.assertIn("SIMION shared single-wave batch plan differs from the canonical source.", runner)
        self.assertIn("--particle-id-min", runner)
        self.assertIn("Invoke-ResourceBudgetedProcesses", runner)
        self.assertIn("SIMION shared single-wave batch plan", runner)
        self.assertIn("SIMION $name particle-state contract failed.", runner)
        self.assertIn("--merge-rebase-csv", runner)
        self.assertIn("--merge-summaries", runner)
        self.assertNotIn("Add-Content -LiteralPath $caseState", runner)
        self.assertIn("Get-ProcessTreeWorkingSetBytes", support)
        self.assertIn("execution_wave", support)
        self.assertIn("$control=$null;$controlName=$null", runner)
        self.assertIn(
            "Primary-only SIMION runs cannot consume a paired-case evidence contract.",
            runner,
        )
        self.assertIn("role='multipole_simion_primary_transport_metrics'", runner)
        self.assertIn(
            "control_transmission=$(if($null-ne$control){$control.transmission}else{$null})",
            runner,
        )


if __name__ == "__main__":
    unittest.main()
