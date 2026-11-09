function verified = apply_wehnelt_contract_parameters(model, contract)
%APPLY_WEHNELT_CONTRACT_PARAMETERS Bind resolved values to GUI parameters.

    parameters = wehnelt_contract_parameter_bindings(contract);

    parameterGroup = model.param;
    for index = 1:size(parameters, 1)
        parameterGroup.set(parameters{index, 1}, parameters{index, 2}, ...
            parameters{index, 3});
    end
    verified = verify_wehnelt_contract_parameters(model, contract);
end
