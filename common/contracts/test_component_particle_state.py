import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.contracts.particle_state import (
    SCHEMA_VERSION,
    csv_columns,
    load_schema,
    load_component_particle_state_csv,
    validate_component_particle_state_csv,
    validate_component_particle_state_rows,
    write_component_particle_state_csv,
)
from msplatform.contracts.particle_physics import kinetic_energy_ev


def valid_row(particle_id: int = 7) -> dict[str, object]:
    mass_amu = 100.0
    velocity = (1000.0, -2000.0, 3000.0)
    return {
        "particle_id": particle_id,
        "parent_particle_id": "",
        "generation": 0,
        "species_id": "ion_100amu_q1",
        "particle_weight": 1.0,
        "source_component_id": "source_component",
        "target_component_id": "target_component",
        "state_event": "component_exit",
        "frame_id": "instrument_global",
        "clock_epoch_id": "instrument_clock_epoch.v1",
        "instrument_time_us": 12.5,
        "lineage_age_us": 7.5,
        "particle_age_us": 7.5,
        "last_component_elapsed_time_us": 2.0,
        "lineage_birth_time_us": 5.0,
        "particle_birth_time_us": 5.0,
        "mass_to_charge_Th": 100.0,
        "mass_amu": mass_amu,
        "charge_state": 1,
        "position_x_mm": 1.0,
        "position_y_mm": -2.0,
        "position_z_mm": 3.0,
        "velocity_x_m_s": velocity[0],
        "velocity_y_m_s": velocity[1],
        "velocity_z_m_s": velocity[2],
        "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity),
        "phase_reference_id": "source_rf.v1",
        "phase_rad": 1.2,
    }


