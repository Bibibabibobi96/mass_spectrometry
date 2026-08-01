from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    publish_family_source_bundle as publisher,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    write_oatof_simion_input as oatof_writer,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.rf_handoff_adapter import (
    decode_simion_accelerator_velocity,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_BASE_PATH = (
    INTEGRATION_ROOT / "config" / "family_dependencies_base.json"
)
DEPENDENCY_OVERLAY_PATH = (
    INTEGRATION_ROOT
    / "config"
    / "family_quadrupole_dependencies_overlay.json"
)
PROFILE_REGISTRY_PATH = INTEGRATION_ROOT / "config" / "connection_profiles.json"
SOURCE_CONTRACT_PATH = (
    INTEGRATION_ROOT / "config" / "family_quadrupole_n100_source_contract.json"
)
FAMILY_PROFILE_ID = (
    "rf_quadrupole_no_acceleration_full_length_direct_mating_gap_0mm"
)
PRE_PULSE_CONSUMER = "pre_pulse_interface_transport"
PUBLISHER_DEPENDENCY_ID = "rf_family_source_bundle_publisher"

SOURCE_COLUMNS = [
    "particle_id",
    "birth_time_s",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "mass_amu",
    "charge_state",
]


class FamilySourceBundlePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contract_path = self.root / "handoff_contract.json"
        self.resolved_path = self.root / "resolved_connection.json"
        self.state_path = self.root / "state.csv"
        self.source_path = self.root / "source.csv"
        self.canonical_path = self.root / "canonical.csv"
        self.ion_path = self.root / "particles.ion"
        self.row_map_path = self.root / "row_map.csv"
        self.metadata_path = self.root / "metadata.json"

        self.contract = {
            "schema_version": 1,
            "role": "multipole_handoff_publication_contract",
            "selector": {"event": "handoff", "status": "transmitted"},
            "geometry": {
                "axial_plane_mm": 90.2,
                "absolute_tolerance_mm": 1e-9,
                "require_positive_axial_velocity": True,
            },
            "population": {
                "expected_source_particle_count": 2,
                "source_particle_id_policy": "contiguous_one_based",
                "handoff_particle_id_policy": "unique_subset_of_source",
            },
            "canonical_state": {
                "state_event": "canonical_handoff",
                "frame_id": "multipole_cartesian_z_axis_v1",
                "clock_epoch_id": "instrument_clock_epoch_v1",
                "source_component_id": "rf_hexapole_ion_optics",
                "target_component_id": "single_reflection_oa_tof_mass_analyzer",
                "lineage_policy": "root_birth_time_plus_component_elapsed_time",
                "species_policy": "frozen_particle_source_mass_and_charge",
                "particle_weight": 1,
                "phase_reference_id": "multipole_rf_drive",
                "clock_tolerance_us": 1e-9,
            },
        }
        self.resolved = {
            "integration_id": publisher.EXPECTED_INTEGRATION_ID,
            "selection": {
                "downstream_project_id": publisher.EXPECTED_DOWNSTREAM_PROJECT_ID
            },
            "coupling_mode": "monolithic_joint_solve",
            "port_geometry": {
                "upstream": {
                    "coordinate_frame": {
                        "frame_id": "multipole_cartesian_z_axis_v1"
                    }
                },
                "downstream": {
                    "coordinate_frame": {"frame_id": "oatof_global"}
                },
            },
            "spatial_registration": {
                "rotation_upstream_to_downstream": [
                    [0.0, 0.0, 1.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                ],
                "translation_mm": [-158.0, 0.0, -18.42918680341103],
            },
        }
        self.contract_path.write_text(
            json.dumps(self.contract), encoding="utf-8"
        )
        self.resolved_path.write_text(
            json.dumps(self.resolved), encoding="utf-8"
        )
        self._write_csv(
            self.source_path,
            SOURCE_COLUMNS,
            [
                {
                    "particle_id": particle_id,
                    "birth_time_s": (particle_id - 1) * 2e-7,
                    "x_mm": 0,
                    "y_mm": 0,
                    "z_mm": 0,
                    "vx_m_s": 0,
                    "vy_m_s": 0,
                    "vz_m_s": 1000,
                    "mass_amu": 100 + particle_id,
                    "charge_state": 1,
                }
                for particle_id in (1, 2)
            ],
        )
        self._write_csv(
            self.state_path,
            PARTICLE_STATE_COLUMNS,
            [
                self._state_row(1, 1.25, 0.2, -0.3, 10.0, -20.0, 1000.0),
                self._state_row(2, 1.7, -0.1, 0.4, -30.0, 40.0, 900.0),
            ],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_csv(
        path: Path, columns: list[str], rows: list[dict[str, object]]
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=columns, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _state_row(
        particle_id: int,
        time_us: float,
        x_mm: float,
        y_mm: float,
        velocity_x: float,
        velocity_y: float,
        velocity_axial: float,
    ) -> dict[str, object]:
        birth_time_us = (particle_id - 1) * 0.2
        elapsed = time_us - birth_time_us
        return {
            "particle_id": particle_id,
            "event": "handoff",
            "status": "transmitted",
            "terminal_reason": "none",
            "time_us": time_us,
            "elapsed_time_us": elapsed,
            "rf_phase_rad": 0.5,
            "axial_z_mm": 90.2,
            "transverse_x_mm": x_mm,
            "transverse_y_mm": y_mm,
            "velocity_axial_m_s": velocity_axial,
            "velocity_x_m_s": velocity_x,
            "velocity_y_m_s": velocity_y,
            "kinetic_energy_eV": 1,
            "radial_position_mm": math.hypot(x_mm, y_mm),
            "divergence_angle_deg": 1,
            "max_rod_radius_mm": math.hypot(x_mm, y_mm),
        }

    def _publish(self) -> dict:
        with (
            patch.object(publisher, "validate_schema") as schema_validator,
            patch.object(
                publisher,
                "write_oatof_simion_input",
                wraps=oatof_writer.write_oatof_simion_input,
            ) as adapter_writer,
        ):
            result = publisher.publish_family_source_bundle(
                self.contract_path,
                self.resolved_path,
                self.state_path,
                self.source_path,
                self.canonical_path,
                self.ion_path,
                self.row_map_path,
                self.metadata_path,
            )
        schema_validator.assert_called_once_with(
            self.resolved, "resolved_connection.schema.json"
        )
        adapter_writer.assert_called_once()
        return result

    def _build_pre_pulse_runtime_snapshot(self) -> tuple[Path, Path]:
        dependency_contract = json.loads(
            DEPENDENCY_BASE_PATH.read_text(encoding="utf-8")
        )
        dependency_overlay = json.loads(
            DEPENDENCY_OVERLAY_PATH.read_text(encoding="utf-8")
        )
        dependency_contract["dependencies"].extend(
            dependency_overlay["dependencies"]
        )
        dependencies = [
            dependency
            for dependency in dependency_contract["dependencies"]
            if PRE_PULSE_CONSUMER in dependency["consumers"]
        ]
        self.assertTrue(dependencies)
        publisher_dependencies = [
            dependency
            for dependency in dependencies
            if dependency["id"] == PUBLISHER_DEPENDENCY_ID
        ]
        self.assertEqual(len(publisher_dependencies), 1)
        publisher_dependency = publisher_dependencies[0]

        frozen_names = {
            dependency["frozen_filename"] for dependency in dependencies
        }
        self.assertIn(
            "runtime_snapshot/common/contracts/component_particle_state.py",
            frozen_names,
        )
        self.assertIn(
            (
                "runtime_snapshot/common/contracts/schemas/"
                "resolved_connection.schema.json"
            ),
            frozen_names,
        )
        self.assertIn(
            (
                "runtime_snapshot/common/contracts/schemas/"
                "connection_profile.schema.json"
            ),
            frozen_names,
        )
        self.assertIn(
            (
                "runtime_snapshot/common/contracts/schemas/"
                "component_port.schema.json"
            ),
            frozen_names,
        )

        for dependency in dependencies:
            source = REPO_ROOT / dependency["source_repo_path"]
            destination = self.root / dependency["frozen_filename"]
            self.assertTrue(source.is_file(), source)
            self.assertEqual(
                destination.relative_to(self.root).parts[0],
                "runtime_snapshot",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        snapshot_root = self.root / "runtime_snapshot"
        snapshot_publisher = self.root / publisher_dependency["frozen_filename"]
        live_publisher = REPO_ROOT / publisher_dependency["source_repo_path"]
        source_contract = json.loads(
            SOURCE_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(
            source_contract["adapter"]["path"],
            publisher_dependency["source_repo_path"],
        )
        self.assertEqual(
            file_sha256(snapshot_publisher),
            file_sha256(live_publisher),
        )
        self.assertEqual(
            file_sha256(snapshot_publisher),
            source_contract["adapter"]["sha256"],
        )
        return snapshot_root, snapshot_publisher

    def _run_snapshot_publisher(
        self, snapshot_root: Path, snapshot_publisher: Path
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(snapshot_root)
        environment["PYTHONNOUSERSITE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                str(snapshot_publisher),
                "--handoff-contract",
                str(self.contract_path),
                "--resolved-connection",
                str(self.resolved_path),
                "--state",
                str(self.state_path),
                "--source",
                str(self.source_path),
                "--canonical-output",
                str(self.canonical_path),
                "--ion-output",
                str(self.ion_path),
                "--row-map-output",
                str(self.row_map_path),
                "--metadata-output",
                str(self.metadata_path),
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def _assert_snapshot_failure_when_missing(
        self,
        snapshot_root: Path,
        snapshot_publisher: Path,
        frozen_relative_path: str,
    ) -> None:
        frozen_path = snapshot_root / frozen_relative_path
        held_path = frozen_path.with_name(f"{frozen_path.name}.held")
        frozen_path.rename(held_path)
        try:
            completed = self._run_snapshot_publisher(
                snapshot_root, snapshot_publisher
            )
        finally:
            held_path.rename(frozen_path)
        self.assertNotEqual(
            completed.returncode,
            0,
            msg=(
                "Publisher unexpectedly escaped the frozen snapshot after "
                f"{frozen_relative_path} was removed.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            ),
        )

    def test_publishes_transformed_canonical_ion11_row_map_and_metadata(self) -> None:
        metadata = self._publish()
        report = validate_component_particle_state_csv(self.canonical_path)
        self.assertEqual(report["particles"], 2)
        self.assertEqual(report["frame_ids"], ["oatof_global"])

        with self.canonical_path.open(encoding="utf-8", newline="") as handle:
            canonical = list(csv.DictReader(handle))
        self.assertEqual(list(canonical[0]), csv_columns())
        first = canonical[0]
        self.assertAlmostEqual(float(first["position_x_mm"]), -67.8)
        self.assertAlmostEqual(float(first["position_y_mm"]), 0.2)
        self.assertAlmostEqual(float(first["position_z_mm"]), -18.72918680341103)
        transformed_velocity = (1000.0, 10.0, -20.0)
        for axis, expected in zip("xyz", transformed_velocity):
            self.assertAlmostEqual(float(first[f"velocity_{axis}_m_s"]), expected)

        with self.row_map_path.open(encoding="utf-8", newline="") as handle:
            row_map = list(csv.DictReader(handle))
        self.assertEqual(list(row_map[0]), oatof_writer.ROW_MAP_COLUMNS)
        self.assertEqual(
            [row["solver_row_index"] for row in row_map], ["1", "2"]
        )
        self.assertEqual([row["particle_id"] for row in row_map], ["1", "2"])
        self.assertEqual(
            row_map[0]["solver_birth_time_us"], first["instrument_time_us"]
        )

        ion_rows = list(csv.reader(self.ion_path.read_text().splitlines()))
        self.assertTrue(all(len(row) == 11 for row in ion_rows))
        decoded = decode_simion_accelerator_velocity(
            float(ion_rows[0][1]),
            float(ion_rows[0][8]),
            float(ion_rows[0][6]),
            float(ion_rows[0][7]),
        )
        for actual, expected in zip(decoded, transformed_velocity):
            self.assertTrue(
                math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8)
            )

        recorded = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata, recorded)
        self.assertEqual(
            recorded["validation"]["simion_velocity_decode_round_trip"],
            "PASS",
        )
        self.assertEqual(
            recorded["outputs"]["canonical_handoff_csv"]["sha256"],
            file_sha256(self.canonical_path),
        )

    def test_repository_publisher_closes_over_frozen_pre_pulse_snapshot(
        self,
    ) -> None:
        resolved = resolve_connection_profile(
            load_connection_profile_registry(PROFILE_REGISTRY_PATH),
            FAMILY_PROFILE_ID,
            repo_root=REPO_ROOT,
        )
        self.resolved_path.write_text(
            json.dumps(resolved), encoding="utf-8"
        )
        snapshot_root, snapshot_publisher = (
            self._build_pre_pulse_runtime_snapshot()
        )

        completed = self._run_snapshot_publisher(
            snapshot_root, snapshot_publisher
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=(
                "Frozen-snapshot publisher execution failed.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            ),
        )
        self.assertIn(
            "FAMILY_SOURCE_BUNDLE=PASS",
            completed.stdout,
        )

        self._assert_snapshot_failure_when_missing(
            snapshot_root,
            snapshot_publisher,
            snapshot_publisher.relative_to(snapshot_root).as_posix(),
        )
        self._assert_snapshot_failure_when_missing(
            snapshot_root,
            snapshot_publisher,
            "common/contracts/component_particle_state.py",
        )
        self._assert_snapshot_failure_when_missing(
            snapshot_root,
            snapshot_publisher,
            "common/contracts/schemas/resolved_connection.schema.json",
        )
        self._assert_snapshot_failure_when_missing(
            snapshot_root,
            snapshot_publisher,
            "common/contracts/schemas/connection_profile.schema.json",
        )
        self._assert_snapshot_failure_when_missing(
            snapshot_root,
            snapshot_publisher,
            "common/contracts/schemas/component_port.schema.json",
        )

    def test_rejects_canonical_frame_that_differs_from_resolved_upstream(self) -> None:
        self.contract["canonical_state"]["frame_id"] = "wrong_frame"
        self.contract_path.write_text(
            json.dumps(self.contract), encoding="utf-8"
        )
        with patch.object(publisher, "validate_schema"):
            with self.assertRaisesRegex(
                ValueError, "differs from resolved upstream frame"
            ):
                publisher.publish_family_source_bundle(
                    self.contract_path,
                    self.resolved_path,
                    self.state_path,
                    self.source_path,
                    self.canonical_path,
                    self.ion_path,
                    self.row_map_path,
                    self.metadata_path,
                )

    def test_rejects_non_monolithic_connection(self) -> None:
        self.resolved["coupling_mode"] = "state_handoff"
        self.resolved_path.write_text(
            json.dumps(self.resolved), encoding="utf-8"
        )
        with patch.object(publisher, "validate_schema"):
            with self.assertRaisesRegex(
                ValueError, "requires monolithic_joint_solve"
            ):
                publisher.publish_family_source_bundle(
                    self.contract_path,
                    self.resolved_path,
                    self.state_path,
                    self.source_path,
                    self.canonical_path,
                    self.ion_path,
                    self.row_map_path,
                    self.metadata_path,
                )


if __name__ == "__main__":
    unittest.main()
