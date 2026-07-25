from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis.validate_release_construction_gate import (
    PHASES,
    _expected_release_state,
    validate_release_construction_gate,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseConstructionGateValidatorTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> dict[str, Path | str]:
        particle_table = root / "source.ion"
        rows = [
            [0.001 * index, 100.0, 1.0, *[float(index + column) for column in range(8)]]
            for index in range(1, 101)
        ]
        with particle_table.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(rows)
        particle_sha256 = _sha256(particle_table)
        run_config_path = root / "run_config.json"
        run_config_path.write_text(
            json.dumps(
                {
                    "role": "rf_quadrupole_comsol_run_config",
                    "particles": 100,
                    "inputs": {"particle_table": str(particle_table)},
                    "provenance": {"particle_source_sha256": particle_sha256},
                    "compiled_scientific_spec": {
                        "role": "rf_quadrupole_comsol_interface_scientific_spec",
                        "source_axial_offset_mm": 0.25,
                    },
                }
            ),
            encoding="utf-8",
        )

        runtime_dir = root / "runtime"
        runtime_dir.mkdir()
        release_files: list[Path] = []
        release_hashes: list[str] = []
        for index in range(1, 101):
            path = runtime_dir / f"particle_{index:03d}.txt"
            release_state = _expected_release_state(rows[index - 1], 0.25)
            path.write_text(
                "\t".join(f"{value:.17g}" for value in release_state) + "\n",
                encoding="utf-8",
            )
            release_files.append(path)
            release_hashes.append(_sha256(path))

        result_path = root / "result.json"
        result = {
            "schema_version": 1,
            "role": "rf_release_construction_gate_result",
            "status": "success",
            "particles": 100,
            "release_tag_count": 100,
            "release_file_count": 100,
            "release_files": [
                {
                    "particle_index": index,
                    "relative_path": f"runtime/particle_{index:03d}.txt",
                    "sha256": release_hashes[index - 1],
                    "row_count": 1,
                    "column_count": 6,
                }
                for index in range(1, 101)
            ],
            "birth_time_count": 100,
            "unique_birth_time_count": 100,
            "unique_release_time_expression_count": 100,
            "first_release_tag": "rel001",
            "last_release_tag": "rel100",
            "breadcrumb_count": 1000,
            "stationary_study_present": True,
            "stationary_solver_present": True,
            "electric_force_present": False,
            "particle_study_present": False,
            "particle_solver_present": False,
            "particle_table_sha256": particle_sha256,
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")

        breadcrumbs = root / "breadcrumbs.jsonl"
        records: list[dict[str, object]] = []
        sequence = 0
        for particle_index in range(1, 101):
            expression = f"{rows[particle_index - 1][0]:.12g}[us]"
            for phase_index, phase in enumerate(PHASES):
                sequence += 1
                records.append(
                    {
                        "schema_version": 1,
                        "role": "rf_release_construction_breadcrumb",
                        "run_id": "test-run",
                        "sequence": sequence,
                        "particle_index": particle_index,
                        "release_tag": f"rel{particle_index:03d}",
                        "phase": phase,
                        "release_tag_count": (
                            particle_index - 1
                            if phase == "before_create"
                            else particle_index
                        ),
                        "release_time_us": rows[particle_index - 1][0],
                        "release_time_expression": expression,
                        "file_relative_path": (
                            f"runtime/particle_{particle_index:03d}.txt"
                        ),
                        "file_sha256": release_hashes[particle_index - 1],
                        "row_count": 1,
                        "column_count": 6,
                        "actual_filename": (
                            ""
                            if phase_index < PHASES.index("after_set_filename")
                            else str(release_files[particle_index - 1])
                        ),
                        "actual_release_time_expression": (
                            expression
                            if phase_index >= PHASES.index("after_set_rt")
                            else ""
                        ),
                    }
                )
        breadcrumbs.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
        return {
            "run_config_path": run_config_path,
            "particle_table": particle_table,
            "breadcrumbs": breadcrumbs,
            "result_path": result_path,
            "runtime_dir": runtime_dir,
        }

    def validate(self, fixture: dict[str, Path | str]) -> dict[str, object]:
        return validate_release_construction_gate(
            run_config_path=fixture["run_config_path"],  # type: ignore[arg-type]
            particle_table=fixture["particle_table"],  # type: ignore[arg-type]
            breadcrumbs=fixture["breadcrumbs"],  # type: ignore[arg-type]
            result_path=fixture["result_path"],  # type: ignore[arg-type]
            runtime_dir=fixture["runtime_dir"],  # type: ignore[arg-type]
        )

    def test_valid_fixed_n100_artifacts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            validation = self.validate(self.build_fixture(Path(directory)))
        self.assertEqual(validation["status"], "success")
        self.assertEqual(validation["breadcrumbs"], 1000)

    def test_invalid_source_contracts_fail_closed(self) -> None:
        mutations = ("count", "shape", "nonfinite", "duplicate", "formatted_duplicate")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                fixture = self.build_fixture(Path(directory))
                particle_table = fixture["particle_table"]
                assert isinstance(particle_table, Path)
                with particle_table.open(encoding="utf-8") as stream:
                    rows = list(csv.reader(stream))
                if mutation == "count":
                    rows.pop()
                elif mutation == "shape":
                    rows[0].pop()
                elif mutation == "nonfinite":
                    rows[0][0] = "nan"
                elif mutation == "duplicate":
                    rows[1][0] = rows[0][0]
                else:
                    rows[0][0] = "1"
                    rows[1][0] = "1.0000000000001"
                with particle_table.open("w", encoding="utf-8", newline="") as stream:
                    csv.writer(stream, lineterminator="\n").writerows(rows)
                run_config_path = fixture["run_config_path"]
                assert isinstance(run_config_path, Path)
                run_config = json.loads(run_config_path.read_text())
                run_config["provenance"]["particle_source_sha256"] = _sha256(
                    particle_table
                )
                run_config_path.write_text(json.dumps(run_config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.validate(fixture)

    def test_tampered_release_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            runtime_dir = fixture["runtime_dir"]
            assert isinstance(runtime_dir, Path)
            (runtime_dir / "particle_065.txt").write_text(
                "1\t2\t3\t4\t5\t999\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                self.validate(fixture)

    def test_synchronized_release_hash_tampering_still_fails_physical_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            runtime_dir = fixture["runtime_dir"]
            result_path = fixture["result_path"]
            breadcrumbs = fixture["breadcrumbs"]
            assert isinstance(runtime_dir, Path)
            assert isinstance(result_path, Path)
            assert isinstance(breadcrumbs, Path)
            release_path = runtime_dir / "particle_065.txt"
            values = [float(value) for value in release_path.read_text().split()]
            values[0] += 0.5
            release_path.write_text(
                "\t".join(f"{value:.17g}" for value in values) + "\n",
                encoding="utf-8",
            )
            forged_hash = _sha256(release_path)
            result = json.loads(result_path.read_text())
            result["release_files"][64]["sha256"] = forged_hash
            result_path.write_text(json.dumps(result), encoding="utf-8")
            records = [
                json.loads(line) for line in breadcrumbs.read_text().splitlines()
            ]
            for record in records[640:650]:
                record["file_sha256"] = forged_hash
            breadcrumbs.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "frozen ION11/scientific-spec"):
                self.validate(fixture)

    def test_tampered_breadcrumb_contracts_fail_closed(self) -> None:
        mutations = ("hash", "phase", "sequence", "rt")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                fixture = self.build_fixture(Path(directory))
                breadcrumbs = fixture["breadcrumbs"]
                assert isinstance(breadcrumbs, Path)
                records = [
                    json.loads(line) for line in breadcrumbs.read_text().splitlines()
                ]
                target = records[644]
                if mutation == "hash":
                    target["file_sha256"] = "0" * 64
                elif mutation == "phase":
                    target["phase"] = "after_import"
                elif mutation == "sequence":
                    target["sequence"] = 9999
                else:
                    records[648]["actual_release_time_expression"] = "0[us]"
                breadcrumbs.write_text(
                    "".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    self.validate(fixture)


if __name__ == "__main__":
    unittest.main()
