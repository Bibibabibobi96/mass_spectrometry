function verified = verify_ei_source_parameter_bindings(model, contract)
%VERIFY_PARAMETER_BINDINGS Confirm GUI-visible parameters consume the contract.
    geometry = contract.physical.geometry_mm;
    gas = contract.physical.gas;
    ionization = contract.physical.ionization;
    checks = {
        'R_tube', ei_source_unit_text(geometry.tube_bore_radius, 'mm');
        'L_cell', ei_source_unit_text(geometry.cathode_anode_path_length, 'mm');
        'r_hole', ei_source_unit_text(geometry.electrode_aperture_radius, 'mm');
        'Nd', ei_source_unit_text(gas.neutral_number_density_per_m3, '1/m^3');
        'sigma_ion', ei_source_unit_text(ionization.cross_section_m2, 'm^2');
        'dE_ion', ei_source_unit_text(ionization.primary_energy_loss_eV, 'eV')
    };
    for index = 1:size(checks, 1)
        actual = char(model.param.get(checks{index, 1}));
        assert(strcmp(actual, checks{index, 2}), ...
            'COMSOL parameter %s is not bound to the resolved contract.', ...
            checks{index, 1});
    end
    verified = true;
end
