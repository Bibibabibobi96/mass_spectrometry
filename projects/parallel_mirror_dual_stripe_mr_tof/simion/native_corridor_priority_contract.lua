-- Explicit Workbench priority contract for the single full-flight corridor.
-- SIMION resolves overlaps by Workbench instance priority; the builder checks
-- this table against the loaded IOB instead of treating seed slot order as an
-- undocumented convention.
return {
  schema_version = 1,
  role = 'mrtof_native_corridor_iob_priority_contract',
  priority_rule = 'slot_order_is_only_a_build_contract; persisted_priority_is_accepted_only_after_wb_find_at_overlap_probes',
  api_note = 'SIMION 2020 has no documented instance.priority setter in the supported Lua API; builder probes candidate fields and otherwise verifies actual winners with wb.find_at',
  instances = {
    { role = 'global_fallback', priority_number = 1 },
    { role = 'native_corridor', priority_number = 2 },
    { role = 'accelerator', priority_number = 3 },
    { role = 'detector', priority_number = 4 },
  },
  -- Native IDs 1..8 are the sole GUI-adjustable corridor channels.  Each
  -- entry lists the physical analyser electrode IDs represented by that
  -- native response.  The IOB builder and flight program both consume this
  -- table, so their one-time seed voltages and later GUI Fast Adjust calls
  -- cannot drift apart.
  corridor_voltage_groups = {
    {2, 7},
    {3, 8},
    {4, 9},
    {5, 10},
    {11, 12},
    {13, 14},
    {16},
    {17},
  },
}