class ComponentParticleStateTests(unittest.TestCase):
    def test_typed_row_validator_and_csv_share_one_contract_without_mutation(self) -> None:
        import copy

        row = valid_row(91)
        self.write([row])
        typed = dict(row, parent_particle_id=None)
        before = copy.deepcopy(typed)
        direct = validate_component_particle_state_rows([typed])
        parsed = load_component_particle_state_csv(self.path)
        self.assertEqual(direct, parsed)
        self.assertEqual(typed, before)
        direct.rows[0]["particle_weight"] = 2.
        self.assertEqual(typed["particle_weight"], 1.)

    def test_all_typed_integer_fields_reject_float_bool_string_and_illegal_null(self) -> None:
        for field in ("particle_id", "parent_particle_id", "generation", "charge_state"):
            for value in (7.0, 7.5, True, False, "7", "", None):
                if field == "parent_particle_id" and value is None:
                    continue
                with self.subTest(field=field, value=value, type=type(value).__name__):
                    row = dict(valid_row(), parent_particle_id=None)
                    row[field] = value
                    with self.assertRaisesRegex(ValueError, field + " must be a typed integer"):
                        validate_component_particle_state_rows([row])
        row = dict(valid_row(), parent_particle_id=None)
        del row["particle_id"]
        with self.assertRaisesRegex(ValueError, "required property"):
            validate_component_particle_state_rows([row])

    def test_typed_sparse_large_and_descendant_integers_round_trip_exactly(self) -> None:
        import copy

        large = 2 ** 60 + 17
        rows = [dict(valid_row(91), parent_particle_id=None),
                dict(valid_row(large), parent_particle_id=91, generation=1)]
        original = copy.deepcopy(rows)
        validated = validate_component_particle_state_rows(rows)
        write_component_particle_state_csv(self.path, validated.rows)
        parsed = load_component_particle_state_csv(self.path)
        self.assertEqual(validated, parsed)
        self.assertEqual(rows, original)
        self.assertEqual([row["particle_id"] for row in parsed.rows], [91, large])
        for row in parsed.rows:
            for field in ("particle_id", "generation", "charge_state"):
                self.assertIs(type(row[field]), int)
            if row["parent_particle_id"] is not None:
                self.assertIs(type(row["parent_particle_id"]), int)
        validated.rows[1]["generation"] = 3
        self.assertEqual(rows[1]["generation"], 1)

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "state.csv"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(
        self,
        rows: list[dict[str, object]],
        columns: list[str] | None = None,
    ) -> None:
        fields = columns or csv_columns()
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_accepts_complete_transfer_state(self) -> None:
        self.write([valid_row(7), valid_row(9)])
        report = validate_component_particle_state_csv(self.path)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["particles"], 2)
        self.assertEqual(report["frame_ids"], ["instrument_global"])
        self.assertEqual(report["clock_epoch_ids"], ["instrument_clock_epoch.v1"])

    def test_core_source_and_legacy_bridge_share_the_same_transfer_contract(self) -> None:
        from common.contracts import component_particle_state as bridge
        from msplatform.contracts import particle_state as core
        from msplatform.contracts.rigid_transform import PhaseSpaceState

        self.assertIs(bridge, core)
        self.assertIs(core.PhaseSpaceState, PhaseSpaceState)
        for name in ("ComponentParticleStateTable", "load_component_particle_state_csv",
                     "validate_component_particle_state_csv", "write_component_particle_state_csv"):
            self.assertEqual(getattr(core, name).__module__, "msplatform.contracts.particle_state")
        row = valid_row(91)
        row.update(state_event="snapshot", phase_reference_id="", phase_rad="")
        self.write([row])
        table = load_component_particle_state_csv(self.path)
        self.assertEqual(table.rows[0]["particle_id"], 91)
        self.assertEqual(table.rows[0]["state_event"], "snapshot")
        self.assertNotIn("terminal", table.report)
        self.assertIsNone(table.rows[0]["phase_rad"])

    def test_legacy_and_canonical_cli_validate_the_same_actual_csv(self) -> None:
        self.write([valid_row(91)])
        root = Path(__file__).resolve().parents[2]
        outputs = []
        for module in ("common.contracts.component_particle_state", "msplatform.contracts.particle_state"):
            result = subprocess.run([sys.executable, "-m", module, "--state", str(self.path)],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs, ["COMPONENT_PARTICLE_STATE=PASS SCHEMA_VERSION=1 PARTICLES=1\n"] * 2)

    def test_loader_reads_once_returns_typed_rows_and_preserves_order(self) -> None:
        rows = [valid_row(9), valid_row(2)]
        rows[0].update(phase_reference_id="", phase_rad="")
        self.write(rows)
        original = self.path.read_bytes()
        open_file, reads = Path.open, []

        def track(path, *args, **kwargs):
            if path == self.path:
                reads.append(path)
            return open_file(path, *args, **kwargs)

        with patch.object(Path, "open", track):
            table = load_component_particle_state_csv(self.path)
        self.assertEqual(len(reads), 1)
        self.assertEqual([row["particle_id"] for row in table.rows], [9, 2])
        self.assertIs(type(table.rows[0]["charge_state"]), int)
        self.assertIs(type(table.rows[0]["mass_amu"]), float)
        self.assertIsNone(table.rows[0]["parent_particle_id"])
        self.assertIsNone(table.rows[0]["phase_rad"])
        self.assertIsNone(table.rows[0]["phase_reference_id"])
        self.assertEqual(table.rows[1]["species_id"], "ion_100amu_q1")
        self.assertEqual(table.report, validate_component_particle_state_csv(self.path))
        self.assertEqual(self.path.read_bytes(), original)

    def test_numeric_lexemes_compare_equal_without_coercing_string_identity(self) -> None:
        row = valid_row()
        row.update(mass_amu="100", species_id="ion100")
        self.write([row])
        original = load_component_particle_state_csv(self.path).rows
        row["mass_amu"] = "100.0"
        self.write([row])
        self.assertEqual(load_component_particle_state_csv(self.path).rows, original)
        row["species_id"] = "ion100.0"
        self.write([row])
        self.assertNotEqual(load_component_particle_state_csv(self.path).rows, original)
        self.assertEqual(load_component_particle_state_csv(self.path).rows[0]["species_id"], "ion100.0")

    def test_writer_uses_schema_order_and_validates_output(self) -> None:
        report = write_component_particle_state_csv(
            self.path, [valid_row(7), valid_row(9)]
        )
        with self.path.open(encoding="utf-8", newline="") as handle:
            self.assertEqual(next(csv.reader(handle)), csv_columns())
        self.assertEqual(report["particles"], 2)

    def test_writer_rejects_unknown_fields(self) -> None:
        row = valid_row()
        row["project_private_field"] = "not canonical"
        with self.assertRaisesRegex(ValueError, "fields not in fieldnames"):
            write_component_particle_state_csv(self.path, [row])

    def test_schema_version_matches_validator(self) -> None:
        self.assertEqual(load_schema()["x-csv-schema-version"], SCHEMA_VERSION)

    def test_rejects_reordered_or_extended_columns(self) -> None:
        columns = csv_columns()
        columns[0], columns[1] = columns[1], columns[0]
        self.write([valid_row()], columns)
        with self.assertRaisesRegex(ValueError, "columns differ"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_duplicate_particle_identity(self) -> None:
        self.write([valid_row(), valid_row()])
        with self.assertRaisesRegex(ValueError, "duplicate particle_id"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_nonfinite_spatial_state(self) -> None:
        row = valid_row()
        row["velocity_z_m_s"] = math.inf
        self.write([row])
        with self.assertRaisesRegex(ValueError, "must be finite"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_clock_discontinuity(self) -> None:
        row = valid_row()
        row["particle_age_us"] = 6.0
        self.write([row])
        with self.assertRaisesRegex(ValueError, "particle clock residual"):
            validate_component_particle_state_csv(self.path)

    def test_requires_parent_for_descendant(self) -> None:
        row = valid_row()
        row["generation"] = 1
        self.write([row])
        with self.assertRaisesRegex(ValueError, "requires a parent"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_root_with_distinct_lineage_clock(self) -> None:
        row = valid_row()
        row["lineage_birth_time_us"] = 4.0
        row["lineage_age_us"] = 8.5
        self.write([row])
        with self.assertRaisesRegex(ValueError, "root particle clock"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_descendant_born_before_lineage(self) -> None:
        row = valid_row()
        row["generation"] = 1
        row["parent_particle_id"] = 3
        row["particle_birth_time_us"] = 4.0
        row["particle_age_us"] = 8.5
        self.write([row])
        with self.assertRaisesRegex(ValueError, "born before its lineage"):
            validate_component_particle_state_csv(self.path)

    def test_accepts_open_component_and_event_identifiers(self) -> None:
        row = valid_row()
        row["source_component_id"] = "future-source:stage_2"
        row["state_event"] = "custom.exit"
        self.write([row])
        report = validate_component_particle_state_csv(self.path)
        self.assertEqual(report["status"], "PASS")

    def test_accepts_state_without_phase_reference(self) -> None:
        row = valid_row()
        row["phase_reference_id"] = ""
        row["phase_rad"] = ""
        self.write([row])
        self.assertEqual(
            validate_component_particle_state_csv(self.path)["status"],
            "PASS",
        )

    def test_rejects_half_populated_phase_reference(self) -> None:
        row = valid_row()
        row["phase_reference_id"] = ""
        self.write([row])
        with self.assertRaisesRegex(ValueError, "not valid"):
            validate_component_particle_state_csv(self.path)

    def test_accepts_states_before_clock_epoch(self) -> None:
        row = valid_row()
        row["instrument_time_us"] = -2.0
        row["lineage_birth_time_us"] = -9.5
        row["particle_birth_time_us"] = -9.5
        self.write([row])
        self.assertEqual(
            validate_component_particle_state_csv(self.path)["status"],
            "PASS",
        )

    def test_accepts_negative_electron_charge(self) -> None:
        row = valid_row()
        row["species_id"] = "electron"
        row["mass_amu"] = 5.485799090441e-4
        row["charge_state"] = -1
        row["mass_to_charge_Th"] = row["mass_amu"]
        row["kinetic_energy_eV"] = kinetic_energy_ev(
            float(row["mass_amu"]),
            float(row["velocity_x_m_s"]),
            float(row["velocity_y_m_s"]),
            float(row["velocity_z_m_s"]),
        )
        self.write([row])
        self.assertEqual(
            validate_component_particle_state_csv(self.path)["status"],
            "PASS",
        )

    def test_rejects_inconsistent_energy(self) -> None:
        row = valid_row()
        row["kinetic_energy_eV"] = float(row["kinetic_energy_eV"]) + 1.0
        self.write([row])
        with self.assertRaisesRegex(ValueError, "kinetic_energy_eV is inconsistent"):
            validate_component_particle_state_csv(self.path)

    def test_rejects_inconsistent_mass_to_charge(self) -> None:
        row = valid_row()
        row["mass_to_charge_Th"] = 50.0
        self.write([row])
        with self.assertRaisesRegex(ValueError, "mass_to_charge_Th is inconsistent"):
            validate_component_particle_state_csv(self.path)


if __name__ == "__main__":
    unittest.main()
