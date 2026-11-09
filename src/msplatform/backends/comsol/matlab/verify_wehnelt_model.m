function evidence = verify_wehnelt_model(modelPath, resolvedContractPath)
%VERIFY_WEHNELT_MODEL Cold readback of the saved unsolved three-stage model.
    arguments
        modelPath (1, :) char
        resolvedContractPath (1, :) char
    end
    assert(isfile(modelPath), 'Wehnelt:MissingModel', ...
        'The explicit Wehnelt model file does not exist: %s', modelPath);
    contract = load_wehnelt_contract(resolvedContractPath);
    assert(strcmp(contract.numerical.execution_mode, 'build_only'), ...
        'Wehnelt:NotBuildOnly', 'Cold Wehnelt verification requires a build-only contract.');
    import com.comsol.model.util.*
    tag = char(ModelUtil.uniquetag('WehneltCold'));
    model = ModelUtil.load(tag, modelPath);
    cleanup = onCleanup(@() ModelUtil.remove(tag)); %#ok<NASGU>
    bindingsVerified = verify_wehnelt_contract_parameters(model, contract);
    assert(isequal(cell(model.component.tags()), {'comp1'}), 'Saved Wehnelt component scope differs.');
    component = model.component('comp1');
    geometryTags = cell(component.geom.tags());
    assert(isequal(sort(geometryTags(:)), {'geom1'; 'pgeom_cpt'}), ...
        'Saved Wehnelt geometry scope differs.');
    assert(component.geom('pgeom_cpt').getSDim() == 1, ...
        'Saved generated particle geometry differs.');
    geometry = component.geom('geom1');
    assert(geometry.getSDim() == 3, 'Saved Wehnelt physical geometry must remain 3D.');
    domains = double(geometry.getNDomains());
    assert(domains > 0, 'Saved Wehnelt geometry is not built.');
    assert(strcmp(char(geometry.feature('hel1').getType()), 'Helix'), ...
        'Saved Wehnelt filament primitive differs.');
    assert(strcmp(char(geometry.feature('hel1').getString('axistype')), 'x'), ...
        'Saved Wehnelt filament must remain transverse.');
    assert(numel(component.selection('sel_vac').entities()) == 1, ...
        'Saved Wehnelt vacuum selection differs.');
    meshTags = cell(component.mesh.tags());
    assert(isequal(meshTags(:), {'mesh1'}), 'Saved Wehnelt mesh scope differs.');
    mesh = component.mesh('mesh1');
    meshComplete = logical(mesh.isComplete()) && ~logical(mesh.isEmpty());
    assert(meshComplete, 'Saved Wehnelt mesh is incomplete or empty.');
    physicsTags = cell(component.physics.tags());
    assert(isequal(sort(physicsTags(:)), {'cpt'; 'es'}), 'Saved Wehnelt physics scope differs.');
    assert(strcmp(char(component.physics('es').getType()), 'Electrostatics'), ...
        'Saved Wehnelt electrostatics interface differs.');
    cpt = component.physics('cpt');
    assert(strcmp(char(cpt.getType()), 'ChargedParticleTracing'), ...
        'Saved Wehnelt particle interface differs.');
    particle = cpt.feature('pp1');
    expectedMass = sprintf('%.17g[kg]', contract.physical.particle.mass_kg);
    assert(strcmp(char(particle.getString('mp')), expectedMass), 'Saved electron mass differs.');
    assert(strcmp(char(particle.getString('Z')), sprintf('%.17g', contract.physical.particle.charge_state)), ...
        'Saved negative electron charge state differs.');
    wallCondition = char(cpt.feature('wall1').getString('WallCondition'));
    assert(strcmp(wallCondition, contract.physical.terminal_outcomes.wall_condition), ...
        'Saved Wehnelt wall condition differs.');
    inlet = cpt.feature('inl1');
    assert(strcmp(char(inlet.getType()), 'Inlet'), 'Saved Wehnelt thermal inlet differs.');
    emissionDistribution = char(inlet.getString('VelocitySpecification'));
    assert(strcmp(emissionDistribution, contract.physical.emission_model.velocity_distribution), ...
        'Saved Wehnelt emission distribution differs.');
    assert(strcmp(char(inlet.getString('N')), sprintf('%.17g', contract.evidence.requested_particle_count)), ...
        'Saved requested particle count differs.');
    studyTags = cell(model.study.tags());
    solverTags = cell(model.sol.tags());
    assert(isequal(sort(studyTags(:)), {'std1'; 'std2'}), 'Saved Wehnelt study scope differs.');
    assert(isequal(sort(solverTags(:)), {'sol1'; 'sol2'}), 'Saved Wehnelt solver scope differs.');
    assert(strcmp(char(model.study('std1').feature('stat1').getType()), 'Stationary'), ...
        'Saved Wehnelt stationary study differs.');
    assert(strcmp(char(model.study('std2').feature('time1').getType()), 'Transient'), ...
        'Saved Wehnelt transient study differs.');
    solutionEmpty = [logical(model.sol('sol1').isEmpty()), logical(model.sol('sol2').isEmpty())];
    assert(all(solutionEmpty), 'Saved Wehnelt preparation contains solution data.');
    evidence = struct('status', 'PASS', 'model_path', modelPath, ...
        'contract_path', resolvedContractPath, 'execution_mode', 'build_only', ...
        'contract_project_id', contract.project_id, 'contract_model_id', contract.model_id, ...
        'selected_mode_id', contract.selected_mode_id, 'parameter_bindings_verified', bindingsVerified, ...
        'geometry_domains', domains, 'mesh_complete', meshComplete, ...
        'solution_data_empty', solutionEmpty, 'compute_calls', 0, 'model_rewritten', false, ...
        'candidate_evidence_allowed', false, 'electron_mass_expression', expectedMass, ...
        'electron_charge_state', contract.physical.particle.charge_state, ...
        'requested_particle_count', contract.evidence.requested_particle_count, ...
        'emission_distribution', emissionDistribution, 'wall_condition', wallCondition);
    evidence.geometry_tags = geometryTags;
    evidence.physics_tags = physicsTags;
    evidence.study_tags = studyTags;
    evidence.solver_tags = solverTags;
end
