"""Grouped release v2 public-validator behavior, isolated tiny files, no vendor."""

from pathlib import Path
import csv
import hashlib
import json
import os
import sys
import subprocess
import tempfile
import unittest

from projects.rf_multipole_ion_optics.analysis import validate_release_construction_gate as V

REPO = Path(__file__).resolve().parents[4]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root, unique=False, all_same=False):
    table = root / "ions.csv"
    rows = [
        [
            0.0 if all_same else (i * 0.01 if unique else float(i % 2)),
            100,
            1,
            i,
            2,
            3,
            0,
            0,
            0,
            1,
            1,
        ]
        for i in range(100)
    ]
    with table.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    source_hash = digest(table)
    config = root / "run_config.json"
    config.write_text(
        json.dumps(
            dict(
                role="rf_quadrupole_comsol_run_config",
                particles=100,
                inputs=dict(particle_table=str(table)),
                provenance=dict(particle_source_sha256=source_hash),
                compiled_scientific_spec=dict(
                    role="rf_quadrupole_comsol_interface_scientific_spec",
                    source_axial_offset_mm=0.25,
                ),
            )
        )
    )
    groups = {}
    for i, row in enumerate(rows, 1):
        groups.setdefault(row[0] * 1e-6, []).append(i)
    runtime = root / "runtime"
    runtime.mkdir()
    entries = []
    records = []
    for group_index, (birth, indices) in enumerate(groups.items(), 1):
        path = runtime / f"particle_{group_index:03d}.txt"
        path.write_text(
            "".join(f"3\t-2\t{row - 1 + 0.25:.17g}\t0\t0\t0\n" for row in indices)
        )
        h = digest(path)
        expr = f"{birth:.17g}[s]"
        entries.append(
            dict(
                group_index=group_index,
                source_rows=indices,
                particle_ids=indices,
                birth_s=birth,
                relative_path=f"runtime/{path.name}",
                sha256=h,
                row_count=len(indices),
                column_count=6,
            )
        )
        for phase_index, phase in enumerate(V.PHASES):
            records.append(
                dict(
                    schema_version=2,
                    role="rf_release_construction_breadcrumb",
                    sequence=len(records) + 1,
                    group_index=group_index,
                    source_rows=indices,
                    release_tag=f"rel{group_index:03d}",
                    phase=phase,
                    release_tag_count=group_index - 1
                    if phase == "before_create"
                    else group_index,
                    file_relative_path=f"runtime/{path.name}",
                    file_sha256=h,
                    row_count=len(indices),
                    column_count=6,
                    birth_s=birth,
                    release_time_expression=expr,
                    actual_filename=str(path) if phase_index >= 3 else "",
                    actual_release_time_expression=expr if phase_index >= 8 else "",
                )
            )
    count = len(groups)
    result = dict(
        schema_version=2,
        role="rf_release_construction_gate_result",
        status="success",
        particle_table_sha256=source_hash,
        particles=100,
        release_tag_count=count,
        release_file_count=count,
        release_files=entries,
        native_order=[i for group in groups.values() for i in group],
        birth_time_count=100,
        unique_birth_time_count=count,
        unique_release_time_expression_count=count,
        first_release_tag="rel001",
        last_release_tag=f"rel{count:03d}",
        breadcrumb_count=len(records),
        stationary_study_present=True,
        stationary_solver_present=True,
        electric_force_present=False,
        particle_study_present=False,
        particle_solver_present=False,
    )
    result_path = root / "result.json"
    result_path.write_text(json.dumps(result))
    breadcrumbs = root / "breadcrumbs.jsonl"
    breadcrumbs.write_text("\n".join(json.dumps(r) for r in records))
    return dict(
        run_config_path=config,
        particle_table=table,
        breadcrumbs=breadcrumbs,
        result_path=result_path,
        runtime_dir=runtime,
    )


