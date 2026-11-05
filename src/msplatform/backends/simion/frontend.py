"""Current frontend scope and native mapping projection, with no runtime receipt I/O."""
from msplatform.backends.simion.rf_electrode_mapping import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID

def native_frontend_instances(plan: dict) -> tuple[tuple[str, ...], str]:
    """Select all native multipoles and the one oaTOF body in scope."""
    multipoles, analyzers = [], []
    for instance_id in plan['scope']['instance_ids']:
        project = plan['components'][instance_id]['project_id']
        if project == 'single_reflection_oa_tof_mass_analyzer':
            analyzers.append(instance_id)
        elif project == 'rf_multipole_ion_optics':
            multipoles.append(instance_id)
        else:
            raise ValueError(f'{instance_id}: native single-reflection renderer/field/drive is unsupported for {project}')
    if len(analyzers) != 1:
        raise ValueError(f'native single-reflection requires one oaTOF and zero or more multipoles; '
                         f'oaTOF={analyzers}, multipoles={multipoles}')
    return tuple(multipoles), analyzers[0]


def _electrodes(mapping: dict, ring_count: int, three_zone: bool,
                multipole_bindings: dict[str, dict[int | str, int]]) -> None:
    required = {"grounded_shield_id", "accelerator_repeller_id", "accelerator_grid1_id",
                "accelerator_grid2_id", "accelerator_ring_ids"}
    if three_zone:
        required.add("accelerator_intermediate2_id")
    if set(mapping) != required or len(mapping["accelerator_ring_ids"]) != ring_count:
        raise ValueError("accelerator electrode mapping must match all rendered planes and rings")
    values = [value for key, value in mapping.items() if key != "accelerator_ring_ids"]
    values += list(mapping["accelerator_ring_ids"])
    values += [value for binding in multipole_bindings.values() for value in binding.values()]
    if (any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for value in values)
            or len(values) != len(set(values))):
        raise ValueError("assembly electrical groups require distinct valid solver electrode IDs")


def frontend_electrode_maps(geometry: dict) -> tuple[dict[str, dict[int | str, int]], dict]:
    """Read the actual selected instances' native-group and OA-role mappings.

    These mappings apply to the shared body in every numerical domain. They
    neither select a physical scope nor assign voltages or component poses.
    """
    plan = geometry['composition_plan']
    version = plan.get('schema_version')
    if type(version) is not int or version not in (3, 4, 5):
        raise ValueError('unsupported frontend composition plan version')
    multipoles, downstream = native_frontend_instances(plan)
    bindings = geometry.get('electrode_bindings')
    if not isinstance(bindings, dict) or set(bindings) != set(plan['scope']['instance_ids']):
        raise ValueError('electrode bindings must name exactly the selected assembly instances')
    if not isinstance(bindings[downstream], dict):
        raise ValueError('instance electrode binding must be a provider mapping')
    if version == 5:
        from msplatform.assembly.electrode_binding import validate_electrode_bindings
        from msplatform.backends.simion.tof_electrode_mapping import native_frontend_electrodes

        if {'accelerator_electrodes', 'multipole_electrode_ids'}.intersection(geometry):
            raise ValueError('canonical frontend geometry cannot contain legacy mapping aliases')
        domain = geometry['frontend_field_domain']
        scope = {instance: [row['electrode_group_id'] for row in plan['components'][instance]['component_electrodes']]
                 for instance in multipoles}
        scope[downstream] = domain['electrode_group_ids']
        record = geometry['backend_electrode_bindings']
        interfaces = {instance: plan['components'][instance] for instance in plan['scope']['instance_ids']}
        validate_electrode_bindings(interfaces, record, field_domain_id=domain['domain_id'],
            provider_inputs=record['provider_inputs'], electrode_group_scope=scope)
        rows = {(row['instance_id'], row['electrode_group_id']): row['native_electrode_id'] for row in record['bindings']}
        if record['backend'] != 'simion' or rows != {(instance, group): native
                for instance, mapping in bindings.items() for group, native in mapping.items()}:
            raise ValueError('frontend native maps differ from the backend binding record')
        multipole = {instance: dict(bindings[instance]) for instance in multipoles}
        if any(set(mapping) != set(scope[instance]) for instance, mapping in multipole.items()):
            raise ValueError('canonical RF map must cover exactly the provider electrode groups')
        accelerator = native_frontend_electrodes(bindings[downstream], frontend_domain=domain)
        _electrodes(accelerator, geometry['accelerator_projection']['ring_count'], True, multipole)
        return multipole, accelerator
    if {'frontend_field_domain', 'backend_electrode_bindings'}.intersection(geometry):
        raise ValueError('legacy frontend geometry cannot contain canonical binding records')
    multipole = {}
    for upstream in multipoles:
        raw = bindings.get(upstream)
        if not isinstance(raw, dict):
            raise ValueError(f'{upstream}: instance electrode binding must be a provider mapping')
        try:
            parsed = {int(key): value for key, value in raw.items()}
        except (TypeError, ValueError) as error:
            raise ValueError(f'{upstream}: native electrode IDs must be integers') from error
        if len(parsed) != len(raw):
            raise ValueError(f'{upstream}: duplicate native electrode identity')
        multipole[upstream] = parsed
    accelerator = bindings[downstream]
    projection = geometry['accelerator_projection']
    try:
        _electrodes(accelerator, projection['ring_count'], 'intermediate2_z_mm' in projection, multipole)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{multipoles}/{downstream}: {error}') from error
    return multipole, accelerator


def frontend_accelerator_operating_voltages(oatof: dict, geometry: dict) -> dict[int, float]:
    """Read actual provider voltage pointers for the authenticated frontend domain.

    This plan5 path rebuilds the provider's domain from the frozen resolved body.
    It does not infer scientific roles from SIMION slots or duplicate OA dividers.
    The caller owns authentication of the frozen provider input file records.
    """
    from msplatform.components.single_reflection_oa_tof.accelerator_geometry import ResolvedAcceleratorGeometry
    from msplatform.components.single_reflection_oa_tof.electrode_topology import (
        build_electrode_topology, resolve_frontend_field_domain,
    )
    from msplatform.backends.simion.electrode_contract import _physical_voltage_value

    plan = geometry['composition_plan']
    if plan.get('schema_version') != 5:
        raise ValueError('scientific frontend voltage projection requires composition plan5')
    _, downstream = native_frontend_instances(plan)
    interface = plan['components'][downstream]
    projection = ResolvedAcceleratorGeometry(interface['variant_id'], geometry['native_frame_id'], geometry['accelerator_projection'])
    options = dict(projection=projection, geometry_profile_id=interface['geometry_profile_id'])
    domain = resolve_frontend_field_domain(oatof, **options)
    if geometry['frontend_field_domain'] != domain:
        raise ValueError('frontend field domain differs from the actual frozen provider')
    frontend_electrode_maps(geometry)
    topology = build_electrode_topology(oatof, **options)
    mapping = geometry['electrode_bindings'][downstream]
    values = {mapping[row['electrode_group_id']]: _physical_voltage_value(topology, row['voltage_source']['pointer'])
              for row in topology['groups'] if row['electrode_group_id'] in domain['electrode_group_ids']}
    if values[mapping['common_ground']] != 0.:
        raise ValueError('OA field design requires the provider shield to be grounded')
    return values
