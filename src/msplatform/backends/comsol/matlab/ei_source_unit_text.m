function text = ei_source_unit_text(value, unit)
%EI_SOURCE_UNIT_TEXT Convert one validated scalar to an explicit COMSOL expression.
    text = sprintf('%.17g[%s]', value, unit);
end
