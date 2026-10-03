from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation import (
    REQUIRED_INPUT_ROLES,
    build_continuation_plan,
)


class MrtofBatchContinuationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        parent = root / "parent"
        current = root / "current"
        for run in (parent, current):
            (run / "inputs").mkdir(parents=True)
            (run / "logs").mkdir()

        def materialize(run: Path) -> dict[str, str]:
            inputs: dict[str, str] = {}
            for role in REQUIRED_INPUT_ROLES:
                path = run / "inputs" / f"{role}.json"
                value = {"role": role}
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")
                inputs[role] = str(path.resolve())
            trial = run / "inputs" / "trial_materialization.json"
            trial.write_text(
                json.dumps(
                    {"role": "trial_materialization", "source_particle_count": 3}
                )
                + "\n",
                encoding="utf-8",
            )
            inputs["trial_materialization"] = str(trial.resolve())
            return inputs

        parent_inputs = materialize(parent)
        current_inputs = materialize(current)
        plan = {
            "role": "simion_single_wave_particle_batch_plan",
            "batches": [
                {"index": 1, "particle_id_min": 1, "particle_id_max": 1, "count": 1},
                {"index": 2, "particle_id_min": 2, "particle_id_max": 3, "count": 2},
            ],
        }
        plan_path = parent / "inputs" / "simion_execution_batch_plan.json"
        plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        parent_inputs["simion_execution_batch_plan"] = str(plan_path.resolve())
        parameters = {
            "execution_mode": "mrtof_native_corridor_bunch",
            "particle_count": 3,
            "launched_particle_count": 3,
        }
        parent_config = parent / "run_config.json"
        parent_config.write_text(
            json.dumps({"parameters": parameters, "inputs": parent_inputs}) + "\n",
            encoding="utf-8",
        )
        current_config = current / "run_config.json"
        current_config.write_text(
            json.dumps({"parameters": parameters, "inputs": current_inputs}) + "\n",
            encoding="utf-8",
        )
        complete = parent / "logs" / "native_two_prism_flight__batch01.log"
        complete.write_text(
            "MRTOF_EVENT terminal ion=1 splat=1 t_us=1\n"
            "status,Fly completed. 1 splats, 1.0 seconds\n"
            "IOB_FLIGHT: PASS iob=fixture.iob\n",
            encoding="utf-8",
        )
        partial = parent / "logs" / "native_two_prism_flight__batch02.log"
        partial.write_text("MRTOF_EVENT terminal ion=1 splat=1 t_us=2\n", encoding="utf-8")
        manifest_inputs = {
            role: {
                "path": path,
                "exists": True,
                "sha256": file_sha256(Path(path)),
            }
            for role, path in parent_inputs.items()
        }
        (parent / "run_manifest.json").write_text(
            json.dumps(
                {
                    "role": "simulation_run_manifest",
                    "run_id": "parent",
                    "status": "interrupted",
                    "run_config": {"sha256": file_sha256(parent_config)},
                    "inputs": manifest_inputs,
                    "outputs": [
                        {"path": str(complete), "sha256": file_sha256(complete)},
                        {"path": str(partial), "sha256": file_sha256(partial)},
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return parent, current_config

    def test_reuses_only_complete_ordered_mrtof_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root)
            plan = build_continuation_plan(
                predecessor_run_dir=parent,
                current_run_config=current,
                output_dir=root / "recovery",
            )
        self.assertEqual(plan["completed_particle_count"], 1)
        self.assertEqual(plan["replay_particle_count"], 2)
        self.assertEqual(
            [batch["replay_particle_count"] for batch in plan["batches"]],
            [0, 2],
        )

    def test_rejects_changed_frozen_physics_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, current = self._fixture(root)
            config = json.loads(current.read_text(encoding="utf-8"))
            operating_point = Path(config["inputs"]["operating_point_lua"])
            operating_point.write_text(
                '{"role":"operating_point_lua","changed":true}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "frozen cohort identity"):
                build_continuation_plan(
                    predecessor_run_dir=parent,
                    current_run_config=current,
                    output_dir=root / "recovery",
                )


if __name__ == "__main__":
    unittest.main()
