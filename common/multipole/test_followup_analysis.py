import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from common.multipole.followup_analysis import (
    analyze_pair,
    engineering_batch,
    factorial_interaction,
    fixed_bin_index,
    load_engineering_batch_plan,
    main,
    normalized_cell_xyz,
    write_json,
)


class FollowupAnalysisTests(unittest.TestCase):
    def engineering_fixture(
        self, root: Path, *, axis: str = "temporal"
    ) -> tuple[Path, Path, Path]:
        contract_root = root / "common" / "multipole"
        contract_root.mkdir(parents=True)
        source_root = Path(__file__).parent
        functional_path = contract_root / "functional_transport_acceptance.json"
        policy_path = contract_root / "engineering_progression_acceptance.json"
        functional_path.write_bytes(
            (source_root / functional_path.name).read_bytes()
        )
        policy_path.write_bytes((source_root / policy_path.name).read_bytes())

        plan_root = root / "batch"
        plan_root.mkdir()
        for name in ("a.json", "b.json", "c.json"):
            (plan_root / name).write_text("{}\n", encoding="utf-8")
        plan = {
            "schema_version": 1,
            "role": "multipole_engineering_reanalysis_plan",
            "runs": {
                "a": {"manifest": "a.json"},
                "b": {"manifest": "b.json"},
                "c": {"manifest": "c.json"},
            },
            "comparisons": [
                {
                    "comparison_id": "a-b",
                    "baseline": "a",
                    "peer": "b",
                    "axis": axis,
                },
                {
                    "comparison_id": "b-c",
                    "baseline": "b",
                    "peer": "c",
                    "axis": axis,
                },
            ],
        }
        plan_path = plan_root / "plan.json"
        plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        return plan_path, policy_path, functional_path

    def test_pair_rejects_empty_comparison_id_before_loading_runs(self) -> None:
        with self.assertRaisesRegex(ValueError, "comparison_id"):
            analyze_pair(
                Path("left.json"),
                Path("right.json"),
                Path("resolution.json"),
                " ",
            )

    def test_legacy_and_anisotropic_cells_normalize(self) -> None:
        self.assertEqual(
            normalized_cell_xyz({"cell_mm": 0.3}),
            (0.3, 0.3, 0.3),
        )
        self.assertEqual(
            normalized_cell_xyz(
                {"cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.3}}
            ),
            (0.2, 0.2, 0.3),
        )

    def test_fixed_bin_edges_are_closed_at_upper_bound(self) -> None:
        specification = {"minimum": 0.0, "maximum": 4.0, "count": 4}
        self.assertEqual(fixed_bin_index(0.0, specification), 0)
        self.assertEqual(fixed_bin_index(3.999, specification), 3)
        self.assertEqual(fixed_bin_index(4.0, specification), 3)
        with self.assertRaisesRegex(ValueError, "outside"):
            fixed_bin_index(4.1, specification)

    def test_factorial_interaction_reports_signed_and_particle_rms(self) -> None:
        def run(value: float) -> dict:
            observables = {
                "rms_radius": value,
                "rms_divergence": value,
                "mean_energy": value,
                "mean_tof": value,
            }
            row = {
                "transverse_x_mm": value,
                "transverse_y_mm": value,
                "velocity_x_m_s": value,
                "velocity_y_m_s": value,
                "elapsed_time_us": value,
                "kinetic_energy_eV": value,
            }
            return {
                "observables": observables,
                "handoff_particle_ids": [1],
                "_handoff": {1: row},
            }

        result = factorial_interaction(
            {"A": run(1.0), "R": run(2.0), "Z": run(3.0), "I": run(7.0)}
        )
        self.assertEqual(
            result["summary_observable_signed_interaction"]["rms_radius"], 3.0
        )
        self.assertEqual(
            result["paired_particle_interaction_rms"]["kinetic_energy_eV"], 3.0
        )

    def test_engineering_batch_loads_runs_once_and_preserves_order(self) -> None:
        with TemporaryDirectory() as directory:
            plan, policy, functional = self.engineering_fixture(Path(directory))
            loaded: list[str] = []

            def loader(path: Path) -> dict:
                loaded.append(path.stem)
                return {
                    "run_id": path.stem,
                    "project": "multipole",
                    "solver": "COMSOL",
                }

            def evaluator(left: dict, right: dict, axis: str, contract: dict) -> dict:
                self.assertEqual(axis, "temporal")
                self.assertEqual(contract["claim_profile"], "engineering_progression")
                status = (
                    "PASS"
                    if (left["run_id"], right["run_id"]) == ("a", "b")
                    else "NOT_EVALUATED_DO_NOT_PROGRESS"
                )
                return {
                    "claim_profile": "engineering_progression",
                    "status": status,
                    "engineering_progression_status": status,
                }

            result = engineering_batch(
                plan,
                policy,
                functional,
                run_loader=loader,
                evaluator=evaluator,
            )

            self.assertEqual(loaded, ["a", "b", "c"])
            self.assertEqual(
                [item["comparison_id"] for item in result["comparisons"]],
                ["a-b", "b-c"],
            )
            self.assertEqual(
                result["decision_status"], "NOT_EVALUATED_DO_NOT_PROGRESS"
            )
            self.assertEqual(
                result["comparison_counts"],
                {"PASS": 1, "FAIL": 0, "NOT_EVALUATED_DO_NOT_PROGRESS": 1},
            )
            self.assertEqual(len(result["plan"]["sha256"]), 64)
            self.assertEqual(
                result["contracts"]["policy"]["status"],
                "DRAFT_PENDING_ENERGY_THRESHOLDS",
            )

    def test_engineering_batch_fail_precedes_not_evaluated(self) -> None:
        with TemporaryDirectory() as directory:
            plan, policy, functional = self.engineering_fixture(Path(directory))
            statuses = iter(["NOT_EVALUATED_DO_NOT_PROGRESS", "FAIL"])

            result = engineering_batch(
                plan,
                policy,
                functional,
                run_loader=lambda path: {
                    "run_id": path.stem,
                    "project": "multipole",
                    "solver": "COMSOL",
                },
                evaluator=lambda *_: {
                    "claim_profile": "engineering_progression",
                    "status": (status := next(statuses)),
                    "engineering_progression_status": status,
                },
            )

            self.assertEqual(result["decision_status"], "FAIL")

    def test_draft_engineering_policy_cannot_aggregate_to_pass(self) -> None:
        with TemporaryDirectory() as directory:
            plan, policy, functional = self.engineering_fixture(Path(directory))
            result = engineering_batch(
                plan,
                policy,
                functional,
                run_loader=lambda path: {
                    "run_id": path.stem,
                    "project": "multipole",
                    "solver": "COMSOL",
                },
                evaluator=lambda *_: {
                    "claim_profile": "engineering_progression",
                    "status": "PASS",
                    "engineering_progression_status": "PASS",
                },
            )
            self.assertEqual(
                result["decision_status"], "NOT_EVALUATED_DO_NOT_PROGRESS"
            )

    def test_active_engineering_policy_can_aggregate_to_pass(self) -> None:
        with TemporaryDirectory() as directory:
            plan, policy, functional = self.engineering_fixture(Path(directory))
            policy_document = json.loads(policy.read_text(encoding="utf-8"))
            policy_document["status"] = "ACTIVE_ENGINEERING_PROGRESSION_POLICY"
            energy = policy_document["continuous_engineering_acceptance"][
                "energy_observables"
            ]
            for entry in energy.values():
                entry["maximum"] = 0.5
                entry["status"] = "APPROVED"
            policy.write_text(json.dumps(policy_document), encoding="utf-8")

            result = engineering_batch(
                plan,
                policy,
                functional,
                run_loader=lambda path: {
                    "run_id": path.stem,
                    "project": "multipole",
                    "solver": "COMSOL",
                },
                evaluator=lambda *_: {
                    "claim_profile": "engineering_progression",
                    "status": "PASS",
                    "engineering_progression_status": "PASS",
                },
            )
            self.assertEqual(result["decision_status"], "PASS")

    def test_engineering_plan_rejects_escape_and_unsupported_axis(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, _ = self.engineering_fixture(root)
            document = json.loads(plan.read_text(encoding="utf-8"))
            document["runs"]["a"]["manifest"] = "../outside.json"
            (plan.parent.parent / "outside.json").write_text("{}\n", encoding="utf-8")
            plan.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                load_engineering_batch_plan(plan)

            document["runs"]["a"]["manifest"] = "a.json"
            document["comparisons"][0]["axis"] = "mesh_strategy"
            plan.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                load_engineering_batch_plan(plan)

    def test_engineering_plan_rejects_noninteger_version_and_aliases(self) -> None:
        with TemporaryDirectory() as directory:
            plan, _, _ = self.engineering_fixture(Path(directory))
            document = json.loads(plan.read_text(encoding="utf-8"))
            document["schema_version"] = True
            plan.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity differs"):
                load_engineering_batch_plan(plan)

            document["schema_version"] = 1
            document["runs"]["b"]["manifest"] = "a.json"
            plan.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifests must be unique"):
                load_engineering_batch_plan(plan)

    def test_engineering_batch_rejects_manifest_changed_while_loading(self) -> None:
        with TemporaryDirectory() as directory:
            plan, policy, functional = self.engineering_fixture(Path(directory))

            def loader(path: Path) -> dict:
                if path.stem == "a":
                    path.write_text('{"changed": true}\n', encoding="utf-8")
                return {
                    "run_id": path.stem,
                    "project": "multipole",
                    "solver": "COMSOL",
                }

            with self.assertRaisesRegex(ValueError, "changed during loading"):
                engineering_batch(
                    plan,
                    policy,
                    functional,
                    run_loader=loader,
                    evaluator=lambda *_: {},
                )

    def test_engineering_batch_rejects_plan_changed_during_analysis(self) -> None:
        with TemporaryDirectory() as directory:
            plan, policy, functional = self.engineering_fixture(Path(directory))

            def evaluator(*_: object) -> dict:
                plan.write_text('{"changed": true}\n', encoding="utf-8")
                return {
                    "claim_profile": "engineering_progression",
                    "status": "PASS",
                    "engineering_progression_status": "PASS",
                }

            with self.assertRaisesRegex(ValueError, "plan changed during analysis"):
                engineering_batch(
                    plan,
                    policy,
                    functional,
                    run_loader=lambda path: {
                        "run_id": path.stem,
                        "project": "multipole",
                        "solver": "COMSOL",
                    },
                    evaluator=evaluator,
                )

    def test_write_json_replaces_atomically_without_temp_residue(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            output.write_text("old", encoding="utf-8")
            with patch(
                "common.multipole.followup_analysis.os.replace",
                wraps=os.replace,
            ) as replace:
                write_json(output, {"status": "PASS"})
                first_temporary = Path(replace.call_args.args[0])
                write_json(output, {"status": "PASS"})
                second_temporary = Path(replace.call_args.args[0])
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"status": "PASS"},
            )
            self.assertNotEqual(first_temporary, second_temporary)
            self.assertFalse(first_temporary.exists())
            self.assertFalse(second_temporary.exists())

    def test_engineering_cli_returns_zero_for_not_evaluated(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            arguments = [
                "followup_analysis.py",
                "--output",
                str(output),
                "engineering-batch",
                "--plan",
                "plan.json",
                "--engineering-policy",
                "policy.json",
                "--functional-contract",
                "functional.json",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch(
                    "common.multipole.followup_analysis.engineering_batch",
                    return_value={
                        "decision_status": "NOT_EVALUATED_DO_NOT_PROGRESS"
                    },
                ),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["decision_status"],
                "NOT_EVALUATED_DO_NOT_PROGRESS",
            )

    def test_engineering_cli_propagates_structural_error(self) -> None:
        with TemporaryDirectory() as directory:
            arguments = [
                "followup_analysis.py",
                "--output",
                str(Path(directory) / "result.json"),
                "engineering-batch",
                "--plan",
                "plan.json",
                "--engineering-policy",
                "policy.json",
                "--functional-contract",
                "functional.json",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch(
                    "common.multipole.followup_analysis.engineering_batch",
                    side_effect=ValueError("invalid plan"),
                ),
                self.assertRaisesRegex(ValueError, "invalid plan"),
            ):
                main()


if __name__ == "__main__":
    unittest.main()
