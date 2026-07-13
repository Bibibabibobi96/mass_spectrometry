-- Build oa-TOF Workbench IOB from a locally prepared two-instance template.
-- The template PA filenames are deliberately retained: their PA0 files are
-- private copies of the two formal oa-TOF PA0 files, preventing any write to
-- 01_accelerator or 02_reflectron while the IOB is saved.
simion.command('"template_bngrid\\bngrid.iob"')
local wb = simion.wb
assert(#wb.instances == 2, 'two-instance template did not load')

-- Accelerator PA: its volume is x,y=0..78 and z=0..40 mm, while the
-- COMSOL origin is at its physical (39,39,10) mm point.
local a = wb.instances[1]
a.x, a.y, a.z = -39, -39, -10
a.az, a.el, a.rt = 0, 0, 0
a.scale = 1

-- Reflectron PA: local x is axial depth from the entry grid, local y is r.
-- Elevation +90 maps its local +x direction to Workbench global +z.
local r = wb.instances[2]
r.x, r.y, r.z = 0, 0, 619.83
r.az, r.el, r.rt = 0, 90, 0
r.scale = 1

wb:save([[oatof_ideal.iob]])
print('saved=oatof_ideal.iob')
