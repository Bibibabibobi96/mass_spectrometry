# RF四极杆离子光学项目状态

本文件是项目当前事实、资格边界和开放任务的唯一权威。实现步骤分别见[`COMSOL.md`](COMSOL.md)和
[`SIMION.md`](SIMION.md)；共享多极杆状态只引用
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)。2026-07-28以前的完整
run编号、故障链和关闭过程冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 当前结论

- 当前v2圆柱机械base上的分段杆轴向加速和出口带孔接口板加速均已完成COMSOL与SIMION N=100
  baseline，两个求解器均为100/100且交接粒子身份一致；功能分类已闭合。两者的COMSOL空间加密均受
  预登记资源帽约束而`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不构成连续量收敛或数值等价PASS。
- 四极杆具名`explicit`非等长、非等间隙、非线性逐段电势案例仍只有v1双求解器N=100历史功能依据；
  当前家族参考只使用`uniform`四段。
- 同一79.6 mm杆长、4 mm场半径几何承载RF-only传输与RF+DC质量过滤。L1理论通带和双求解器有限
  几何功能响应均已建立，但质量过滤尚未获得网格、数值一致性或分辨能力资格。
- 面向接口的N=100四极杆工况在COMSOL和SIMION中均100/100传输；出口束斑、发散与均能未满足暂定
  相空间一致性目标，因此严格跨求解器接口结论仍为FAIL。
- RF四极杆离子光学→单次反射oa-TOF默认1 mm及0 mm兼容连接均完成N=100功能链；它们证明物理孔、被动连接器、共享时钟和
  数据链可贯通，不构成阶段资格、传输率优化、分辨率或整机Formal。
- 碰撞冷却物理尚未建立。旧150 mm碰撞脚本为拒绝执行短桩，不属于当前几何或物理合同。
- 当前圆柱全尺寸家族机械base已固定为`r0=4 mm`、杆半径比0.5、杆区`0..79.6 mm`、四段
  19.6 mm导体与三处0.4 mm gap；源释放面、入口板、出口板、handoff和近接口面分别为
  `-1.5 mm`、`[-1.0,-0.5] mm`、`[80.1,80.6] mm`、`80.6 mm`和`81.1 mm`。
- 无加速、分段杆加速和出口接口板加速已统一为一个机械base上的三种typed电气模式，并绑定四、六、八
  极杆共同的2 eV N=100/N=1000母样本。无加速N=100基线已在统一四段机械几何和统一近接口统计面上
  完成COMSOL与SIMION真实重跑：RF-on均为100/100，zero-RF均为21/100；这只恢复基线功能分类，
  空间/时间敏感性、连续相空间等价、机械、Candidate和Formal仍未完成。
- 本项目适用公共多极杆家族工程推进合同；阈值、状态和判定只读取
  `../../../common/multipole/engineering_progression_acceptance.json`，不在项目文件保存副本。
  工程推进不回写既有`INCONCLUSIVE`收敛结论，也不代表求解器等价、绝对准确度、Candidate或Formal。
- 旧A/B/C/D四臂合同已由上述三模式实验取代；5 eV独立源不再被解释为一种轴向加速方式。
- RF四极杆离子光学→单次反射oaTOF的0 mm direct-mating和1 mm grounded-connector profile已用同一
  冻结N=100源完成真实COMSOL→SIMION重跑；源身份、五级census和四组离散粒子事件集合均与只读
  migration oracle精确一致。零物理变化的功能迁移已闭合；连续相空间、场、分辨率、数值收敛及
  Candidate/Formal资格均未由此建立。

## 资格边界

| 对象 | 当前证据 | 当前资格 |
|---|---|---|
| 圆柱家族三模式 | 三个N=100 baseline均双求解器100/100；无加速空间/时间矩阵完成；两加速模式COMSOL空间档资源受限 | 三模式功能分类闭合；连续数值资格仍INCONCLUSIVE |
| 接口就绪输运 | v1双端100/100及严格相空间比较FAIL | 历史有效负结果；v2重跑待完成 |
| RF+DC质量过滤 | L0/L1及v1双求解器功能扫描 | v2商业重跑与分辨能力资格待完成 |
| RF四极杆离子光学→单次反射oa-TOF pre_pulse_interface_transport/pulse_capture/analyzer_transport | 当前integration入口下0 mm/1 mm同源N=100真实重跑与oracle离散等价PASS | 零物理变化功能迁移闭合；连续量、stage资格与整机Formal仍未评价 |
| 机械/CAD/Formal | 无当前正式机械闭环 | BLOCKED |

`Static`门禁当前可用；workflow blocking profile按各自声明执行；`Formal`在机械几何、CAD装配同步和
完整复验前固定拒绝执行。

## 机器权威与隔离边界

活动求解器物理入口为具名design profile编译的完整request/resolved发布：

- 官方传输与接口：`../config/resolved_design_official.json`；
- 圆柱家族机械base、typed电气模式与三profile：
  `../config/requests/baseline.json`、`../config/operating_modes.json`与
  `../config/design_profiles.json`；
- 家族N=100/N=1000母样本：`../config/particle_source_profiles.json`；
- N=100数值矩阵、acceptance、effect-resolution和engineering-budget：
  `../config/family_experiment/n100_convergence_preregistration.json`及同目录资格合同；
- 暂时下游工程推进判据：
  `../../../common/multipole/engineering_progression_acceptance.json`；
- 无加速混合网格粒子收敛活动：
  `../config/family_experiment/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json`
  及其独立budget；它不改写既有冻结预算；
- 质量过滤：`../config/resolved_design_mass_filter.json`；
- 接口就绪、质量过滤和旧同求解器比较的COMSOL数值：
  `../config/comsol_solver_numerics.json`；
- 三种家族电气模式各自的N=100 baseline/spatial/temporal及N=1000 runtime：
  `../config/runtime_profiles.json`唯一绑定
  `../config/multipole_transport_comsol_solver_numerics.json`；
- SIMION数值：`../config/simion_solver_numerics.json`；
- frame、事件、各具名物理面和状态schema：`../config/interface_contract.json`；
- oaTOF集成oracle专用出口端口：
  `../config/interfaces/provided/rf_multipole_exit.json`；
- execution profile：`../config/execution_profiles.json`。

`../config/project.json`的注册身份由全部design profile的一致identity给出，不再绑定
`../config/baseline.json`。该旧文件仍由尚未迁移的专用workflow只读消费且不接收新参数。科学mode
不覆盖resolved物理量，runner CLI不暴露任意resolved、RF/DC、几何、轴向加速或数值标量路径。缺失
绑定必须在商业软件启动前失败关闭。

当前出口端口只绑定`official_transport`矩形参考外壳及pre_pulse_interface_transport/pulse_capture/analyzer_transport oaTOF集成oracle。其
`profile_scope.family_experiment_port=false`，不得解释为四、六、八极杆统一圆柱机械族的实验端口。

两份COMSOL numerics合同不是同一workflow的双重权威：旧专用合同只服务接口就绪、质量过滤和其
同求解器比较；multipole transport合同只经runtime profile服务公共L3传输三模式。消费者不得跨读，
也不得通过自由profile参数在两套作用域间切换。

接口输运、质量过滤、无碰撞回归与轴向加速各自冻结role、claim、输入、输出、schema和provenance；
它们可复用配置编译、SIMION启动、run生命周期、粒子规范化和分析内核，但不得互相消费run或通过
`Mode`分支切换科学声明。

## 当前参考参数

精确值只以机器合同为准。用于识别当前设计的摘要为：

| 项目 | 当前参考 |
|---|---|
| 极数/杆数 | 四极、4根圆杆 |
| 场半径 | 4 mm |
| 杆长 | 79.6 mm |
| 圆柱家族杆半径比 | 0.5 |
| 家族轴向面 | release −1.5 mm；handoff 80.6 mm；near census 81.1 mm |
| RF | 两组杆反相，1.1 MHz；峰值及DC由resolved发布 |
| 家族样本 | 公共2 eV N=100为N=1000精确前缀 |
| 三种电气模式 | 全0 V；分段杆0/−1/−2/−3 V且出口板−3 V；杆全0且出口板−3 V |

这些摘要不能用于重建模型；求解器必须读取resolved与数值合同。

## 当前活动能力

### 轴向加速

当前三模式只允许typed operating-mode registry中的电气差异，严格共享圆柱机械base、RF和粒子母样本。
项目已补齐与六极杆同语义的无加速混合网格COMSOL三个arm：`0.25 mm/160`参考、
`0.20 mm/160`空间加密和`0.25 mm/80`时间粗档。这里只迁移网格机制和比较设计，不继承六极杆结果；
六极杆混合源下游A/B在2026-07-30满足预注册扩展规则后，只授权首个`0.25 mm/160`参考arm，
用于生成四极杆oaTOF source revision；该参考run
`20260730_231700__sim__comsol__quad-noacc-hybrid-exit025-t160__r02`为100/100传输。接入固定oaTOF链后
得到`100→86→30→30→7→7`，相对旧COMSOL源只有crossing/hit各增加1；30个共同局部出口粒子的
位置、速度、时间、能量RMS差分别为0.2606 mm、469.6 m/s、0.03649 µs和17.36 eV。空间和时间arm仍
未授权；这些差异只证明source revision敏感性，不授予收敛、精度或资格结论。
基线pilot后登记的v2空间敏感性pair已经完成：COMSOL局部`0.5→0.35 mm`的RMS半径相对变化约
`0.92%`，SIMION全局`0.4→0.3 mm`约`9.57%`；两者的100个RF-on粒子身份和功能分类均保持一致，
但这些连续量没有来源充分的误差预算，仍为`INCONCLUSIVE`。空间结果后、时间档运行前登记的v3
只授权的无加速N=100时间敏感性pair也已完成：COMSOL固定`0.35 mm`的`80→160`步/周期使RMS半径
变化约`0.20%`，SIMION固定`0.3 mm`的`40→80`步/周期约`0.034%`。最终两求解器的功能分类和
全部传输粒子身份闭合，RMS半径诊断差约`3.59%`；连续相空间仍不能贴数值等价PASS。实测最大值为
592.194 s、1.031 GB瞬态目录、8.808 GB进程树内存，零自动重试。分段杆轴向加速N=100 baseline
已在两求解器完成并保持100/100传输与精确粒子身份；SIMION空间档也保持100/100和精确身份。
2026-07-31无加速定向跟进进一步完成SIMION A/R/Z/I/T五臂和COMSOL局部0.20 mm的160→320步时间
pair。SIMION径向/轴向RMS半径变化为`2.597%/0.246%`，I→T为`0.00595%`且只在固定分箱下稳定；
COMSOL时间变化为`0.0807%`但仍有粒子跨固定分箱。功能仍100/100，连续结论保持
`INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`；机器身份见
[`followup_result.json`](../config/family_experiment/no_acceleration_followup/followup_result.json)。
随后唯一授权的无加速COMSOL N=1000 bridge在7200 s执行边界前完成760106单元网格和2635598
自由度静电场，但逐粒子`ReleaseFromDataFile`只构造到746/1000，未进入粒子求解，也没有出口状态。
该run已终结为`interrupted`，746份release日志以校验清单保留；campaign结论为
`EXECUTED_INTERRUPTED_INCONCLUSIVE`且关闭自动重试。机器状态见
[`preregistration.json`](../config/family_experiment/no_acceleration_n1000_comsol_bridge/preregistration.json)。
为降低大样本release构造开销而登记的单节点向量化phase释放在N=100 v3中完成真实COMSOL运行，
但未通过预登记的实现等价门禁：RF-on虽仍为100/100且终态分类精确一致，仍有1个粒子跨y分箱、
8个跨发散角分箱、5个跨能量分箱；最大连续差分别达到0.00909 mm、0.398°和0.00724 eV。
候选用时312.606 s，旧逐粒子release参考为312.020 s，且峰值进程树内存略高，因此没有N=100
性能收益。该路线固定为`EXECUTED_NOT_EQUIVALENT`，不得推广到N=1000；生产和既有profile继续使用
逐粒子`ReleaseFromDataFile`语义。机器判定见
[`preregistration_v3.json`](../config/family_experiment/vectorized_release_validation/preregistration_v3.json)。
COMSOL首次空间档在`MESH_COMPLETE`
后以17.752 GB超过原17.180 GB进程树帽而失败关闭，当时系统仍有11.35 GB可用。预算v7保留
8.59 GB系统可用内存底线、把进程树帽调整为21.475 GB后，唯一人工替代运行仍升至21.835 GB，
同时系统可用内存降至7.653 GB。COMSOL空间收敛因此为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`；
不再抬高内存帽。出口孔板加速N=100 baseline已在两求解器保持100/100传输和精确粒子身份，
SIMION空间档也保持100/100和精确身份；COMSOL空间档在`MESH_COMPLETE`后以17.454 GB超过
17.180 GB进程树帽，记为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`。结合分段杆替代运行已证明
继续抬帽会触及系统内存底线，本模式不再重跑。当前无商业求解器授权。功能分类使用已有
`functional_transport_acceptance.json`；连续相空间与minimum relevant effect仍缺少下游依据，必须保持
`INCONCLUSIVE`。现有三个N=100 baseline已在2026-07-29发布两个求解器各一份
`POSTHOC_DESCRIPTIVE` binding和报告；它们不计算bootstrap、不评价资格，只提供同一观察面上的
方向性点估计。正式three-mode dispersion binding仍须由运行前冻结完整统计设置的新实验发布，
禁止把事后报告升级或占位伪造。
完整运行身份和诊断值登记在
`../config/family_experiment/n100_no_acceleration_qualification.json`。
分段杆轴向加速的运行身份、功能结论和资源失败链登记在
`../config/family_experiment/n100_segmented_rod_axial_acceleration_qualification.json`。
出口孔板加速的对应记录在
`../config/family_experiment/n100_exit_aperture_plate_acceleration_qualification.json`。
2026-07-31声明式SIMION H15 N=100三模式对照中，出口孔板加速相对无加速把中心化空间/角RMS降低
`0.0788 mm/2.5445°`；相对分段加速，空间RMS低`0.0076 mm`，但角RMS高`0.8558°`。统一九臂证据见
[`../../../docs/history/20260731__multipole-three-mode-h15-n100.md`](../../../docs/history/20260731__multipole-three-mode-h15-n100.md)；
该结果只用于工程取舍，不改变数值资格。统一图组和机器摘要已发布为成功analysis run
`20260731_223000__analysis__python__multipole-three-mode-h15-n100`，不再依赖scratch。
同日另以当前ACTIVE六指标工程合同正式评价无加速T→H15相邻横向加密：质心位置、中心化空间展宽、
平均方向、中心化角展宽、平均能量和中心化能量展宽差依次为`0.008413 mm`、`0.000188 mm`、
`0.250108°`、`0.142313°`、`0.002427 eV`和`0.000739 eV`，机器结论为`PASS`；analysis run为
`20260731_223200__analysis__python__quad-simion-t-to-h15`。它只允许工程推进，数值收敛仍为
`DEFERRED_NOT_WAIVED`。包含本项目在内的家族18项既有比较也已按ACTIVE合同重分析为18/18 PASS，
统一记录见
[`../../../docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md`](../../../docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md)。
随后统一oaTOF屏蔽罩终端H15 campaign完成9/9；四极杆无加速/分段/终端阶跃的handoff分别为
`83/95/94`，穿过4 mm厚矩形孔后的terminal分别为`31/59/38`。分段模式给出本项目最高terminal透射
`59/100`和最低中心化角RMS`5.7398°`，终端阶跃给出最小handoff中心化空间RMS`0.2737 mm`。
handoff是屏蔽罩开孔外侧切平面入口，不能与terminal混称；完整对照见
[`../../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md`](../../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md)。
这是新矩形厚孔拓扑下的N=100事后工程结果，不可与旧独立末端板H15表作仅模式变化的配对比较，也不
改变数值资格。

### RF+DC质量过滤

质量过滤与接口输运共享机械几何，不共享科学声明。COMSOL和SIMION各自产生单求解器响应；只有
`workflows/mass_filter_reference/compare_responses.ps1`可显式消费COMSOL、SIMION与L1三个成功run。
跨求解器容差尚未冻结时，比较只能报告`NOT_EVALUATED`，不能宣称数值闭合。

### RF四极杆离子光学→单次反射oa-TOF连接

活动合同为`../config/rf_to_oatof_pre_pulse_passive_connector.json`、
`../config/rf_to_oatof_pulse_capture.json`、公共解析后的连接合同及共享物理端口合同。唯一累积入口为
[`../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/execute_integration.ps1`](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/execute_integration.ps1)。
四、六、八极杆同源功能闭合只使用同一integration的
[`workflows/family_source_closure/execute.ps1`](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/workflows/family_source_closure/execute.ps1)；
内部phase不构成公开入口。公共resolved connection决定器件pose和接口面，
共享端口决定法向、孔径与公共电位，pulse_capture合同决定frame、clock epoch和目标物种；任一身份冲突失败关闭。
多极杆自身的源释放面、出口孔穿越面、规范交接面和近接口统计面仍按公共multipole术语区分；pre_pulse_interface_transport/pulse_capture/analyzer_transport
连接模型中的下游部件面不能反向改名或合并这些上游事件面。

当前功能漏斗、诊断run ID和关闭过程不在本文件重复，统一从同日history快照追溯。单次反射oa-TOF Formal MPH、
SIMION包与SolidWorks装配均未被该候选链修改。
oaTOF handoff、pulse_capture local-exit和legacy迁移仍分别保留其项目专用坐标、事件及迁移语义，但canonical
component-state写出与即时校验统一调用公共合同入口，不再维护项目私有列序或序列化实现。

## 开放任务

1. 若需声明束斑、发散、TOF、能量或逐粒子相空间等价，先为目标效应预注册独立误差预算，再完成
   相应连续量数值资格；不得从当前传输分类PASS外推。
2. 若批准混合网格粒子收敛活动，严格按预登记的参考、空间、时间顺序执行；任一资源或结构门禁失败即停止。
3. 为RF-only、RF+DC及三模式轴向实验分别建立不互相替代的Candidate证据包；不得以功能run晋升。
4. 将当前圆柱机器base升级为机械/CAD权威，补端部、屏蔽、馈通、装配与GUI/CAD同步，再开放Formal门禁。
5. 若恢复RF四极杆离子光学→单次反射oa-TOF接口资格工作，先单独批准目标与指标，再完成连接场数值资格、N=1000、
   脉冲/时间步收敛、分辨率、容差及机械装配；当前功能链不自动进入该阶段。
6. 若恢复碰撞冷却，必须从当前共享几何和新碰撞合同建立独立workflow，不恢复旧150 mm脚本。
7. 迁移仍消费旧`baseline.json`的专用workflow；完成前只读保留，不把该文件重新接入项目注册身份。
8. SIMION 2026 `.wgem`仍受许可证限制，活动路线使用已验证的SIMION 2020 legacy-GEM；许可证与
   跨工作区模板可移植性由公共multipole文档统一跟踪。

每项关闭时把过程和完整run清单迁入日期化history；本节只保留未完成动作、进入条件和关闭条件。

## 产物与历史

活动产物位于`artifacts/projects/rf_quadrupole_ion_optics/`。run三件套与manifest保存完整输入、
结果和证据身份；本文件不复制全部run ID。2026-07-28以前的实现目录清单、数值表、诊断失败链和
既有开放任务原文均冻结于`history/20260728__pre-document-consolidation-*.md`，不得用其“当前”
覆盖本文件。
改名前证据继续只读保存在`config/project.json`登记的legacy artifact根，不搬入活动根、不改写旧
manifest、不追加新run，并保持原身份、状态与声明边界。

无碰撞L3薄wrapper默认使用根README定义的`compact`产物保留类；数值资格或GUI复核需要MPH、PA解阵列
或完整轨迹时，必须在运行前显式选择非compact类并写明理由。该设置只管理产物，不是数值或资格参数。
