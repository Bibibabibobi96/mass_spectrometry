# RF六极杆离子光学

本项目是`rf_multipole_ion_optics`家族的独立六极杆设计线。当前已从理想L1、二维圆杆L2推进到带
参数化带孔接口板和有限外部区的三维COMSOL直接传输；现状与边界以
[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 理论读取[`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

只有调整设计族范围、跨项目优先级或长期阶段时才读
[`docs/ROADMAP.md`](../../docs/ROADMAP.md)，日常项目任务不把它加入固定阅读链。

## 当前入口

- 项目身份：[`config/project.json`](config/project.json)
- 三项目共享运行合同：[`../../common/multipole/README.md`](../../common/multipole/README.md)
  （轴向实体与物理面只采用其中的“轴向部件与物理面术语”）。
- 历史L1兼容输入：[`config/baseline.json`](config/baseline.json)，只读；`project.json`的注册身份
  已改由全部design profile的一致identity给出，不再绑定该文件。旧L1/L2兼容消费者尚未迁移，
  该文件不是活动L3 solver参数权威。
- 当前家族实验机械base、typed电气mode、变量目录和优化包络：
  [`config/requests/mechanical_base.json`](config/requests/mechanical_base.json)、
  [`config/operating_modes.json`](config/operating_modes.json)、
  [`config/design_variables.json`](config/design_variables.json)、
  [`config/optimization_envelope.json`](config/optimization_envelope.json)
- 设计profile注册与解析发布：[`config/design_profiles.json`](config/design_profiles.json)、
  [`config/resolved_design.json`](config/resolved_design.json)。后者是兼容静态快照；当前三个家族实验
  resolved均由profile resolver从同一mechanical base和typed mode即时编译。
- L3运行profile：[`config/runtime_profiles.json`](config/runtime_profiles.json)只绑定设计、
  粒子源和求解器数值profile身份；粒子源与COMSOL/SIMION数值分别由
  [`config/particle_source_profiles.json`](config/particle_source_profiles.json)、
  [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json)和
  [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json)发布。
- 三个当前实验profile为`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
  `exit_aperture_plate_acceleration`；三者机械严格相同，只允许typed registry改变杆段和出口板电位。
- 共享粒子源：四/六/八极杆家族实验使用
  [`../../common/multipole/sources/rf_multipole_family_mother_sample_v1.json`](../../common/multipole/sources/rf_multipole_family_mother_sample_v1.json)
  发布的N=1000母样本及其精确N=100前缀。旧`hex_oct_baseline_fixed_100.csv`仅供legacy功能兼容。
- 数值与dispersion预登记位于[`config/qualification/`](config/qualification/)；当前没有有依据的连续量
  阈值和完整矩阵资源预算，因此连续资格结论必须为`INCONCLUSIVE`。当前只授权
  无加速N=100 baseline、空间和时间敏感性矩阵已完成，功能传输闭合；连续相空间仍为
  `INCONCLUSIVE`。分段杆轴向加速N=100 baseline功能已闭合，但COMSOL空间档耗尽工程内存预算。
  出口孔板加速N=100 baseline功能也已闭合，SIMION空间档保持100/100，但COMSOL空间档同样在
  `MESH_COMPLETE`后耗尽工程内存预算。COMSOL D1 build-only网格诊断的唯一一次运行在
  `mesh.run`前因诊断实现错误闭锁，登记为`INCONCLUSIVE_DIAGNOSTIC_IMPLEMENTATION_FAILURE`；
  D1零重试授权已经耗尽。随后
  [`D2 build-only资格记录`](config/qualification/comsol_hybrid_mesh_build_d2_preregistration.json)
  已以新身份完成一次COMSOL网格构建并通过拓扑、质量、全局单元数和资源门禁；其一次性授权也已耗尽，
  随后以
  [`混合网格粒子筛查预登记`](config/qualification/comsol_hybrid_transport_screen_preregistration.json)
  完成COMSOL N=100 field+particle工程筛查：纠错身份在场求解完成前超过12 GiB进程树预算，当前
  MUMPS hybrid候选已拒绝且授权关闭。当前另以
  [`PARDISO field-only隔离预登记`](config/qualification/comsol_hybrid_d2_pardiso_field_screen_preregistration.json)
  完成同一884,643单元D2网格的一次双场预检；它只改变stationary direct backend，但在首个差分场
  完成前以13,716,545,536 bytes超过12 GiB进程树硬帽。PARDISO比MUMPS失败峰值还高约0.40%，没有
  建立field-only可运行性或资源改进；该授权已经关闭。随后
  [`CG-AMG field-only隔离预登记`](config/qualification/comsol_hybrid_d2_cg_amg_field_screen_preregistration.json)
  曾在运行前授权同一D2网格、显式二次电势阶次和双场的唯一一次R0
  `20260729_234500__analysis__comsol__hex-hybrid-d2-cg-amg-field__r01`；唯一求解因素是CG+AMG
  稳态线性求解配置，禁止创建粒子并冻结零重试。该次COMSOL原始报告以884,643单元、二次电势
  单元和双场完成返回`PASS`，实测142.829 s、6,342,643,712 bytes进程树峰值，较完整FreeTet
  baseline低32.6846676%。但运行后合同错误地要求两个Electrostatics physics，而有效配对架构是
  一个physics复用于两个Study/两个Solution，故终态manifest为`failed`。这些数值只具有
  `POSTHOC_ENGINEERING_OBSERVATION_ONLY`身份，不构成预登记PASS；该次授权已经耗尽，零重试且
  本身不授权粒子跟进、后续细化、时间档、直接求解器等价、收敛、N=1000、Candidate或Formal资格。
  当前已另行预登记
  [`C1共享采样CG-AMG场诊断`](config/qualification/comsol_hybrid_c1_cg_amg_field_screen_preregistration.json)：
  将D2的非轴向局部尺寸统一放宽1.4倍、轴向每段10层保持不变，硬帽为60万单元、600 s、12 GiB，
  已一次完成CG-AMG并发布3330个公共空间点的双场V/E样本：371,447单元、双场各733,422 DOF，
  145.463 s、4,678,553,600 bytes进程树峰值，双场各5次迭代。当前仅以
  [`同配方MUMPS预登记`](config/qualification/comsol_hybrid_c1_mumps_field_screen_preregistration.json)
  完成第二臂一次、零重试：精确重现371,447单元及双场733,422 DOF，145.532 s、9,637,584,896
  bytes进程树峰值。公共
  [`场比较记录`](config/qualification/comsol_hybrid_c1_solver_comparison.json)显示差分/静态场矢量
  normalized RMS分别约`2.300e-6/3.030e-5`；因尚无来源化误差预算，结论保持
  `INCONCLUSIVE_DIAGNOSTIC_ONLY`。C1两臂授权均已关闭。随后
  [`D2 sampled CG-AMG非轴向细化臂`](config/qualification/comsol_hybrid_d2_cg_amg_sampled_field_preregistration.json)，
  保持轴向每段10层和CG-AMG不变，完成0.7→0.5 mm非轴向局部加密：884,643单元、双场各
  1,657,156 DOF，130.145 s、6,360,670,208 bytes进程树峰值。C1→D2的差分/静态场矢量
  normalized RMS约为`2.09%/4.36%`，所以C1不接受为空间参考。随后
  [`D3 axial-14 CG-AMG轴向细化臂`](config/qualification/comsol_hybrid_d3_axial14_cg_amg_sampled_field_preregistration.json)：
  固定D2全部非轴向尺寸，只把每物理段轴向层数从10增至14，并以979,785单元、双场各
  2,016,046 DOF、145.026 s和7,004,827,648 bytes进程树峰值完成。D2→D3的差分/静态场矢量
  normalized RMS约为`0.157%/0.810%`，支持轴向离散的工程稳定性；但D2之后没有第二个非轴向
  加密点，且D3距100万单元硬帽只剩约2.02%，所以总体空间收敛仍未建立。本轮预算和全部场运行
  授权均已关闭，不授权继续加密、粒子或资格结论。随后独立预登记的
  [`0.50 mm局部敏感区首臂`](config/qualification/comsol_local_sensitive_050_field_preregistration.json)
  正确建立了9个敏感走廊domain、28个接口边界实体和6个局部Size feature，但固定D2级背景网格后
  全局单元数为1,019,364，超过100万硬帽约1.94%，因此在场求解前登记为
  `INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`。0.40/0.32 mm、另一静电拓扑及全部粒子臂均未执行；
  当前授权再次关闭。后续新身份把非敏感背景改为C1级粗度，局部0.50和0.40 mm臂分别以
  685,215和990,929单元完成双场及6660行公共采样；常规杆区差分场normalized RMS由
  C1→0.50的1.341%降至0.50→0.40的0.490%，变化方向改善。但0.40 mm后只剩9,071单元余量，
  0.32 mm无法可信地留在同一硬帽内，因此不再浪费一次商业运行去确认预期超帽。
  [`趋势记录`](config/qualification/comsol_c1_background_sensitive_field_trend.json)据此保持
  `INCONCLUSIVE_MESH_STRATEGY_CHANGE_REQUIRED`；三点收敛、另一静电拓扑和粒子矩阵均未授权。
  后续V2没有增加CLI或配置字段，而是恢复既有三个正交控制轴：`sensitive_region.maximum_element_size_mm`
  只细化3.6 mm粒子走廊体积，杆表面继续由`radial_core_and_rod_hmax_mm`控制，端板边界继续由
  `transition_and_end_tetra_hmax_mm`控制。这样可先验证走廊空间误差，再分别验证杆面和端面误差，
  避免单个局部参数把完整杆面和完整端板同步加密。当前仅
  [`V2 0.50 mm首臂`](config/qualification/comsol_v2_corridor_only_050_field_preregistration.json)
  已执行且将单元数降到494,663，但COMSOL把四个扫掠段和四面体区全部标为`HAS_PROBLEMS=1`，
  因此公共门禁在场求解前停止。一次授权已耗尽且未重试；更少单元不能替代有效网格或收敛证据。
  V3代码已移除局部模式下被更细域继承覆盖的边界Size，并增加逐feature问题消息；当前仅
  [`V3 0.50 mm首臂`](config/qualification/comsol_v3_inherited_boundary_050_field_preregistration.json)
  已执行，但新增诊断调用了当前COMSOL客户端未暴露的`MeshFeatureClient.hasProblems()`，在`mesh.run`
  返回后、`mphmeshstats`之前中断。因而没有V3单元数或场结果，一次授权已耗尽且未重试。
  公共实现现已把详细问题消息降为`mphmeshstats`之后的非阻断诊断，并以新身份
  [`0.50 mm继承边界场臂`](config/qualification/comsol_inherited_boundary_nonblocking_050_field_preregistration.json)
  执行一次真实COMSOL运行。该运行得到434,876单元、全部网格区`HAS_PROBLEMS=0`、双场和6660行
  采样PASS，但预注册漏写`required_report`，runner在求解后的合同复核失败；因此这些结果仅为
  `POSTHOC_ENGINEERING_OBSERVATION_ONLY`，一次授权耗尽，后续档和粒子仍未授权。
  运行前报告合同门禁修复后，当前另以
  [`0.50 mm资格复验`](config/qualification/comsol_inherited_boundary_050_field_requalification.json)
  已以434,876单元、全部权威网格区无问题、双场和6660行采样完整PASS。当前据其另行预注册
  [`0.40 mm场臂`](config/qualification/comsol_inherited_boundary_040_field_preregistration.json)；
  该臂以537,566单元完整PASS。0.50→0.40 mm的常规杆跨区差分/静态场矢量normalized RMS约为
  0.486%/1.039%，接口区变化更高，且仍有46.24%单元预算，因此当前另行预注册
  [`0.32 mm场臂`](config/qualification/comsol_inherited_boundary_032_field_preregistration.json)；
  粒子仍未授权。
  既有三模式baseline的两份
  求解器报告只具有`POSTHOC_DESCRIPTIVE`身份，统一
  比较见[`../../docs/history/20260729__multipole-three-mode-posthoc-n100.md`](../../docs/history/20260729__multipole-three-mode-posthoc-n100.md)。
- 执行组合：[`config/execution_profiles.json`](config/execution_profiles.json)保留compile-only门禁；
  商业运行可由薄wrapper绑定同一profile，未提供evidence合同即为`UNQUALIFIED`。
- 运行入口：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2圆杆筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)，
  固定通过兼容alias `baseline_finite_3d`编译resolved，只发布逐候选场指标，不选择L3几何。
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- L3 COMSOL薄wrapper：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)，
  公开入口只接受具名runtime profile，不接受粒子路径或自由数值。
- L3 SIMION独立回归：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

运行产物只进入`artifacts/projects/rf_hexapole_ion_optics/runs/`，不进入Git。

## 历史入口

- [`docs/history/20260723__pre-n100-multipole-functional-evidence.md`](docs/history/20260723__pre-n100-multipole-functional-evidence.md)：
  N=100规范生效前的L1/L2/L3、正长度连接器和分段加速功能证据。
- [`docs/history/20260729__closed-hybrid-mesh-campaigns.md`](docs/history/20260729__closed-hybrid-mesh-campaigns.md)：
  已关闭 P1–P4 与 D1 hybrid mesh 预登记、终态和零重试边界。
