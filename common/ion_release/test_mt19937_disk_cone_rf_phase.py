from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.ion_release.mt19937_disk_cone_rf_phase import (
    IDEAL_TRANSPORT_STRATEGY,
    STRATEGY,
    _render,
    generate_mt19937_disk_cone_rf_phase_states,
    generate_mt19937_disk_sqrt_cone_rf_phase_states,
    materialize_mt19937_disk_cone_rf_phase_release,
    validate_materialized_mt19937_disk_cone_rf_phase_release,
    validate_mt19937_disk_cone_rf_phase_release_spec,
    validate_mt19937_disk_sqrt_cone_rf_phase_release_spec,
)
from common.ion_release.release import (
    RELEASE_HANDLER_REGISTRY,
    generate_release_states,
    materialize_release,
    validate_materialized_release,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILY_N100 = REPO_ROOT / "common/multipole/sources/rf_multipole_family_mother_sample_v1_100.csv"
FAMILY_N1000 = REPO_ROOT / "common/multipole/sources/rf_multipole_family_mother_sample_v1_1000.csv"


def _spec(count: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "role": "repository_ion_release",
        "frame_id": "rf_multipole_source_local_cartesian_v1",
        "particle_count": count,
        "mother_particle_count": 5000,
        "geometry": {"shape": "disk", "center_mm": [0.0, 0.0, -1.5], "radius_mm": 0.5},
        "species": {"mass_amu": 100.0, "charge_state": 1},
        "sampling": {
            "strategy": STRATEGY,
            "seed": 2026072801,
            "rf_frequency_hz": 1_100_000.0,
            "kinetic_energy_ev": 2.0,
            "cone_half_angle_deg": 5.0,
        },
    }


def _ideal_transport_spec(count: int) -> dict[str, object]:
    spec = _spec(count)
    spec["mother_particle_count"] = count
    spec["geometry"] = {"shape": "disk", "center_mm": [0.0, 0.0, 0.0], "radius_mm": 0.5}
    spec["sampling"] = {
        **spec["sampling"],
        "strategy": IDEAL_TRANSPORT_STRATEGY,
        "seed": 20260722,
    }
    return spec


class Mt19937DiskConeRfPhaseTests(unittest.TestCase):
    def test_disk_strategy_is_exposed_by_the_public_registry(self) -> None:
        self.assertIn(("disk", STRATEGY), RELEASE_HANDLER_REGISTRY)
        self.assertEqual(
            generate_release_states(_spec(100)),
            generate_mt19937_disk_cone_rf_phase_states(_spec(100)),
        )

    def test_ideal_transport_strategy_preserves_its_historical_draw_order(self) -> None:
        spec = _ideal_transport_spec(3)
        self.assertIn(("disk", IDEAL_TRANSPORT_STRATEGY), RELEASE_HANDLER_REGISTRY)
        states = generate_release_states(spec)
        self.assertEqual(states, generate_mt19937_disk_sqrt_cone_rf_phase_states(spec))
        self.assertEqual(
            [
                (state["birth_time_s"], state["x_mm"], state["y_mm"], state["vx_m_s"], state["vy_m_s"], state["vz_m_s"])
                for state in states
            ],
            [
                (9.005917074680262e-07, -0.3005021254129064, 0.21591805458583815, 102.4804793163208, 35.336438712049, 1961.5459142534435),
                (7.897899115417313e-07, 0.07029143790761463, -0.12228344093233935, -110.31001246837077, 69.33907541741773, 1960.2135291941072),
                (8.525622223489484e-07, -0.18356434191543916, -0.007429147237812107, 102.86857159076358, -18.940300056625865, 1961.7524329738378),
            ],
        )
        validate_mt19937_disk_sqrt_cone_rf_phase_release_spec(spec)
        with tempfile.TemporaryDirectory() as directory:
            receipt = materialize_release(spec, Path(directory) / "source.csv", Path(directory) / "receipt.json")
            self.assertEqual(validate_materialized_release(Path(directory) / "receipt.json"), receipt)

    def test_existing_rf_multipole_family_csvs_are_byte_compatible(self) -> None:
        self.assertEqual(_render(generate_mt19937_disk_cone_rf_phase_states(_spec(100))), FAMILY_N100.read_bytes())
        self.assertEqual(_render(generate_mt19937_disk_cone_rf_phase_states(_spec(1000))), FAMILY_N1000.read_bytes())

    def test_materialized_release_rebuilds_and_binds_its_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "source.csv"
            receipt = Path(directory) / "receipt.json"
            result = materialize_release(_spec(100), table, receipt)
            self.assertEqual(result["state_table"]["sha256"], file_sha256(FAMILY_N100))
            self.assertEqual(validate_materialized_release(receipt), result)
            self.assertEqual(validate_materialized_mt19937_disk_cone_rf_phase_release(receipt), result)

    def test_invalid_cone_is_rejected(self) -> None:
        invalid = _spec(1)
        sampling = dict(invalid["sampling"])
        sampling["cone_half_angle_deg"] = 90.0
        invalid["sampling"] = sampling
        with self.assertRaisesRegex(ValueError, "cone_half_angle"):
            validate_mt19937_disk_cone_rf_phase_release_spec(invalid)


if __name__ == "__main__":
    unittest.main()
