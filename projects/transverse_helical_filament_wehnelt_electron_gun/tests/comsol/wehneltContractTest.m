classdef wehneltContractTest < matlab.unittest.TestCase
    % Pure contracts and parameter APIs only; no COMSOL connection or model.
    properties
        Contract
        TemporaryDirectory
    end
    properties (TestParameter)
        phaseBuilder = struct('geometry', @phase1_geometry_coil_transverse, ...
            'electrostatic', @phase2_electrostatics_coil_transverse, ...
            'thermal', @phase4_thermal_emission_coil_transverse)
    end
    methods (TestClassSetup)
        function addCanonicalHelpers(testCase)
            projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            repoRoot = fileparts(fileparts(projectRoot));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture( ...
                fullfile(repoRoot, 'src', 'msplatform', 'backends', 'comsol', 'matlab')));
            testCase.Contract = jsondecode(fileread(fullfile(projectRoot, 'config', 'resolved_model.json')));
        end
    end
    methods (TestMethodSetup)
        function createTemporaryDirectory(testCase)
            fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.TemporaryDirectory = fixture.Folder;
        end
    end
    methods (Test)
        function buildWrapperRequiresContract(testCase)
            testCase.verifyError(@() build_wehnelt_model(), 'Wehnelt:MissingContract');
        end
        function buildWrapperRequiresOwnerDirectory(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            testCase.verifyError(@() build_wehnelt_model(contractPath), 'Wehnelt:MissingRunDirectory');
        end
        function buildWrapperRejectsFullModeBeforeComsol(testCase)
            contract = testCase.Contract;
            contract.selected_mode_id = 'functional_reference';
            contract.numerical.execution_mode = 'full';
            contract.evidence.minimum_particle_count = 100;
            contract.evidence.requested_particle_count = 100;
            contractPath = testCase.writeContract(contract);
            testCase.verifyError(@() build_wehnelt_model(contractPath, testCase.TemporaryDirectory), ...
                'Wehnelt:NotBuildOnly');
        end
        function validResolvedFixtureKeepsPrototypeScope(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            actual = load_wehnelt_contract(contractPath);
            testCase.verifyEqual(actual.project_id, 'transverse_helical_filament_wehnelt_electron_gun');
            testCase.verifyEqual(actual.numerical.execution_mode, 'build_only');
            testCase.verifyEqual(actual.physical.particle.charge_state, -1);
            testCase.verifyFalse(actual.evidence.candidate_evidence_allowed);
        end
        function missingContractStopsBeforeComsol(testCase, phaseBuilder)
            testCase.verifyError(@() phaseBuilder(), 'Wehnelt:MissingContract');
        end
        function missingRunDirectoryStopsBeforeComsol(testCase, phaseBuilder)
            contractPath = testCase.writeContract(testCase.Contract);
            testCase.verifyError(@() phaseBuilder(contractPath), 'Wehnelt:MissingRunDirectory');
        end
        function nonexistentRunDirectoryStopsBeforeComsol(testCase, phaseBuilder)
            contractPath = testCase.writeContract(testCase.Contract);
            runDirectory = fullfile(testCase.TemporaryDirectory, 'not-created');
            testCase.verifyError(@() phaseBuilder(contractPath, runDirectory), 'Wehnelt:RunDirectoryMissing');
        end
        function parameterTableKeepsAllOriginalBindingsAndPrecision(testCase)
            contract = testCase.Contract;
            contract.physical.filament.coil_major_radius_mm = 1/3;
            bindings = wehnelt_contract_parameter_bindings(contract);
            testCase.verifySize(bindings, [41, 3]);
            testCase.verifyEqual(bindings{1,1}, 'coil_rmaj');
            testCase.verifyEqual(bindings{1,2}, '0.33333333333333331[mm]');
        end
        function parameterVerificationNeverUsesSetter(testCase)
            model = testCase.boundParameterModel();
            testCase.verifyTrue(verify_wehnelt_contract_parameters(model, testCase.Contract));
        end
        function changedSavedParameterIsRejectedWithoutRepair(testCase)
            model = testCase.boundParameterModel();
            original = model.param.get;
            model.param.get = @(name) replace(original(name), '[mm]', '[s]');
            exception = testCase.captureException(@() verify_wehnelt_contract_parameters(model, testCase.Contract));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'COMSOL parameter coil_rmaj is not bound to the resolved contract.');
        end
        function coldVerifierRequiresActualModel(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            model = fullfile(testCase.TemporaryDirectory, 'missing.mph');
            testCase.verifyError(@() verify_wehnelt_model(model, contractPath), 'Wehnelt:MissingModel');
        end
        function coldVerifierRejectsFullModeBeforeComsol(testCase)
            contract = testCase.Contract;
            contract.selected_mode_id = 'functional_reference';
            contract.numerical.execution_mode = 'full';
            contract.evidence.minimum_particle_count = 100;
            contract.evidence.requested_particle_count = 100;
            contractPath = testCase.writeContract(contract);
            model = fullfile(testCase.TemporaryDirectory, 'inert-not-a-model.mph');
            fid = fopen(model, 'w');
            fclose(fid);
            testCase.verifyError(@() verify_wehnelt_model(model, contractPath), 'Wehnelt:NotBuildOnly');
        end
        function positiveChargeCannotBecomeElectron(testCase)
            contract = testCase.Contract;
            contract.physical.particle.charge_state = 1;
            contractPath = testCase.writeContract(contract);
            exception = testCase.captureException(@() load_wehnelt_contract(contractPath));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'Resolved electron species, mass, or charge is invalid.');
        end
        function unfrozenSamplingCannotClaimReproducibility(testCase)
            contract = testCase.Contract;
            contract.numerical.particle_sampling.reproducible_particle_realization = true;
            contractPath = testCase.writeContract(contract);
            exception = testCase.captureException(@() load_wehnelt_contract(contractPath));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'Resolved particle sampling overstates reproducibility.');
        end
    end
    methods (Access = private)
        function contractPath = writeContract(testCase, contract)
            contractPath = fullfile(testCase.TemporaryDirectory, 'resolved.json');
            fid = fopen(contractPath, 'w', 'n', 'UTF-8');
            assert(fid >= 0);
            cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
            fprintf(fid, '%s', jsonencode(contract));
        end
        function exception = captureException(testCase, action)
            exception = [];
            try
                action();
            catch actual
                exception = actual;
            end
            testCase.assertClass(exception, 'MException');
        end
        function model = boundParameterModel(testCase)
            bindings = wehnelt_contract_parameter_bindings(testCase.Contract);
            values = containers.Map(bindings(:,1), bindings(:,2));
            model = struct('param', struct('get', @(name) values(name), ...
                'set', @(varargin) error('WehneltTest:UnexpectedWrite', 'Read-only verification attempted a write.')));
        end
    end
end
