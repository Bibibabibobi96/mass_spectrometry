from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.particle_release.continuous_axial_volume import (
    CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY,
    METHOD,
    ROLE,
    generate_continuous_axial_volume_states,
)
from msplatform.particle_release.release import (
    RELEASE_HANDLER_REGISTRY,
    materialize_release_from_file,
    validate_materialized_release,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_SPEC = REPO_ROOT / "src/msplatform/components/rf_multipole/config/sources/rf_octupole_continuous_axial_volume_snapshot_v1_n1000.json"
FROZEN_TABLE = REPO_ROOT / "src/msplatform/components/rf_multipole/config/sources/rf_octupole_continuous_axial_volume_snapshot_v1_1000.csv"


def spec(*, particle_count: int = 20) -> dict[str, object]:
    return {
        "schema_version": 2, "role": ROLE, "method": METHOD,
        "source_region_model": "particle_source_volume_cylinder_v2",
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
        "species": {"species_kind": "ion", "mass_amu": 100.0, "charge_state": 1},
    }


class ContinuousAxialVolumeReleaseTest(unittest.TestCase):
    def test_registered_release_is_byte_compatible_with_frozen_n1000_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            historical = json.loads(FROZEN_SPEC.read_text(encoding="utf-8"))
            historical["schema_version"] = 2
            historical["role"] = ROLE
            historical["method"] = METHOD
            historical["source_region_model"] = CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY[0]
            if "ion" in historical:
                historical["species"] = {"species_kind": "ion", **historical.pop("ion")}
            current = root / "current.json"
            current.write_text(json.dumps(historical), encoding="utf-8")
            materialize_release_from_file(
                current, root / "source.csv", root / "receipt.json"
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

    def test_version1_receipt_is_read_only_and_never_enables_old_new_execution(self) -> None:
        from msplatform.particle_release.release import generate_release_states, materialize_release
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = spec(particle_count=3)
            receipt = materialize_release(current, root / "source.csv", root / "current.json")
            old = json.loads(json.dumps(current))
            old.update(schema_version=1, role="continuous_axial_volume_ion_beam_source",
                       method="independent_spatial_velocity_ion_source_snapshot_v1",
                       source_region_model="ion_source_volume_cylinder_v1")
            old["ion"] = {k: v for k, v in old.pop("species").items() if k != "species_kind"}
            old_hash = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":"),
                                                 allow_nan=False).encode()).hexdigest().upper()
            receipt.update(schema_version=1, role=old["role"], method=old["method"],
                           source_region_model=old["source_region_model"], release_spec=old,
                           release_spec_sha256=old_hash)
            path = root / "old.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            before = path.read_bytes()
            with patch("msplatform.particle_release.continuous_axial_volume.generate_continuous_axial_volume_states",
                       side_effect=AssertionError("historical reader invoked a producer")):
                self.assertEqual(validate_materialized_release(path)["release_spec"], old)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                generate_release_states(old)


if __name__ == "__main__":
    unittest.main()
