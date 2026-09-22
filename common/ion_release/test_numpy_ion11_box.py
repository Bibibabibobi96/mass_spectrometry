from __future__ import annotations

import hashlib
import io
import json
import unittest
from pathlib import Path

import numpy as np

from common.ion_release.numpy_ion11_box import (
    LATENT_FIELDS,
    render_numpy_ion11_box_table,
    sample_numpy_ion11_box_latent,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = REPO_ROOT / "projects/rf_quadrupole_ion_optics/config/official_particle_source.json"


def _sha_table(table: np.ndarray) -> str:
    output = io.StringIO(newline="")
    np.savetxt(output, table, delimiter=",", fmt="%.12g")
    return hashlib.sha256(output.getvalue().encode("ascii")).hexdigest().upper()


class NumpyIon11BoxTests(unittest.TestCase):
    def test_registered_rfq_legacy_rows_are_exact_and_prefix_stable(self) -> None:
        distribution = json.loads(DISTRIBUTION.read_text(encoding="utf-8"))
        n100 = sample_numpy_ion11_box_latent(
            distribution=distribution, seed=20260716, particle_count=100,
        )
        n1000 = sample_numpy_ion11_box_latent(
            distribution=distribution, seed=20260716, particle_count=1000,
        )
        n1001 = sample_numpy_ion11_box_latent(
            distribution=distribution, seed=20260716, particle_count=1001,
        )
        self.assertEqual(tuple(n100), LATENT_FIELDS)
        for field in LATENT_FIELDS:
            self.assertTrue(np.array_equal(n100[field], n1000[field][:100]))
            self.assertTrue(np.array_equal(n1000[field], n1001[field][:1000]))
        parameters = {
            "mass_amu": 100.0, "charge_state": 1, "axial_mm": 0.0,
            "energy_min_ev": 1.8, "energy_max_ev": 2.2, "cwf": 1.0, "color": 3.0,
        }
        self.assertEqual(
            _sha_table(render_numpy_ion11_box_table(latent=n100, **parameters)),
            "7F7E9FDC12CE75E2B88FC29A9CE0A675D9FD7BD9D41847FF166F2F441BD15B95",
        )
        self.assertEqual(
            _sha_table(render_numpy_ion11_box_table(latent=n1000, **parameters)),
            "60D26B95137CD357E410A75E6A6161111FF722840DCEAD7EC0D0DF8ABF2EECA7",
        )

    def test_invalid_box_inputs_are_rejected(self) -> None:
        distribution = json.loads(DISTRIBUTION.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "positive integer"):
            sample_numpy_ion11_box_latent(distribution=distribution, seed=2, particle_count=0)
        with self.assertRaisesRegex(ValueError, "half_angle"):
            bad = dict(distribution)
            bad["direction"] = {"half_angle_deg": 90}
            sample_numpy_ion11_box_latent(distribution=bad, seed=2, particle_count=1)


if __name__ == "__main__":
    unittest.main()
