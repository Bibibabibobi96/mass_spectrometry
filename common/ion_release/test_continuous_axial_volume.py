from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.ion_release.continuous_axial_volume import (
    CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY,
    METHOD,
    ROLE,
    generate_continuous_axial_volume_states,
)
from common.ion_release.release import (
    RELEASE_HANDLER_REGISTRY,
    materialize_release_from_file,
    validate_materialized_release,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_SPEC = REPO_ROOT / "common/multipole/sources/rf_octupole_continuous_axial_volume_snapshot_v1_n1000.json"
FROZEN_TABLE = REPO_ROOT / "common/multipole/sources/rf_octupole_continuous_axial_volume_snapshot_v1_1000.csv"


def spec(*, particle_count: int = 20) -> dict[str, object]:
    return {
        "schema_version": 1, "role": ROLE, "method": METHOD,
        "source_region_model": "ion_source_volume_cylinder_v1",
        "source_frame_id": "multipole_cartesian_z_axis_v1",
        "particle_count": particle_count, "seed": 73, "snapshot_time_s": 0.0,
        "geometry_mm": {
            "center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": -1.5,
            "radius_mm": 0.5, "axial_length_mm": 2.2,
        },
        "velocity_distribution": {
            "mean_vx_m_s": 0.0, "mean_vy_m_s": 0.0,
            "mean_vz_m_s": 1964.668136, "sigma_vx_m_s": 35.0,
            "sigma_vy_m_s": 35.0, "sigma_vz_m_s": 50.0,
            "minimum_vz_m_s": 1500.0,
        },
        "ion": {"mass_amu": 100.0, "charge_state": 1},
    }


class ContinuousAxialVolumeReleaseTest(unittest.TestCase):
    def test_registered_release_is_byte_compatible_with_frozen_n1000_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialize_release_from_file(
                FROZEN_SPEC, root / "source.csv", root / "receipt.json"
            )
            self.assertEqual((root / "source.csv").read_bytes(), FROZEN_TABLE.read_bytes())

    def test_registry_materialization_preserves_the_historical_sequence(self) -> None:
        self.assertIn(CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY, RELEASE_HANDLER_REGISTRY)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "source.json"
            table_path = root / "source.csv"
            receipt_path = root / "receipt.json"
            spec_path.write_text(json.dumps(spec()), encoding="utf-8")
            receipt = materialize_release_from_file(spec_path, table_path, receipt_path)
            self.assertEqual(
                hashlib.sha256(table_path.read_bytes()).hexdigest().upper(),
                "0F861AAC39E17D3FA361568B40E0D3984CE6EA29D44AD34020B2DC77F583FCBA",
            )
            self.assertEqual(receipt["method"], METHOD)
            self.assertEqual(validate_materialized_release(receipt_path), receipt)

    def test_small_cohort_is_a_deterministic_prefix(self) -> None:
        self.assertEqual(
            generate_continuous_axial_volume_states(spec(particle_count=20)),
            generate_continuous_axial_volume_states(spec(particle_count=50))[:20],
        )


if __name__ == "__main__":
    unittest.main()
