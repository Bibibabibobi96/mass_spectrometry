# RF六极杆离子光学项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。分段杆轴向加速和出口带孔接口板加速（历史简称“端面加速”）曾分别
通过COMSOL与SIMION N=100功能复验；这些run早于request/resolved schema v2，现只作为
[`family_contract.json`](../../../common/multipole/family_contract.json)中的`superseded_evidence`
保留，不构成当前功能PASS。当前v2三模式后来均已完成双求解器N=100 baseline并恢复功能分类；
这仍不授予连续量网格收敛、跨求解器数值等价、机械或Formal资格。

当前家族实验已用[`../config/design_profiles.json`](../config/design_profiles.json)冻结
`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`三个canonical profile。三者共享唯一
`mechanical_base.json + design_variables.json + optimization_envelope.json`，只由
`operating_modes.json`映射三项电气量；`baseline_finite_3d`和
`exit_aperture_plate_acceleration_reference`仅为兼容alias，不是第二机械权威。项目L3薄wrapper只接受
`RuntimeProfileId`，由版本化profile绑定design profile、canonical粒子
CSV的SHA和各求解器数值profile；任意粒子路径和自由数值不再属于生产入口。公共runner保留为低层
投影机制。无evidence contract的运行固定为`UNQUALIFIED`。

当前`no_acceleration_full_length`保持79.6 mm杆、圆柱外壳、紧邻接口几何及四段物理导体，把四段和
出口带孔接口板电位全部冻结为0 V。2026-07-28完成的同名双求解器功能复验和随后数值矩阵属于改名前
`rf_hexapole_ion_guide`、旧固定N=100源（SHA-256
`494CB26FA128C475CB2DC1DB1A3437342DFBB5D1C1900E811E4BEBF47D7A6385`）及旧resolved几何；其run只在
`project.json`登记的legacy artifact根中只读保留。当前家族实验改为始终存在的四物理段和公共母样本
前缀后，这些结果不得继承为功能、收敛、跨求解器数值等价或Candidate资格。

Phase 2设计配置把当前`n=3`、6根电极身份、`r0=4 mm`、圆杆比0.5、有限杆范围、圆柱接地屏蔽及
真空域、圆孔接口、canonical驱动和uniform四段参考冻结为单一求解器无关请求。34个数值变量均以
请求JSON pointer、单位和双向边界声明；pole count保持项目身份，外壳model与连接器shape保持受支持
的锁定拓扑。注册execution profile仍是compile-only；薄wrapper运行公共runner时，无evidence合同只能
生成`UNQUALIFIED`结果。

项目已建立独立身份和理想有限长度L1传输合同。模型使用六根交替极性电极对应的理想六极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。L1/L2/L3迁移前小样本及2 mm连接器数值只保留在
[`history/20260723__pre-n100-multipole-functional-evidence.md`](history/20260723__pre-n100-multipole-functional-evidence.md)，
不构成当前Candidate证据。

## 当前参数与边界

- 阶数`n=3`，电极数6，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 坐标、`r0`和双极性组电压语义由`common/multipole/family_contract.json`统一；具体物理量只由项目
  design request编译，数值设置只由solver-numerics profile发布，并在每个run冻结。
- 新家族实验的N=100和N=1000源由同一版本化算法/seed生成，前者是后者精确前缀；100 amu、+1、
  2 eV，最大源半径0.5 mm，最大入射发散5°。旧六/八N=100只供legacy功能兼容。
- baseline pilot后、refined运行前登记的N=100数值三档为：COMSOL基线
  `0.5 mm/80 steps per RF period`、空间敏感性`0.35 mm/80`、在同一`0.35 mm`网格上的时间
  敏感性`160`；SIMION对应为`0.4 mm/40`、`0.3 mm/40`和在同一`0.3 mm`网格上的`80`。
  时间比较必须使用空间敏感性档作为对照，
  不得回到粗网格，也不增加第四档。
