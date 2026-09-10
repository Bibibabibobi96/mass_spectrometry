# SIMION 最小实现与边界

本项目的离子轨迹推进权威是 SIMION。Python 只编译 GEM、校验输入、序列化粒子源和整理证据，不能
积分离子运动。

## 最简 400 Pa 快速原型

首轮轨迹不依赖 COMSOL。第二锥出口 `z=3 mm` 之后直接规定为均匀 `400 Pa`、`300 K`、轴向
载气速度 `100 m/s`，第二锥之前省略碰撞；SIMION 负责 RF/DC 轨迹，官方 `collision_sds.lua`
负责氮气碰撞与扩散。入口离子视为已经去溶剂化。该模型只用于快速判断能否穿过几何和两段杆，
不解释喷流、压强梯度、泵口或绝对传输率。

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\run_uniform_400pa_prototype.ps1 `
  -OutputDir ..\artifacts\projects\dual_cone_tandem_quadrupole_ion_interface\runs\<run_id>
```

一条命令会复用/生成 PA、编译受控 Lua 气体场、冻结官方 SDS、构建单实例 IOB、执行真实 Fly，
并输出 `prototype_run_report.json`、逐点轨迹和粒子末态。`100 m/s` 是明确可替换的规定参数，
不是 CFD 或实测结果。

## 当前可执行链

无碰撞 C0 几何 smoke：

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\run_c0_gem_smoke.ps1 `
  -OutputDir ..\artifacts\projects\dual_cone_tandem_quadrupole_ion_interface\runs\<run_id>
```

该入口只生成 GEM、执行 `gem2pa` 和不带 convergence 参数的 `refine`，并检查电极基组
`0,1,2,11,12,21,22`。它不飞行粒子、不输出传输率，也不构成 Candidate 或 Formal 证据。

COMSOL 气体场升级路径的输入准备：

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\prepare.ps1 `
  -Mode gas_assisted_transport -GasFieldManifest <comsol-export-manifest.json> `
  -OutputDir ..\artifacts\projects\dual_cone_tandem_quadrupole_ion_interface\runs\<run_id>
```

在 COMSOL 场 manifest 缺失、字段/坐标域不符、Lua 场文件缺失或 SHA-256 漂移时，入口在调用
SIMION 前失败。当前 `gas_field_interface.json` 的 `current_artifact` 是 `null`，表示没有已发布的
COMSOL 场；它不影响每次运行即时生成并冻结的均匀 `400 Pa` 原型场。

准备阶段从 SIMION 安装目录的 `examples\collision_sds` 冻结并哈希
`collision_sds.lua`、`mbmr.dat`、`textfilelib.lua`、`arraylib.lua` 和 `m_defs.dat`。这些 SIMION 官方、
受许可约束的文件只进入运行目录，不复制进 Git。RF 电压计算冻结并复用
`common/multipole/simion_rf_drive.lua`；粒子文件由 `common/simion/particle_source.py` 序列化。

## 几何范围

单体 PA 使用电极 `1/2` 表示两锥，`11/12` 表示椭圆杆两相，`21/22` 表示圆杆两相。设备坐标到
Workbench 的平移记录在 `simion_solver_numerics.json`。杆几何由
`common.multipole.simion_geometry.render_grouped_rod_array_gem` 生成，项目不复制圆杆或椭圆杆公式。

当前 C0 GEM 把椭圆杆入口暂时截为 `z=4.6 mm` 平面。真实“沿第二锥面切削”仍需项目级、经拓扑
测试的 CSG mask；在它完成前，C0 只证明 GEM/PA 电极命名和粗几何可编译，不证明入口边缘场。

低压圆柱壳因壁厚和端部结构未知而未虚构为导体；泵口、两段间透镜和出口透镜同样未建模。

## 气体场接口

COMSOL CSV 先由 `analysis/export_simion_gas_runtime.py`（或 `build_gas_runtime.ps1`）在独立校验通过后编译。导出 manifest 必须严格满足 `config/gas_field_interface.json`，并指向一个带 SHA-256 的自包含 Lua
只读场适配器。适配器在设备局部坐标中提供：

- `pressure_pa(x_mm,y_mm,z_mm)`：绝对压力 Pa；
- `temperature_k(x_mm,y_mm,z_mm)`：K；
- `velocity_m_s(x_mm,y_mm,z_mm)`：三分量 m/s。

禁止外推；整个 `z=-2..108 mm, r=0..23.5 mm` 域必须覆盖。后续飞行 Program 必须通过官方
`collision_sds.lua` 注入这些函数，并通过共享 RF kernel 驱动电极；不得用 Python 阻尼积分器替代。
