"""Actual author compilation and independent physical face-section oracles."""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import math
import unittest

from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.core.face_sections import local_face_conductor_sections
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request


def compiled(*, version=4, segmented=True, shell=False, recessed=False, caps=False):
    """Compile an actual request, with no upgrade of a backend resolved fixture."""
    author = design_request()
    author["schema_version"] = version
    author["coordinate"]["orientation_rad"] = 0.
    if segmented:
        author["segmentation"] = dict(strategy="uniform", segment_count=2, intersegment_gap_mm=.4,
            entrance_common_mode_V=-8., exit_common_mode_V=-8., output_reference_V=-8.)
    if shell:
        geometry = author["geometry_mm"]
        geometry["enclosure"] = dict(model="cylindrical_grounded_shell", inner_radius_mm=10.,
            wall_thickness_mm=1., z_min_mm=2. if recessed else 5., z_max_mm=89. if recessed else 85.)
        if caps:
            geometry["enclosure"]["endcaps"] = {
                side: dict(aperture_radius_mm=3., thickness_mm=.5) for side in ("entrance", "exit")}
        author["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.)
    return compile_design_request(author, expected_identity=author["identity"])


class FaceSectionTests(unittest.TestCase):
    def test_neutral_direct_request_has_independent_circle_and_member_oracle(self):
        source = compiled()
        before = copy.deepcopy(source)
        self.assertEqual(source["schema_version"], 4)
        array = source["segmentation"]["segmented_rod_array"]
        self.assertEqual(array["schema_version"], 2)
        self.assertTrue(all("electrode_id" not in rod for rod in array["electrodes"]))
        for side, segment, start, z in (("entrance", 1, 0, 5.), ("exit", 2, 4, 85.)):
            rows = local_face_conductor_sections(source, side=side)
            self.assertEqual(len(rows), 4)
            for index, row in enumerate(rows):
                angle = index * math.pi / 2
                self.assertAlmostEqual(row.center_mm[0], 6. * math.cos(angle))
                self.assertAlmostEqual(row.center_mm[1], 6. * math.sin(angle))
                self.assertEqual(row.center_mm[2], z)
                self.assertEqual((row.inner_radius_mm, row.outer_radius_mm, row.role), (0., 2., "rod"))
                self.assertEqual(row.electrode_group_id, f"segment_{segment:04d}_rf_group_{index % 2 + 1}")
                self.assertEqual(row.member_ref, f"/segmentation/segmented_rod_array/electrodes/{start + index}")
                self.assertFalse(row.is_grounded)
        self.assertEqual(source, before)
        with self.assertRaises(FrozenInstanceError):
            rows[0].role = "changed"

    def test_recessed_rods_leave_only_true_shell_and_cap_annuli(self):
        source = compiled(shell=True, recessed=True, caps=True)
        for side, z in (("entrance", 2.), ("exit", 89.)):
            rows = local_face_conductor_sections(source, side=side)
            self.assertEqual({row.role for row in rows}, {"shell", side + "_endcap"})
            self.assertEqual({(r.inner_radius_mm, r.outer_radius_mm) for r in rows}, {(10., 11.), (3., 10.)})
            for row in rows:
                self.assertEqual(row.center_mm, (0., 0., z))
                self.assertEqual(row.electrode_group_id, "grounded_shell")
                self.assertTrue(row.is_grounded)
                self.assertTrue(row.member_ref.startswith("/geometry_mm/enclosure_layout/bodies/"))

    def test_legacy_and_neutral_are_scientifically_identical_without_native_labels(self):
        legacy, neutral = compiled(version=3, shell=True), compiled(shell=True)
        for side in ("entrance", "exit"):
            expected = local_face_conductor_sections(neutral, side=side)
            self.assertEqual(local_face_conductor_sections(legacy, side=side), expected)
            for member in legacy["segmentation"]["segmented_rod_array"]["electrodes"]:
                member["electrode_id"] = 23 if member["electrode_group"] == 1 else 17
            self.assertEqual(local_face_conductor_sections(legacy, side=side), expected)

    def test_continuous_zero_drive_is_not_static_ground(self):
        source = compiled(segmented=False)
        source["drive"].update(common_mode_offset_V=0., dc_amplitude_V_per_group=0.)
        rows = local_face_conductor_sections(source, side="exit")
        self.assertEqual([r.electrode_group_id for r in rows], ["rod_group_1", "rod_group_2"] * 2)
        self.assertTrue(all(not r.is_grounded for r in rows))
        self.assertEqual([r.member_ref for r in rows], [f"/geometry_mm/rod_array/rods/{i}" for i in range(4)])

    def test_missing_member_and_false_ground_proofs_reject(self):
        for mutation in (
            lambda s: s["segmentation"]["segmented_rod_array"]["electrodes"].pop(),
            lambda s: s["static_electrodes_V"].update(ground_V=1.),
            lambda s: s["geometry_mm"]["enclosure_layout"]["bodies"].pop(),
        ):
            source = compiled(shell=True)
            mutation(source)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                local_face_conductor_sections(source, side="entrance")

    def test_unknown_mixed_incomplete_versions_and_unknown_side_reject(self):
        for mutation in (
            lambda s: s.update(schema_version=99),
            lambda s: s["segmentation"]["segmented_rod_array"].update(schema_version=1),
            lambda s: s["segmentation"]["segmented_rod_array"].pop("schema_version"),
        ):
            source = compiled()
            mutation(source)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                local_face_conductor_sections(source, side="entrance")
        with self.assertRaisesRegex(ValueError, "side"):
            local_face_conductor_sections(compiled(), side="unknown")


if __name__ == "__main__":
    unittest.main()
