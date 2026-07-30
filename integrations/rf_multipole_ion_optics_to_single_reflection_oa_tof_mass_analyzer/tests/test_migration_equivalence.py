"""Pure fixture tests for RF-to-oaTOF migration publication and evaluation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.evaluate_migration_equivalence import (
    STAGE_MODES,
    evaluate_migration,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.publish_integration_run import (
    INTEGRATION_ID,
    publish_integration_run,
    stage_run_id,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PROFILE_GAP_ONE = "rf_quadrupole_grounded_connector_gap_1mm"
PROFILE_GAP_ZERO = "rf_quadrupole_direct_mating_gap_0mm"
PHASES = (
    "pre_pulse_interface_transport",
    "pulse_capture",
    "analyzer_transport",
)
RESULT_NAMES = {
    "pre_pulse_interface_transport": ("particle_events", "pre_pulse_interface_transport_particles.csv"),
    "pulse_capture": ("terminal_census", "pulse_capture_particle_terminal_census.csv"),
    "pulse_capture_local": ("local_accelerator_exit", "pulse_capture_local_accelerator_exit.csv"),
    "analyzer_transport": ("downstream_particles", "simion_downstream_particles.csv"),
}
CSV_TEXT = {
    "pre_pulse_interface_transport": "particle_id,event,status,terminal_reason\n1,oatof_entry,transmitted,none\n",
    "pulse_capture": (
        "particle_id,event,status,terminal_reason,oatof_entry_status,active_at_pulse,"
        "local_accelerator_exit\n"
        "1,local_accelerator_exit,transmitted,none,transmitted,1,1\n"
    ),
    "pulse_capture_local": "particle_id,state_event\n1,local_accelerator_exit\n",
    "analyzer_transport": "Ion,Hit\n1,True\n",
}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def workspace_record(path: Path, workspace: Path) -> dict[str, Any]:
    return dict(
        path=path.resolve().relative_to(workspace.resolve()).as_posix(),
        sha256=file_sha256(path),
        bytes=path.stat().st_size,
    )


def file_record(path: Path) -> dict[str, Any]:
    return dict(
        path=str(path.resolve()), exists=True, bytes=path.stat().st_size,
        sha256=file_sha256(path),
    )


def write_manifest(
    run_dir: Path,
    *,
    project: str,
    mode: str,
    outputs: list[Path],
) -> Path:
    run_config = run_dir / "run_config.json"
    manifest = run_dir / "run_manifest.json"
    write_json(
        manifest,
        {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "run_id": run_dir.name,
            "project": project,
            "mode": mode,
            "status": "success",
            "run_config": file_record(run_config),
            "outputs": [file_record(path) for path in outputs],
        },
    )
    return manifest


class MigrationFixture:
    """Build a complete two-profile migration fixture without solver execution."""

    def __init__(self, root: Path) -> None:
        self.workspace = root
        self.repo = root / "simulation_repo"
        self.fake_integration = (
            self.repo
            / "integrations"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        )
        self.oracle_path = self.fake_integration / "config" / "migration_oracles.json"
        self.prereg_path = (
            self.fake_integration
            / "config"
            / "migration_equivalence_preregistration.json"
        )
        self.profile_runs: dict[str, Path] = {}
        self._write_project_descriptor()
        source = self._write_source()
        oracle_profiles = []
        cases = (
            (PROFILE_GAP_ONE, "1", "20260729_120000"),
            (PROFILE_GAP_ZERO, "0", "20260729_121000"),
        )
        for profile_id, gap, stamp in cases:
            legacy = self._write_legacy_profile(profile_id, gap)
            oracle_profiles.append(legacy)
            run_path = self._write_new_profile(
                profile_id,
                gap,
                stamp,
                source,
            )
            self.profile_runs[profile_id] = run_path
        oracle = {
            "schema_version": 2,
            "role": "connection_profile_migration_oracles",
            "integration_id": INTEGRATION_ID,
            "legacy_identity": {
                "current_project_descriptor": (
                    "projects/rf_quadrupole_ion_optics/config/project.json"
                ),
                "mapping_id": "rf_quad_rename_20260728",
                "legacy_project_id": "rf_quadrupole_collision_cooling",
                "artifact_root": (
                    "artifacts/projects/rf_quadrupole_collision_cooling"
                ),
                "artifact_access": "read_only",
                "new_runs_allowed": False,
            },
            "source_identity": source,
            "profile_interpretation": {},
            "shared_sources": {},
            "profiles": oracle_profiles,
        }
        write_json(self.oracle_path, oracle)
        prereg = json.loads(
            (
                INTEGRATION_ROOT
                / "config"
                / "migration_equivalence_preregistration.json"
            ).read_text(encoding="utf-8")
        )
        prereg["legacy_oracle"]["path"] = (
            "integrations/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "config/migration_oracles.json"
        )
        prereg["legacy_oracle"]["sha256"] = file_sha256(self.oracle_path)
        write_json(self.prereg_path, prereg)

    def _write_project_descriptor(self) -> None:
        write_json(
            self.repo
            / "projects"
            / "rf_quadrupole_ion_optics"
            / "config"
            / "project.json",
            {
                "project_id": "rf_quadrupole_ion_optics",
                "legacy_identities": [
                    {
                        "mapping_id": "rf_quad_rename_20260728",
                        "project_id": "rf_quadrupole_collision_cooling",
                        "artifact_root": (
                            "artifacts/projects/rf_quadrupole_collision_cooling"
                        ),
                        "artifact_access": "read_only",
                        "new_runs_allowed": False,
                    }
                ],
            },
        )

    def _write_source(self) -> dict[str, Any]:
        run_id = "20260722_193000__sim__comsol__rf-input__n1"
        run = (
            self.workspace
            / "artifacts"
            / "projects"
            / "rf_quadrupole_collision_cooling"
            / "runs"
            / run_id
        )
        events = run / "results" / "source.csv"
        metadata = run / "inputs" / "metadata.json"
        manifest = run / "run_manifest.json"
        write_text(events, "particle_id\n1\n")
        write_json(metadata, {"particle_count": 1})
        write_json(
            manifest,
            {
                "role": "simulation_run_manifest",
                "run_id": run_id,
                "project": "rf_quadrupole_collision_cooling",
                "mode": "legacy_source",
                "status": "success",
            },
        )
        return {
            "run_id": run_id,
            "project_id": "rf_quadrupole_collision_cooling",
            "particle_count": 100,
            "manifest": workspace_record(manifest, self.workspace),
            "events": workspace_record(events, self.workspace),
            "metadata": workspace_record(metadata, self.workspace),
        }

    def _write_legacy_profile(
        self, profile_id: str, gap: str
    ) -> dict[str, Any]:
        runs = []
        for phase in PHASES:
            run_id = f"20260722_16000{gap}__sim__comsol__legacy-{phase.replace('_', '-')}__n1"
            run = (
                self.workspace
                / "artifacts"
                / "projects"
                / "rf_quadrupole_collision_cooling"
                / "runs"
                / run_id
            )
            summary = run / "summary.json"
            manifest = run / "run_manifest.json"
            write_json(summary, {"status": "success"})
            results: dict[str, dict[str, Any]] = {}
            keys = [phase]
            if phase == "pulse_capture":
                keys.append("pulse_capture_local")
            for key in keys:
                legacy_name, new_name = RESULT_NAMES[key]
                result = run / "results" / new_name
                write_text(result, CSV_TEXT[key])
                results[legacy_name] = workspace_record(result, self.workspace)
            mode = f"legacy_{phase}"
            write_json(
                manifest,
                {
                    "role": "simulation_run_manifest",
                    "run_id": run_id,
                    "project": "rf_quadrupole_collision_cooling",
                    "mode": mode,
                    "status": "success",
                },
            )
            runs.append(
                {
                    "phase": phase,
                    "run_id": run_id,
                    "project_id": "rf_quadrupole_collision_cooling",
                    "mode": mode,
                    "manifest": workspace_record(manifest, self.workspace),
                    "summary": workspace_record(summary, self.workspace),
                    "results": results,
                }
            )
        return {
            "connection_profile_id": profile_id,
            "source_case": f"gap_{gap}",
            "source_particles": 1,
            "census": {
                "rf_exit": 1,
                "oatof_entry": 1,
                "active_at_pulse": 1,
                "local_accelerator_exit": 1,
                "detector_hit": 1,
            },
            "legacy_runs": runs,
        }

    def _write_new_profile(
        self,
        profile_id: str,
        gap: str,
        stamp: str,
        source: dict[str, Any],
    ) -> Path:
        stage_root = (
            self.workspace
            / "artifacts"
            / "projects"
            / "rf_quadrupole_ion_optics"
            / "runs"
        )
        for phase in PHASES:
            run = stage_root / stage_run_id(stamp, phase, gap)
            source_identity = {
                "run_id": source["run_id"],
                "project_id": source["project_id"],
                "manifest_sha256": source["manifest"]["sha256"],
                "event_sha256": source["events"]["sha256"],
                "metadata_sha256": source["metadata"]["sha256"],
            }
            write_json(
                run / "run_config.json",
                {
                    "run_id": run.name,
                    "source_particle_identity": source_identity,
                },
            )
            outputs = []
            keys = [phase]
            if phase == "pulse_capture":
                keys.append("pulse_capture_local")
            for key in keys:
                _, filename = RESULT_NAMES[key]
                content = CSV_TEXT[key]
                result = run / "results" / filename
                write_text(result, content)
                outputs.append(result)
            summary = run / "summary.json"
            if phase == "analyzer_transport":
                write_json(
                    summary,
                    {
                        "status": "success",
                        "census": {
                            "rf_exit": 1,
                            "oatof_entry": 1,
                            "active_at_pulse": 1,
                            "local_accelerator_exit": 1,
                            "detector_hit": 1,
                        },
                    },
                )
            else:
                write_json(summary, {"status": "success"})
            outputs.append(summary)
            write_manifest(
                run,
                project="rf_quadrupole_ion_optics",
            mode=STAGE_MODES[phase],
                outputs=outputs,
            )

        run_id = f"{stamp}__migration__cross__rf-oatof-gap{gap}__n100"
        parent = (
            self.workspace
            / "artifacts"
            / "projects"
            / INTEGRATION_ID
            / "runs"
            / run_id
        )
        parent.mkdir(parents=True)
        plan = parent / "composition_plan.json"
        resolved = parent / "resolved_connection.json"
        receipt = parent / "execution_receipt.json"
        budget = parent / "resolved_engineering_budget.json"
        governance = {
            "runtime_binding_sha256": "A" * 64,
            "preregistration_sha256": "B" * 64,
            "oracle_sha256": "C" * 64,
        }
        write_json(
            plan,
            {
                "selection": {"connection_profile_id": profile_id},
                "execution_steps": [
                    {
                        "arguments": [
                            f"{name}={value}"
                            for name, value in governance.items()
                        ]
                    }
                ],
            },
        )
        write_json(
            resolved,
            {
                "selection": {"connection_profile_id": profile_id},
                "connector": {"length_mm": float(gap)},
            },
        )
        write_json(
            budget,
            {
                "schema_version": 1,
                "role": "integration_resolved_engineering_budget",
                "integration_id": INTEGRATION_ID,
                "connection_profile_id": profile_id,
                "particle_count": 100,
                "retention_class": "compact",
                "source_identity": {
                    "run_id": source["run_id"],
                    "project_id": source["project_id"],
                    "manifest_sha256": source["manifest"]["sha256"],
                    "event_sha256": source["events"]["sha256"],
                    "metadata_sha256": source["metadata"]["sha256"],
                },
                "stage_limits": {},
                "budget_path": "fixture",
            },
        )
        write_json(
            receipt,
            {
                "schema_version": 1,
                "role": "integration_migration_execution_receipt",
                "integration_run_id": run_id,
                "connection_profile_id": profile_id,
                "composition_plan_sha256": file_sha256(plan),
                "resolved_connection_sha256": file_sha256(resolved),
                "resolved_engineering_budget_sha256": file_sha256(budget),
                **governance,
                "execution_status": "completed_not_equivalence_evaluated",
                "equivalence_status": "BLOCKED",
            },
        )
        publish_integration_run(
            repo_root=REPO_ROOT,
            workspace_root=self.workspace,
            integration_run_dir=parent,
            project_runs_root=stage_root,
            receipt_path=receipt,
            resolved_path=resolved,
            plan_path=plan,
            budget_path=budget,
        )
        return parent


class MigrationEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        (REPO_ROOT / ".tmp").mkdir(exist_ok=True)

    def test_complete_fixture_passes_then_exact_event_difference_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            fixture = MigrationFixture(Path(directory))
            result = evaluate_migration(
                repo_root=fixture.repo,
                workspace_root=fixture.workspace,
                oracle_path=fixture.oracle_path,
                preregistration_path=fixture.prereg_path,
                profile_runs=fixture.profile_runs,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(
                {item["status"] for item in result["profiles"]}, {"PASS"}
            )
            self.assertEqual(result["continuous_state"]["status"], "NOT_EVALUATED")
            parent = fixture.profile_runs[PROFILE_GAP_ONE]
            parent_config_path = parent / "run_config.json"
            parent_config = json.loads(parent_config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                parent_config["migration_governance"],
                {
                    "preregistration_sha256": "B" * 64,
                    "oracle_sha256": "C" * 64,
                },
            )
            analyzer = next(
                item
                for item in parent_config["stage_runs"]
                if item["phase"] == "analyzer_transport"
            )
            analyzer_run = fixture.workspace / analyzer["path"]
            downstream = (
                analyzer_run / "results" / "simion_downstream_particles.csv"
            )
            write_text(downstream, "Ion,Hit\n1,False\n")
            stage_manifest_path = analyzer_run / "run_manifest.json"
            stage_manifest = json.loads(
                stage_manifest_path.read_text(encoding="utf-8")
            )
            stage_manifest["outputs"] = [
                file_record(downstream)
                if Path(item["path"]).resolve() == downstream.resolve()
                else item
                for item in stage_manifest["outputs"]
            ]
            write_json(stage_manifest_path, stage_manifest)
            analyzer["manifest_sha256"] = file_sha256(stage_manifest_path)
            write_json(parent_config_path, parent_config)
            parent_manifest_path = parent / "run_manifest.json"
            parent_manifest = json.loads(
                parent_manifest_path.read_text(encoding="utf-8")
            )
            parent_manifest["run_config"] = file_record(parent_config_path)
            write_json(parent_manifest_path, parent_manifest)
            changed = evaluate_migration(
                repo_root=fixture.repo,
                workspace_root=fixture.workspace,
                oracle_path=fixture.oracle_path,
                preregistration_path=fixture.prereg_path,
                profile_runs=fixture.profile_runs,
            )
            self.assertEqual(changed["status"], "FAIL")
            gap_one = next(
                item
                for item in changed["profiles"]
                if item["connection_profile_id"] == PROFILE_GAP_ONE
            )
            self.assertIn(
                "FAIL",
                {item["status"] for item in gap_one["particle_event_sets"]},
            )


if __name__ == "__main__":
    unittest.main()
