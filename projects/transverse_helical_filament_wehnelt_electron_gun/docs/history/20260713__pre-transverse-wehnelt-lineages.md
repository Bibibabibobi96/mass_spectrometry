# Wehnelt 横置基线前历史谱系源码

DOC_STATUS: ARCHIVED_READ_ONLY

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本入口冻结实心阴极与轴向螺旋灯丝两条已被横置螺旋灯丝
> 基线取代的 MATLAB 源码谱系。payload 仅用于追溯归档时点的实现与历史结论，禁止作为活动入口、
> 受管运行输入或新模型起点，也禁止为适配当前工具链而修改其中源码。

## 冻结范围

payload 位于同名目录
[`20260713__pre-transverse-wehnelt-lineages/`](20260713__pre-transverse-wehnelt-lineages/)，
保持九个脚本的原始字节。原路径、谱系和 SHA-256 如下：

|谱系|原仓库相对路径|payload文件|SHA-256|
|---|---|---|---|
|实心阴极|`projects/wehnelt_electron_gun/legacy/solid_cathode/phase1_geometry.m`|[`phase1_geometry.m`](20260713__pre-transverse-wehnelt-lineages/phase1_geometry.m)|`23406ECFD12E2720571259807ACDB3E42DBBDA4AE7223D5CF8637B9E36A5F0DB`|
|实心阴极|`projects/wehnelt_electron_gun/legacy/solid_cathode/phase2_electrostatics.m`|[`phase2_electrostatics.m`](20260713__pre-transverse-wehnelt-lineages/phase2_electrostatics.m)|`F5D0761873ACF6AD2AB0A49FF06400C465F089A4D714CED839C77D9C8C182011`|
|实心阴极|`projects/wehnelt_electron_gun/legacy/solid_cathode/phase3_particle_tracing.m`|[`phase3_particle_tracing.m`](20260713__pre-transverse-wehnelt-lineages/phase3_particle_tracing.m)|`039D4C7684D5B2AD08EFA3A6FC67CCA81ECBD1209DF255C0D98E401B9DD1C3E8`|
|实心阴极|`projects/wehnelt_electron_gun/legacy/solid_cathode/gpu_solver_comparison.m`|[`gpu_solver_comparison.m`](20260713__pre-transverse-wehnelt-lineages/gpu_solver_comparison.m)|`58F1D69CEE41A759DB287B249342700E15DDBE82D10C7D29F77CACB09B3DE313`|
|轴向螺旋灯丝|`projects/wehnelt_electron_gun/legacy/axial_coil/phase1_geometry_coil.m`|[`phase1_geometry_coil.m`](20260713__pre-transverse-wehnelt-lineages/phase1_geometry_coil.m)|`AA0632F89039A61B535E52ED1EB651E8C045057C6D0D02CEB83356DCB71B0460`|
|轴向螺旋灯丝|`projects/wehnelt_electron_gun/legacy/axial_coil/phase2_electrostatics_coil.m`|[`phase2_electrostatics_coil.m`](20260713__pre-transverse-wehnelt-lineages/phase2_electrostatics_coil.m)|`7553F6C053FBE9E23C6EF9A8335518D4D00E3218AAE1B85B49BD5315769A831B`|
|轴向螺旋灯丝|`projects/wehnelt_electron_gun/legacy/axial_coil/phase3_particle_tracing_coil.m`|[`phase3_particle_tracing_coil.m`](20260713__pre-transverse-wehnelt-lineages/phase3_particle_tracing_coil.m)|`18F9EF63D092173C8A5C63ED7822892CF07BF49E8B13D7AAB0DA4170092D915F`|
|轴向螺旋灯丝|`projects/wehnelt_electron_gun/legacy/axial_coil/phase4_thermal_emission_coil.m`|[`phase4_thermal_emission_coil.m`](20260713__pre-transverse-wehnelt-lineages/phase4_thermal_emission_coil.m)|`78D89328AE25503DECCD0E5DE5CE32E002ECFCDF4091552555B1F3177FFCF315`|
|轴向螺旋灯丝|`projects/wehnelt_electron_gun/legacy/axial_coil/phase5_wehnelt_sweep.m`|[`phase5_wehnelt_sweep.m`](20260713__pre-transverse-wehnelt-lineages/phase5_wehnelt_sweep.m)|`65A9BD443BD2FA7105FA7967C95360532C79BC7BDF20C92EFC96EA8DB4C08C11`|

机器复核清单见
[`SHA256SUMS.txt`](20260713__pre-transverse-wehnelt-lineages/SHA256SUMS.txt)。
相关旧 MPH 与结果仍位于 artifact migration snapshot
`archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`；本 payload
不复制二进制产物。

## 谱系结论与边界

- 实心阴极脚本只证明早期几何、静电、冷发射粒子追踪和求解器对照的实现谱系；不属于当前横置灯丝
  模型，也不具备现行合同、run 三件套或工具链资格。
- 轴向螺旋灯丝脚本保留冷/热发射与旧 Wehnelt 扫描的算法上下文。历史结果支持“轴向灯丝存在匝间
  自吸收”和“Wehnelt 偏压响应可能非单调”的历史观察，但不得把旧扫描的具体孔径、电压或效率用于
  当前横置基线。
- 九个脚本包含旧连接、绝对安装路径和旧产物写入方式。归档保留这些事实，不表示它们可在当前
  MATLAB R2025b/COMSOL 6.4 受管入口中执行。

当前物理状态、受管入口与开放任务只以
[`../PROJECT.md`](../PROJECT.md)为准；完整历史叙事见
[`PROJECT_HISTORY.md`](PROJECT_HISTORY.md)。
