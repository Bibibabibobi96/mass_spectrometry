from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.simion import batch_continuation
from common.simion.batch_continuation import (
    WholeUnitReplayUnit,
    build_whole_unit_replay_plan,
)


def _parent(root: Path, batches: list[list[int]], logs: list[list[str]]) -> tuple[Path, str]:
    run = root / "parent"
    (run / "inputs").mkdir(parents=True)
    (run / "logs").mkdir()
    contract = run / "inputs" / "screening.json"
    contract.write_text("{}\n", encoding="utf-8")
    cohort = run / "inputs" / "cohort.csv"
    cohort.write_text("particle_id,state\n1,fixture\n", encoding="utf-8")
    plan = {"role": "simion_single_wave_particle_batch_plan", "batches": [
        {"index": index, "particle_id_min": ids[0], "particle_id_max": ids[-1], "count": len(ids)}
        for index, ids in enumerate(batches, start=1)
    ]}
    (run / "inputs" / "simion_execution_batch_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    count = sum(map(len, batches))
    config = run / "run_config.json"
    config.write_text(json.dumps({
        "parameters": {"execution_mode": "fixture", "particle_count": count, "launched_particle_count": count},
        "inputs": {
            "screening_contract": str(contract.resolve()),
            "simion_execution_batch_plan": str((run / "inputs" / "simion_execution_batch_plan.json").resolve()),
            "cohort": str(cohort.resolve()),
        },
    }), encoding="utf-8")
    outputs = []
    for index, lines in enumerate(logs, start=1):
        path = run / "logs" / f"simion__batch{index:02d}.stdout.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        outputs.append({"path": str(path), "sha256": file_sha256(path)})
    inputs = {key: {"path": str(path.resolve()), "exists": True, "sha256": file_sha256(path)} for key, path in {
        "screening_contract": contract,
        "simion_execution_batch_plan": run / "inputs" / "simion_execution_batch_plan.json",
        "cohort": cohort,
    }.items()}
    (run / "run_manifest.json").write_text(json.dumps({"role": "simulation_run_manifest", "run_id": "parent", "status": "interrupted", "run_config": {"sha256": file_sha256(config)}, "inputs": inputs, "outputs": outputs}), encoding="utf-8")
    return run, file_sha256(contract)


class BatchContinuationTests(unittest.TestCase):
    def test_checkpoint_accepts_completion_metadata_after_config_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            config_path = run / "run_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config.update({"run_id": "parent", "mode": "fixture"})
            config["parameters"]["completion_metadata"] = {"batch": 1}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update({"status": "checkpoint", "mode": "fixture"})
            # Keep the old run-config digest: this models a native batch that
            # completed after the checkpoint was published.
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            unit = WholeUnitReplayUnit("complete", (Path("logs/simion__batch01.stdout.log"),), True)
            plan = build_whole_unit_replay_plan(
                predecessor_run_dir=run, output_dir=root / "child", units=(unit,),
            )
            (run / "inputs" / "cohort.csv").write_text("changed immutable input\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "run config is unbound"):
                build_whole_unit_replay_plan(
                    predecessor_run_dir=run, output_dir=root / "invalid-child", units=(unit,),
                )

        self.assertEqual(plan["reusable_unit_count"], 1)

    def test_whole_unit_replay_reuses_only_complete_manifest_bound_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            stable = run / "results" / "stable.json"
            stable.parent.mkdir()
            stable.write_text("stable\n", encoding="utf-8")
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
            manifest["outputs"].append({"path": str(stable), "sha256": file_sha256(stable)})
            (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            plan = build_whole_unit_replay_plan(
                predecessor_run_dir=run,
                output_dir=root / "child",
                units=(
                    WholeUnitReplayUnit("stable", (Path("results/stable.json"),), True),
                    WholeUnitReplayUnit("missing", (Path("results/missing.json"),), True),
                ),
            )
        self.assertEqual([unit["action"] for unit in plan["units"]], ["reuse", "replay"])

    def test_whole_unit_replay_replays_bound_partial_output_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            partial = run / "results" / "partial.stdout.log"
            partial.parent.mkdir()
            partial.write_text("partial native output\n", encoding="utf-8")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"].append({"path": str(partial), "sha256": file_sha256(partial)})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(batch_continuation, "file_sha256", wraps=file_sha256) as hashed:
                plan = build_whole_unit_replay_plan(
                    predecessor_run_dir=run,
                    output_dir=root / "child",
                    units=(WholeUnitReplayUnit(
                        "partial", (Path("results/partial.stdout.log"),), False,
                    ),),
                )
        self.assertEqual(plan["units"][0]["action"], "replay")
        self.assertEqual(plan["units"][0]["terminal_outputs"], [])
        self.assertNotIn(partial.resolve(), [call.args[0] for call in hashed.call_args_list])

    def test_whole_unit_replay_rejects_non_boolean_completion_fact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            with self.assertRaisesRegex(ContractError, "completion fact"):
                build_whole_unit_replay_plan(
                    predecessor_run_dir=run,
                    output_dir=root / "child",
                    units=(WholeUnitReplayUnit(
                        "invalid", (Path("results/output.json"),), 1,  # type: ignore[arg-type]
                    ),),
                )

    def test_whole_unit_replay_rejects_unbound_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            stale = run / "results" / "stale.json"
            stale.parent.mkdir()
            stale.write_text("stale\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "manifest-bound"):
                build_whole_unit_replay_plan(
                    predecessor_run_dir=run, output_dir=root / "child",
                    units=(WholeUnitReplayUnit("stale", (Path("results/stale.json"),), True),),
                )
            with self.assertRaisesRegex(ContractError, "manifest-bound"):
                build_whole_unit_replay_plan(
                    predecessor_run_dir=run, output_dir=root / "absolute-child",
                    units=(WholeUnitReplayUnit("stale", (stale.resolve(),), True),),
                )

    def test_whole_unit_replay_rejects_hash_drift_for_complete_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            output = run / "results" / "complete.json"
            output.parent.mkdir()
            output.write_text("published\n", encoding="utf-8")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"].append({"path": str(output), "sha256": file_sha256(output)})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "hash differs"):
                build_whole_unit_replay_plan(
                    predecessor_run_dir=run,
                    output_dir=root / "child",
                    units=(WholeUnitReplayUnit("complete", (Path("results/complete.json"),), True),),
                )

    def test_whole_unit_replay_reuses_current_parent_bound_ancestor_and_local_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ancestor, _ = _parent(root / "ancestor", [[1]], [["TERMINAL 1", "COMPLETE"]])
            ancestor_output = ancestor / "results" / "batch01.native.log"
            ancestor_output.parent.mkdir()
            ancestor_output.write_text("ancestor complete\n", encoding="utf-8")
            ancestor_manifest_path = ancestor / "run_manifest.json"
            ancestor_manifest = json.loads(ancestor_manifest_path.read_text(encoding="utf-8"))
            ancestor_manifest["outputs"].append({
                "path": str(ancestor_output), "sha256": file_sha256(ancestor_output),
            })
            ancestor_manifest_path.write_text(json.dumps(ancestor_manifest), encoding="utf-8")
            build_whole_unit_replay_plan(
                predecessor_run_dir=ancestor,
                output_dir=root / "b-plan",
                units=(WholeUnitReplayUnit("ancestor", (Path("results/batch01.native.log"),), True),),
            )

            parent, _ = _parent(root / "parent", [[2]], [["TERMINAL 2"]])
            parent_output = parent / "results" / "batch02.native.log"
            parent_output.parent.mkdir()
            parent_output.write_text("parent complete\n", encoding="utf-8")
            parent_config_path = parent / "run_config.json"
            parent_config = json.loads(parent_config_path.read_text(encoding="utf-8"))
            parent_config["inputs"]["reused_ancestor_output"] = str(ancestor_output)
            parent_config_path.write_text(json.dumps(parent_config), encoding="utf-8")
            parent_manifest_path = parent / "run_manifest.json"
            parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
            parent_manifest["run_config"]["sha256"] = file_sha256(parent_config_path)
            parent_manifest["inputs"]["reused_ancestor_output"] = {
                "path": str(ancestor_output), "exists": True, "sha256": file_sha256(ancestor_output),
            }
            parent_manifest["outputs"].append({
                "path": str(parent_output), "sha256": file_sha256(parent_output),
            })
            parent_manifest_path.write_text(json.dumps(parent_manifest), encoding="utf-8")
            ancestor_before, parent_before = ancestor_manifest_path.read_bytes(), parent_manifest_path.read_bytes()

            plan = build_whole_unit_replay_plan(
                predecessor_run_dir=parent,
                output_dir=root / "child",
                units=(
                    WholeUnitReplayUnit("ancestor", (ancestor_output,), True),
                    WholeUnitReplayUnit("parent", (Path("results/batch02.native.log"),), True),
                ),
            )

            self.assertEqual([unit["action"] for unit in plan["units"]], ["reuse", "reuse"])
            self.assertEqual(
                [unit["terminal_outputs"][0]["path"] for unit in plan["units"]],
                [str(ancestor_output.resolve()), str(parent_output.resolve())],
            )
            self.assertEqual(ancestor_manifest_path.read_bytes(), ancestor_before)
            self.assertEqual(parent_manifest_path.read_bytes(), parent_before)
            self.assertEqual(
                list((root / "child").iterdir()),
                [root / "child" / "simion_whole_unit_replay_plan.json"],
            )

    def test_whole_unit_replay_rejects_conflicting_current_parent_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = _parent(root, [[1]], [["TERMINAL 1"]])
            output = run / "results" / "complete.json"
            output.parent.mkdir()
            output.write_text("complete\n", encoding="utf-8")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["inputs"]["conflicting_output"] = {
                "path": str(output), "exists": True, "sha256": "A" * 64,
            }
            manifest["outputs"].append({"path": str(output), "sha256": file_sha256(output)})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "binding conflicts"):
                build_whole_unit_replay_plan(
                    predecessor_run_dir=run,
                    output_dir=root / "child",
                    units=(WholeUnitReplayUnit("complete", (Path("results/complete.json"),), True),),
                )


if __name__ == "__main__":
    unittest.main()
