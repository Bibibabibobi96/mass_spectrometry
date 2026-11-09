function evidence = verify_ei_source_model(modelPath, resolvedContractPath)
%VERIFY_EI_SOURCE_MODEL Cold-load and inspect one saved unsolved EI model.
% No geometry/mesh rebuild, Study/Solver Compute, model save or source sampling.
    arguments
        modelPath (1, :) char
        resolvedContractPath (1, :) char
    end
    assert(isfile(modelPath), 'EISource:MissingModel', ...
        'The explicit EI-source model file does not exist: %s', modelPath);
    contract = load_ei_source_contract(resolvedContractPath);
    assert(strcmp(contract.numerical.execution_mode, 'build_only'), ...
        'EISource:NotBuildOnly', 'Cold EI verification requires a build-only contract.');
    assert(~contract.evidence.candidate_evidence_allowed, ...
        'EISource:NotBuildOnly', 'Unsolved EI preparation cannot grant candidate evidence.');

    import com.comsol.model.util.*
    tag = char(ModelUtil.uniquetag('EISourceCold'));
    model = ModelUtil.load(tag, modelPath);
    cleanup = onCleanup(@() ModelUtil.remove(tag)); %#ok<NASGU>
    parameterBindingsVerified = verify_ei_source_parameter_bindings(model, contract);
    componentTags = cell(model.component.tags());
    assert(isequal(componentTags(:), {'comp1'}), 'Saved EI component scope differs.');
    component = model.component('comp1');
    geometryTags = cell(component.geom.tags());
    meshTags = cell(component.mesh.tags());
    % COMSOL 6.4 creates a one-dimensional PARTICLE geometry for cpt when its
    % solver sequence is configured. It accompanies the explicit 3D geometry;
    % it is not another physical source component or a computed trajectory.
    assert(isequal(sort(geometryTags(:)), {'geom1'; 'pgeom_cpt'}), ...
        'Saved EI geometry scope differs.');
    assert(component.geom('pgeom_cpt').getSDim() == 1, ...
        'Saved EI generated particle geometry differs.');
    assert(isequal(meshTags(:), {'mesh1'}), 'Saved EI mesh scope differs.');
    geometry = component.geom('geom1');
    assert(geometry.getSDim() == 3, 'Saved EI geometry must remain three-dimensional.');
    geometryDomains = double(geometry.getNDomains());
    assert(geometryDomains > 0, 'Saved EI geometry is not built.');
    assert(numel(component.selection('sel_vac').entities()) == 2, ...
        'Saved EI vacuum/gas topology differs.');
    mesh = component.mesh('mesh1');
    meshComplete = logical(mesh.isComplete()) && ~logical(mesh.isEmpty());
    assert(meshComplete, 'Saved EI mesh is incomplete or empty.');
    physicsTags = cell(component.physics.tags());
    assert(isequal(sort(physicsTags(:)), {'cpt'; 'es'}), 'Saved EI physics scope differs.');
    assert(strcmp(char(component.physics('es').getType()), 'Electrostatics'), ...
        'Saved EI electrostatics interface type differs.');
    cpt = component.physics('cpt');
    assert(strcmp(char(cpt.getType()), 'ChargedParticleTracing'), ...
        'Saved EI particle interface type differs.');
    assert(strcmp(char(cpt.feature('rel1').getType()), 'Release'), ...
        'Saved EI release feature differs.');
    assert(strcmp(char(cpt.feature('ef1').getType()), 'ElectricForce'), ...
        'Saved EI electric-force feature differs.');
    collision = cpt.feature('coll1');
    assert(strcmp(char(collision.getType()), 'Collisions'), ...
        'Saved EI collision feature differs.');
    ionization = collision.feature('ion1');
    assert(strcmp(char(ionization.getType()), 'Ionization'), ...
        'Saved EI ionization feature differs.');
    assert(logical(ionization.getBoolean('ReleaseSecondaryElectron')) == ...
        contract.physical.ionization.release_secondary_electron, ...
        'Saved EI secondary-electron policy differs.');
    assert(logical(ionization.getBoolean('ReleaseIonizedParticle')) == ...
        contract.physical.ionization.release_ionized_particle, ...
        'Saved EI ionized-particle policy differs.');
    assert(logical(ionization.getBoolean('ReleasePrimaryElectron')) == ...
        contract.physical.ionization.release_primary_electron, ...
        'Saved EI primary-electron policy differs.');
    studyTags = cell(model.study.tags());
    solverTags = cell(model.sol.tags());
    assert(isequal(sort(studyTags(:)), {'std1'; 'std2'}), 'Saved EI study scope differs.');
    assert(isequal(sort(solverTags(:)), {'sol1'; 'sol2'}), 'Saved EI solver scope differs.');
    assert(strcmp(char(model.study('std1').feature('stat1').getType()), 'Stationary'), ...
        'Saved EI stationary study differs.');
    assert(strcmp(char(model.study('std2').feature('time1').getType()), 'Transient'), ...
        'Saved EI transient study differs.');
    solutionDataEmpty = [logical(model.sol('sol1').isEmpty()), logical(model.sol('sol2').isEmpty())];
    assert(all(solutionDataEmpty), 'Saved EI preparation unexpectedly contains solution data.');
    evidence = struct('status', 'PASS', 'model_path', modelPath, ...
        'contract_path', resolvedContractPath, 'execution_mode', 'build_only', ...
        'contract_project_id', contract.project_id, 'contract_model_id', contract.model_id, ...
        'selected_mode_id', contract.selected_mode_id, ...
        'parameter_bindings_verified', parameterBindingsVerified, ...
        'geometry_domains', geometryDomains, 'mesh_complete', meshComplete, ...
        'solution_data_empty', solutionDataEmpty, 'compute_calls', 0, ...
        'model_rewritten', false, 'candidate_evidence_allowed', false);
    evidence.physics_tags = physicsTags;
    evidence.geometry_tags = geometryTags;
    evidence.study_tags = studyTags;
    evidence.solver_tags = solverTags;
end
