from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.rigid_transform import PlaneSurface, RigidTransform
from common.contracts.spatial_registration import (
    resolve_spatial_registration,
    write_or_check_release,
)


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class SpatialRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.json"
        self.source.write_text('{"schema_version": 1}\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def resolve(self) -> dict:
        return resolve_spatial_registration(
            registration_id="source_to_target",
            instrument_frame_id="instrument",
            component_poses={
                "source": RigidTransform(
                    "source", "instrument", IDENTITY, (-1.0, 0.0, 0.0)
                ),
                "target": RigidTransform(
                    "target", "instrument", IDENTITY, (0.0, 0.0, 0.0)
                ),
            },
            source_component_id="source",
            target_component_id="target",
            surfaces={
                "source_exit": PlaneSurface(
                    "source", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
                ),
                "target_entry": PlaneSurface(
                    "target", (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0)
                ),
            },
            source_files=[self.source],
            repository_root=self.root,
        )

    def test_release_contains_sources_unique_relative_transform_and_surfaces(self) -> None:
        release = self.resolve()
        self.assertEqual(release["schema_version"], 1)
        self.assertEqual(len(release["sources"][0]["sha256"]), 64)
        self.assertEqual(
            release["derived_relative_transform"]["transform"]["translation_mm"],
            [-1.0, 0.0, 0.0],
        )
        self.assertEqual(
            release["resolved_surfaces"]["source_exit"]["in_instrument_frame"][
                "center_mm"
            ],
            [-1.0, 0.0, 0.0],
        )

    def test_check_fails_for_missing_stale_and_source_hash_drift(self) -> None:
        output = self.root / "resolved.json"
        release = self.resolve()
        with self.assertRaisesRegex(ValueError, "stale or missing"):
            write_or_check_release(output, release, check=True)
        write_or_check_release(output, release, check=False)
        write_or_check_release(output, release, check=True)
        self.source.write_text('{"schema_version": 2}\n', encoding="utf-8")
        drifted = self.resolve()
        self.assertNotEqual(
            drifted["sources"][0]["sha256"],
            json.loads(output.read_text(encoding="utf-8"))["sources"][0]["sha256"],
        )
        with self.assertRaisesRegex(ValueError, "stale or missing"):
            write_or_check_release(output, drifted, check=True)

    def test_rejects_extra_pose_and_unresolved_surface_frame(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly source and target"):
            resolve_spatial_registration(
                registration_id="bad",
                instrument_frame_id="instrument",
                component_poses={
                    "source": RigidTransform.identity("source"),
                    "target": RigidTransform.identity("target"),
                    "extra": RigidTransform.identity("extra"),
                },
                source_component_id="source",
                target_component_id="target",
                surfaces={
                    "surface": PlaneSurface(
                        "other", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
                    )
                },
                source_files=[self.source],
                repository_root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
