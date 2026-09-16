from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_parallel_angle_discovery import (
    select_parallel_p1_anchors,
    validate_discovery_polarity_domain,
)


def sample(p1, p2, angle, signature):
    return {
        "status": "legal_topology",
        "prism_voltages_v": [p1, p2],
        "residual_vector": [p1, angle],
        "topology_signature_sha256": signature,
    }


class ParallelAngleDiscoveryTests(unittest.TestCase):
    def test_anchor_selection_covers_each_signature_and_p1_span(self):
        records = [
            sample(100.0 + 10.0 * index, -100.0, 0.2 - 0.01 * index, "a")
            for index in range(10)
        ] + [
            sample(150.0 + 5.0 * index, -120.0, 0.1 - 0.005 * index, "b")
            for index in range(10)
        ]
        coverage = {"coverage": {"sobol": {"samples": records}, "local": {"samples": []}}}
        selected = select_parallel_p1_anchors(
            coverage, p1_bounds_v=(100.0, 300.0), requested_anchor_count=8,
        )
        self.assertEqual(len(selected), 8)
        self.assertEqual({item["topology_signature_sha256"] for item in selected}, {"a", "b"})
        for signature in ("a", "b"):
            values = [
                item["prism_voltages_v"][0]
                for item in selected if item["topology_signature_sha256"] == signature
            ]
            self.assertEqual(len(values), 4)
            self.assertGreater(max(values) - min(values), 20.0)

    def test_selector_includes_observed_branch_endpoints(self):
        coverage = {"coverage": {"sobol": {"samples": [
            sample(100.0, 0.0, 0.5, "a"),
            sample(105.0, 0.0, 0.1, "a"),
            sample(110.0, 0.0, 0.4, "a"),
            sample(115.0, 0.0, 0.2, "a"),
        ]}, "local": {"samples": []}}}
        selected = select_parallel_p1_anchors(
            coverage, p1_bounds_v=(100.0, 120.0), requested_anchor_count=2,
        )
        self.assertEqual([item["prism_voltages_v"][0] for item in selected], [100.0, 115.0])

    def test_selector_uses_nearest_evenly_spaced_interior_samples(self):
        coverage = {"coverage": {"sobol": {"samples": [
            sample(100.0, 0.0, 0.5, "a"),
            sample(104.0, 0.0, 0.4, "a"),
            sample(106.0, 0.0, 0.1, "a"),
            sample(110.0, 0.0, 0.3, "a"),
            sample(115.0, 0.0, 0.2, "a"),
        ]}, "local": {"samples": []}}}
        selected = select_parallel_p1_anchors(
            coverage, p1_bounds_v=(100.0, 120.0), requested_anchor_count=3,
        )
        self.assertEqual(
            [item["prism_voltages_v"][0] for item in selected],
            [100.0, 106.0, 115.0],
        )

    def test_selector_can_prefer_position_residual(self):
        records = [
            {
                "status": "legal_topology",
                "prism_voltages_v": [100.0, 1.0],
                "residual_vector": [0.01, 0.5],
                "topology_signature_sha256": "a",
            },
            {
                "status": "legal_topology",
                "prism_voltages_v": [100.0, 2.0],
                "residual_vector": [1.0, 0.01],
                "topology_signature_sha256": "a",
            },
        ]
        coverage = {"coverage": {"sobol": {"samples": records}, "local": {"samples": []}}}
        selected = select_parallel_p1_anchors(
            coverage,
            p1_bounds_v=(99.0, 101.0),
            requested_anchor_count=1,
            preferred_residual_index=0,
        )
        self.assertEqual(selected[0]["prism_voltages_v"], [100.0, 1.0])

    def test_position_selector_prefers_low_y_within_each_p1_bin(self):
        records = [
            {
                "status": "legal_topology",
                "prism_voltages_v": [p1, p2],
                "residual_vector": [y_value, angle],
                "topology_signature_sha256": "a",
            }
            for p1, p2, y_value, angle in (
                (100.0, 1.0, 5.0, 0.1),
                (104.0, 2.0, 0.1, 0.2),
                (106.0, 3.0, 4.0, 0.1),
                (110.0, 4.0, 6.0, 0.1),
                (115.0, 5.0, 7.0, 0.1),
            )
        ]
        coverage = {"coverage": {"sobol": {"samples": records}, "local": {"samples": []}}}
        selected = select_parallel_p1_anchors(
            coverage,
            p1_bounds_v=(100.0, 115.0),
            requested_anchor_count=3,
            preferred_residual_index=0,
        )
        self.assertEqual(
            [item["prism_voltages_v"] for item in selected],
            [[100.0, 1.0], [104.0, 2.0], [115.0, 5.0]],
        )

    def test_selector_rejects_unknown_residual_index(self):
        coverage = {"coverage": {"sobol": {"samples": [
            sample(100.0, 0.0, 0.5, "a"),
        ]}, "local": {"samples": []}}}
        with self.assertRaisesRegex(CandidateContractError, "zero or one"):
            select_parallel_p1_anchors(
                coverage,
                p1_bounds_v=(99.0, 101.0),
                requested_anchor_count=1,
                preferred_residual_index=2,
            )

    def test_selector_filters_anchor_polarity_domain(self):
        coverage = {"coverage": {"sobol": {"samples": [
            sample(100.0, 50.0, 0.01, "a"),
            sample(100.0, -150.0, 0.02, "a"),
        ]}, "local": {"samples": []}}}
        selected = select_parallel_p1_anchors(
            coverage,
            p1_bounds_v=(99.0, 101.0),
            p2_bounds_v=(-300.0, -100.0),
            requested_anchor_count=1,
            preferred_residual_index=0,
        )
        self.assertEqual(selected[0]["prism_voltages_v"], [100.0, -150.0])

    def test_selector_fails_closed_when_domain_has_no_legal_anchor(self):
        coverage = {"coverage": {"sobol": {"samples": [
            sample(150.0, 0.0, 0.1, "a"),
        ]}, "local": {"samples": []}}}
        with self.assertRaisesRegex(CandidateContractError, "contains no legal"):
            select_parallel_p1_anchors(
                coverage, p1_bounds_v=(200.0, 300.0), requested_anchor_count=4,
            )

    def test_historical_contract_requires_explicit_charge_consistent_signs(self):
        receipt = validate_discovery_polarity_domain(
            {}, charge_state=1,
            p1_bounds_v=(100.0, 300.0), p2_bounds_v=(-300.0, -100.0),
        )
        self.assertEqual(receipt["p1_required_sign"], "positive")
        self.assertEqual(receipt["p2_required_sign"], "negative")
        with self.assertRaisesRegex(CandidateContractError, "charge-consistent"):
            validate_discovery_polarity_domain(
                {}, charge_state=1,
                p1_bounds_v=(100.0, 300.0), p2_bounds_v=(100.0, 300.0),
            )


if __name__ == "__main__":
    unittest.main()
