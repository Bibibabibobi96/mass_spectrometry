import math
import unittest

from common.contracts.rigid_transform import (
    FramedCovariance,
    FramedPosition,
    FramedTensor,
    FramedVector,
    PhaseSpaceCovariance,
    PhaseSpaceState,
    PlaneSurface,
    RigidTransform,
    relative_transform,
)

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ROTATE_Z_90 = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


class RigidTransformValidationTests(unittest.TestCase):
    def test_contract_round_trip_is_versioned_and_exact(self) -> None:
        transform = RigidTransform("component", "instrument", IDENTITY, (1, 2, 3))
        self.assertEqual(
            RigidTransform.from_contract(transform.to_contract()), transform
        )
        contract = transform.to_contract()
        contract["unknown"] = True
        with self.assertRaisesRegex(ValueError, "fields differ"):
            RigidTransform.from_contract(contract)

    def test_nonfinite_and_left_handed_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            RigidTransform("a", "b", IDENTITY, (math.nan, 0, 0))
        with self.assertRaisesRegex(ValueError, "finite"):
            RigidTransform(
                "a",
                "b",
                ((1, 0, 0), (0, math.inf, 0), (0, 0, 1)),
                (0, 0, 0),
            )
        with self.assertRaisesRegex(ValueError, "right handed"):
            RigidTransform(
                "a",
                "b",
                ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
                (0, 0, 0),
            )

    def test_frame_mismatches_fail_closed(self) -> None:
        transform = RigidTransform("source", "target", IDENTITY, (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "frame mismatch"):
            transform.transform_position(FramedPosition("other", (0, 0, 0)))
        with self.assertRaisesRegex(ValueError, "composition frame mismatch"):
            transform.then(
                RigidTransform("other", "final", IDENTITY, (0, 0, 0))
            )


class RigidTransformOperationTests(unittest.TestCase):
    def test_position_uses_translation_but_vector_does_not(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        position = transform.transform_position(
            FramedPosition("source", (1, 0, 0))
        )
        vector = transform.transform_vector(FramedVector("source", (1, 0, 0)))
        self.assertEqual(position, FramedPosition("target", (10, 21, 30)))
        self.assertEqual(vector, FramedVector("target", (0, 1, 0)))

    def test_inverse_and_composition_round_trip(self) -> None:
        first = RigidTransform("a", "b", ROTATE_Z_90, (10, 20, 30))
        second = RigidTransform("b", "c", IDENTITY, (-4, 5, 6))
        position = FramedPosition("a", (1.25, -2.5, 8))
        sequential = second.transform_position(first.transform_position(position))
        self.assertEqual(
            first.then(second).transform_position(position), sequential
        )
        restored = first.inverse().transform_position(
            first.transform_position(position)
        )
        for actual, expected in zip(
            restored.coordinates_mm, position.coordinates_mm
        ):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_relative_transform_is_derived_from_component_poses(self) -> None:
        source = RigidTransform(
            "source", "instrument", IDENTITY, (10, 2, 0)
        )
        target = RigidTransform(
            "target", "instrument", IDENTITY, (4, -1, 0)
        )
        relative = relative_transform(source, target)
        self.assertEqual(
            (relative.from_frame_id, relative.to_frame_id),
            ("source", "target"),
        )
        self.assertEqual(relative.translation_mm, (6, 3, 0))

    def test_phase_space_transform_preserves_instrument_time(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        source = PhaseSpaceState(
            "source", (1, 0, 0), (100, 0, 0), 12.5
        )
        target = transform.transform_state(source)
        self.assertEqual(target.position_mm, (10, 21, 30))
        self.assertEqual(target.velocity_m_s, (0, 100, 0))
        self.assertEqual(target.instrument_time_us, source.instrument_time_us)

    def test_vector_kinds_share_proper_rotation_and_preserve_norm(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        source_components = (3.0, 4.0, 12.0)
        for kind in ("free", "polar", "axial"):
            with self.subTest(kind=kind):
                target = transform.transform_vector(
                    FramedVector("source", source_components, kind)
                )
                self.assertEqual(target.kind, kind)
                self.assertEqual(target.components, (-4.0, 3.0, 12.0))
                self.assertAlmostEqual(
                    sum(value * value for value in target.components),
                    sum(value * value for value in source_components),
                )
        with self.assertRaisesRegex(ValueError, "vector kind"):
            FramedVector("source", source_components, "invalid")  # type: ignore[arg-type]

    def test_tensor_and_covariance_use_congruence_transform(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        diagonal = ((1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0))
        expected = ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 3.0))
        self.assertEqual(
            transform.transform_tensor(
                FramedTensor("source", diagonal)
            ).components,
            expected,
        )
        self.assertEqual(
            transform.transform_covariance(
                FramedCovariance("source", diagonal)
            ).components,
            expected,
        )
        with self.assertRaisesRegex(ValueError, "symmetric"):
            FramedCovariance(
                "source",
                ((1.0, 2.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            )

    def test_phase_space_covariance_uses_block_diagonal_rotation(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        diagonal = tuple(
            tuple(float(row + 1) if row == column else 0.0 for column in range(6))
            for row in range(6)
        )
        transformed = transform.transform_phase_space_covariance(
            PhaseSpaceCovariance("source", diagonal)  # type: ignore[arg-type]
        )
        self.assertEqual(
            tuple(transformed.components[index][index] for index in range(6)),
            (2.0, 1.0, 3.0, 5.0, 4.0, 6.0),
        )
        with self.assertRaisesRegex(ValueError, "frame mismatch"):
            transform.transform_phase_space_covariance(
                PhaseSpaceCovariance("other", diagonal)  # type: ignore[arg-type]
            )

    def test_scalar_time_and_particle_energy_are_invariant(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        state = PhaseSpaceState(
            "source", (1, 2, 3), (300.0, 400.0, 1200.0), 8.5
        )
        transformed = transform.transform_state(state)
        self.assertEqual(transform.transform_scalar(123.5), 123.5)
        self.assertEqual(transform.transform_time(8.5), 8.5)
        self.assertAlmostEqual(
            sum(value * value for value in transformed.velocity_m_s),
            sum(value * value for value in state.velocity_m_s),
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            transform.transform_scalar(math.inf)
        with self.assertRaisesRegex(ValueError, "finite"):
            transform.transform_time(math.nan)


class PlaneSurfaceTests(unittest.TestCase):
    def test_plane_center_and_normal_transform_with_distinct_rules(self) -> None:
        transform = RigidTransform(
            "source", "target", ROTATE_Z_90, (10, 20, 30)
        )
        transformed = transform.transform_plane(
            PlaneSurface("source", (1, 0, 0), (1, 0, 0))
        )
        self.assertEqual(transformed.center_mm, (10, 21, 30))
        self.assertEqual(transformed.normal, (0, 1, 0))
        self.assertEqual(transformed.frame_id, "target")

    def test_forward_crossing_requires_side_change_and_positive_velocity(
        self,
    ) -> None:
        plane = PlaneSurface("instrument", (0, 0, 0), (1, 0, 0))
        previous = FramedPosition("instrument", (-1, 2, 3))
        current = FramedPosition("instrument", (0.5, 2, 3))
        self.assertTrue(
            plane.is_forward_crossing(
                previous,
                current,
                FramedVector("instrument", (10, 0, 0)),
            )
        )
        self.assertFalse(
            plane.is_forward_crossing(
                previous,
                current,
                FramedVector("instrument", (-10, 0, 0)),
            )
        )
        self.assertFalse(
            plane.is_forward_crossing(
                current,
                FramedPosition("instrument", (1, 2, 3)),
                FramedVector("instrument", (10, 0, 0)),
            )
        )

    def test_plane_rejects_invalid_normal_tolerance_and_frame(self) -> None:
        with self.assertRaisesRegex(ValueError, "unit vector"):
            PlaneSurface("instrument", (0, 0, 0), (2, 0, 0))
        plane = PlaneSurface("instrument", (0, 0, 0), (1, 0, 0))
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            plane.is_forward_crossing(
                FramedPosition("instrument", (-1, 0, 0)),
                FramedPosition("instrument", (1, 0, 0)),
                FramedVector("instrument", (1, 0, 0)),
                tolerance_mm=-1,
            )
        with self.assertRaisesRegex(ValueError, "frame mismatch"):
            plane.signed_distance_mm(FramedPosition("other", (0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
