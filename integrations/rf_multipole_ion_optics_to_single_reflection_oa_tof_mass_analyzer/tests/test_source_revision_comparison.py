from __future__ import annotations

import unittest
from dataclasses import replace

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.paired_downstream_analysis import (
    BranchData,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_source_revision_comparison_run import (
    REQUIRED_METRICS,
    _comparison_metrics,
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


if __name__ == "__main__":
    unittest.main()
