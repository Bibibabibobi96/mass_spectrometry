from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_mirror_stripe_operating_point import (
    build_downstream_authority_receipt,
    load_fixed_mirror_stripe_operating_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
REPOSITORY = PROJECT.parents[1]
RUN = (
    REPOSITORY.parent / "artifacts" / "projects"
    / "parallel_mirror_dual_stripe_mr_tof" / "runs"
    / "20260917_211500__analysis__python__dual-stripe-fixed-mirror-variable-slow-energy-r3"
)
MANIFEST = RUN / "run_manifest.json"
R130_CONTRACT = (
    REPOSITORY.parent / "artifacts" / "projects"
    / "parallel_mirror_dual_stripe_mr_tof" / "runs"
    / "20260917_223000__sim__simion__mrtof-measured-chord-root-fixed-grid-r130"
    / "inputs" / "simion_candidate_two_zone.json"
)
DOWNSTREAM_SLOW_ENERGY_POLICY = (
    "5 eV is the nominal adjustable slow-axis source seed, not a fixed equality. "
    "For a qualified fixed mirror, the native Stripe spatial-return inverse and "
    "T_D/T_0=K analytically select the nearby slow-energy centre and both Stripe "
    "biases; measured or simulated source spread is added around that selected centre."
)


@unittest.skipUnless(
    MANIFEST.is_file() and R130_CONTRACT.is_file(),
    "fixed-mirror Stripe r3 or r130 frozen evidence is unavailable",
)
class FixedMirrorStripeOperatingPointTests(unittest.TestCase):
    def test_loads_one_joined_downstream_authority(self) -> None:
        point = load_fixed_mirror_stripe_operating_point(MANIFEST)

        self.assertEqual(point.fixed_grid_run_id, "20260917_223000__sim__simion__mrtof-measured-chord-root-fixed-grid-r130")
        self.assertAlmostEqual(point.axial_energy_per_charge_v, 4372.010347796059)
        self.assertAlmostEqual(point.slow_energy_per_charge_v, 4.961131691875478)
        self.assertEqual(point.target_period_ratio, 25.5)
        self.assertEqual(point.predicted_period_ratio, 25.5)
        self.assertEqual(len(point.mirror_voltages_v), 5)
        self.assertEqual(len(point.stripe_biases_v), 2)

    def test_rebinds_only_the_authorized_slow_energy_policy(self) -> None:
        contract = json.loads(R130_CONTRACT.read_text(encoding="utf-8-sig"))
        contract["prism_transport"]["energy_partition"][
            "candidate_operating_partition"
        ] = DOWNSTREAM_SLOW_ENERGY_POLICY
        with tempfile.TemporaryDirectory() as directory:
            downstream_contract = Path(directory) / "simion_candidate_two_zone.json"
            downstream_contract.write_text(
                json.dumps(contract, indent=2) + "\n",
                encoding="utf-8",
            )
            point = load_fixed_mirror_stripe_operating_point(
                MANIFEST,
                downstream_contract,
            )

        self.assertEqual(
            point.contract["prism_transport"]["energy_partition"]
            ["candidate_operating_partition"],
            DOWNSTREAM_SLOW_ENERGY_POLICY,
        )

    def test_rejects_nonterminal_manifest_before_reading_values(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
        manifest["status"] = "checkpoint"
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "run_manifest.json"
            altered.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "identity is invalid"):
                load_fixed_mirror_stripe_operating_point(altered)

    def test_compact_receipt_exposes_one_shared_downstream_energy_partition(self) -> None:
        receipt = build_downstream_authority_receipt(MANIFEST)

        self.assertEqual(
            receipt["role"], "mrtof_fixed_mirror_stripe_downstream_operating_authority",
        )
        self.assertEqual(receipt["axial_energy_per_charge_v"], 4372.010347796059)
        self.assertEqual(receipt["slow_energy_per_charge_v"], 4.961131691875478)
        self.assertEqual(receipt["target_period_ratio"], receipt["predicted_period_ratio"])


if __name__ == "__main__":
    unittest.main()
