from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.multipole.phase_matched_particle_source import (
    COLUMNS,
    derive_phase_matched_source,
    validate_phase_matched_source_metadata,
)


SOURCE_ROOT = Path(__file__).resolve().parent / "sources"
N100_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_100.csv"
N1000_PATH = SOURCE_ROOT / "rf_multipole_family_mother_sample_v1_1000.csv"
BASELINE_FREQUENCY_HZ = 1_100_000.0
CANDIDATE_FREQUENCY_HZ = 1_210_000.0


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class PhaseMatchedParticleSourceTests(unittest.TestCase):
    def _derive(
        self,
        directory: Path,
        *,
        source: Path = N100_PATH,
        reference: Path | None = N1000_PATH,
        baseline_frequency_hz: float = BASELINE_FREQUENCY_HZ,
        candidate_frequency_hz: float = CANDIDATE_FREQUENCY_HZ,
        stem: str = "derived",
        target_kinetic_energy_ev: float | None = None,
    ) -> tuple[Path, Path, dict[str, object]]:
        output_csv = directory / f"{stem}.csv"
        output_metadata = directory / f"{stem}.json"
        metadata = derive_phase_matched_source(
            source,
            output_csv,
            output_metadata,
            baseline_frequency_hz=baseline_frequency_hz,
            candidate_frequency_hz=candidate_frequency_hz,
            n1000_reference_path=reference,
            target_kinetic_energy_ev=target_kinetic_energy_ev,
        )
        return output_csv, output_metadata, metadata

    def test_n100_derivation_preserves_state_and_every_particle_phase(self) -> None:
        baseline_sha = file_sha256(N100_PATH)
        with tempfile.TemporaryDirectory() as directory_name:
            output_csv, output_metadata, metadata = self._derive(Path(directory_name))
            original_rows = _read_rows(N100_PATH)
            derived_rows = _read_rows(output_csv)
            self.assertEqual(len(derived_rows), 100)
            for original, derived in zip(original_rows, derived_rows, strict=True):
                for column in COLUMNS:
                    if column != "birth_time_s":
                        self.assertEqual(derived[column], original[column])
                original_phase = (
                    float(original["birth_time_s"]) * BASELINE_FREQUENCY_HZ
                ) % 1.0
                derived_phase = (
                    float(derived["birth_time_s"]) * CANDIDATE_FREQUENCY_HZ
                ) % 1.0
                phase_error = abs(original_phase - derived_phase)
                phase_error = min(phase_error, 1.0 - phase_error)
                self.assertLessEqual(
                    phase_error,
                    metadata["rf_phase_invariance"]["maximum_allowed_error_cycles"],
                )
            self.assertEqual(metadata["baseline_source_sha256"], baseline_sha)
            self.assertEqual(metadata["derived_source_sha256"], file_sha256(output_csv))
            self.assertTrue(
                metadata["particle_count_policy"][
                    "input_n100_prefix_of_n1000_verified"
                ]
            )
            self.assertTrue(
                metadata["particle_count_policy"][
                    "derived_n100_prefix_projection_verified"
                ]
            )
            self.assertEqual(
                json.loads(output_metadata.read_text(encoding="utf-8")), metadata
            )
            validate_phase_matched_source_metadata(metadata)
        self.assertEqual(file_sha256(N100_PATH), baseline_sha)

    def test_outputs_are_deterministic_and_n100_remains_n1000_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as first_name, tempfile.TemporaryDirectory() as second_name:
            first = Path(first_name)
            second = Path(second_name)
            first_csv, first_metadata, _ = self._derive(first)
            second_csv, second_metadata, _ = self._derive(second)
            n1000_csv, _, _ = self._derive(
                second,
                source=N1000_PATH,
                reference=None,
                stem="derived_n1000",
            )
            self.assertEqual(first_csv.read_bytes(), second_csv.read_bytes())
            self.assertEqual(first_metadata.read_bytes(), second_metadata.read_bytes())
            n100_lines = first_csv.read_text(encoding="utf-8").splitlines()
            n1000_lines = n1000_csv.read_text(encoding="utf-8").splitlines()
            self.assertEqual(n100_lines[0], n1000_lines[0])
            self.assertEqual(n100_lines[1:], n1000_lines[1:101])

    def test_energy_scaling_preserves_direction_state_and_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output_csv, _, metadata = self._derive(
                Path(directory_name),
                candidate_frequency_hz=BASELINE_FREQUENCY_HZ,
                target_kinetic_energy_ev=5.0,
            )
            original_rows = _read_rows(N100_PATH)
            derived_rows = _read_rows(output_csv)
            expected_scale = math.sqrt(5.0 / 2.0)
            unchanged = (
                "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
                "mass_amu", "charge_state",
            )
            for original, derived in zip(original_rows, derived_rows, strict=True):
                for column in unchanged:
                    self.assertEqual(derived[column], original[column])
                for column in ("vx_m_s", "vy_m_s", "vz_m_s"):
                    self.assertAlmostEqual(
                        float(derived[column]) / float(original[column]),
                        expected_scale,
                        places=12,
                    )
            self.assertEqual(metadata["schema_version"], 2)
            self.assertEqual(
                metadata["kinetic_energy_scaling"]["target_kinetic_energy_eV"],
                5.0,
            )
            self.assertTrue(
                metadata["particle_count_policy"][
                    "derived_n100_prefix_projection_verified"
                ]
            )

    def test_rejects_invalid_frequencies(self) -> None:
        for label, baseline, candidate in (
            ("zero baseline", 0.0, CANDIDATE_FREQUENCY_HZ),
            ("negative candidate", BASELINE_FREQUENCY_HZ, -1.0),
            ("infinite baseline", math.inf, CANDIDATE_FREQUENCY_HZ),
            ("NaN candidate", BASELINE_FREQUENCY_HZ, math.nan),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory_name:
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    self._derive(
                        Path(directory_name),
                        baseline_frequency_hz=baseline,
                        candidate_frequency_hz=candidate,
                    )

    def test_rejects_n100_without_or_with_wrong_prefix_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            with self.assertRaisesRegex(ValueError, "requires n1000_reference_path"):
                self._derive(directory, reference=None)
            rows = _read_rows(N1000_PATH)
            rows[0]["x_mm"] = "0.123"
            wrong_reference = directory / "wrong_n1000.csv"
            _write_rows(wrong_reference, rows)
            with self.assertRaisesRegex(ValueError, "not the deterministic prefix"):
                self._derive(directory, reference=wrong_reference)

    def test_rejects_nonfinite_input_and_accepts_nonstandard_positive_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            rows = _read_rows(N100_PATH)
            rows[0]["vx_m_s"] = "nan"
            nonfinite = directory / "nonfinite.csv"
            _write_rows(nonfinite, rows)
            with self.assertRaisesRegex(ValueError, "non-finite"):
                self._derive(directory, source=nonfinite, stem="out_nonfinite")

            short = directory / "short.csv"
            _write_rows(short, _read_rows(N100_PATH)[:-1])
            output_csv, _, metadata = self._derive(
                directory, source=short, reference=None, stem="out_short"
            )
            self.assertEqual(len(_read_rows(output_csv)), 99)
            self.assertFalse(metadata["particle_count_policy"]["standard_count_verified"])

    def test_rejects_missing_column_duplicate_id_and_negative_birth_time(self) -> None:
        mutations = {
            "missing": lambda rows: rows[0].pop("x_mm"),
            "duplicate": lambda rows: rows[1].update(particle_id="1"),
            "negative": lambda rows: rows[0].update(birth_time_s="-1e-9"),
        }
        expected = {
            "missing": "incomplete",
            "duplicate": "contiguous",
            "negative": "negative birth time",
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory_name:
                directory = Path(directory_name)
                rows = _read_rows(N100_PATH)
                mutate(rows)
                source = directory / f"{name}.csv"
                _write_rows(source, rows)
                with self.assertRaisesRegex(ValueError, expected[name]):
                    self._derive(directory, source=source, stem=f"out_{name}")

    def test_refuses_existing_or_input_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            existing_csv = directory / "existing.csv"
            existing_csv.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                derive_phase_matched_source(
                    N100_PATH,
                    existing_csv,
                    directory / "metadata.json",
                    baseline_frequency_hz=BASELINE_FREQUENCY_HZ,
                    candidate_frequency_hz=CANDIDATE_FREQUENCY_HZ,
                    n1000_reference_path=N1000_PATH,
                )
            self.assertEqual(existing_csv.read_text(encoding="utf-8"), "keep")
            with self.assertRaisesRegex(ValueError, "must differ"):
                derive_phase_matched_source(
                    N100_PATH,
                    N100_PATH,
                    directory / "metadata2.json",
                    baseline_frequency_hz=BASELINE_FREQUENCY_HZ,
                    candidate_frequency_hz=CANDIDATE_FREQUENCY_HZ,
                    n1000_reference_path=N1000_PATH,
                )

    def test_metadata_validator_rejects_missing_per_particle_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            _, _, metadata = self._derive(Path(directory_name))
            metadata["rf_phase_invariance"]["all_particles_verified"] = False
            with self.assertRaisesRegex(ValueError, "phase verification is invalid"):
                validate_phase_matched_source_metadata(metadata)


if __name__ == "__main__":
    unittest.main()
