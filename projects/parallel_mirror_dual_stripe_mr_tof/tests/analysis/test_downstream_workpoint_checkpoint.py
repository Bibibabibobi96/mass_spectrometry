from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_checkpoint import (
    reconstruct_checkpoint,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
    decide_iteration,
)


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CheckpointFixture:
    def __init__(self, root: Path):
        self.root = root
        self.run_id = "20260920_161000__sim__simion__fixture-r8"
        self.parent = root / self.run_id
        self.inputs = self.parent / "inputs"
        self.results = self.parent / "results"
        names = [
            "P1_P2_positive_mirror_turn_y_mm",
            "P1_P2_P2_shield_low_field_signed_vy_over_vz",
            "Stripe_slow_turn_y_minus_L_mm",
            "Stripe_target_phase_y_minus_origin_mm",
        ]
        self.prior = {
            "status": "linearized_candidate_step",
            "unknown_names": ["stripe_1_voltage_v", "stripe_2_voltage_v", "prism_1_voltage_v", "prism_2_voltage_v"],
            "residual_names": names,
            "baseline_voltages_v": [-24.0, 52.0, 190.0, -192.0],
            "proposed_voltages_v": [-25.0, 51.0, 196.0, -195.0],
            "physical_jacobian_rows": [
                [-0.0015, 0.00018, 0.19, 0.068], [1.4e-7, 1.8e-7, 2.2e-4, 2.3e-4],
                [1.245, -2.092, 0.85, 0.92], [5.646, -0.715, -1.40, -1.39],
            ],
            "resolved_numerics": {
                "parameter_scales_v": [25, 52, 190, 192],
                "maximum_abs_step_v": [2, 2, 2, 2], "lower_bounds_v": [-4000, 1, 100, -300],
                "upper_bounds_v": [-1, 3900, 300, -100],
            },
            "native_bank_identity": {"cache_key": "A" * 64, "generation_sha256": "B" * 64},
        }
        self.contract = {"downstream_fixed_grid_workpoint_profile": {
            "schema_version": 1,
            "automatic_iteration": {
                "schema_version": 1, "maximum_iterations": 8, "damping_factor": 0.5,
                "minimum_step_linf_v": 1e-6, "minimum_relative_improvement": 0.01,
                "maximum_consecutive_non_improving_iterations": 3, "cycle_voltage_tolerance_v": 1e-8,
                "oscillation_window": 4, "capacity_protection_ttl_seconds": 14400,
                "acceptance_tolerances": {
                    names[0]: 0.01, "P1_P2_P2_shield_low_field_angle_degrees": 0.01,
                    names[2]: 0.01, names[3]: 0.01,
                },
            },
        }}
        self.current_prior = write_json(root / "current_prior.json", self.prior)
        self.current_contract = write_json(root / "current_contract.json", self.contract)
        self.current_initial_manifest = write_json(root / "current_initial_manifest.json", {"seed": "same"})
        write_json(self.inputs / "initial_workpoint.json", self.prior)
        write_json(self.inputs / "contract.json", self.contract)
        write_json(self.inputs / "initial_workpoint_manifest.json", {"seed": "same"})
        write_json(self.parent / "summary.json", {"status": "checkpoint"})
        write_json(self.parent / "run_manifest.json", {
            "schema_version": 2, "role": "simulation_run_manifest", "run_id": self.run_id,
            "project": "parallel_mirror_dual_stripe_mr_tof", "mode": "downstream_fixed_grid_workpoint_iteration",
            "status": "checkpoint", "outputs": [],
        })
        self.decisions: list[dict] = []
        self.children: list[Path] = []
        self.add_child(1, [0.001, 1e-6, -1.0, 2.0], record=True)
        self.add_child(2, [0.001, 1e-6, -0.5, 1.0], record=False)
        self.bind_baseline()

    def bind_baseline(self):
        self.prior["baseline_manifest"] = str(self.children[0])
        self.prior["consumed_trials"] = [{"manifest": str(self.children[0]), "manifest_sha256": sha(self.children[0])}]
        write_json(self.inputs / "initial_workpoint.json", self.prior)
        write_json(self.current_prior, self.prior)

    def add_child(self, iteration: int, residuals: list[float], *, record: bool) -> None:
        child = self.root / f"{self.run_id}-iter-{iteration:02d}"
        names = self.prior["residual_names"]
        expected = self.prior["proposed_voltages_v"] if not self.decisions else self.decisions[-1]["proposed_voltages_v"]
        materialization = {
            "stripe_biases_v": expected[:2], "prism_voltages_v": expected[2:],
            "target_low_field_tangent_ratio_vy_over_vz": 0.033686,
            "inputs": {"geometry": "same"}, "target_drift_period_ratio": 25.5,
            "target_positive_mirror_turn_y_mm": 0.0, "target_slow_turn_y_mm": 340.0,
            "mirror_voltages_v": [0, -5900, -2600, 4200, 6030],
            "selected_axial_energy_per_charge_v": 4372.0, "source_slow_kinetic_energy_per_charge_v": 4.96,
            "fly2_sha256": "same-source", "drift_phase_contract": {"half_oscillations": 51},
        }
        observation = {
            "prism_voltages_v": expected[2:],
            "status": "full_drift_observed", "return_topology": "exact_target_k_phase_return",
            "termination_diagnostic": {"physical_collision": False},
            "static_return_diagnostic": {"status": "detector_hit", "event_contract_ok": True},
            "residuals": dict(zip(names, residuals, strict=True)),
        }
        result = child / "results"
        obs = write_json(result / "two_prism_trial_observation.json", observation)
        mat = write_json(result / "two_prism_trial_materialization.json", materialization)
        bank = self.prior["native_bank_identity"]
        generation = str(self.root / bank["cache_key"] / "generations" / "g")
        identity = write_json(result / "native_corridor_runtime_family.json", {
            "schema_version": 1, "role": "mrtof_private_native_corridor_family", "status": "prepared",
            **bank, "generation_directory": generation, "response_refine_performed": False,
            "published_native_members_opened": False, "controller_refine": "solutions={0}",
        })
        key = bank["cache_key"]
        protection = write_json(result / "local_operating_cache_protection_renewal.json", {
            "schema_version": 1, "role": "mrtof_local_operating_cache_protection_renewal", "status": "success",
            "lease_id": f"lease-{iteration}", "lease_owner": "owner", "cache_key": key,
            "generation_directory": generation,
            "renewal": {"lease_id": f"lease-{iteration}", "owner": "owner", "protected_cache_keys": [key]},
        })
        baseline = write_json(result / "artifact_capacity_gate_terminal.json", {"schema_version": 1, "role": "artifact_capacity_gate"})
        outputs = [{"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size} for path in (obs, mat, identity, protection, baseline)]
        manifest = write_json(child / "run_manifest.json", {
            "schema_version": 2, "role": "simulation_run_manifest", "run_id": child.name,
            "project": "parallel_mirror_dual_stripe_mr_tof", "mode": "finite_3d_two_prism_voltage_trial",
            "status": "success", "outputs": outputs,
        })
        write_json(child / "run_config.json", {"parameters": {
            "pa_binding_mode": "native_corridor_private_fast_adjust_family__four_instances__n1",
            "stripe_biases_v": expected[:2],
            "prism_1_voltage_v": expected[2],
            "prism_2_voltage_v": expected[3],
        }})
        config_path = child / "run_config.json"
        config = json.loads(config_path.read_text())
        config["parameters"]["local_region_mesh_mm_per_gu"] = [[0.25] * 3] * 5
        write_json(config_path, config)
        doc = json.loads(manifest.read_text())
        doc["run_config"] = {"path": str(config_path), "sha256": sha(config_path), "bytes": config_path.stat().st_size}
        write_json(manifest, doc)
        decision = decide_iteration(self.prior, observation, materialization, self.contract, self.decisions, iteration)
        self.decisions.append(decision)
        if record:
            write_json(self.results / f"iteration_{iteration:02d}_decision.json", decision)
        self.children.append(manifest)

    def reconstruct(self, latest: Path | None = None):
        return reconstruct_checkpoint(
            self.parent, latest or self.children[-1], self.current_initial_manifest,
            self.current_prior, self.current_contract, self.root,
        )

    def write_lineage(self, *, replayed_iteration: int | None = None, count: int | None = None) -> None:
        selected = self.children[:count]
        children = []
        for iteration, child in enumerate(selected, 1):
            children.append({
                "iteration": iteration,
                "child_manifest": str(child),
                "child_manifest_sha256": sha(child),
                "replayed_checkpoint": iteration == replayed_iteration,
            })
        write_json(self.results / "iteration_lineage.json", {"children": children})


class DownstreamWorkpointCheckpointTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return CheckpointFixture(Path(temporary.name))

    def test_reconstructs_latest_unrecorded_decision_and_starts_next_iteration(self):
        fixture = self.fixture()
        result = fixture.reconstruct()
        self.assertEqual(result["completed_iterations"], 2)
        self.assertEqual(result["next_iteration"], 3)
        self.assertEqual(result["current_voltages_v"], fixture.decisions[-1]["proposed_voltages_v"])

    def test_native_checkpoint_replays_and_rejects_cross_bank_jacobian(self):
        fixture = self.fixture()
        result = fixture.reconstruct()
        self.assertEqual(result["next_iteration"], 3)
        fixture.prior["native_bank_identity"]["generation_sha256"] = "C" * 64
        write_json(fixture.inputs / "initial_workpoint.json", fixture.prior)
        write_json(fixture.current_prior, fixture.prior)
        with self.assertRaisesRegex(Exception, "bank differs from initial Jacobian"):
            fixture.reconstruct()

    def test_rejects_retired_non_native_binding(self):
        fixture = self.fixture()
        child = fixture.children[-1]
        config_path = child.parent / "run_config.json"
        config = json.loads(config_path.read_text())
        config["parameters"]["pa_binding_mode"] = "retired_legacy_binding"
        write_json(config_path, config)
        manifest = json.loads(child.read_text())
        manifest["run_config"]["sha256"] = sha(config_path)
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        write_json(child, manifest)
        with self.assertRaisesRegex(Exception, "retired non-native PA binding"):
            fixture.reconstruct()

    def test_rejects_tampered_recorded_decision(self):
        fixture = self.fixture()
        path = fixture.results / "iteration_01_decision.json"
        value = json.loads(path.read_text())
        value["observation_record"]["voltages_v"][0] += 1
        write_json(path, value)
        with self.assertRaisesRegex(Exception, "observation voltage differs"):
            fixture.reconstruct()

    def test_rejects_tampered_history(self):
        fixture = self.fixture()
        history = json.loads(json.dumps(fixture.decisions))
        history[0]["proposed_voltages_v"][0] += 1
        write_json(fixture.results / "iteration_history.json", {"decisions": history[:1]})
        with self.assertRaisesRegex(Exception, "history differs"):
            fixture.reconstruct()

    def test_rejects_missing_intermediate_child(self):
        fixture = self.fixture()
        fixture.children[0].unlink()
        with self.assertRaisesRegex(Exception, "unreadable"):
            fixture.reconstruct()

    def test_rejects_non_continuous_latest_iteration(self):
        fixture = self.fixture()
        latest = json.loads(fixture.children[-1].read_text())
        latest["run_id"] = fixture.run_id + "-iter-04"
        write_json(fixture.children[-1], latest)
        with self.assertRaisesRegex(Exception, "continuous"):
            fixture.reconstruct()

    def test_rejects_materialized_voltage_mismatch(self):
        fixture = self.fixture()
        materialization = fixture.children[-1].parent / "results" / "two_prism_trial_materialization.json"
        value = json.loads(materialization.read_text())
        value["stripe_biases_v"][0] += 1
        write_json(materialization, value)
        manifest = json.loads(fixture.children[-1].read_text())
        next(item for item in manifest["outputs"] if Path(item["path"]).name == materialization.name)["sha256"] = sha(materialization)
        write_json(fixture.children[-1], manifest)
        with self.assertRaisesRegex(Exception, "materialization differs"):
            fixture.reconstruct()

    def test_replays_only_imported_first_lineage_child(self):
        fixture = self.fixture()
        fixture.prior["proposed_voltages_v"][0] += 1
        write_json(fixture.inputs / "initial_workpoint.json", fixture.prior)
        write_json(fixture.current_prior, fixture.prior)
        first = fixture.children[0]
        first_manifest = json.loads(first.read_text())
        first_manifest["run_id"] = "20260919_161000__sim__simion__predecessor-iter-01"
        write_json(first, first_manifest)
        fixture.bind_baseline()
        observation = json.loads((first.parent / "results" / "two_prism_trial_observation.json").read_text())
        materialization = json.loads((first.parent / "results" / "two_prism_trial_materialization.json").read_text())
        decision = decide_iteration(fixture.prior, observation, materialization, fixture.contract, [], 1)
        write_json(fixture.results / "iteration_01_decision.json", decision)
        fixture.write_lineage(replayed_iteration=1, count=1)
        result = fixture.reconstruct(latest=first)
        self.assertEqual(result["completed_iterations"], 1)

    def test_accepts_replayed_checkpoint_metadata_on_multiple_lineage_children(self):
        fixture = self.fixture()
        fixture.write_lineage(replayed_iteration=2)
        self.assertEqual(fixture.reconstruct()["completed_iterations"], 2)

    def test_rejects_contract_or_jacobian_change(self):
        fixture = self.fixture()
        altered = dict(fixture.prior)
        altered["physical_jacobian_rows"] = [row[:] for row in fixture.prior["physical_jacobian_rows"]]
        altered["physical_jacobian_rows"][0][0] += 1
        write_json(fixture.current_prior, altered)
        with self.assertRaisesRegex(Exception, "proposal/Jacobian differs"):
            fixture.reconstruct()
        fixture = self.fixture()
        altered_contract = json.loads(json.dumps(fixture.contract))
        altered_contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["damping_factor"] = 0.25
        write_json(fixture.current_contract, altered_contract)
        with self.assertRaisesRegex(Exception, "contract differs"):
            fixture.reconstruct()


if __name__ == "__main__":
    unittest.main()
