"""Evaluate the authenticated IP provider voltage schedule without a Fly."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from msplatform.execution.inputs import freeze_file
from msplatform.io.manifest_records import file_record


def project_provider_voltages(source: dict, request: dict, inputs: Path, lua_executable: Path) -> dict:
    """Evaluate the sole provider Lua schedule with RF=0; no field or flight API."""
    from msplatform.components.ion_processor.assembly_geometry import derive_lift_seed
    if lua_executable.name.lower() not in {"lua", "lua.exe", "lua5.1", "lua5.1.exe"} or not lua_executable.is_file():
        raise ValueError("an explicit plain Lua interpreter is required; no SIMION solver fallback")
    baseline, point = copy.deepcopy(source["baseline"]), copy.deepcopy(source["native_operating_point"])
    point["lift_v"] = derive_lift_seed(source, request)
    baseline["electric"]["lift_v"] = point["lift_v"]
    dependency = json.loads((inputs / "accelerator_dependency.json").read_text(encoding="utf-8-sig"))
    if dependency["provider_voltage_schedule"] != "src/msplatform/backends/simion/resources/native_drive.lua":
        raise ValueError("provider voltage schedule must belong to the selected IP component")
    schedule = freeze_file(native_resource_path("native_drive.lua"),
                           inputs / "provider_native_drive.lua")
    if dependency["provider_voltage_waveforms"] != "src/msplatform/backends/simion/resources/voltage_waveforms.lua":
        raise ValueError("provider voltage waveforms must be the declared common module")
    waveforms = freeze_file(native_resource_path("voltage_waveforms.lua"), inputs / "provider_voltage_waveforms.lua")
    when = max(baseline["schedule"]["lift_end_us"], source["native_timing"]["pulse_start_us"])
    config = dict(baseline=baseline, native_operating_point=point, native_timing=source["native_timing"])
    program = inputs / "provider_voltage_evaluation.lua"
    program.write_text("local waveforms=assert(loadfile(" + lua_value(waveforms["path"]) + "))()\n"
                       "local d=assert(loadfile(" + lua_value(schedule["path"]) + "))(waveforms)\n"
                       "local v=d.voltages(" + lua_value(config) + "," + lua_value(when) + ",0)\n"
                       "local out={} for i=1,15 do out[i]=string.format('%.17g',assert(v[i])) end\n"
                       "assert(#v==15);print(table.concat(out,','))\n", encoding="utf-8", newline="\n")
    from msplatform.execution.lua_process import run_lua_program

    output = run_lua_program(lua_executable, program, inputs)
    values = [float(token) for token in output.strip().split(",")]
    if len(values) != 15 or not all(math.isfinite(v) for v in values):
        raise ValueError("provider native schedule did not return 15 finite electrode voltages")
    result = dict(values_v15=values, source_native_drive=schedule, source_voltage_waveforms=waveforms, evaluation_time_us=when,
                  basis="post_extraction_pulse_held_rf_zero", evaluated_native_operating_point=point,
                  evaluated_baseline_lift_v=baseline["electric"]["lift_v"], plain_lua=file_record(lua_executable))
    (inputs / "provider_voltage_projection.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return result
