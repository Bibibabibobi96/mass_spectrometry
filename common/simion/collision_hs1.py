"""Run-local lifecycle adaptation of the official SIMION 2020 HS1 module.

No collision equation, adjustable binding or random-number algorithm is changed.
"""
from __future__ import annotations

import re


def adapt_hs1_for_repeat_fly(original: str) -> str:
    """Add reset and read-only lexical parameter audit; preserve collision code.

    SIMION 2020 rejects simion.workbench_program during callback-time imports.
    The installed official source is never edited. This run-local adapter resets
    private state and exposes the module-bound adjustables without mutating them.
    Unknown source declarations are rejected before creating the adapted copy.
    """
    for declaration in ("local max_timestep", "local is_initialized", "local ke_averages", "local last_collision_times", "local trace_count"):
        if declaration not in original:
            raise ValueError(f"official HS1 reset contract missing: {declaration}")
    bound_names = ("_gas_mass_amu", "_temperature_k", "_pressure_pa", "_sigma_m2",
                   "_mean_free_path_mm", "_steps_per_MFP", "_random_seed",
                   "_mark_collisions", "_trace_level")
    for name in bound_names:
        if not re.search(rf"(?m)^adjustable\s+{re.escape(name)}\s*=", original):
            raise ValueError(f"official HS1 bound parameter declaration missing: {name}")
    if "function HS1.bound_parameters" in original or "function HS1.reset_run_state" in original:
        raise ValueError("official HS1 source already contains project adapter hooks")
    if original.count("return HS1")!=1:
        raise ValueError("unsupported official HS1 return structure")
    hook="""-- Project lifecycle adapter: no change to collision equations or sampling.
function HS1.reset_run_state()
    is_initialized = false
    max_timestep = nil
    ke_averages = {}
    last_collision_times = {}
    trace_count = 0
end

-- Read the actual adjustable bindings in the imported HS1 module's scope.
-- This allocates an audit table only; no parameter, PRNG or collision state changes.
function HS1.bound_parameters()
    return {
        gas_mass_amu = _gas_mass_amu,
        temperature_k = _temperature_k,
        pressure_pa = _pressure_pa,
        sigma_m2 = _sigma_m2,
        mean_free_path_mm = _mean_free_path_mm,
        steps_per_mfp = _steps_per_MFP,
        random_seed = _random_seed,
        mark_collisions = _mark_collisions,
        trace_level = _trace_level,
    }
end

"""
    return original.replace("return HS1",hook+"return HS1")
