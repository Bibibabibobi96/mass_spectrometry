"""Evaluate the shared-clock oaTOF extraction-pulse functional test."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import fmean


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def summarize(rows: list[dict[str, str]]) -> dict[str, float | int | None]:
    hits = [row for row in rows if row["Hit"].lower() == "true"]
    tofs = [float(row["TofUs"]) for row in hits]
    return {
        "emitted": len(rows),
        "hits": len(hits),
        "transmission": len(hits) / len(rows) if rows else 0.0,
        "mean_local_tof_us": fmean(tofs) if tofs else None,
        "tof_standard_deviation_us": (
            math.sqrt(sum((value - fmean(tofs)) ** 2 for value in tofs) / (len(tofs) - 1))
            if len(tofs) > 1 else None
        ),
    }


def analyze(timed_path: Path, control_path: Path, mode_path: Path, pulse_log: Path) -> dict:
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    timed = summarize(read_csv(timed_path))
    control = summarize(read_csv(control_path))
    acceptance = mode["acceptance"]
    pulse_events = sum(1 for line in pulse_log.read_text(encoding="utf-8", errors="replace").splitlines()
                       if "TRACE: handoff_pulse_on ion=" in line)
    checks = {
        "minimum_particles": timed["emitted"] >= int(acceptance["minimum_particles"]),
        "timed_pulse_transmission": timed["transmission"] >= float(
            acceptance["minimum_timed_pulse_detector_transmission"]
        ),
        "gain_over_held_off_control": timed["transmission"] - control["transmission"] >= float(
            acceptance["minimum_transmission_gain_over_held_off_control"]
        ),
        "minimum_pulse_event_fraction": pulse_events / timed["emitted"] >= float(
            acceptance["minimum_pulse_event_fraction"]
        ),
    }
    return {
        "schema_version": 1,
        "role": "oa_tof_rf_handoff_shared_clock_pulse_test",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "timed_pulse": timed,
        "held_off_control": control,
        "transmission_gain": timed["transmission"] - control["transmission"],
        "pulse_event_count": pulse_events,
        "checks": checks,
        "functional_link_scope": "time-ordered projected RF-COMSOL entry with continuous pre/post trajectories through one shared-clock finite oaTOF extraction pulse",
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timed", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--mode", type=Path, required=True)
    parser.add_argument("--pulse-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.timed, args.control, args.mode, args.pulse_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"RF_HANDOFF_PULSE={result['status']} TIMED={result['timed_pulse']['hits']}/{result['timed_pulse']['emitted']} CONTROL={result['held_off_control']['hits']}/{result['held_off_control']['emitted']}")
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
