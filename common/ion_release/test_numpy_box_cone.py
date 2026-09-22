from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

from common.ion_release.numpy_box_cone import (
    BOX_CONE_FIELDS,
    sample_numpy_box_cone_phase_space,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RFQ_SOURCE = REPO_ROOT / "projects/rf_quadrupole_ion_optics/config/official_particle_source.json"


class NumpyBoxConeTests(unittest.TestCase):
    def test_rfq_l1_registered_release_is_deterministic(self) -> None:
        source = json.loads(RFQ_SOURCE.read_text(encoding="utf-8"))
        release = sample_numpy_box_cone_phase_space(
            source=source, seed=20260722, particle_count=64,
        )
        matrix = np.column_stack([release[field] for field in BOX_CONE_FIELDS])
        self.assertEqual(
            hashlib.sha256(matrix.tobytes()).hexdigest().upper(),
            "A3537DB53C7D278D24846EB63D30096CC8B6B384EB778AFF50374A3C25E89EBC",
        )

    def test_invalid_request_is_rejected(self) -> None:
        source = json.loads(RFQ_SOURCE.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "positive integer"):
            sample_numpy_box_cone_phase_space(source=source, seed=1, particle_count=0)
        invalid = dict(source)
        invalid["direction"] = {"half_angle_deg": 90}
        with self.assertRaisesRegex(ValueError, "half_angle"):
            sample_numpy_box_cone_phase_space(source=invalid, seed=1, particle_count=1)


if __name__ == "__main__":
    unittest.main()
