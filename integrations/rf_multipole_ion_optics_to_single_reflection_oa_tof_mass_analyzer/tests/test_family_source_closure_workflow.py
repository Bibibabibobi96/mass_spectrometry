"""License-free workflow contracts for multipole-family source closure."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    prepare_family_source_closure,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    STAGES,
    publish_family_source_closure_run,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PROFILE_REGISTRY = INTEGRATION_ROOT / "config" / "connection_profiles.json"
ADAPTER_REGISTRY = (
    INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
)
PREREGISTRATION = (
    INTEGRATION_ROOT
    / "config"
    / "family_source_closure_preregistration.json"
)
REVISION_REGISTRY = (
    INTEGRATION_ROOT / "config" / "family_source_revision_registry.json"
)
FAMILY_EXECUTE = (
    INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
)
FAMILY_ADAPTER = FAMILY_EXECUTE.with_name("adapter.ps1")
FAMILY_PROFILES = {
    "rf_quadrupole_no_acceleration_full_length_direct_mating_gap_0mm",
    "rf_hexapole_no_acceleration_full_length_direct_mating_gap_0mm",
    "rf_octupole_no_acceleration_full_length_direct_mating_gap_0mm",
}
BRANCHES = {"comsol", "simion"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def source_evidence_available(*contract_paths: Path) -> bool:
    for contract_path in contract_paths:
        contract = load(contract_path)
        sources = (
            [contract["source"]]
            if contract["schema_version"] == 1
            else [
                branch["source"]
                for branch in contract["source_branches"].values()
            ]
        )
        for source in sources:
            for record_name in (
                "manifest",
                "state",
                "particle_source",
                "metadata",
            ):
                if not (WORKSPACE_ROOT / source[record_name]["path"]).is_file():
                    return False
    return True


FAMILY_SOURCE_EVIDENCE_AVAILABLE = source_evidence_available(
    *(
        INTEGRATION_ROOT
        / "config"
        / f"family_{family}_n100_source_contract.json"
        for family in ("quadrupole", "hexapole", "octupole")
    )
)
HEXAPOLE_HYBRID_EVIDENCE_AVAILABLE = source_evidence_available(
    INTEGRATION_ROOT
    / "config"
    / "family_hexapole_hybrid_reference_n100_source_contract.json"
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def record(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def arguments(plan: dict) -> dict[str, str]:
    return dict(
        argument.split("=", 1)
        for argument in plan["execution_steps"][0]["arguments"]
    )


class FamilySourceClosureWorkflowTests(unittest.TestCase):
    def test_family_profiles_exhaust_current_registry(self) -> None:
        registry_ids = {
            item["connection_profile_id"]
            for item in load(PROFILE_REGISTRY)["profiles"]
        }
        preregistered = {
            item["connection_profile_id"]
            for item in load(PREREGISTRATION)["profiles"]
        }
        self.assertEqual(preregistered, FAMILY_PROFILES)
        self.assertEqual(registry_ids, FAMILY_PROFILES)

    def test_public_execute_requires_branch_without_solver_selector(self) -> None:
        text = FAMILY_EXECUTE.read_text(encoding="utf-8")
        self.assertIn(
            "[Parameter(Mandatory)][ValidateSet('comsol','simion')]",
            text,
        )
        self.assertIn("[string]$SourceBranchId", text)
        self.assertNotIn("$SolverId", text)
        self.assertNotIn("[string]$Solver", text)
        self.assertNotIn("-SolverId", text)

    def test_prepare_closes_every_profile_branch_and_exact_source_budget(
        self,
    ) -> None:
        preregistered = {
            item["connection_profile_id"]: item
            for item in load(PREREGISTRATION)["profiles"]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for profile_id in sorted(FAMILY_PROFILES):
                source_contract_path = (
                    REPO_ROOT
                    / preregistered[profile_id]["source_contract"]["path"]
                )
                source_contract = load(source_contract_path)
                for branch_id in sorted(BRANCHES):
                    with self.subTest(
                        profile_id=profile_id,
                        branch_id=branch_id,
                    ):
                        output = root / profile_id / branch_id
                        resolved_path, plan_path = (
                            prepare_family_source_closure(
                                repo_root=REPO_ROOT,
                                profile_registry_path=PROFILE_REGISTRY,
                                adapter_registry_path=ADAPTER_REGISTRY,
                                preregistration_path=PREREGISTRATION,
                                revision_registry_path=REVISION_REGISTRY,
                                profile_id=profile_id,
                                source_branch_id=branch_id,
                                resolved_output=output / "resolved.json",
                                plan_output=output / "plan.json",
                            )
                        )
                        self.assertTrue(resolved_path.is_file())
                        plan = load(plan_path)
                        frozen = arguments(plan)
                        self.assertEqual(
                            frozen["source_branch_id"],
                            branch_id,
                        )
                        self.assertFalse(
                            {"oracle_sha256", "equivalence_status"}
                            & set(frozen)
                        )
                        self.assertNotIn(
                            "oracle",
                            json.dumps(plan).lower(),
                        )
                        source_branch = source_contract[
                            "source_branches"
                        ][branch_id]
                        source = source_branch["source"]
                        budget = load(
                            plan_path.with_name(
                                "resolved_engineering_budget.json"
                            )
                        )
                        self.assertEqual(
                            budget["connection_profile_id"],
                            profile_id,
                        )
                        self.assertEqual(
                            budget["source_identity"],
                            {
                                "source_branch_id": branch_id,
                                "solver_id": source_branch["solver_id"],
                                "run_id": source["run_id"],
                                "project_id": source_branch[
                                    "recorded_project_id"
                                ],
                                "manifest_sha256": source["manifest"][
                                    "sha256"
                                ],
                                "event_sha256": source["state"]["sha256"],
                                "particle_source_sha256": source[
                                    "particle_source"
                                ]["sha256"],
                                "metadata_sha256": source["metadata"][
                                    "sha256"
                                ],
                            },
                        )
                        self.assertEqual(
                            frozen["resolved_budget_sha256"],
                            file_sha256(
                                plan_path.with_name(
                                    "resolved_engineering_budget.json"
                                )
                            ),
                        )

    def test_prepare_rejects_wrong_branch_and_unknown_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            common = {
                "repo_root": REPO_ROOT,
                "profile_registry_path": PROFILE_REGISTRY,
                "adapter_registry_path": ADAPTER_REGISTRY,
                "preregistration_path": PREREGISTRATION,
                "revision_registry_path": REVISION_REGISTRY,
                "resolved_output": output / "resolved.json",
                "plan_output": output / "plan.json",
            }
            with self.assertRaisesRegex(
                ContractError,
                "source_branch_id must be",
            ):
                prepare_family_source_closure(
                    **common,
                    profile_id=next(iter(FAMILY_PROFILES)),
                    source_branch_id="solver",
                )
            with self.assertRaisesRegex(
                ContractError,
                "profile is not unique",
            ):
                prepare_family_source_closure(
                    **common,
                    profile_id="unknown_profile",
                    source_branch_id="comsol",
                )

    def test_family_adapter_has_one_transfer_runner_and_no_stage_copy(
        self,
    ) -> None:
        text = FAMILY_ADAPTER.read_text(encoding="utf-8")
        self.assertEqual(text.count("& $transferRunner"), 1)
        self.assertIn(
            "$transferRunner = $runtime.implementation.transfer_runner",
            text,
        )
        self.assertNotIn("stages/comsol", text)
        self.assertNotIn("stages\\comsol", text)
        self.assertNotIn("run_pre_pulse_interface_transport.ps1", text)
        self.assertNotIn("run_pulse_capture.ps1", text)
        self.assertNotIn("run_analyzer_transport.ps1", text)

    def test_pulse_and_analyzer_assert_and_propagate_source_identity(
        self,
    ) -> None:
        runners = (
            INTEGRATION_ROOT
            / "stages"
            / "comsol"
            / "run_pulse_capture.ps1",
            INTEGRATION_ROOT
            / "stages"
            / "cross_solver"
            / "run_analyzer_transport.ps1",
        )
        for runner in runners:
            with self.subTest(runner=runner.name):
                text = runner.read_text(encoding="utf-8")
                self.assertIn(
                    "Assert-RfOatofSourceIdentityMatches",
                    text,
                )
                self.assertIn(
                    "-Expected $runtime.source_identity",
                    text,
                )
                self.assertIn(
                    "upstream_source_identity = $runtime.source_identity",
                    text,
                )

    @unittest.skipUnless(
        FAMILY_SOURCE_EVIDENCE_AVAILABLE,
        "family source manifest/state/source evidence is incomplete",
    )
    def test_public_prepare_runs_without_commercial_software(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        with tempfile.TemporaryDirectory(dir=REPO_ROOT.parent) as directory:
            output = Path(directory)
            for profile_id in sorted(FAMILY_PROFILES):
                for branch_id in sorted(BRANCHES):
                    completed = subprocess.run(
                        [
                            pwsh,
                            "-NoProfile",
                            "-File",
                            str(FAMILY_EXECUTE),
                            "-ConnectionProfileId",
                            profile_id,
                            "-SourceBranchId",
                            branch_id,
                            "-OutputDirectory",
                            str(output / profile_id / branch_id),
                            "-PythonExe",
                            sys.executable,
                            "-PrepareOnly",
                        ],
                        cwd=REPO_ROOT,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        timeout=60,
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stdout + completed.stderr,
                    )
                    self.assertIn(
                        "FAMILY_SOURCE_CLOSURE_ADAPTER=PREPARED",
                        completed.stdout,
                    )
                    self.assertIn(
                        f"SOURCE_BRANCH={branch_id}",
                        completed.stdout,
                    )

    def test_hexapole_hybrid_revision_is_closed_and_comsol_only(self) -> None:
        profile_id = (
            "rf_hexapole_no_acceleration_full_length_"
            "direct_mating_gap_0mm"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            _, plan_path = prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                preregistration_path=PREREGISTRATION,
                revision_registry_path=REVISION_REGISTRY,
                profile_id=profile_id,
                source_branch_id="comsol",
                source_revision_id="hexapole_hybrid_reference",
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            frozen = arguments(load(plan_path))
            self.assertEqual(
                frozen["source_revision_id"],
                "hexapole_hybrid_reference",
            )
            self.assertIn(
                "hybrid_reference",
                frozen["runtime_binding_path"],
            )
            budget = load(
                plan_path.with_name("resolved_engineering_budget.json")
            )
            self.assertEqual(
                budget["source_identity"]["run_id"],
                "20260730_152000__sim__comsol__"
                "hex-noacc-hybrid-exit025-t160__r04",
            )
            self.assertEqual(
                budget["source_revision_id"],
                "hexapole_hybrid_reference",
            )
            with self.assertRaisesRegex(
                ContractError,
                "source branch is not authorized by the revision",
            ):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    preregistration_path=PREREGISTRATION,
                    revision_registry_path=REVISION_REGISTRY,
                    profile_id=profile_id,
                    source_branch_id="simion",
                    source_revision_id="hexapole_hybrid_reference",
                    resolved_output=output / "rejected_resolved.json",
                    plan_output=output / "rejected_plan.json",
                )

    def test_revision_registry_rejects_duplicate_unselected_key(self) -> None:
        registry = load(REVISION_REGISTRY)
        registry["revisions"].append(
            json.loads(json.dumps(registry["revisions"][0]))
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            duplicate_registry = output / "revision_registry.json"
            write_json(duplicate_registry, registry)
            with self.assertRaisesRegex(
                ContractError,
                "source revision registry contains duplicate keys",
            ):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    preregistration_path=PREREGISTRATION,
                    revision_registry_path=duplicate_registry,
                    profile_id=next(iter(sorted(FAMILY_PROFILES))),
                    source_branch_id="comsol",
                    resolved_output=output / "resolved.json",
                    plan_output=output / "plan.json",
                )

    def test_revision_preregistration_requires_all_frozen_metrics(self) -> None:
        preregistration = load(
            INTEGRATION_ROOT
            / "config"
            / (
                "family_hexapole_hybrid_reference_"
                "source_revision_preregistration.json"
            )
        )
        preregistration["comparison"]["required_metrics"].pop()
        with self.assertRaises(ContractError):
            validate_schema(
                preregistration,
                (
                    "integration_family_source_revision_"
                    "preregistration.schema.json"
                ),
            )

    @unittest.skipUnless(
        HEXAPOLE_HYBRID_EVIDENCE_AVAILABLE,
        "hexapole hybrid manifest/state/source evidence is incomplete",
    )
    def test_public_hybrid_prepare_with_external_evidence(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        profile_id = (
            "rf_hexapole_no_acceleration_full_length_"
            "direct_mating_gap_0mm"
        )
        with tempfile.TemporaryDirectory(dir=REPO_ROOT.parent) as directory:
            output = Path(directory) / "hybrid"
            command = [
                pwsh,
                "-NoProfile",
                "-File",
                str(FAMILY_EXECUTE),
                "-ConnectionProfileId",
                profile_id,
                "-SourceBranchId",
                "comsol",
                "-SourceRevisionId",
                "hexapole_hybrid_reference",
                "-OutputDirectory",
                str(output),
                "-PythonExe",
                sys.executable,
                "-PrepareOnly",
            ]
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=60,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )
            self.assertIn(
                "SOURCE_REVISION=hexapole_hybrid_reference",
                completed.stdout,
            )

    def test_public_hybrid_rejects_unauthorized_source_branch(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        profile_id = (
            "rf_hexapole_no_acceleration_full_length_"
            "direct_mating_gap_0mm"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "simion"
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(FAMILY_EXECUTE),
                    "-ConnectionProfileId",
                    profile_id,
                    "-SourceBranchId",
                    "simion",
                    "-SourceRevisionId",
                    "hexapole_hybrid_reference",
                    "-OutputDirectory",
                    str(output),
                    "-PythonExe",
                    sys.executable,
                    "-PrepareOnly",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=60,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "source branch is not authorized by the revision",
                completed.stdout + completed.stderr,
            )

    def test_family_adapter_rejects_tampered_revision_binding(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        profile_id = (
            "rf_hexapole_no_acceleration_full_length_"
            "direct_mating_gap_0mm"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hybrid"
            _, plan_path = prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                preregistration_path=PREREGISTRATION,
                revision_registry_path=REVISION_REGISTRY,
                profile_id=profile_id,
                source_branch_id="comsol",
                source_revision_id="hexapole_hybrid_reference",
                resolved_output=output / "resolved_connection.json",
                plan_output=output / "composition_plan.json",
            )
            plan_path = output / "composition_plan.json"
            plan = load(plan_path)
            arguments = plan["execution_steps"][0]["arguments"]
            arguments[
                next(
                    index
                    for index, value in enumerate(arguments)
                    if value.startswith("runtime_binding_sha256=")
                )
            ] = "runtime_binding_sha256=" + "A" * 64
            write_json(plan_path, plan)
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(FAMILY_ADAPTER),
                    "-CompositionPlan",
                    str(plan_path),
                    "-ResolvedConnection",
                    str(output / "resolved_connection.json"),
                    "-PythonExe",
                    sys.executable,
                    "-RepoRoot",
                    str(REPO_ROOT),
                    "-PrepareOnly",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=60,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "runtime binding differs from its revision registry",
                completed.stdout + completed.stderr,
            )

    def test_parent_publisher_requires_explicit_source_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = (
                "20260730_120000__analysis__cross__"
                "family-source-closure"
            )
            run_dir = root / run_id
            run_dir.mkdir()
            receipt = run_dir / "receipt.json"
            resolved = run_dir / "resolved.json"
            plan = run_dir / "plan.json"
            budget = run_dir / "budget.json"
            write_json(
                receipt,
                {
                    "role": (
                        "integration_family_source_closure_execution_receipt"
                    ),
                    "integration_run_id": run_id,
                    "execution_status": (
                        "completed_pending_paired_analysis"
                    ),
                },
            )
            write_json(
                resolved,
                {"integration_id": INTEGRATION_ROOT.name},
            )
            write_json(plan, {"integration_id": INTEGRATION_ROOT.name})
            write_json(budget, {"source_revision_id": "baseline"})
            with self.assertRaisesRegex(
                ContractError,
                "source revision identity is missing",
            ):
                publish_family_source_closure_run(
                    repo_root=REPO_ROOT,
                    workspace_root=root,
                    integration_run_dir=run_dir,
                    receipt_path=receipt,
                    resolved_path=resolved,
                    plan_path=plan,
                    budget_path=budget,
                )

    def test_parent_publisher_rejects_pulse_or_analyzer_identity_mismatch(
        self,
    ) -> None:
        for tampered_phase in ("pulse_capture", "analyzer_transport"):
            with self.subTest(tampered_phase=tampered_phase):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    run_id = (
                        "20260730_120000__analysis__cross__"
                        "family-source-closure"
                    )
                    run_dir = workspace / "parent" / run_id
                    run_dir.mkdir(parents=True)
                    profile_id = next(iter(sorted(FAMILY_PROFILES)))
                    project_id = "rf_quadrupole_ion_optics"
                    source_identity = {
                        "source_branch_id": "comsol",
                        "solver_id": "comsol",
                        "run_id": "source_run",
                        "project_id": project_id,
                        "manifest_sha256": "A" * 64,
                        "event_sha256": "B" * 64,
                        "particle_source_sha256": "C" * 64,
                        "metadata_sha256": "D" * 64,
                    }
                    receipt = run_dir / "receipt.json"
                    resolved = run_dir / "resolved.json"
                    runtime = run_dir / "runtime.json"
                    plan = run_dir / "plan.json"
                    budget = run_dir / "budget.json"
                    write_json(runtime, {"role": "runtime_fixture"})
                    write_json(
                        resolved,
                        {
                            "integration_id": INTEGRATION_ROOT.name,
                            "selection": {
                                "connection_profile_id": profile_id,
                                "upstream_project_id": project_id,
                            },
                        },
                    )
                    write_json(
                        receipt,
                        {
                            "role": (
                                "integration_family_source_closure_"
                                "execution_receipt"
                            ),
                            "integration_run_id": run_id,
                            "execution_status": (
                                "completed_pending_paired_analysis"
                            ),
                            "connection_profile_id": profile_id,
                            "source_branch_id": "comsol",
                            "source_revision_id": "baseline",
                            "source_identity": source_identity,
                            "runtime_binding_sha256": file_sha256(runtime),
                            "stage_run_ids": {
                                phase: "20260730_120000"
                                + contract["run_suffix"]
                                for phase, contract in STAGES.items()
                            },
                            "stage_runtime_binding_sha256s": {
                                phase: file_sha256(runtime)
                                for phase in STAGES
                            },
                            "resolved_connection_sha256": file_sha256(
                                resolved
                            ),
                        },
                    )
                    write_json(
                        plan,
                        {
                            "integration_id": INTEGRATION_ROOT.name,
                            "selection": {
                                "connection_profile_id": profile_id
                            },
                        },
                    )
                    write_json(
                        budget,
                        {
                            "connection_profile_id": profile_id,
                            "source_revision_id": "baseline",
                            "source_identity": source_identity,
                        },
                    )
                    stage_root = (
                        workspace
                        / "artifacts"
                        / "projects"
                        / project_id
                        / "runs"
                    )
                    for phase, contract in STAGES.items():
                        stage = stage_root / (
                            "20260730_120000" + contract["run_suffix"]
                        )
                        stage.mkdir(parents=True)
                        propagated = dict(source_identity)
                        if phase == tampered_phase:
                            propagated["event_sha256"] = "E" * 64
                        run_config = {
                            "schema_version": 2,
                            "run_id": stage.name,
                            "project": project_id,
                            "mode": contract["mode"],
                            "parameters": {
                                "connection_profile_id": profile_id,
                                "source_branch_id": "comsol",
                            },
                            "inputs": {
                                "runtime_binding": str(runtime.resolve()),
                                "resolved_connection": str(
                                    resolved.resolve()
                                ),
                            },
                            (
                                "source_particle_identity"
                                if phase
                                == "pre_pulse_interface_transport"
                                else "upstream_source_identity"
                            ): propagated,
                        }
                        write_json(stage / "run_config.json", run_config)
                        write_json(
                            stage / "run_manifest.json",
                            {
                                "role": "simulation_run_manifest",
                                "run_id": stage.name,
                                "project": project_id,
                                "mode": contract["mode"],
                                "status": "success",
                                "run_config": record(
                                    stage / "run_config.json"
                                ),
                            },
                        )
                        if phase == "analyzer_transport":
                            write_json(
                                stage / "summary.json",
                                {"census": {}},
                            )
                    with self.assertRaisesRegex(
                        ContractError,
                        "family stage source/profile identity differs: "
                        f"{tampered_phase}",
                    ):
                        publish_family_source_closure_run(
                            repo_root=REPO_ROOT,
                            workspace_root=workspace,
                            integration_run_dir=run_dir,
                            receipt_path=receipt,
                            resolved_path=resolved,
                            plan_path=plan,
                            budget_path=budget,
                        )


if __name__ == "__main__":
    unittest.main()
