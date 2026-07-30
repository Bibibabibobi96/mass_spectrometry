# RF八极杆离子光学

本项目是`rf_multipole_ion_optics`家族的独立八极杆设计线。当前机器状态、资格边界和未决事项以
[`docs/PROJECT.md`](docs/PROJECT.md)为准；共享编译、typed operating mode、粒子状态及三模式发散方法
以[`../../common/multipole/README.md`](../../common/multipole/README.md)为准。

## 固定阅读顺序

1. 仓库根[`README.md`](../../README.md)。
2. 本项目[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 仅在需要理论背景时读取
   [`../../docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`../../docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

## 当前机器权威

- 单一机械请求：[`config/requests/mechanical_base.json`](config/requests/mechanical_base.json)。
- 单一变量目录与包络：
  [`config/design_variables.json`](config/design_variables.json)和
  [`config/optimization_envelope.json`](config/optimization_envelope.json)。
- typed电气模式：[`config/operating_modes.json`](config/operating_modes.json)。
- 三个规范design profile及兼容别名：
  [`config/design_profiles.json`](config/design_profiles.json)。
- `config/project.json`的注册身份由全部design profile的一致identity给出，不绑定历史
  `config/baseline.json`；后者只供尚未迁移的兼容路径只读访问。
- runtime、粒子源和求解器数值：
  [`config/runtime_profiles.json`](config/runtime_profiles.json)、
  [`config/particle_source_profiles.json`](config/particle_source_profiles.json)、
  [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json)和
  [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json)。
- N=100三档收敛预登记及三模式发散前置合同：
  [`config/qualification/n100_convergence_preregistration.json`](config/qualification/n100_convergence_preregistration.json)
  和
  [`config/qualification/three_mode_dispersion_preregistration.json`](config/qualification/three_mode_dispersion_preregistration.json)。
- 无加速混合网格粒子收敛活动：
  [`config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json`](config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json)
  与独立预算合同；具体已执行 arm、关闭状态和后续授权只以该预登记及
  [`docs/PROJECT.md`](docs/PROJECT.md)为准，本页不复制运行状态。

三个规范模式为`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`。旧名`baseline_finite_3d`与
`exit_aperture_plate_acceleration_reference`仅是分别映射到后两种typed mode的兼容别名；它们仍
消费同一机械请求、目录、包络和mode registry，不是第二机械权威，也不是第四或第五种实验模式。

runtime命名与四/六极杆一致：N=100 baseline直接使用完整mode ID；空间和时间加密分别追加
`_n100_spatial_refined`、`_n100_temporal_refined`；N=1000追加`_n1000`。solver numerics ID固定为
`baseline_finite_3d`、`n100_spatial_refined`和`n100_temporal_refined`。

## 冻结机械基线

杆范围为`z=0..79.6 mm`，`r0=4 mm`，杆半径比为`0.5`。四个导体段各长`19.6 mm`，由三个
`0.4 mm`间隙分隔。释放面为`z=-1.5 mm`，入口带孔接口板两面为`-1.0/-0.5 mm`；出口带孔接口板
两面为`80.1/80.6 mm`，规范交接面为`80.6 mm`，近接口统计面为`81.1 mm`。

三模式只允许电气差异：无加速杆段和两端接口板均为`0 V`；分段加速四段依次为
`0/-1/-2/-3 V`且出口板为`-3 V`；出口板加速的四段均为`0 V`且出口板为`-3 V`。任何几何、
RF、粒子源或非变化数值差异都会使配对实验失效。

## 运行与资格边界

- COMSOL薄wrapper：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)。
- SIMION薄wrapper：
  [`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)。
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)。

baseline pilot后登记的N=100三档只包含相邻的空间、时间离散比较：COMSOL局部最大单元
`0.5→0.35 mm`、每RF周期`80→160`步；SIMION全局cell`0.4→0.3 mm`、每RF周期`40→80`步。
空间比较先选择相邻网格，时间比较随后固定COMSOL `0.35 mm`和SIMION `0.3 mm`。不得事后改变输入、
观察量或接受尺度。

当前没有得到下游验收、物理相空间预算或可辩护的误差尺度，因此acceptance和effect-resolution合同
明确返回`INCONCLUSIVE`，不包含任意百分比。当前只授权
无加速N=100 baseline、空间和时间敏感性矩阵已完成，功能传输闭合；连续相空间仍为
`INCONCLUSIVE`。分段杆轴向加速N=100 baseline功能已闭合，SIMION空间档保持100/100，但
COMSOL空间档在`MESH_COMPLETE`后耗尽工程内存预算。
出口孔板加速N=100 baseline功能也已闭合，SIMION空间档保持100/100，但COMSOL空间档同样在
`MESH_COMPLETE`后耗尽工程内存预算。当前没有授权任何商业求解器运行；时间档、N=1000和
完整矩阵仍未授权。
六极杆已验证的混合网格机制已经按相同profile语义登记到本项目；这里只复用机制和比较设计，不继承
六极杆数值结果。新活动在取得明确商业运行授权前不会创建run。
项目合同
不能把求解器运行、Candidate或Formal状态从旧证据继承到新机械基线。

项目preregistration只冻结母样本、几何、电压和三份资格前置合同。每个求解器必须在三种模式真实运行
并验证canonical handoff-state路径、SHA和solver-numerics SHA之后，才能生成符合公共schema的正式
dispersion binding；缺少真实状态时固定失败关闭，不允许用占位路径或哈希。
现有preregistration还没有在运行前冻结公共方法要求的bootstrap seed和resample数，因此已完成的N=100
run不能事后发布为正式dispersion binding；公共发布器必须在创建输出前失败关闭。未来统计实验须先登记
这两个值再运行，不能回填到既有证据。既有run已另行生成两份明确标为`POSTHOC_DESCRIPTIVE`的
点估计报告；统一比较见
[`../../docs/history/20260729__multipole-three-mode-posthoc-n100.md`](../../docs/history/20260729__multipole-three-mode-posthoc-n100.md)。

运行产物只进入`artifacts/projects/rf_octupole_ion_optics/runs/`，不进入Git。旧request、旧证据和
兼容快照在活动引用退出并取得删除授权前保留，但不得接收新参数或覆盖上述机器权威。

## 历史

- [`docs/history/20260723__pre-n100-multipole-functional-evidence.md`](docs/history/20260723__pre-n100-multipole-functional-evidence.md)：
  N=100仓库级口径和当前typed机械合同生效前的功能证据，只读且不授予当前资格。
