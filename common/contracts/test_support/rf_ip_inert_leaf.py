"""Inert SIMION leaf used by source and installed RF-IP owner probes."""

import json
import sys
from pathlib import Path


def inert_native_leaf(actual_process, observed):
    """Retain the actual process owner while replacing only native execution."""

    def inert_native(actual_context, **options):
        if options["role"] != "SIMION":
            return actual_process(actual_context, **options)
        run = Path(options["working_directory"])
        args = options["arguments"]
        paths = {Path(r["path"]).resolve() for r in options["immutable_input_records"]}
        expected = {
            *(
                run / "inputs/hs1" / name
                for name in (
                    "original.lua",
                    "vendor.lua",
                    "bath.lua",
                    "outer.lua",
                    "identity.json",
                )
            ),
            *(
                run / "inputs/native_sources" / name
                for name in (
                    "rf_ip_gas_selection.lua",
                    "rf_ip_tracking_hs1.lua",
                    "collision_hs1_gas.lua",
                )
            ),
        }
        observed.append((options, paths, {path.resolve() for path in expected}))
        if "fly" not in args:
            mode = args[-2]
            iob = run / "simion/tracking/instrument.iob"
            code = "from pathlib import Path\n" + (
                "Path(" + repr(str(iob)) + ').write_bytes(b"INERT_IOB")\n'
                if mode == "build"
                else ""
            )
            if mode == "build":
                neutral = run / "simion/geometry/iob_seed/iob_seed_placeholder_01.pa0"
                code += (
                    "Path(" + repr(str(neutral)) + ').write_bytes(b"INERT_BOOTSTRAP")\n'
                )
            code += (
                "print("
                + repr(
                    "RF_IP_TRACKING_IOB=PASS"
                    if mode == "build"
                    else "RF_IP_TRACKING_IOB_REOPEN=PASS"
                )
                + ")"
            )
        else:
            rows = json.loads((run / "inputs/canonical_source_states.json").read_text())
            lines = [
                'RF_DYNAMICS_V1: {"grouped":0,"repulsion":"none","relativity":0,"segment_global":1}'
            ]
            for ion, row in enumerate(rows, 1):
                state = dict(
                    event="source_release",
                    reason="none",
                    particle_id=row["particle_id"],
                    ion=ion,
                    instrument_time_us=row["instrument_time_us"],
                    mass_amu=row["mass_amu"],
                    charge_state=row["charge_state"],
                    instance=1,
                )
                state.update({a + "_mm": row["position_" + a + "_mm"] for a in "xyz"})
                state.update(
                    {
                        "v" + a + "_mm_per_us": row["velocity_" + a + "_m_s"] / 1000
                        for a in "xyz"
                    }
                )
                lines.extend(
                    [
                        "RF_NATIVE_STATE_V1: " + json.dumps(state),
                        "RF_NATIVE_STATE_V1: "
                        + json.dumps(
                            dict(
                                state,
                                event="terminal",
                                reason="unknown",
                                instrument_time_us=2.0,
                            )
                        ),
                    ]
                )
            lines.append("status,Fly completed. 2 splats")
            code = "print(" + repr("\n".join(lines)) + ")"
        guarded = [str(path) for path in expected]
        protection = (
            "for p in " + repr(guarded) + ":\n"
            ' try:\n  f=open(p,"ab");f.close()\n'
            " except PermissionError: pass\n"
            ' else: raise AssertionError("frozen collision input is writable")\n'
        )
        return actual_process(
            actual_context,
            **dict(
                options,
                executable=Path(sys.executable),
                arguments=["-I", "-c", protection + code],
                role="GATE",
                stage="inert_rf_ip_tracking",
            ),
        )

    return inert_native
