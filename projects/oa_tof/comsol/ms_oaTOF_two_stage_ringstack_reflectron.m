function result = ms_oaTOF_two_stage_ringstack_reflectron(varargin)
%MS_OATOF_TWO_STAGE_RINGSTACK_REFLECTRON Legacy positional API wrapper.
% New code should call run_oatof_model with named options. The implementation
% lives in oatof_build_model_core so this compatibility surface cannot acquire
% solver, geometry, analysis, or artifact responsibilities.
result = oatof_build_model_core(varargin{:});
end
