from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.simion.batch_continuation import (
    TraceContinuationPolicy,
    WholeUnitReplayUnit,
    build_batch_continuation_plan,
    build_whole_unit_replay_plan,
)


POLICY = TraceContinuationPolicy(
    terminal_prefix="TERMINAL ",
    terminal_pattern=re.compile(r"TERMINAL (?P<particle_id>\d+)$"),
    state_prefix="STATE ",
    state_pattern=re.compile(r"STATE (?P<particle_id>\d+) (?P<sample_index>\d+)$"),
    completion_prefix="COMPLETE",
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
    def _build(self, run: Path, contract: str, output: Path, ids: list[int]) -> dict:
        return build_batch_continuation_plan(
            predecessor_run_dir=run, particle_ids=ids, expected_execution_mode="fixture",
            contract_input_role="screening_contract", expected_contract_sha256=contract,
            cohort_input_paths={"cohort": run / "inputs" / "cohort.csv"},
            policy=POLICY, output_dir=output,
        )

    def test_preserves_only_a_contiguous_prefix_of_complete_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, contract = _parent(root, [[1, 2], [3, 4], [5, 6]], [
                ["TERMINAL 1", "TERMINAL 2", "COMPLETE"], ["TERMINAL 3"],
                ["TERMINAL 5", "TERMINAL 6", "COMPLETE"],
            ])
            plan = self._build(run, contract, root / "child", list(range(1, 7)))
        # Batch 2 did not finish; batch 3's otherwise complete raw log cannot
        # leapfrog it into a global mother-cohort checkpoint.
        self.assertEqual([entry["replay_particle_count"] for entry in plan["batches"]], [0, 2, 2])
        self.assertEqual(plan["completed_particle_count"], 2)

    def test_rejects_partial_or_appended_completed_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, contract = _parent(root, [[1, 2]], [["TERMINAL 1", "COMPLETE"]])
            with self.assertRaisesRegex(ContractError, "completion sentinel"):
                self._build(run, contract, root / "partial", [1, 2])
            run, contract = _parent(root / "appended", [[1]], [["TERMINAL 1", "COMPLETE", "noise"]])
            with self.assertRaisesRegex(ContractError, "completion sentinel"):
                self._build(run, contract, root / "appended-child", [1])

    def test_ignores_unmanifested_active_suffix_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, contract = _parent(root, [[1], [2]], [
                ["TERMINAL 1", "COMPLETE"], ["TERMINAL 2"],
            ])
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # The first batch was checkpointed before the host interruption;
            # stdout from the active second worker exists but is not bound.
            manifest["outputs"] = manifest["outputs"][:1]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            plan = self._build(run, contract, root / "child", [1, 2])
        self.assertEqual(plan["completed_particle_count"], 1)
        self.assertEqual(
            [entry["replay_particle_count"] for entry in plan["batches"]], [0, 1]
        )

    def test_rejects_noncontiguous_prefix_and_manifest_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, contract = _parent(root, [[1, 2]], [["TERMINAL 2"]])
            with self.assertRaisesRegex(ContractError, "contiguous"):
                self._build(run, contract, root / "child", [1, 2])
            run, contract = _parent(root / "other", [[1]], [["TERMINAL 1", "COMPLETE"]])
            (run / "logs" / "simion__batch01.stdout.log").write_text("TERMINAL 1\nCOMPLETE\nchanged\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "hash"):
                self._build(run, contract, root / "other-child", [1])

    def test_rejects_unbound_batch_plan_and_different_same_size_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, contract = _parent(root, [[1, 2]], [["TERMINAL 1"]])
            plan_path = run / "inputs" / "simion_execution_batch_plan.json"
            plan_path.write_text(json.dumps({"role": "simion_single_wave_particle_batch_plan", "batches": [
                {"index": 1, "particle_id_min": 1, "particle_id_max": 2, "count": 2},
            ], "tampered": True}), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "input hash"):
                self._build(run, contract, root / "child", [1, 2])
            run, contract = _parent(root / "cohort", [[1]], [["TERMINAL 1", "COMPLETE"]])
            other = root / "other_cohort.csv"
            other.write_text("particle_id,state\n1,other\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "frozen cohort"):
                build_batch_continuation_plan(
                    predecessor_run_dir=run, particle_ids=[1], expected_execution_mode="fixture",
                    contract_input_role="screening_contract", expected_contract_sha256=contract,
                    cohort_input_paths={"cohort": other}, policy=POLICY, output_dir=root / "cohort-child",
                )

    def test_rejects_overwriting_a_continuation_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, contract = _parent(root, [[1]], [["TERMINAL 1", "COMPLETE"]])
            output = root / "child"
            self._build(run, contract, output, [1])
            with self.assertRaisesRegex(ContractError, "already exists"):
                self._build(run, contract, output, [1])

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
                    WholeUnitReplayUnit("stable", (Path("results/stable.json"),)),
                    WholeUnitReplayUnit("missing", (Path("results/missing.json"),)),
                ),
            )
        self.assertEqual([unit["action"] for unit in plan["units"]], ["reuse", "replay"])

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
                    units=(WholeUnitReplayUnit("stale", (Path("results/stale.json"),)),),
                )


if __name__ == "__main__":
    unittest.main()
