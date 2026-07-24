from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from projects.rf_quadrupole_collision_cooling.analysis import validate_s3_pulse_capture as module


class S3PulseCaptureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner_path = (
            module.PROJECT_ROOT / "tests" / "comsol" / "run_s3_pulse_capture.ps1"
        )
        cls.support_path = (
            module.PROJECT_ROOT / "tests" / "support" / "rf_run_artifact_support.ps1"
        )
        cls.runner = cls.runner_path.read_text(encoding="utf-8")
        cls.support = cls.support_path.read_text(encoding="utf-8")

    @staticmethod
    def _ps_literal(value: Path | str) -> str:
        return str(value).replace("'", "''")

    def _run_pwsh(self, script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=30,
        )

    def test_repository_contract_passes(self) -> None:
        contract = module.validate_contract()
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["inputs"]["spatial_registration"],
            "config/resolved_rf_to_oatof_s2_spatial_registration.json",
        )
        self.assertEqual(
            contract["identity_contract"]["species_identity_key"],
            ["species_id", "mass_amu", "charge_state"],
        )
        self.assertTrue(contract["permissions"]["nominal_particle_runtime_allowed"])
        self.assertFalse(contract["permissions"]["s3_stage_pass_allowed"])
        self.assertEqual(contract["waveform"]["rise_fall_model"], "ideal_finite_step")
        self.assertEqual(
            contract["local_exit_adapter"]["canonical_columns_source"],
            "common.contracts.component_particle_state.csv_columns",
        )

    def test_local_exit_adapter_authority_drift_is_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["local_exit_adapter"]["derived_physics_source"] = "solver_local_formula"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "adapter authority"):
                module.validate_contract(path)

    def test_stage_plan_has_one_public_cumulative_entry(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        plan = module._load(module._relative(contract["inputs"]["stage_plan"]))
        self.assertEqual([item["id"] for item in plan["stages"]], ["S2", "S3"])
        self.assertEqual(
            [item["role"] for item in plan["stages"]],
            ["internal_passive_connector_step", "current_cumulative_entry"],
        )
        self.assertEqual(plan["governance"]["public_entry_count"], 1)
        self.assertFalse(plan["stages"][0]["public_entrypoint"])
        self.assertTrue(plan["stages"][1]["public_entrypoint"])
        self.assertEqual(
            plan["stages"][1]["entrypoint"],
            "tests/cross_solver/run_s3_cumulative_chain.ps1",
        )

    def test_stage_plan_drift_is_rejected_by_the_runtime_validator(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        plan_path = module._relative(contract["inputs"]["stage_plan"])
        original_load = module._load
        plan = original_load(plan_path)
        mutations = []
        changed = copy.deepcopy(plan)
        changed["governance"]["public_entry_count"] = 2
        mutations.append(changed)
        changed = copy.deepcopy(plan)
        changed["stages"][0]["public_entrypoint"] = True
        mutations.append(changed)
        changed = copy.deepcopy(plan)
        changed["stages"][1]["entrypoint"] = "tests/comsol/run_s3_pulse_capture.ps1"
        mutations.append(changed)
        for changed in mutations:
            def load(path: Path, replacement: dict = changed) -> dict:
                return replacement if Path(path).resolve() == plan_path else original_load(path)

            with self.subTest(plan=changed):
                with mock.patch.object(module, "_load", side_effect=load):
                    with self.assertRaisesRegex(ValueError, "entry|S2|S3"):
                        module.validate_contract()

    def test_clock_origin_and_pulse_timing_authority_drift_are_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["source"]["clock_epoch_id"] = "solver_local_time"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "clock epochs"):
                module.validate_contract(path)

        pulse_path = module._relative(contract["inputs"]["pulse_timing_policy"])
        pulse = module._load(pulse_path)
        changed_pulse = copy.deepcopy(pulse)
        changed_pulse["method"] = "fixed_solver_local_time"
        original_load = module._load

        def load(path: Path) -> dict:
            if Path(path).resolve() == pulse_path:
                return changed_pulse
            return original_load(path)

        with mock.patch.object(module, "_load", side_effect=load):
            with self.assertRaisesRegex(ValueError, "pulse timing method"):
                module.validate_contract()

    def test_stage_promotion_is_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["claims"]["s3_stage_passed"] = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overclaims qualification"):
                module.validate_contract(path)

    def test_continuous_pre_pulse_field_is_rejected(self) -> None:
        contract = module._load(module.DEFAULT_CONTRACT)
        changed = copy.deepcopy(contract)
        changed["waveform"]["pre_pulse_oatof_field_scale"] = 1.0
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s3.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite pulse scales"):
                module.validate_contract(path)

    def test_s3_extends_the_shared_s2_geometry_and_clock(self) -> None:
        task = (module.PROJECT_ROOT / "tests" / "comsol" / "solve_s3_pulse_capture.m").read_text(
            encoding="utf-8")
        self.assertIn("prepare_s2_joint_field_model", task)
        self.assertIn("RF_OATOF_S3_SHARED_JOINT_CONTRACT", task)
        self.assertIn("ions.instrument_time_us(index)", task)
        self.assertIn("if(t>=", task)
        self.assertIn("directMating = abs(s2.nominal_registration.connector_gap_mm)", task)
        self.assertIn("releaseIndices = find(insidePhysicalAperture)", task)
        self.assertIn("restartDtS = releaseOffset*1e-3/ions.velocity_x_m_s(index)", task)
        self.assertIn("canonical_rf_exit_at_s2_connector.csv", self.runner)
        self.assertIn("'--s2-contract',$s2", self.runner)
        self.assertIn("rf_s3_pulse_scheduler", self.runner)
        self.assertIn("rf_s3_geometry_snapshot_plotter", self.runner)
        self.assertIn("common_verify_run_manifest", self.runner)
        self.assertIn("s3_stage_passed = $false", self.runner)

    def test_runner_freezes_every_post_freeze_consumer(self) -> None:
        required = (
            "$dependencyConsumer = 's3_pulse_capture'",
            "Where-Object { @($_.consumers) -contains $dependencyConsumer }",
            "$manifestToolRoot = $snapshotRoot",
            "$oaBaselineSnapshot = $dependencySnapshotPaths['oatof_baseline']",
            "$oaBaselineMatlab = $dependencyCompatibilityPaths['oatof_baseline']",
            "Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot",
            "Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot",
            "Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $manifestToolRoot",
            "& $frozenComsolRunner",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.runner)
        self.assertNotIn(
            "Join-Path $repoRoot 'common\\contracts\\verify_run_manifest.py'",
            self.runner,
        )
        self.assertNotIn(
            "& (Join-Path $repoRoot 'common\\comsol\\run_comsol_r2025b.ps1')",
            self.runner,
        )
        self.assertNotIn("Push-Location -LiteralPath $repoRoot", self.runner)

    def test_s3_dependency_contract_is_frozen_before_consumer_parse(self) -> None:
        freeze = self.runner.index(
            "$dependencyContractIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot"
        )
        parse = self.runner.index(
            "$dependencyDocument = Get-Content -LiteralPath $dependencyContract",
            freeze,
        )
        select = self.runner.index("$selectedDependencies = @(", parse)
        confirm = self.runner.index("Confirm-RfFrozenDependencyIdentity", select)
        self.assertLess(freeze, parse)
        self.assertLess(parse, select)
        self.assertLess(select, confirm)
        self.assertNotIn(
            "Get-Content -LiteralPath $dependencyContractSource",
            self.runner[freeze:select],
        )

    def test_source_run_is_manifest_bound_before_runtime(self) -> None:
        required = (
            "Resolve-RfDirectChildDirectory",
            "Copy-RfStableFile -SourceRunRoot $timingRun",
            "Copy-RfManifestBoundFile -SourceRunRoot $timingRun",
            "Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 's2_contract'",
            "Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'spatial_registration'",
            "Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'particle_source'",
            "Get-RfManifestOutputRecord -Manifest $sourceManifestDocument",
            "source_run_config = $sourceRunConfig",
            "timing_state_sha256 = $sourceTimingIdentity.sha256",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.runner)

    def test_source_manifest_is_frozen_before_strong_verification(self) -> None:
        freeze = self.runner.index(
            "$sourceManifestIdentity = Copy-RfStableFile -SourceRunRoot $timingRun"
        )
        verify = self.runner.index(
            "$frozenManifestVerifier,$sourceManifest,", freeze
        )
        parse = self.runner.index(
            "$sourceManifestDocument = Get-Content -LiteralPath $sourceManifest",
            verify,
        )
        self.assertLess(freeze, verify)
        self.assertLess(verify, parse)
        verification_block = self.runner[verify:parse]
        self.assertIn("'--require-status','success'", verification_block)
        self.assertIn("'--require-run-id',$SourceRunId", verification_block)
        self.assertIn(
            "'--require-project','rf_quadrupole_collision_cooling'",
            verification_block,
        )
        self.assertIn(
            "'--require-mode','rf_to_oatof_s2_passive_connector_n100'",
            verification_block,
        )
        self.assertNotIn("$sourceManifestOriginal", verification_block)

    def test_snapshot_python_rejects_live_provider_poison(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "snapshot"
            poison = root / "poison"
            dependency_contract = json.loads(
                (
                    module.PROJECT_ROOT / "config" / "rf_to_oatof_s2_dependencies.json"
                ).read_text(encoding="utf-8")
            )
            selected = [
                item
                for item in dependency_contract["dependencies"]
                if "s3_pulse_capture" in item["consumers"]
            ]
            for dependency in selected:
                source = module.PROJECT_ROOT.parents[1] / dependency["source_repo_path"]
                destination = snapshot / dependency["frozen_filename"].removeprefix(
                    "runtime_snapshot/"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if source.suffix == ".py":
                    poisoned = poison / dependency["source_repo_path"]
                    poisoned.parent.mkdir(parents=True, exist_ok=True)
                    poisoned.write_text(
                        "raise RuntimeError('live provider poison imported')\n",
                        encoding="utf-8",
                    )

            fixture = root / "fixture"
            fixture.mkdir()
            prepare = root / "prepare_snapshot_fixture.py"
            prepare.write_text(
                textwrap.dedent(
                    f"""
                    import csv, json
                    from pathlib import Path
                    from common.contracts.component_particle_state import csv_columns
                    from common.contracts.particle_physics import kinetic_energy_ev
                    from common.contracts.rigid_transform import FramedPosition, RigidTransform
                    from projects.rf_quadrupole_collision_cooling.analysis import (
                        derive_shared_centroid_pulse_time as scheduler,
                        plot_shared_pulse_geometry_snapshot as plotter,
                    )
                    root = Path({json.dumps(str(fixture))})
                    velocity = 1000.0
                    source = root / "source.csv"
                    source_row = {{
                        "particle_id": 1, "parent_particle_id": 42, "generation": 1,
                        "species_id": "ion_100amu_q1", "particle_weight": 1.0,
                        "source_component_id": "s2", "target_component_id": "s3",
                        "state_event": "component_handoff", "frame_id": "oatof_global",
                        "clock_epoch_id": "epoch", "instrument_time_us": 10.0,
                        "lineage_age_us": 4.0, "particle_age_us": 4.0,
                        "last_component_elapsed_time_us": 0.0,
                        "lineage_birth_time_us": 6.0, "particle_birth_time_us": 6.0,
                        "mass_to_charge_Th": 100.0, "mass_amu": 100.0,
                        "charge_state": 1, "position_x_mm": 0.0,
                        "position_y_mm": 0.0, "position_z_mm": 0.0,
                        "velocity_x_m_s": velocity, "velocity_y_m_s": 0.0,
                        "velocity_z_m_s": 0.0,
                        "kinetic_energy_eV": kinetic_energy_ev(100.0, velocity, 0.0, 0.0),
                        "phase_reference_id": "rf_drive.v1", "phase_rad": 0.0,
                    }}
                    with source.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=csv_columns(), lineterminator="\\n")
                        writer.writeheader(); writer.writerow(source_row)
                    terminal_row = {{
                        "particle_id": 1, "event": "contract_local_exit",
                        "status": "transmitted", "frame_id": "oatof_global",
                        "clock_epoch_id": "epoch", "instrument_time_us": 12.0,
                        "lineage_age_us": 6.0, "particle_age_us": 6.0,
                        "last_component_elapsed_time_us": 2.0,
                        "mass_amu": 100.0, "charge_state": 1,
                        "x_mm": 1.0, "y_mm": 2.0, "z_mm": 3.0,
                        "vx_m_s": velocity, "vy_m_s": 0.0, "vz_m_s": 0.0,
                        "rf_phase_rad": 0.25, "local_accelerator_exit": True,
                        "first_forward_oatof_entry": True,
                    }}
                    with (root / "terminal.csv").open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=terminal_row, lineterminator="\\n")
                        writer.writeheader(); writer.writerow(terminal_row)
                    capture_row = {{
                        "particle_id": 1, "frame_id": "oatof_global",
                        "clock_epoch_id": "epoch", "instrument_time_us": 11.0,
                        "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
                        "vx_m_s": velocity, "vy_m_s": 0.0, "vz_m_s": 0.0,
                        "inside_oatof_ideal_reference_volume": True,
                        "active_at_pulse": True,
                    }}
                    with (root / "capture.csv").open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=capture_row, lineterminator="\\n")
                        writer.writeheader(); writer.writerow(capture_row)
                    contract = {{
                        "source": {{"source_particles": 1, "clock_epoch_id": "epoch",
                                    "target_mass_amu": 100.0, "target_charge_state": 1}},
                        "identity_contract": {{"frame_id": "oatof_global"}},
                        "local_exit_adapter": {{
                            "terminal_event": "contract_local_exit",
                            "terminal_status": "transmitted",
                            "source_component_id": "rf_quadrupole_to_oatof_s3",
                            "target_component_id": "oatof_analyzer",
                            "state_event": "canonical_contract_local_exit",
                        }},
                        "runtime": {{"minimum_active_at_pulse": 1,
                                     "minimum_local_accelerator_exit": 1}},
                    }}
                    (root / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
                    (root / "schedule.json").write_text(json.dumps({{
                        "stage": "S3", "derived_pulse_time_us": 11.0,
                        "pulse_width_us": 1.0,
                        "target_species": {{"mass_amu": 100.0, "charge_state": 1}},
                    }}), encoding="utf-8")
                    assert scheduler._sha256(source)
                    assert plotter.particle_marker_areas(1)["active"] > 0
                    transform = RigidTransform.identity("oatof_global")
                    assert transform.transform_position(
                        FramedPosition("oatof_global", (1.0, 2.0, 3.0))
                    ).coordinates_mm == (1.0, 2.0, 3.0)
                    run = root / "20260724_180000__test__repo__s3-snapshot-poison"
                    run.mkdir()
                    (run / "run_config.json").write_text(json.dumps({{
                        "schema_version": 1, "run_id": run.name,
                        "project": "rf_quadrupole_collision_cooling",
                        "mode": "s3_snapshot_poison_test", "project_root": str(root),
                        "inputs": {{"particle_source": str(source)}},
                        "formal_gate_passed": False,
                    }}), encoding="utf-8")
                    """
                ),
                encoding="utf-8",
            )
            analysis = snapshot / "projects/rf_quadrupole_collision_cooling/analysis"
            adapter = analysis / "build_s3_local_exit_component_state.py"
            audit = analysis / "audit_s3_pulse_chain.py"
            writer = snapshot / "common/contracts/write_run_manifest.py"
            verifier = snapshot / "common/contracts/verify_run_manifest.py"
            run_dir = fixture / "20260724_180000__test__repo__s3-snapshot-poison"
            script = (
                f". '{self._ps_literal(self.support_path)}'; "
                "$tokens=$null;$errors=$null;"
                f"$ast=[System.Management.Automation.Language.Parser]::ParseFile("
                f"'{self._ps_literal(self.runner_path)}',[ref]$tokens,[ref]$errors);"
                "$definition=$ast.FindAll({param($node) "
                "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $node.Name -eq 'Invoke-S3SnapshotPython'},$true)[0].Extent.Text;"
                "Invoke-Expression $definition;"
                f"$env:PYTHONPATH='{self._ps_literal(poison)}';"
                "Invoke-S3SnapshotPython "
                f"-Python '{self._ps_literal(sys.executable)}' "
                f"-SnapshotRoot '{self._ps_literal(snapshot)}' "
                f"-Arguments @('{self._ps_literal(prepare)}') "
                "-FailureMessage 'snapshot fixture preparation failed';"
                "Invoke-S3SnapshotPython "
                f"-Python '{self._ps_literal(sys.executable)}' "
                f"-SnapshotRoot '{self._ps_literal(snapshot)}' "
                "-Arguments @('-m','common.contracts.component_particle_state',"
                f"'--state','{self._ps_literal(fixture / 'source.csv')}',"
                f"'--output','{self._ps_literal(fixture / 'source_validation.json')}') "
                "-FailureMessage 'snapshot component-state CLI failed';"
                "Invoke-S3SnapshotPython "
                f"-Python '{self._ps_literal(sys.executable)}' "
                f"-SnapshotRoot '{self._ps_literal(snapshot)}' "
                f"-Arguments @('{self._ps_literal(adapter)}','--source',"
                f"'{self._ps_literal(fixture / 'source.csv')}','--terminal',"
                f"'{self._ps_literal(fixture / 'terminal.csv')}','--contract',"
                f"'{self._ps_literal(fixture / 'contract.json')}','--output',"
                f"'{self._ps_literal(fixture / 'exit.csv')}','--validation',"
                f"'{self._ps_literal(fixture / 'exit_validation.json')}') "
                "-FailureMessage 'snapshot adapter fixture failed';"
                "Invoke-S3SnapshotPython "
                f"-Python '{self._ps_literal(sys.executable)}' "
                f"-SnapshotRoot '{self._ps_literal(snapshot)}' "
                f"-Arguments @('{self._ps_literal(audit)}','--source',"
                f"'{self._ps_literal(fixture / 'source.csv')}','--terminal',"
                f"'{self._ps_literal(fixture / 'terminal.csv')}','--capture',"
                f"'{self._ps_literal(fixture / 'capture.csv')}','--local-exit',"
                f"'{self._ps_literal(fixture / 'exit.csv')}','--schedule',"
                f"'{self._ps_literal(fixture / 'schedule.json')}','--contract',"
                f"'{self._ps_literal(fixture / 'contract.json')}','--output',"
                f"'{self._ps_literal(fixture / 'audit.json')}') "
                "-FailureMessage 'snapshot audit fixture failed';"
                "Invoke-S3SnapshotPython "
                f"-Python '{self._ps_literal(sys.executable)}' "
                f"-SnapshotRoot '{self._ps_literal(snapshot)}' "
                f"-Arguments @('{self._ps_literal(writer)}','--run-config',"
                f"'{self._ps_literal(run_dir / 'run_config.json')}','--status',"
                f"'interrupted','--manifest','{self._ps_literal(run_dir / 'run_manifest.json')}') "
                "-FailureMessage 'snapshot manifest writer failed';"
                "Invoke-S3SnapshotPython "
                f"-Python '{self._ps_literal(sys.executable)}' "
                f"-SnapshotRoot '{self._ps_literal(snapshot)}' "
                f"-Arguments @('{self._ps_literal(verifier)}',"
                f"'{self._ps_literal(run_dir / 'run_manifest.json')}',"
                "'--require-status','interrupted') "
                "-FailureMessage 'snapshot manifest verifier failed';"
                f"if($env:PYTHONPATH -ne '{self._ps_literal(poison)}'){{exit 7}}"
            )
            result = self._run_pwsh(script, root)
            self.assertEqual(
                result.returncode, 0, script + "\n" + result.stdout + result.stderr
            )
            self.assertIn("COMPONENT_STATE=PASS", result.stdout)
            self.assertIn("S3_LOCAL_EXIT_COMPONENT_STATE=PASS", result.stdout)
            self.assertIn("S3_PARTICLE_CHAIN_AUDIT=PASS", result.stdout)
            self.assertNotIn("poison", result.stderr)

    def test_direct_child_and_manifest_path_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runs = root / "runs"
            source_run = runs / "valid"
            source_run.mkdir(parents=True)
            source = root / "outside.txt"
            source.write_text("outside\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest().upper()
            script = (
                f". '{self._ps_literal(self.support_path)}';"
                "$failures=0;"
                f"try{{Resolve-RfDirectChildDirectory -ParentRoot "
                f"'{self._ps_literal(runs)}' -ChildName '..\\escape' -Role SourceRunId;"
                "$failures++}catch{};"
                "$record=[pscustomobject]@{"
                f"path='{self._ps_literal(source)}';exists=$true;"
                f"bytes={source.stat().st_size};sha256='{digest}'"
                "};"
                f"try{{Copy-RfManifestBoundFile -SourceRunRoot "
                f"'{self._ps_literal(source_run)}' -SourcePath "
                f"'{self._ps_literal(source)}' -Destination "
                f"'{self._ps_literal(root / 'copy.txt')}' -ManifestRecord $record "
                "-Role particle_source;$failures++}catch{};"
                "if($failures-ne 0){exit 9};exit 0"
            )
            result = self._run_pwsh(script, root)
            self.assertEqual(
                result.returncode, 0, script + "\n" + result.stdout + result.stderr
            )

    def test_manifest_copy_detects_toctou_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_run = root / "runs" / "source"
            source_run.mkdir(parents=True)
            source = source_run / "input.txt"
            source.write_text("frozen\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest().upper()
            destination = root / "frozen" / "input.txt"
            script = (
                f". '{self._ps_literal(self.support_path)}';"
                "$record=[pscustomobject]@{"
                f"path='{self._ps_literal(source)}';exists=$true;"
                f"bytes={source.stat().st_size};sha256='{digest}'"
                "};"
                "function Copy-Item{param([string]$LiteralPath,[string]$Destination);"
                "Microsoft.PowerShell.Management\\Copy-Item "
                "-LiteralPath $LiteralPath -Destination $Destination;"
                "Microsoft.PowerShell.Management\\Set-Content "
                "-LiteralPath $LiteralPath -Value 'mutated'};"
                "try{Copy-RfManifestBoundFile "
                f"-SourceRunRoot '{self._ps_literal(source_run)}' "
                f"-SourcePath '{self._ps_literal(source)}' "
                f"-Destination '{self._ps_literal(destination)}' "
                "-ManifestRecord $record -Role timing_state;exit 8}"
                "catch{if($_.Exception.Message -notmatch 'changed while frozen'){exit 9}};"
                "exit 0"
            )
            result = self._run_pwsh(script, root)
            self.assertEqual(
                result.returncode, 0, script + "\n" + result.stdout + result.stderr
            )

    def test_replacing_live_manifest_after_freeze_cannot_change_verified_copy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_run = (
                root
                / "runs"
                / "20260724_181000__sim__comsol__s3-source-manifest-freeze__n100"
            )
            source_run.mkdir(parents=True)
            source_input = source_run / "input.json"
            source_input.write_text("{}\n", encoding="utf-8")
            run_config = source_run / "run_config.json"
            run_config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": source_run.name,
                        "project": "rf_quadrupole_collision_cooling",
                        "mode": "rf_to_oatof_s2_passive_connector_n100",
                        "project_root": str(root),
                        "inputs": {"source": str(source_input)},
                        "formal_gate_passed": False,
                    }
                ),
                encoding="utf-8",
            )
            repo_root = module.PROJECT_ROOT.parents[1]
            writer = repo_root / "common/contracts/write_run_manifest.py"
            verifier = repo_root / "common/contracts/verify_run_manifest.py"
            manifest = source_run / "run_manifest.json"
            written = subprocess.run(
                [
                    sys.executable,
                    str(writer),
                    "--run-config",
                    str(run_config),
                    "--status",
                    "success",
                    "--manifest",
                    str(manifest),
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
            frozen = root / "inputs" / "source_manifest.json"
            script = (
                f". '{self._ps_literal(self.support_path)}';"
                "Copy-RfStableFile "
                f"-SourceRunRoot '{self._ps_literal(source_run)}' "
                f"-SourcePath '{self._ps_literal(manifest)}' "
                f"-Destination '{self._ps_literal(frozen)}' "
                "-Role 'source run manifest' | Out-Null;"
                f"Set-Content -LiteralPath '{self._ps_literal(manifest)}' "
                "-Value '{\"status\":\"failed\"}';"
                f"& '{self._ps_literal(sys.executable)}' "
                f"'{self._ps_literal(verifier)}' '{self._ps_literal(frozen)}' "
                f"--require-status success --require-run-id '{source_run.name}' "
                "--require-project rf_quadrupole_collision_cooling "
                "--require-mode rf_to_oatof_s2_passive_connector_n100;"
                "if($LASTEXITCODE-ne 0){exit 8};exit 0"
            )
            result = self._run_pwsh(script, root)
            self.assertEqual(
                result.returncode, 0, script + "\n" + result.stdout + result.stderr
            )


if __name__ == "__main__":
    unittest.main()
