from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from common.multipole.test_exit_state_plot import write_fixture
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.paired_downstream_analysis import (
    BranchData,
    _paired,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_source_revision_comparison_run import (
    BRANCH_LABELS,
    OUTPUT_ROLE,
    PAIR_DEFINITIONS,
    REQUIRED_METRICS,
    _comparison_result,
    _comparison_metrics,
    _pair_edge,
    _render_source_triangle,
    _validate_source_revision_result,
)


def branch(*, offset: float, census_delta: int = 0) -> BranchData:
    states = {
        1: {
            "species_id": "ion",
            "parent_particle_id": None,
            "generation": 0,
            "particle_weight": 1.0,
            "mass_amu": 100.0,
            "charge_state": 1,
            "source_component_id": "rf",
            "target_component_id": "oatof",
            "position": (offset, 0.0, 0.0),
            "velocity": (offset * 10.0, 0.0, 1000.0),
            "instrument_time_us": 1.0 + offset,
            "kinetic_energy_eV": 2.0 + offset,
        }
    }
    census = {
        "rf_exit": 100,
        "oatof_entry": 80 + census_delta,
        "active_at_pulse": 40,
        "local_accelerator_exit": 1,
        "detector_crossing": 1,
        "detector_hit": 1,
    }
    return BranchData(
        summary={"census": census},
        metrics={"census": census},
        states=states,
        downstream={
            1: {
                "hit": True,
                "crossing": True,
            }
        },
        source_lineage={},
        binding_identity={},
    )


class SourceRevisionComparisonTests(unittest.TestCase):
    def test_reports_frozen_ten_metrics(self) -> None:
        result = _comparison_metrics(
            branch(offset=0.0),
            branch(offset=2.0, census_delta=3),
        )
        metrics = result["required_metrics"]
        self.assertEqual(set(metrics), set(REQUIRED_METRICS))
        self.assertEqual(
            metrics["oatof_entry_count"]["delta_revised_minus_baseline"], 3
        )
        self.assertAlmostEqual(
            metrics["common_local_exit_position_rms_mm"], 2.0
        )
        self.assertAlmostEqual(
            metrics["common_local_exit_velocity_rms_m_per_s"], 20.0
        )
        self.assertAlmostEqual(metrics["common_local_exit_time_rms_us"], 2.0)
        self.assertAlmostEqual(metrics["common_local_exit_energy_rms_eV"], 2.0)

    def test_requires_a_common_local_exit_particle(self) -> None:
        revised = replace(branch(offset=1.0), states={})
        with self.assertRaisesRegex(ValueError, "intersection is empty"):
            _comparison_metrics(branch(offset=0.0), revised)

    def test_schema_v2_pair_names_right_minus_left_and_reports_sets(self) -> None:
        edge = _pair_edge(
            branch(offset=0.0),
            branch(offset=2.0),
            left_label="baseline_comsol",
            right_label="hybrid_comsol",
        )
        self.assertEqual(
            edge["pair"],
            {
                "left_label": "baseline_comsol",
                "right_label": "hybrid_comsol",
                "difference_convention": "right_minus_left",
            },
        )
        paired = edge["local_accelerator_exit"][
            "paired_continuous_diagnostics"
        ]
        components = paired["position_mm"]["components_right_minus_left"]
        self.assertEqual(components["x"]["mean_signed"], 2.0)
        self.assertNotIn(
            "components_simion_minus_comsol",
            paired["position_mm"],
        )
        self.assertEqual(
            edge["local_accelerator_exit"]["particle_sets"][
                "common_particle_ids"
            ],
            [1],
        )
        self.assertTrue(
            edge["detector"]["crossing_particle_sets"]["sets_exact"]
        )
        self.assertTrue(edge["detector"]["hit_particle_sets"]["sets_exact"])

    def test_historical_paired_schema_remains_available(self) -> None:
        paired = _paired(branch(offset=0.0), branch(offset=1.0))
        self.assertNotIn("schema_version", paired)
        self.assertIn(
            "components_simion_minus_comsol",
            paired["position_mm"],
        )

    def test_result_reader_accepts_v1_and_requires_v2_triangle(self) -> None:
        historical = {
            "schema_version": 1,
            "role": OUTPUT_ROLE,
            "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "comparisons": [],
        }
        self.assertIs(_validate_source_revision_result(historical), historical)
        edge = {
            "pair": {
                "left_label": "left",
                "right_label": "right",
                "difference_convention": "right_minus_left",
            }
        }
        current = {
            "schema_version": 2,
            "role": OUTPUT_ROLE,
            "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
            "comparisons": [
                {
                    "branches": {label: {} for label in BRANCH_LABELS},
                    "pairwise_edges": {
                        edge_id: edge for edge_id, _, _ in PAIR_DEFINITIONS
                    },
                }
                for _ in range(3)
            ],
        }
        self.assertIs(_validate_source_revision_result(current), current)
        current["comparisons"][0]["pairwise_edges"].pop(
            PAIR_DEFINITIONS[0][0]
        )
        with self.assertRaisesRegex(ValueError, "triangle fields"):
            _validate_source_revision_result(current)

    def test_renders_three_series_with_one_shared_scale_and_fixed_bins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = {
                "profile_id": (
                    "rf_quadrupole_no_acceleration_full_length_"
                    "direct_mating_gap_0mm"
                )
            }
            branches = {}
            for index, label in enumerate(BRANCH_LABELS):
                source = root / f"{label}.csv"
                write_fixture(source, offset=float(index))
                request[label] = {"source_state": {"path": str(source)}}
                branches[label] = replace(
                    branch(offset=float(index)),
                    source_lineage={"source_run_id": f"run-{index}"},
                )
            output = root / "triangle.png"
            manifest = root / "triangle.figure.json"
            _render_source_triangle(
                request_item=request,
                branches=branches,
                output=output,
                manifest=manifest,
                repo_root=root,
            )
            figure = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(output.is_file())
            self.assertEqual(figure["bin_count"], 24)
            self.assertEqual(len(figure["series"]), 3)
            self.assertEqual(
                {item["label"] for item in figure["series"]},
                {"Baseline COMSOL", "Hybrid COMSOL", "Baseline SIMION"},
            )
            for edges in figure["shared_scales"]["histogram_edges"].values():
                self.assertEqual(len(edges), 25)

    def test_triangle_requires_one_resolved_connection(self) -> None:
        profile_id = (
            "rf_quadrupole_no_acceleration_full_length_"
            "direct_mating_gap_0mm"
        )
        baseline_binding = {
            "connection_profile_id": profile_id,
            "resolved_connection_sha256": "A" * 64,
            "runtime_binding_sha256": "B" * 64,
        }

        def governed(offset: float, binding: dict[str, str]) -> BranchData:
            return replace(
                branch(offset=offset),
                source_lineage={
                    "source_input_sha256": "C" * 64,
                    "source_run_id": f"run-{offset}",
                },
                binding_identity=binding,
            )

        branches = {
            "baseline_comsol": governed(0.0, baseline_binding),
            "hybrid_comsol": governed(
                1.0,
                baseline_binding
                | {"runtime_binding_sha256": "D" * 64},
            ),
            "baseline_simion": governed(2.0, baseline_binding),
        }
        result = _comparison_result(
            profile_id=profile_id,
            source_revision_id="quadrupole_hybrid_reference",
            parent_run_ids={label: f"parent-{label}" for label in BRANCH_LABELS},
            branches=branches,
        )
        self.assertEqual(
            set(result["pairwise_edges"]),
            {name for name, _, _ in PAIR_DEFINITIONS},
        )
        branches["hybrid_comsol"] = governed(
            1.0,
            baseline_binding
            | {
                "resolved_connection_sha256": "E" * 64,
                "runtime_binding_sha256": "D" * 64,
            },
        )
        with self.assertRaisesRegex(ValueError, "resolved connections differ"):
            _comparison_result(
                profile_id=profile_id,
                source_revision_id="quadrupole_hybrid_reference",
                parent_run_ids={
                    label: f"parent-{label}" for label in BRANCH_LABELS
                },
                branches=branches,
            )


if __name__ == "__main__":
    unittest.main()
