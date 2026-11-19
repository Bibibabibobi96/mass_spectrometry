"""Canonical CSV fields for recorded IP force and trajectory audits."""

AXES = "xyz"
STEP_COLUMNS = ("particle_id", "step_index", "start_t_us", "end_t_us",
               *(f"{end}_{axis}_mm" for end in ("start", "end") for axis in AXES),
               *(f"{state}_v{axis}_mm_us" for state in ("start_post", "end_pre", "end_post") for axis in AXES),
               "pressure_pa")
IMPULSE_COLUMNS = ("particle_id", "step_index", "electrode_id", "start_t_us", "end_t_us",
                  *(f"integral_e{a}_v_us_per_mm" for a in AXES),
                  *(f"fine_minus_coarse_e{a}_v_us_per_mm" for a in AXES),
                  "max_reconstruction_error_v_per_mm",
                  *(f"unit_integral_e{a}_us_per_mm" for a in AXES))