class GroupedReleaseValidatorTest(unittest.TestCase):
    def test_repeated_and_unique_birth_close_same_mother(self):
        for unique, expected in [(False, 2), (True, 100)]:
            with self.subTest(unique=unique), tempfile.TemporaryDirectory() as td:
                result = V.validate_release_construction_gate(
                    **fixture(Path(td), unique)
                )
                self.assertEqual(result["release_tags"], expected)
                self.assertEqual(sorted(result["native_order"]), list(range(1, 101)))

    def test_bad_mapping_clock_shape_schema_and_failure_propagate(self):
        for fault in (
            "mapping",
            "clock",
            "shape",
            "schema",
            "breadcrumb",
            "source_state",
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as td:
                args = fixture(Path(td))
                path = args["result_path"]
                result = json.loads(path.read_text())
                if fault == "mapping":
                    result["native_order"][0] = 2
                if fault == "clock":
                    result["release_files"][0]["birth_s"] = 0.001
                if fault == "shape":
                    result["release_files"][0]["row_count"] = 1
                if fault == "schema":
                    result["schema_version"] = 1
                if fault == "breadcrumb":
                    args["breadcrumbs"].write_text("")
                if fault == "source_state":
                    next(args["runtime_dir"].glob("*.txt")).write_text(
                        "NaN\t0\t0\t0\t0\t0\n"
                    )
                path.write_text(json.dumps(result))
                with self.assertRaises(ValueError):
                    V.validate_release_construction_gate(**args)

    def test_cli_reports_actual_group_and_breadcrumb_counts(self):
        for all_same, count in ((True, 1), (False, 2)):
            with self.subTest(groups=count), tempfile.TemporaryDirectory() as td:
                args = fixture(Path(td), all_same=all_same)
                output = Path(td) / "validation.json"
                command = [sys.executable, "-m", V.__name__]
                for key, value in args.items():
                    command.extend(
                        ["--" + key.replace("_", "-").replace("-path", ""), str(value)]
                    )
                command.extend(["--output", str(output)])
                environment = dict(os.environ)
                environment.pop("PYTHONPATH", None)
                execution = subprocess.run(
                    command, cwd=REPO, env=environment, capture_output=True,
                    text=True, encoding="utf-8", timeout=30
                )
                self.assertEqual(
                    execution.returncode, 0, execution.stdout + execution.stderr
                )
                self.assertIn(
                    f"GROUPS={count} BREADCRUMBS={count * 10}", execution.stdout
                )
                validation = json.loads(output.read_text())
                self.assertEqual(validation["release_files"], count)
                self.assertEqual(validation["breadcrumbs"], count * 10)
                inventory = json.loads(args["result_path"].read_text())["release_files"]
                self.assertIsInstance(inventory, list)
                self.assertEqual(len(inventory), count)

    def test_synchronized_hash_tamper_still_rejects_physical_state(self):
        with tempfile.TemporaryDirectory() as td:
            args = fixture(Path(td))
            path = args["runtime_dir"] / "particle_001.txt"
            path.write_text(path.read_text().replace("3\t-2", "4\t-2", 1))
            forged = digest(path)
            result = json.loads(args["result_path"].read_text())
            result["release_files"][0]["sha256"] = forged
            args["result_path"].write_text(json.dumps(result))
            records = [
                json.loads(line)
                for line in args["breadcrumbs"].read_text().splitlines()
            ]
            for record in records[:10]:
                record["file_sha256"] = forged
            args["breadcrumbs"].write_text("\n".join(json.dumps(r) for r in records))
            with self.assertRaisesRegex(ValueError, "6D differs"):
                V.validate_release_construction_gate(**args)

    def test_breadcrumb_and_frozen_source_fail_closed(self):
        for fault in (
            "hash",
            "phase",
            "sequence",
            "rt",
            "negative_birth",
            "mixed_species",
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as td:
                args = fixture(Path(td))
                records = [
                    json.loads(line)
                    for line in args["breadcrumbs"].read_text().splitlines()
                ]
                if fault == "hash":
                    records[4]["file_sha256"] = "0" * 64
                if fault == "phase":
                    records[4]["phase"] = "after_import"
                if fault == "sequence":
                    records[4]["sequence"] = 999
                if fault == "rt":
                    records[8]["actual_release_time_expression"] = "0[us]"
                if fault in ("negative_birth", "mixed_species"):
                    rows = list(
                        csv.reader(args["particle_table"].read_text().splitlines())
                    )
                    rows[0][0 if fault == "negative_birth" else 1] = (
                        "-1" if fault == "negative_birth" else "101"
                    )
                    with args["particle_table"].open("w", newline="") as f:
                        csv.writer(f).writerows(rows)
                args["breadcrumbs"].write_text(
                    "\n".join(json.dumps(r) for r in records)
                )
                with self.assertRaises(ValueError):
                    V.validate_release_construction_gate(**args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
