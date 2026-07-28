-- Builds non-physical PA0 files used only to create an independent Candidate IOB.
local source = assert(arg[1], 'usage: build_candidate_layout_placeholders.lua SOURCE_GEM OUTPUT_DIR')
local output_dir = assert(arg[2], 'output directory is required')
local names = {
  'flight_tube_ground.pa0', 'reflectron.pa0', 'accelerator.pa0', 'detector_ground.pa0',
}
for _, name in ipairs(names) do
  local path = output_dir .. '\\' .. name
  simion.command(string.format('gem2pa %q %q', source, path))
  local file = assert(io.open(path, 'rb'), 'placeholder PA was not created: ' .. path)
  file:close()
end
print('CANDIDATE_LAYOUT_PLACEHOLDERS=PASS')
