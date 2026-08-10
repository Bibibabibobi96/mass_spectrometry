"""Generate governed parallel steady-candidate pilot campaigns."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from common.contracts.file_identity import file_sha256


def generate(
    repo_root: Path,
    template_path: Path,
    output_directory: Path,
    mode: str = "candidate",
) -> list[Path]:
    template = json.loads(template_path.read_text(encoding="utf-8-sig"))
    source_root = repo_root / "common/multipole/sources"
    outputs: list[Path] = []
    batch_count = 4 if mode == "candidate" else 5
    batch_size = 500 if mode == "candidate" else 200
    receipt_path = (
        repo_root / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
        "config/diagnostics/octupole_steady_source_selection_receipt.json"
    )
    for index in range(1, batch_count + 1):
        stem = "steady_candidate" if mode == "candidate" else "steady_pulse_eligible"
        batch = source_root / f"rf_multipole_{stem}_v1_batch{index:02d}_{batch_size}.csv"
        campaign = copy.deepcopy(template)
        suffix = f"{index:02d}"
        family = "steady_candidate" if mode == "candidate" else "steady_final"
        campaign["campaign_id"] = f"octupole_{family}_batch_{suffix}_n{batch_size}"
        campaign["claim_limit"] = (
            f"Parallel pulse-only candidate batch {index}/4; detector-blind source construction only; no resolution, Candidate or Formal claim."
            if mode == "candidate"
            else f"Full-flight batch {index}/5 of the detector-blind pulse-eligible N=1000 steady-source diagnostic; claim only after governed five-batch aggregation."
        )
        experiment = campaign["experiments"][0]
        experiment["experiment_id"] = f"octupole_{family}_batch_{suffix}_n{batch_size}"
        minute = 39 + index if mode == "candidate" else index - 1
        experiment["run_id"] = (
            f"20260810_18{minute:02d}00__sim__cross__oct-steady-b{suffix}__n{batch_size}"
            if mode == "candidate"
            else f"20260810_19{minute:02d}00__sim__cross__oct-steady-final-b{suffix}__n{batch_size}"
        )
        experiment["single_flight_particle_source"] = {
            "path": batch.relative_to(repo_root).as_posix(),
            "sha256": file_sha256(batch),
            "particle_count": batch_size,
            "sampling_mode": "steady_candidate_pool" if mode == "candidate" else "pulse_eligible_conditional",
        }
        if mode == "final":
            experiment["single_flight_particle_source"]["selection_receipt"] = {
                "path": receipt_path.relative_to(repo_root).as_posix(),
                "sha256": file_sha256(receipt_path),
            }
        output = output_directory / f"octupole_{family}_batch_{suffix}_n{batch_size}_campaign.json"
        output.write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8", newline="\n")
        outputs.append(output)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--mode", choices=("candidate", "final"), default="candidate")
    args = parser.parse_args()
    outputs = generate(args.repo_root.resolve(), args.template.resolve(), args.output_directory.resolve(), args.mode)
    print("STEADY_BATCH_CAMPAIGNS=PASS " + " ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
