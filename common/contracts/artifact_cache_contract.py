"""Registered artifact cache namespaces shared by inventory and capacity owners.

This data-only contract does not load payloads, discover artifacts or import
verifier/maintenance entry points. Cache producers retain their own schemas.
"""

INTEGRATION_CACHE_ROLES = {
    "simion_single_flight_frontend": {"simion_single_flight_frontend_pa_cache"},
    "simion_single_flight_upstream_bridge": {
        "simion_single_flight_upstream_bridge_pa_cache"
    },
    "simion_single_flight_connector_collision": {
        "simion_single_flight_connector_collision_pa_cache"
    },
    "simion_single_flight_accelerator_main": {
        "simion_single_flight_accelerator_main_pa_cache"
    },
    "simion_single_flight_accelerator_entrance_local": {
        "simion_single_flight_accelerator_entrance_local_pa_cache"
    },
    "simion_single_flight_accelerator_entrance_zone_collision": {
        "simion_single_flight_accelerator_entrance_zone_collision_pa_cache"
    },
    "simion_accelerator_overlay": {
        "simion_accelerator_overlay_pa_cache",
        "simion_accelerator_entrance_overlay_pa_cache",
        "simion_accelerator_intermediate_overlay_pa_cache",
    },
    "simion_oatof_downstream_pa": {
        "simion_oatof_flight_tube_pa_cache",
        "simion_oatof_reflectron_pa_cache",
    },
    "verified_pulse": {"rf_oatof_verified_pulse_timing_receipt"},
}
INTEGRATION_CACHE_ROOT_BY_ROLE = {
    role: root
    for root, roles in INTEGRATION_CACHE_ROLES.items()
    for role in roles
}
