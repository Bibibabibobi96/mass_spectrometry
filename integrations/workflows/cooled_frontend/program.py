"""Extend the established single-carrier Program with real HP fields and HS1."""
from __future__ import annotations

from pathlib import Path
from itertools import product

from msplatform.backends.simion.tracking_program import build_local_frontend_program
from msplatform.backends.simion.source import lua_value as _lua_value
from msplatform.workflows.local_frontend.runtime import _write_once, response_field_paths
from msplatform.contracts.gas import BoxDomain
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import build_cooled_gas_field_spec
from msplatform.gas.field import prepare_gas_field
from msplatform.backends.simion.gas_runtime import compile_gas_runtime
from msplatform.backends.simion.resources import native_resource_path


def carrier_query_domain(frontend: dict, pose: RigidTransform) -> BoxDomain:
    """Exact carrier-box preimage for the existing signed-permutation pose only."""
    if any(sorted(abs(v) for v in row) != [0, 0, 1] for row in pose.rotation):
        raise ValueError("cooled carrier query box requires the existing signed-permutation pose")
    bounds = frontend["instance_bounds_mm"]
    inverse = pose.inverse()
    points = [inverse.transform_position(FramedPosition(pose.to_frame_id, point)).coordinates_mm
              for point in product(*[(bounds[a+"_min"], bounds[a+"_max"]) for a in "xyz"])]
    return BoxDomain(tuple(min(p[i] for p in points) for i in range(3)),
                     tuple(max(p[i] for p in points) for i in range(3)), (True,)*3, (True,)*3)


def build_program(context: dict, phase: dict, births: list, ids: list, velocities: list, directory: Path) -> str:
    """Keep source/clock/loss/IOB behavior in the shared assembler unchanged."""
    numerical = context["numerics"]
    mode=phase.get("pulse_mode",1)
    if (mode==2) != (phase["pulse_time_us"] is None):
        raise ValueError("held-OFF phase has no applied pulse; timed phase requires its pulse clock")
    conditioner=context["conditioner"]
    pose=RigidTransform.from_contract(conditioner["native_to_mr"])
    gas_spec=build_cooled_gas_field_spec(conditioner,
        pressure_scale=context["experiment"]["pressure_scale"], domain=carrier_query_domain(context["frontend"],pose))
    gas_source=compile_gas_runtime(prepare_gas_field(gas_spec),placement=pose)
    binding_source=native_resource_path("collision_hs1_gas.lua").read_text(encoding="utf-8")
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
    _write_once(directory/"cooled_gas_field.lua",gas_source)
    _write_once(directory/"collision_hs1_gas.lua",binding_source)
    config=dict(drive=context["cooled_drive"], gas=dict(parameters={key:conditioner["gas"]["parameters"][key]
        for key in ("mass_amu","temperature_k","cross_section_m2","mean_free_path_mm")}), numerics=numerical,
        gas_path=(directory/"cooled_gas_field.lua").as_posix(),
        gas_binding_path=(directory/"collision_hs1_gas.lua").as_posix(),query_frame_id=pose.to_frame_id,
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
