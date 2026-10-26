"""Extend the established single-carrier Program with real HP fields and HS1."""
from __future__ import annotations

from pathlib import Path

from integrations.runtime.build_single_flight_program import build_local_frontend_program
from integrations.runtime.single_flight_source import lua_value as _lua_value
from integrations.workflows.local_frontend.runtime import _write_once, response_field_paths


def build_program(context: dict, phase: dict, births: list, ids: list, velocities: list, directory: Path) -> str:
    """Keep source/clock/loss/IOB behavior in the shared assembler unchanged."""
    numerical = context["numerics"]
    mode=phase.get("pulse_mode",1)
    if (mode==2) != (phase["pulse_time_us"] is None):
        raise ValueError("held-OFF phase has no applied pulse; timed phase requires its pulse clock")
    # Mode 2 never applies a pulse. Its hook's finite bookkeeping anchor is
    # the actual reference release, not a fictitious future extraction time.
    core = build_local_frontend_program(context["guide"], context["frontend"], birth_times_us=births,
        particle_ids=ids, initial_velocities_mm_per_us=velocities, pulse_time_us=context["cooled_drive"]["release_start_us"] if phase["pulse_time_us"] is None else phase["pulse_time_us"],
        pulse_mode=mode,
        pulse_width_us=context["flight_horizon_us"], maximum_flight_us=numerical["maximum_flight_us"],
        maximum_step_us=numerical["maximum_step_us"], shared_times_us=phase["shared_times_us"],
        trajectory_cadence_us=numerical["trajectory_sample_interval_us"],
        standalone_dynamic_field_bank=context["fields"]["bank"], rf_steps_per_period=numerical["rf_steps_per_period"],
        standalone_dynamic_field_paths=response_field_paths(context["fields"]["records"]),
        trajectory_quality=numerical["trajectory_quality"], **context["sources"])
    _write_once(directory/"cooled_collision_hs1.lua", context["hs1_source"])
    conditioner=context["conditioner"]
    config=dict(drive=context["cooled_drive"], gas=conditioner["gas"], pose=conditioner["native_to_mr"],
        pressure_scale=context["experiment"]["pressure_scale"], numerics=numerical,
        calibration=context["voltage_calibration"],
        extra_fields={kind:Path(record["path"]).as_posix() for kind,record in context["fields"]["records"].items()
                      if kind not in ("carrier_off","rf_differential_unit","pulse_delta")},
        hs1_path=(directory/"cooled_collision_hs1.lua").as_posix())
    return core+"\nlocal cooled_frontend_component=(function()\n"+context["cooled_module_source"]+"\nend)()\ncooled_frontend_component.install("+_lua_value(config)+""", {
 clock=single_flight_instrument_time_us,
 voltage_waveforms=single_flight_voltage_waveforms,
 particle_id=single_flight_canonical_particle_id,
 state_for=function() return states[ion_number] end,
 validate_response=function(response,label)
   single_flight_assert_matching_response(assert(simion.wb.instances[1]),response,label)
 end
})
"""