- 入口和出口孔半径均为3.6 mm；入口、出口连接器长度当前均为0 mm（直连合同）。入口带孔接口板
  上/下游面为`z=-1.0/-0.5 mm`，源释放面为`z=-1.5 mm`；出口带孔接口板上/下游面为
  `z=80.1/80.6 mm`，出口孔穿越面与零长度连接器的规范交接面在`z=80.6 mm`，近接口统计面为
  `z=81.1 mm`。外壳封闭端盖是屏蔽外壳的独立实体面，不是上述带孔接口板。绝对位置只由request
  编译后的接口合同派生；即使穿越面与交接面坐标重合，事件职责仍不同。
- Gate 0把源释放面和近接口统计面限定为紧邻接口发散：两者分别距杆入口/出口1.5 mm，统计面仅在
  出口带孔接口板下游面后0.5 mm。Pittman与O'Connor的真实FT-ICR六极杆接口设计报告9.53 mm内径导引器之间
  5.21 mm总间距和2.67 mm剩余边缘场区
  （[JASMS 16 (2005) 441–445](https://doi.org/10.1016/j.jasms.2004.12.010)）；据此当前毫米级间距
  不属于失去物理意义的远距离，但这是尺度相容的设计判断，不是本机械实现的直接复现。当前近接口
  统计面不得解释为数厘米下游远场；真实下游匹配须另建带独立漂移距离/观察面的workflow。
- 碰撞、空间电荷、磁场、支撑和机械公差均未启用。
- L2从兼容alias `baseline_finite_3d`即时编译resolved，再使用二维COMSOL场的谐波展开；
  只发布逐候选metrics，不选择或回写L3几何。未做网格收敛，不允许机械设计、Candidate或Formal声明。
- L3使用20 mm内半径连续接地圆柱外壳、独立外壳封闭端盖、四段有限圆杆、两块带孔接地接口板和
  两段有限外部区；无加速模式已用公共N=100前缀完成双求解器baseline、空间和时间功能矩阵，
  连续相空间仍为`INCONCLUSIVE`。两种加速模式已恢复当前v2 N=100 baseline功能分类；连续量资格和
  Candidate门禁仍未完成。

## 权威入口

- [`../config/requests/mechanical_base.json`](../config/requests/mechanical_base.json)
- [`../config/operating_modes.json`](../config/operating_modes.json)
- [`../config/design_variables.json`](../config/design_variables.json)
- [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- [`../config/execution_profiles.json`](../config/execution_profiles.json)
- [`../config/design_profiles.json`](../config/design_profiles.json)
- [`../config/resolved_design.json`](../config/resolved_design.json)
- [`../config/interfaces/provided/rf_multipole_exit.json`](../config/interfaces/provided/rf_multipole_exit.json)
- [`../config/runtime_profiles.json`](../config/runtime_profiles.json)
- [`../config/particle_source_profiles.json`](../config/particle_source_profiles.json)
- [`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)
- [`../config/simion_solver_numerics.json`](../config/simion_solver_numerics.json)
- [`../config/qualification/n100_convergence_preregistration.json`](../config/qualification/n100_convergence_preregistration.json)
- [`../config/qualification/dispersion_acceptance.json`](../config/qualification/dispersion_acceptance.json)
- [`../config/qualification/dispersion_effect_resolution.json`](../config/qualification/dispersion_effect_resolution.json)
- [`../config/qualification/engineering_budget.json`](../config/qualification/engineering_budget.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../config/round_rod_field_screen.json`](../config/round_rod_field_screen.json)
- [`../analysis/run_round_rod_field_screen.ps1`](../analysis/run_round_rod_field_screen.ps1)
- [`../analysis/run_round_rod_transport.ps1`](../analysis/run_round_rod_transport.ps1)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

`config/baseline.json`和`config/finite_3d_transport.json`仅为历史L1/L3兼容快照，不得接收新参数或
供活动L3 solver直接消费。项目注册身份已改由全部design profile的一致identity给出，不再绑定前者；
尚未迁移的兼容消费者仍可只读访问这些快照，但它们不构成solver权威。
`config/requests/baseline.json`、`requests/no_acceleration_full_length.json`、
`requests/exit_aperture_plate.json`及其专属catalog/envelope只保留历史/兼容读取；当前家族实验不得引用。
`config/evidence/no_acceleration_full_length.json`和
`config/evidence/exit_aperture_plate_acceleration_reference.json`中的固定功能阈值同样只保留给旧profile复现，
不得绑定当前公共母样本三模式，也不得替代`config/qualification/`中显式保持`INCONCLUSIVE`的资格判据。
`rf_multipole_exit`只发布`resolved_design.json`的出口交接视图；其来源SHA和逐值binding防止陈旧，
frame、轴向法向、中心向量、RF相位零点clock及场是否到达交接面的派生前提由项目直接测试冻结。
四/六/八极杆当前家族实验共同使用
`common/multipole/sources/rf_multipole_family_mother_sample_v1_1000.csv`及其精确
`..._100.csv`前缀；metadata冻结单一生成算法、seed、分布和SHA。旧
`hex_oct_baseline_fixed_100.csv`不属于新实验。

## 下一步

多极杆公共机制已冻结，后续不再为本项目复制公共杆阵列、运行时或接口实现。v1离子导引和接口功能链
曾由COMSOL与SIMION独立贯通，但不能继承为当前三模式资格。新的三模式机械base、typed电气合同、
N=100/N=1000源和N=100三档数值矩阵已经预登记，但没有有依据的连续量阈值。当前只授权无加速
N=100 baseline和空间敏感性双求解器pair已经完成：各档两边均为RF 100/100、zero-RF 21/100且
传输粒子身份一致；0.35/0.3 mm加密解间的RMS半径相对差约`2.47%`。当前只授权固定该空间离散的
时间敏感性pair也已完成；SIMION时间RMS半径变化约`0.092%`，COMSOL约`5.11%`，最终跨求解器
RMS半径差约`7.67%`。功能传输闭合，但连续结果只能`INCONCLUSIVE`，不得增加第四档。实测最大值
为578.056 s、1.031 GB瞬态目录、8.893 GB进程树内存，零自动重试；分段杆轴向加速N=100
baseline已在两求解器保持100/100传输和精确粒子身份，SIMION空间档也保持100/100；COMSOL空间档
在`MESH_COMPLETE`后以19.453 GB超过17.180 GB进程树帽，记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不重跑、不抬帽。出口孔板加速N=100
baseline已在两求解器保持100/100传输和精确粒子身份；SIMION空间档也保持100/100，RMS半径、
发散角和平均能量相对baseline分别变化约`8.16%`、`2.20%`和`0.152%`。COMSOL空间档在
`MESH_COMPLETE`后以19.288 GB超过17.180 GB进程树帽，记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不重跑、不抬帽。下述COMSOL D1 build-only网格诊断
也已经结束。新身份D2随后完成唯一一次build-only网格诊断并耗尽一次性授权；独立预登记的N=100
混合网格field+particle工程筛查也已关闭并拒绝当时的粒子候选，该筛查本身未授权后续细化、时间档、
N=1000或完整矩阵。后来独立完成的field-only C1/D2/D3序列见本文末尾；它同样不授权粒子。完整
身份登记在`../config/qualification/n100_no_acceleration_qualification.json`。
分段杆轴向加速身份和资源结论登记在
`../config/qualification/n100_segmented_rod_axial_acceleration_qualification.json`。
出口孔板加速身份和资源结论登记在
`../config/qualification/n100_exit_aperture_plate_acceleration_qualification.json`。
2026-07-29已从三个真实baseline run为COMSOL和SIMION分别发布
`POSTHOC_DESCRIPTIVE` binding和报告；它们固定声明非预注册、不计算bootstrap、不评价资格。正式
`three_mode_dispersion_binding`仍须由运行前冻结完整统计设置的新run生成，不得把事后报告升级或
伪造。没有N=1000真实运行、GUI/CAD同步与formal asset promotion时不得
声明Formal。碰撞冷却与CAD仍为独立后续阶段。轴向加速若
继续推进，应使用当前typed runtime profile研究各段电势，同时另行研究分段数量、长度/间隙、
馈电和机械实现；当前uniform四段参数是家族实验机械baseline，不是
正式硬件选择。

COMSOL全长工作域`0.35 mm` FreeTet细化已在出口带孔接口板加速和分段杆加速中重复于
`MESH_COMPLETE`后触发MUMPS进程树内存门禁，因此下一轮不得继续全域暴力细化。新的
[`已归档的 hybrid mesh pilot 预登记`](history/20260729__closed-hybrid-mesh-campaigns.md)
只冻结出口带孔接口板加速N=100的四步MUMPS工程pilot：P1验证每个物理杆段中央
`FreeTri + Sweep`及杆端、三个段隙、孔板/外部区`FreeTet`的粗网格；P2只加密径向core和杆边界，
P3只增加每段轴向层数，P4只加密过渡/端区四面体。任一步拓扑、资源或功能门禁失败即停止，不重排、
不重试、不追加第五次。四步原本采用逐次窄授权而非一次开放完整矩阵；P1失败后该campaign已经关闭，
当前资源门禁不再授权P1或P2–P4。PARDISO和CG-AMG只能另立预注册，不属于本轮失败重试。即使未来
另立并完成新序列，连续量仍因
缺少有来源误差预算保持`INCONCLUSIVE`。

P1随后在`88.817 s`内于场求解前触发真空网格拓扑门禁，进程树峰值仅
`3,489,751,040 bytes`，不是资源耗尽。按预注册停止规则，当前campaign已经关闭，P1不得重试，
P2–P4均未执行且未授权。冻结版本只输出了合并网格断言，因此不能从保留证据进一步区分全局mesh
problem、空真空选择或覆盖缺口；若要继续，必须另立小型build-only诊断预注册，不能把诊断伪装成
本轮重试。公共solver已补充逐项网格指标，供未来获批运行使用，不改变本次冻结证据。

独立的[`已归档 build-only 诊断预登记`](history/20260729__closed-hybrid-mesh-campaigns.md)
曾只授权一次D1 `mesh_build`：它复用既有COMSOL入口和hybrid策略，采用`8.5 mm` core以及
`radial_core_and_rod_hmax_mm=0.5 mm`的显式杆边界尺寸，计划在断言前输出选择、体积、覆盖/重叠、feature和
质量诊断，然后停止；field physics/Study/solution及particle physics/Study必须为0。唯一运行
`20260729_155030__build__comsol__hex-hybrid-d1-mesh-build__r01`观测到31个真空domain，但旧实现把
`mphmeasure`实体类型误写为`volume`并吞掉异常，所以体积只报告`NaN`；随后把带字段的诊断写入空结构体
数组，在`mesh.run`前因MATLAB不同结构体下标赋值失败。该运行登记为
`INCONCLUSIVE_DIAGNOSTIC_IMPLEMENTATION_FAILURE`：没有网格/拓扑证据，也没有资源门禁触发证据。
D1预算原固定为300 s、128 MiB瞬态目录、6 GiB进程树、8 GiB可用系统内存、10 MiB最终保留及零重试；
其一次运行和零重试授权已经耗尽，不重开P1，也不授权D1重跑或P2–P4。代码已静态修正为使用`domain`
几何测量、不可测时显式输出`UNKNOWN`并闭锁，以及以cell保存异构诊断，但修复本身不产生新的商业
求解器证据。

新的
[`D2 build-only资格记录`](../config/qualification/comsol_hybrid_mesh_build_d2_preregistration.json)
使用独立runtime/numerics身份，于run
`20260729_203000__build__comsol__hex-hybrid-d2-mesh-build__r01`完成唯一一次COMSOL N=100出口带孔
接口板加速`mesh_build`，不属于D1或P1重试。它冻结`8.5 mm` core、径向core/杆边界`0.5 mm`、
每物理段10个轴向层、过渡与端区
`0.5 mm`、外部真空`1.0 mm`和最小单元`0.02 mm`；资源上限为300 s、128 MiB瞬态目录、
6 GiB进程树、8 GiB最低系统可用内存、10 MiB最终compact保留、3,000,000个全局网格单元及零重试。
该运行以`success / UNQUALIFIED_MESH_BUILD_DIAGNOSTIC_ONLY`结束：全局/真空/四面体单元数分别为
`884,643 / 746,131 / 527,571`，四个扫掠段各`54,640`；全局与真空最小质量均为`0.1983`，扫掠段
最小质量为`0.5311`。扫掠-四面体重叠、真空未覆盖和非真空分区domain均为0，field physics/study/
solution及particle physics/study创建数均为0。运行耗时`56.488 s`，进程树峰值
`3,137,204,224 bytes`，最低系统可用内存`24,665,997,312 bytes`，运行目录峰值和最终保留均为
`1,664,539 bytes`，全部低于预登记上限。

D2只建立该hybrid网格的构建、拓扑、质量、全局单元数和资源可行性，不产生场解、粒子传输、连续
收敛、跨求解器数值等价、N=1000分散、机械、Candidate或Formal证据。其一次性零重试授权已经耗尽；
当前另以
[`混合网格粒子筛查预登记`](../config/qualification/comsol_hybrid_transport_screen_preregistration.json)
授权唯一一次COMSOL N=100真实场与粒子运行。它冻结旧FreeTet baseline run、resolved design、公共
N=100源和80步/周期、80 us轨迹设置，只把网格替换为D2已经建网通过的混合策略；预算为900 s、
12 GiB进程树、8 GiB最低系统可用内存、1 GiB瞬态目录、25 MiB compact终态、100万全局单元和零重试。
硬PASS只要求双工况100/100、primary粒子ID不变、正孔径裕量、混合分区拓扑和全部资源帽成立，并据
实测比较墙钟、内存和目录体积。RMS半径、发散、能量、TOF和逐粒子状态没有有来源误差预算，仍固定为
`INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET`；本次筛查不能声明连续数值等价、空间收敛、Candidate或Formal。
首个运行身份`20260729_220000__sim__comsol__hex-exitplate-hybrid-n100__r01`再次在
`MESH_COMPLETE`得到884,643单元和零分区缺口，但随后因任务脚本调用MATLAB不存在的`fflush`而在场
创建前失败；110.915 s内峰值进程树为3,126,431,744 bytes，未触发资源帽，登记为
`INCONCLUSIVE_DIAGNOSTIC_IMPLEMENTATION_FAILURE`，不是网格或物理FAIL，也不产生粒子证据。
旧baseline与当前编译resolved的总SHA因optimization-envelope权威文件演化和run-local来源路径表示而
不同，但剔除compiler、governance、sources和总SHA这些来源字段后的编译物理载荷SHA均为
`A868E5C06A6A98BF86C0D662D53118FCFF6EE51BA208214FACD7D39E32F6FD66`；逐字段审计未发现几何、电压、
源或接口差异。`fflush`移除后，纠错身份
`20260729_223000__sim__comsol__hex-exitplate-hybrid-n100__r02`仍完成同一884,643单元建网，但在场
求解完成前以13,661,315,072 bytes超过12 GiB进程树帽；当时系统可用内存仍有13,991,477,248 bytes，
因此终态为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`而非整机资源枯竭。相比旧FreeTet完整baseline
峰值9,422,286,848 bytes，未完成的hybrid候选已经高出44.989%，无法满足资源优化目标；当前策略登记为
`REJECT_CURRENT_HYBRID_FOR_PARTICLE_TRACKING`，不抬帽、不重跑，也没有粒子输出可用于连续量比较。

独立的
[`PARDISO field-only隔离预登记`](../config/qualification/comsol_hybrid_d2_pardiso_field_screen_preregistration.json)
已完成唯一一次`20260729_233000__analysis__comsol__hex-hybrid-d2-pardiso-field__r01`。它冻结上述D2
网格、出口孔板加速resolved、N=100源身份及全部物理量，唯一变量为两次stationary direct solve由
MUMPS改为显式PARDISO；计划在双场后停止且禁止创建粒子。真实运行再次得到884,643单元和零拓扑
缺口，但在首个差分场完成前于111.635 s达到13,716,545,536 bytes，超过12 GiB进程树硬帽；当时系统
仍有13,179,715,584 bytes可用，运行目录峰值仅1,738,045 bytes。该峰值比MUMPS失败身份高约0.404%，
比完整FreeTet baseline高约45.576%，因此PARDISO没有建立field-only可运行性或资源改进。运行登记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED / REJECT_SAME_MESH_PARDISO_FIELD_SOLVE`；一次性授权已经耗尽，
不重跑、不抬帽，也不授权粒子或后续细化。

此前独立
[`CG-AMG field-only隔离预登记`](../config/qualification/comsol_hybrid_d2_cg_amg_field_screen_preregistration.json)
在运行前授权唯一一次R0
`20260729_234500__analysis__comsol__hex-hybrid-d2-cg-amg-field__r01`。它保持出口带孔接口板加速的
resolved物理、D2的884,643单元网格目标、N=100源身份、80步/周期和80 us轨迹设置不变，显式冻结
二次电势单元阶次，只把两次稳态线性求解改为CG+AMG，容差`0.001`、最多500次迭代并开启误差检查。
运行在双场后停止，禁止创建粒子；成功还必须从COMSOL原生progress日志取得每个场的正`LinIt`和有限
`LinRes`，并证明没有全系统direct fallback。硬上限为703 s、12 GiB进程树、8 GiB最低系统可用内存、
128 MiB瞬态目录、10 MiB compact终态、100万单元和零重试；资源改进判据仍要求峰值低于旧完整
FreeTet baseline的9,422,286,848 bytes。

该R0已经执行一次。COMSOL原始报告自身以`STATUS=PASS`结束：网格仍为884,643单元，电势单元阶次
为二次，每个差分场和静态场均为1,657,156 DOF；差分场为6次线性迭代、末残差`5.5e-7`，静态场
为7次线性迭代、末残差`2.9e-7`。两者均从原生progress日志取得`LinIt/LinRes`，且报告CG+AMG、
一个Electrostatics physics、两个Study、两个Solution及零粒子physics/Study。资源监测记录
142.829 s、6,342,643,712 bytes进程树峰值、20,599,001,088 bytes最低系统可用内存，运行目录
峰值与最终保留均为1,788,736 bytes；观测内存峰值比已完成FreeTet baseline低32.6846676%，所有
预登记资源上限在观测值上均满足。

但预登记及运行后报告校验器错误地要求`FIELD_PHYSICS_CREATED=2`，而该有效配对架构正确地复用
一个Electrostatics physics，通过两个Study和两个Solution分别求解差分场与静态场。原始求解
完成后，后处理合同因此拒绝报告，summary和manifest登记为
`failed / INCONCLUSIVE_PREREGISTERED_REPORT_CONTRACT_MISMATCH`。所以以上原始求解与资源数值只
具有`POSTHOC_ENGINEERING_OBSERVATION_ONLY`身份，不能升级为预登记可运行性PASS或资源改进PASS；
该失败也不是COMSOL场求解FAIL。唯一商业运行和零重试授权已经耗尽，不重跑、不作粒子跟进，也不
授予粒子传输、与MUMPS/PARDISO的直接数值等价、场或粒子收敛、Candidate、Formal或N=1000结论。

当前后续不是重跑R0，而是独立的
[`hybrid C1 sampled-field预登记`](../config/qualification/comsol_hybrid_c1_cg_amg_field_screen_preregistration.json)。
C1保持二次电势、四段扫掠结构和每段10个轴向层，把径向core/rod与transition/end四面体上限从
0.5 mm放宽为0.7 mm、outer从1.0 mm放宽为1.4 mm、minimum从0.02 mm改为0.028 mm。它先授权
一次CG-AMG field-only运行，硬帽为60万单元、600 s、12 GiB且零重试；公共采样计划固定3330个
空间点，双场输出6660行V/E。该臂已一次成功：371,447单元，差分/静态场各733,422 DOF且各5次
CG迭代，末残差分别为`1.6e-7/4.2e-7`；145.463 s，进程树峰值4,678,553,600 bytes，最终保留
3,336,483 bytes。当前
[`同配方MUMPS预登记`](../config/qualification/comsol_hybrid_c1_mumps_field_screen_preregistration.json)
冻结这些实测网格/DOF身份、首臂manifest/report/numerics/field-sample SHA，并仅授权一次MUMPS
field-only运行。该臂也已一次成功，精确重现371,447单元及两个733,422 DOF场；145.532 s，
进程树峰值9,637,584,896 bytes，最终保留3,338,418 bytes。统一
[`比较记录`](../config/qualification/comsol_hybrid_c1_solver_comparison.json)绑定两份manifest与
field-sample SHA：CG-AMG相对MUMPS的差分场电势/场矢量normalized RMS为
`1.658e-6/2.300e-6`，静态场为`4.891e-6/3.030e-5`。这证明同配方双求解器功能闭合且数值非常接近，
但比较仍为`INCONCLUSIVE_DIAGNOSTIC_ONLY`；未定义物理误差预算前不得称为数值等价PASS，也不允许
提前进入粒子追踪。C1两臂一次性授权均已耗尽。随后
[`D2 sampled CG-AMG预登记`](../config/qualification/comsol_hybrid_d2_cg_amg_sampled_field_preregistration.json)
完成一次非轴向细化臂：轴向每段10层保持不变，core/rod及transition/end从0.7 mm细化至
0.5 mm、outer从1.4 mm细化至1.0 mm、minimum从0.028 mm细化至0.02 mm。真实运行得到884,643
单元、双场各1,657,156 DOF，差分/静态场分别6/7次CG迭代，130.145 s、6,360,670,208 bytes
进程树峰值。公共采样显示C1→D2的差分场电势/场矢量normalized RMS为`0.165%/2.086%`，
静态场为`0.107%/4.358%`；因此C1不接受为空间参考。随后
[`D3 axial-14 sampled CG-AMG预登记`](../config/qualification/comsol_hybrid_d3_axial14_cg_amg_sampled_field_preregistration.json)
只固定D2非轴向局部尺寸并把每物理段轴向层数从10增至14。首个`r01`在进入MATLAB/COMSOL前被
外层5 s编排时限终止，没有网格、场或资源证据，不消耗商业运行次数；同一冻结输入的`r02`一次成功，
得到979,785单元、双场各2,016,046 DOF，差分/静态场分别5/6次CG迭代，145.026 s、
7,004,827,648 bytes进程树峰值。D2→D3的差分场电势/场矢量normalized RMS为
`0.0236%/0.1574%`，静态场为`0.0505%/0.8097%`，支持轴向离散的工程稳定性。总体空间收敛仍为
`NOT_ESTABLISHED`：C1→D2非轴向变化明显，而D2之后没有第二个非轴向加密点；D3距100万单元硬帽
只剩约2.02%。本轮场运行预算已经关闭，不继续加密、不抬帽，粒子、Candidate、Formal和N=1000
跟进均未授权。

之后按独立身份执行的
[`局部敏感区0.50 mm首臂`](../config/qualification/comsol_local_sensitive_050_field_preregistration.json)
证明新选择和Size feature均真实存在：9个敏感走廊domain、28个入口/出口带孔接口板边界实体、
6个局部Size feature，且扫掠/四面体覆盖门禁通过。但该臂仍把非敏感core和transition背景固定在
D2的0.5 mm，新增分区后全局网格达到1,019,364单元，超过预登记100万硬帽约1.94%；运行在任何
场求解前以`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`终止。零重试成立，0.40/0.32 mm、分段杆
静电拓扑和全部粒子运行均未启动。该结果表明问题不是局部选择缺失，而是背景网格不够粗；若建立
新策略，应固定C1级非敏感背景，只在3.6 mm粒子走廊、杆表面和接口板边界沿0.50→0.40→0.32 mm
细化，并重新预登记，不能修改本次冻结身份或放宽资源帽。

共享SIMION模板、GUI复核、`.wgem`绕过和跨机可移植性状态只由
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)维护；公共机制证据不授予
本项目Candidate或Formal资格。

项目L3薄wrapper默认使用根README定义的`compact`产物保留类；数值资格或GUI复核需要MPH、PA解阵列或
完整轨迹时，必须在运行前显式选择非compact类并写明理由。该设置只管理产物，不是数值或资格参数。

活动产物位于`artifacts/projects/rf_hexapole_ion_optics/`；改名前证据继续只读保存在
`config/project.json`登记的legacy artifact根，不搬移、不改写旧manifest、不追加新run，也不改变其
原身份、状态和声明边界。

本项目还保留两项项目专属退出任务：

1. 迁移仍只读消费`config/baseline.json`的旧L1/L2兼容路径；项目注册身份不得重新绑定该快照，
   旧文件的后续处置仍须单独删除授权。
2. `config/finite_3d_transport.json`仍供旧family/L1测试读取。测试改为消费design request、resolved和
   solver-numerics profile且活动引用归零后，按删除授权退出该快照。
