function verified = verify_wehnelt_contract_parameters(model, contract)
%VERIFY_WEHNELT_CONTRACT_PARAMETERS Read-only comparison with canonical bindings.
    parameters = wehnelt_contract_parameter_bindings(contract);
    parameterGroup = model.param;
    for index = 1:size(parameters, 1)
        actual = char(parameterGroup.get(parameters{index, 1}));
        assert(strcmp(actual, parameters{index, 2}), ...
            'COMSOL parameter %s is not bound to the resolved contract.', ...
            parameters{index, 1});
    end
    verified = true;
end
