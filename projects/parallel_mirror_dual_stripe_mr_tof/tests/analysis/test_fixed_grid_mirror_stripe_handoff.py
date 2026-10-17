from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_grid_mirror_stripe_handoff import (
    load_fixed_grid_mirror_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)


PROJECT = Path(__file__).resolve().parents[2]
REPOSITORY = PROJECT.parents[1]
R130_MANIFEST = (
    REPOSITORY.parent
    / "artifacts"
    / "projects"
    / "parallel_mirror_dual_stripe_mr_tof"
    / "runs"
    / "20260917_223000__sim__simion__mrtof-measured-chord-root-fixed-grid-r130"
    / "run_manifest.json"
)
DOWNSTREAM_CONTRACT = (
    REPOSITORY.parent
    / "artifacts"
    / "projects"
    / "parallel_mirror_dual_stripe_mr_tof"
    / "runs"
    / "20260917_211500__analysis__python__dual-stripe-fixed-mirror-variable-slow-energy-r3"
    / "inputs"
    / "simion_candidate_two_zone.json"
)
CURRENT_CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


@unittest.skipUnless(
    R130_MANIFEST.is_file() and DOWNSTREAM_CONTRACT.is_file(),
    "r130 frozen evidence or its authorized downstream contract is unavailable",
)
class FixedGridMirrorStripeHandoffTests(unittest.TestCase):
    """Mutate one r130 output at a time while retaining manifest integrity."""

    def _manifest_with_output_mutation(
        self,
        temporary: Path,
        output_name: str,
        mutate: Callable[[dict[str, Any]], None],
    ) -> Path:
        manifest = json.loads(R130_MANIFEST.read_text(encoding="utf-8-sig"))
        record = next(
            item for item in manifest["outputs"]
            if Path(item["path"]).name == output_name
        )
        payload = json.loads(Path(record["path"]).read_text(encoding="utf-8-sig"))
        mutate(payload)
        altered = temporary / output_name
        altered.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        contents = altered.read_bytes()
        record.update({
            "path": str(altered.resolve()),
            "exists": True,
            "bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest().upper(),
        })
        local_manifest = temporary / "run_manifest.json"
        local_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return local_manifest

    def test_r130_style_evidence_yields_native_real_field_period(self) -> None:
        point = load_fixed_grid_mirror_point(R130_MANIFEST, DOWNSTREAM_CONTRACT)
        self.assertEqual(len(point.energy_points_v), 3)
        self.assertAlmostEqual(point.energy_points_v[1], 4372.010347796, places=9)
        self.assertGreater(point.nominal_reduced_period_mm_per_sqrt_v, 0.0)
        self.assertGreater(point.nominal_axial_width_w_mm, 0.0)

    def test_slow_energy_policy_compatibility_does_not_allow_numeric_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            altered = json.loads(DOWNSTREAM_CONTRACT.read_text(encoding="utf-8-sig"))
            altered["prism_transport"]["energy_partition"]["drift_kinetic_energy_ev"] = 4.9
            contract = Path(temporary) / "contract.json"
            contract.write_text(json.dumps(altered, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "changes more than"):
                load_fixed_grid_mirror_point(R130_MANIFEST, contract)

    def test_target_k_is_a_downstream_stripe_condition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            altered = json.loads(DOWNSTREAM_CONTRACT.read_text(encoding="utf-8-sig"))
            altered["nominal"]["target_drift_period_ratio"] = 25.5
            contract = Path(temporary) / "contract.json"
            contract.write_text(json.dumps(altered, indent=2) + "\n", encoding="utf-8")
            point = load_fixed_grid_mirror_point(R130_MANIFEST, contract)
            self.assertEqual(point.contract["nominal"]["target_drift_period_ratio"], 25.5)
            phase = resolve_drift_phase_contract(point.contract)
            self.assertEqual(phase.target_half_oscillation_count, 51)
            self.assertEqual(phase.return_mirror_side, -1)

    def test_prism_shield_design_is_checked_by_assembled_transport_not_mirror_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            altered = json.loads(DOWNSTREAM_CONTRACT.read_text(encoding="utf-8-sig"))
            altered["prisms"]["ground_shields"][1]["cross_aperture"]["stripe_side_wall_y_mm"] = 0.75
            contract = Path(temporary) / "contract.json"
            contract.write_text(json.dumps(altered, indent=2) + "\n", encoding="utf-8")
            point = load_fixed_grid_mirror_point(R130_MANIFEST, contract)
            self.assertEqual(
                point.contract["prisms"]["ground_shields"][1]["cross_aperture"]["stripe_side_wall_y_mm"],
                0.75,
            )

    def test_selected_center_energy_nodes_must_match_contract_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_with_output_mutation(
                Path(temporary), "mirror_real_field_period_comparison.json",
                lambda payload: payload["energy_centers_ev"].__setitem__(1, payload["energy_centers_ev"][1] + 1.0),
            )
            with self.assertRaisesRegex(CandidateContractError, "energy nodes differ"):
                load_fixed_grid_mirror_point(manifest, DOWNSTREAM_CONTRACT)

    def test_d_voltage_must_remain_in_selected_center_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_with_output_mutation(
                Path(temporary), "fixed_grid_voltage_point.json",
                lambda payload: payload["mirror_voltages_v"].__setitem__(3, 5000.0),
            )
            with self.assertRaisesRegex(CandidateContractError, "voltages violate envelope"):
                load_fixed_grid_mirror_point(manifest, DOWNSTREAM_CONTRACT)

    def test_period_slope_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_with_output_mutation(
                Path(temporary), "mirror_real_field_period_comparison.json",
                lambda payload: payload["simion_normalized_period_slopes_per_v"].__setitem__(0, 1.0e-3),
            )
            with self.assertRaisesRegex(CandidateContractError, "period slopes fail"):
                load_fixed_grid_mirror_point(manifest, DOWNSTREAM_CONTRACT)

    def test_native_gamma_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_with_output_mutation(
                Path(temporary), "native_transverse_l1.json",
                lambda payload: payload["directions"]["1"].__setitem__("gamma_degrees", 90.02),
            )
            with self.assertRaisesRegex(CandidateContractError, "gamma physical gate fails"):
                load_fixed_grid_mirror_point(manifest, DOWNSTREAM_CONTRACT)

    def test_current_consumer_numerics_preserve_frozen_mirror_initializer(self) -> None:
        original = load_fixed_grid_mirror_point(R130_MANIFEST, DOWNSTREAM_CONTRACT)
        current = load_fixed_grid_mirror_point(R130_MANIFEST, CURRENT_CONTRACT)
        self.assertEqual(current.design, original.design)
        self.assertEqual(current.energy_points_v, original.energy_points_v)
        self.assertEqual(current.nominal_reduced_period_mm_per_sqrt_v,
                         original.nominal_reduced_period_mm_per_sqrt_v)

    def test_each_downstream_numeric_update_preserves_mirror_period(self) -> None:
        original = load_fixed_grid_mirror_point(R130_MANIFEST, DOWNSTREAM_CONTRACT)
        current = json.loads(CURRENT_CONTRACT.read_text(encoding="utf-8-sig"))
        for name in ("step", "quantum", "assembled_field", "statistics"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                altered = json.loads(DOWNSTREAM_CONTRACT.read_text(encoding="utf-8-sig"))
                if name == "step":
                    altered["simion"]["trajectory_profiles"]["center_screening"]["maximum_step_us"] = 0.004
                elif name == "statistics":
                    altered["peak_analysis"] = current["peak_analysis"]
                else:
                    key = "grid_generation" if name == "quantum" else "native_static_field"
                    altered["simion"]["numerical_profiles"][key] = current["simion"]["numerical_profiles"][key]
                contract = Path(temporary) / "contract.json"
                contract.write_text(json.dumps(altered, indent=2) + "\n", encoding="utf-8")
                point = load_fixed_grid_mirror_point(R130_MANIFEST, contract)
                self.assertEqual(point.design, original.design)
                self.assertEqual(point.nominal_reduced_period_mm_per_sqrt_v,
                                 original.nominal_reduced_period_mm_per_sqrt_v)

    def test_current_consumer_changes_do_not_allow_mirror_geometry_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            altered = json.loads(CURRENT_CONTRACT.read_text(encoding="utf-8-sig"))
            altered["mirror"]["theory_requirements"]["berdnikov_transverse_half_gap_mm"] += 0.01
            contract = Path(temporary) / "contract.json"
            contract.write_text(json.dumps(altered, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "changes more than"):
                load_fixed_grid_mirror_point(R130_MANIFEST, contract)


if __name__ == "__main__":
    unittest.main()
