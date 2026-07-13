simion.command('"api_test.iob"')
local wb = simion.wb
print('before=' .. #wb.instances)
local ok, err = pcall(function() wb.instances[1].pa.filename = [[..\01_accelerator\oatof_accelerator_3d.pa0]] end)
print('replace_filename_ok=' .. tostring(ok) .. ' result=' .. tostring(err))
print('instance=' .. tostring(wb.instances[1]))
