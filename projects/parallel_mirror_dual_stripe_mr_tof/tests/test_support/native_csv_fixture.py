"""Tiny complete-program native boundary inputs; no production field qualification."""
from pathlib import Path
import argparse
import json
import shutil


def prepare(repo: Path, root: Path) -> None:
    """Use the existing four-slot/native-response fixture, not another field model."""
    project = repo / "projects/parallel_mirror_dual_stripe_mr_tof"
    copies = {
        "program_current.lua": project / "simion/mrtof_candidate.lua",
        "program_current.voltage_waveforms.lua": repo / "common/simion/voltage_waveforms.lua",
        "program_current.mirror_cycle_counter.lua": project / "simion/mirror_cycle_counter.lua",
        "voltage_map_current.lua": project / "simion/candidate_voltage_map.lua",
        "scientific_event_csv.lua": repo / "common/simion/scientific_event_csv.lua",
    }
    from common.contracts.write_run_manifest import file_record
    records = {}
    for name, source in copies.items():
        target = root / name
        if target.exists():
            raise FileExistsError(target)
        shutil.copyfile(source, target)
        records[name] = dict(source=file_record(source), frozen=file_record(target))
    # Explicit synthetic observation geometry. All drives zero, no real MR field.
    # This preserves the complete production callbacks and their existing timeout policy.
    point = r"""return {
 mirror_voltages_v={0,0,0,0,0},stripe_biases_v={0,0},prism_voltages_v={0,0},
 accelerator_voltages_v={0,0,0},accelerator_ring_voltages_v={0,0,0,0}, -- 4 endpoint slots + 4 rings = this fixture family's 8 IDs
 nonaccelerator_scale=1,detector_box_mm={100,100,100,101,101,101},detector_normal_project='+z',
 first_prism_l0={target_plane_z_mm=-5},
 mirror_regions_project={negative={z_min_mm=-20,z_max_mm=-10},positive={z_min_mm=10,z_max_mm=20}},
 prism_regions_project={p1={y_min_mm=-6,y_max_mm=6,z_min_mm=-4,z_max_mm=1},p2={y_min_mm=-6,y_max_mm=6,z_min_mm=-8,z_max_mm=-4}},
 phase_origin_mirror_side=1,return_mirror_side=-1,target_drift_period_ratio=25.5,target_half_oscillation_count=51,
 trajectory_quality=8,maximum_step_us=0.002,full_path_timeout_us=0.02,
 trajectory_recording_enabled=true,trajectory_recording_mode='every_step',runtime_fast_adjust_enable=true,
 scientific_event_output={csv_writer_path=WRITER,environment_required=true,
 events_environment_variable='MRTOF_FIXTURE_EVENTS',trajectory_environment_variable='MRTOF_FIXTURE_TRAJECTORY'}
}
"""
    point = point.replace("WRITER", json.dumps((root / "scientific_event_csv.lua").as_posix()))
    (root / "operating_current.lua").write_text(point, encoding="utf-8", newline="\n")
    # Reuse the existing priority contract: no new role registry/instance interpretation.
    if not (root / "priority.lua").is_file():
        raise FileNotFoundError("Existing native corridor fixture must prepare priority.lua first")
    (root / "source_current.fly2").write_text(
        "particles { standard_beam { n = 1, mass = 100, charge = 1, ke = 1, position = vector(5,5,5), direction = vector(1,0,0) } }\n",
        encoding="utf-8")
    (root / "current_source_records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def verify(root: Path) -> None:
    from common.simion.scientific_event_io import iter_csv_rows
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import read_scientific_events
    import hashlib
    records = json.loads((root / "current_source_records.json").read_text(encoding="utf-8"))
    # These are tiny test-only code companions, never scientific PA payloads.
    for record in records.values():
        path = Path(record["frozen"]["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == record["frozen"]["sha256"].upper()
    assert (root / "current.lua").read_bytes() == (root / "program_current.lua").read_bytes()
    outputs = []
    for name in ("first", "cold"):
        log = root / (name + ".stdout.log")
        declaration = dict(events_path=str(root / (name + ".events.csv")), trajectory_path=str(root / (name + ".trajectory.csv")))
        events, finished, _ = read_scientific_events(log, scientific_event_output=declaration)
        terminal = [row for row in events if row["kind"] == "terminal"]
        assert len(terminal) == 1 and int(terminal[0]["ion"]) == 1
        samples = list(iter_csv_rows(Path(declaration["trajectory_path"]), ("ion", "phase", "t_us")))
        assert samples[0]["phase"] == "birth" and samples[-1]["phase"] == "terminal"
        assert any(row["phase"] == "step" for row in samples)
        assert all(int(row["ion"]) == 1 for row in samples)
        assert all(float(b["t_us"]) >= float(a["t_us"]) for a, b in zip(samples, samples[1:]))
        text = log.read_text(encoding="utf-8")
        assert "MRTOF_EVENT " not in text and "MRTOF_TRAJECTORY " not in text
        assert finished and "IOB_FLIGHT: PASS" in text
        outputs.append((events, samples))
    assert outputs[0] == outputs[1], "Cold IOB replay changed same-fixture scientific rows"
    print("MRTOF_TINY_COMPLETE_PROGRAM_CSV=PASS N=1 scope=callbacks_saved_iob_replay_only")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "verify"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.repo, args.root)
    else:
        verify(args.root)


if __name__ == "__main__":
    main()
