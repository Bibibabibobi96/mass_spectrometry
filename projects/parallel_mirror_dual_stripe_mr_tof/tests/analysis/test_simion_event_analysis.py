"""Cohort-integrity regression tests; no commercial solver or historical run writes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import _particle_source_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    SOURCE_COUNT_KEYS, analyze_log, load_particle_source, parse_events, summarize_events,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def terminal(ion: int, **changes: object) -> dict[str, object]:
    return {"kind": "terminal", "ion": ion, "splat": -1, "turns": 2,
            "t_us": 100 + ion * .01, **changes}


def detector(ion: int) -> dict[str, object]:
    return {"kind": "detector", "ion": ion, "t_us": 100 + ion * .01,
            "x_mm": 0, "y_mm": 0, "z_mm": 96}


def fixture_manifest(root: Path) -> Path:
    contract = {"particle_source": {"center_particle_count": 1, "candidate_bunch_particle_count": 8},
                "nominal": {"target_oscillation_count": 25}}
    contract_path = root / "simion_prototype_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    manifest = {"schema_version": 2, "derived_contract": {
        "filename": contract_path.name, "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest()}}
    for key, count_key in SOURCE_COUNT_KEYS.items():
        source = root / f"{key}.fly2"
        source.write_text(f"particles {{ standard_beam {{ n = {contract['particle_source'][count_key]} }} }}\n",
                          encoding="utf-8")
        manifest[key] = _particle_source_record(source, contract["particle_source"], count_key)
    path = root / "prototype_input_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class SimionEventAnalysisTest(unittest.TestCase):
    def assert_invalid(self, events, expected, splats, error):
        result = summarize_events(events, 25, splats, expected_particle_ids=expected)
        self.assertFalse(result["event_integrity_passed"])
        self.assertIn(error, result["integrity_errors"])
        for key in ("detection_rate", "target_k_fraction", "detector_tof_fwhm_us",
                    "mass_resolution_t_over_2fwhm", "target_k_handoff_tof_fwhm_us"):
            self.assertIsNone(result[key], key)
        return result

    def test_complete_cohort_keeps_actual_losses_and_detector_metrics(self):
        events = [terminal(i) for i in range(1, 10)] + [detector(i) for i in range(1, 9)]
        result = summarize_events(events, 25, 9, expected_particle_ids=tuple(range(1, 10)))
        self.assertTrue(result["all_losses_retained"])
        self.assertEqual(result["electrode_collision_count"], 9)
        self.assertEqual(result["detection_rate"], 8 / 9)
        self.assertGreater(result["mass_resolution_t_over_2fwhm"], 0)

    def test_no_completion_or_source_never_infers_population_from_events(self):
        result = self.assert_invalid([terminal(1)], (1,), None, "missing_or_multiple_fly_completion")
        self.assertEqual(result["particle_terminal_count"], 1)
        result = self.assert_invalid([], None, None, "missing_frozen_particle_source")
        self.assertIsNone(result["expected_particle_count"])
        self.assertFalse(result["all_losses_retained"])

    def test_missing_identity_blocks_metrics_even_with_usable_peak(self):
        events = [terminal(i) for i in range(1, 9)] + [detector(i) for i in range(1, 9)]
        result = self.assert_invalid(events, tuple(range(1, 11)), 10, "missing_particle_terminal_events")
        self.assertEqual(result["missing_terminal_particle_ids"], [9, 10])
        self.assertEqual(result["detector_hit_count"], 8)
        self.assertEqual(len(result["detector_tof_us"]), 8)

    def test_duplicate_and_unknown_ids_cannot_replace_missing_particle(self):
        result = self.assert_invalid([terminal(1), terminal(1)], (1, 2), 2, "duplicate_particle_events")
        self.assertEqual(result["duplicate_event_particle_ids"]["terminal"], [1])
        self.assertEqual(result["unique_particle_terminal_count"], 1)
        result = self.assert_invalid([terminal(1), terminal(9)], (1, 2), 2, "unknown_particle_ids")
        self.assertEqual(result["unknown_particle_ids"], [9])
        for kind in ("detector", "target_k", "splat"):
            event = ({**detector(1), "kind": kind, **({"k": 25} if kind == "target_k" else {})}
                     if kind != "splat" else {"kind": kind, "ion": 1, "code": -1, "turns": 2, "t_us": 100})
            with self.subTest(kind=kind):
                self.assert_invalid([terminal(1), event, event], (1,), 1, "duplicate_particle_events")

    def test_splat_fallback_is_counted_once_and_conflicts_are_rejected(self):
        splat = {"kind": "splat", "ion": 1, "code": -1, "t_us": 100, "turns": 2}
        result = summarize_events([splat], 25, 1, expected_particle_ids=(1,))
        self.assertTrue(result["event_integrity_passed"])
        self.assertEqual(result["splat_code_missing_count"], 0)
        result = summarize_events([splat, terminal(1)], 25, 1, expected_particle_ids=(1,))
        self.assertEqual(result["particle_terminal_count"], 1)
        self.assertEqual(result["splat_fallback_event_count"], 0)
        self.assert_invalid([splat, terminal(1, splat=1)], (1,), 1, "splat_terminal_reason_conflict")

    def test_solver_count_must_equal_frozen_source_count(self):
        self.assert_invalid([terminal(1)], (1,), 2, "fly_splat_count_differs_from_source")
        result = summarize_events([terminal(1)], 25, 1, expected_particle_ids=(1,), completion_count=2)
        self.assertFalse(result["event_integrity_passed"])

    def test_strict_event_anchor_never_salvages_prefixed_or_malformed_events(self):
        line = ("MRTOF_EVENT terminal ion=1 splat=-1 t_us=100 turns=2 x_mm=0 y_mm=0 z_mm=0 "
                "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=2")
        self.assertEqual(parse_events("status," + line + "\n"), [])
        for malformed in (line + " broken", line + " ion=2", line.replace("turns=2", "turns="),
                          line.replace("t_us=100", "t_us=nan"), line.replace("ion=1", "ion=1.5")):
            with self.subTest(line=malformed), self.assertRaises(ValueError):
                parse_events(malformed)
        self.assertEqual(len(parse_events(line + "\n")), 1)
        with self.assertRaisesRegex(ValueError, "incomplete_log_event"):
            parse_events(line.rsplit(" ", 1)[0] + "\n")

    def test_all_four_sources_have_contract_derived_ids_counts_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture_manifest(Path(directory))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for key in SOURCE_COUNT_KEYS:
                source = load_particle_source(path, key)
                record = manifest[key]
                self.assertEqual(list(source["expected_particle_ids"]), record["expected_particle_ids"])
                self.assertEqual(len(source["expected_particle_ids"]), record["particle_count"])
                self.assertEqual(source["target_k"], 25)
                self.assertEqual(source["provenance"]["fly2_sha256"], record["sha256"])

    def test_modified_source_contract_or_id_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = fixture_manifest(root)
            original = json.loads(path.read_text(encoding="utf-8"))
            for key, value in (("particle_count", 2), ("expected_particle_ids", [2]),
                               ("expected_particle_ids_sha256", "0" * 64),
                               ("particle_count_contract_key", "candidate_bunch_particle_count")):
                changed = copy.deepcopy(original)
                changed["center_fly2"][key] = value
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_particle_source(path, "center_fly2")
            path.write_text(json.dumps(original), encoding="utf-8")
            for filename in ("center_fly2.fly2", "simion_prototype_contract.json"):
                target = root / filename
                payload = target.read_bytes()
                target.write_bytes(payload + b" ")
                with self.subTest(filename=filename), self.assertRaises(ValueError):
                    load_particle_source(path, "center_fly2")
                target.write_bytes(payload)

    def test_legacy_manifest_has_no_executable_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture_manifest(Path(directory))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_particle_source(path, "center_fly2")

    def test_cli_exit_code_tracks_integrity_and_selected_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = fixture_manifest(root)
            log = root / "stdout.log"
            output = root / "summary.json"
            event = ("MRTOF_EVENT terminal ion=1 splat=-1 t_us=100 turns=2 x_mm=0 y_mm=0 z_mm=0 "
                     "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=2\n")
            for suffix, expected_code in (("status,Fly completed. 1 splats, 1 seconds\n", 0), ("", 1)):
                log.write_text(event + suffix, encoding="utf-8")
                result = subprocess.run([sys.executable, "-m",
                    "projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis",
                    str(log), str(output), "--input-manifest", str(manifest), "--source-key", "center_fly2"],
                    cwd=REPOSITORY_ROOT, capture_output=True, text=True,
                    timeout=30, check=False)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertIn("=PASS" if expected_code == 0 else "=FAIL", result.stdout)
                summary = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(summary["event_integrity_passed"], expected_code == 0)
            log.write_text(event + "status,Fly completed. 1 splats\n" * 2, encoding="utf-8")
            summary = analyze_log(log, output, input_manifest=manifest, source_key="center_fly2")
            self.assertFalse(summary["event_integrity_passed"])
            self.assertEqual(summary["fly_completion_count"], 2)


if __name__ == "__main__":
    unittest.main()
