# RF四极杆离子光学项目状态

本文件是项目当前事实、资格边界和开放任务的唯一权威。实现步骤分别见[`COMSOL.md`](COMSOL.md)和
[`SIMION.md`](SIMION.md)；共享多极杆状态只引用
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)。2026-07-28以前的完整
run编号、故障链和关闭过程冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 当前结论

- 分段杆轴向加速和出口带孔接口板加速（历史简称“端面加速”）曾完成四、六、八极杆COMSOL与SIMION
  N=100功能复验；这些run早于request/resolved schema v2，现只作为
  [`family_contract.json`](../../../common/multipole/family_contract.json)中的`superseded_evidence`
  保留，不构成当前功能PASS。
- 四极杆具名`explicit`非等长、非等间隙、非线性逐段电势案例也只有v1双求解器N=100历史功能依据。
  默认参考仍为`uniform`四段，但两者都须按v2重跑后才能恢复功能资格。
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
  极杆共同的2 eV N=100/N=1000母样本。N=100空间/时间三档已经预注册，但尚未运行商业求解器，
  因而当前仍无数值收敛、跨求解器等价、机械、Candidate或Formal PASS。
- 旧A/B/C/D四臂合同已由上述三模式实验取代；5 eV独立源不再被解释为一种轴向加速方式。

## 资格边界

| 对象 | 当前证据 | 当前资格 |
|---|---|---|
| 圆柱家族三模式 | 共享base/source及N=100数值矩阵已预注册；无新run | INCONCLUSIVE；商业运行未授权 |
| 接口就绪输运 | v1双端100/100及严格相空间比较FAIL | 历史有效负结果；v2重跑待完成 |
| RF+DC质量过滤 | L0/L1及v1双求解器功能扫描 | v2商业重跑与分辨能力资格待完成 |
| RF四极杆离子光学→单次反射oa-TOF S2/S3 | v1真实孔/连接器/脉冲累积链贯通 | v2重跑待完成；stage与整机BLOCKED |
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

`../config/baseline.json`只承担尚未迁移的注册兼容，不接收新参数。科学mode不覆盖resolved物理量，
runner CLI不暴露任意resolved、RF/DC、几何、轴向加速或数值标量路径。缺失绑定必须在商业软件启动前
失败关闭。

当前出口端口只绑定`official_transport`矩形参考外壳及S2/S3 oaTOF集成oracle。其
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
COMSOL预注册为空间档局部`0.5→0.25 mm`，时间档在已选`0.25 mm`细网格上将`80→160`步/周期；
SIMION为空间档全局`0.4→0.2 mm`，时间档在已选`0.2 mm`细网格上将`40→80`步/周期。acceptance与minimum relevant effect缺少下游依据，结果必须为
`INCONCLUSIVE`；engineering budget尚缺wall-clock和内存上限，商业运行当前未授权。正式
three-mode dispersion binding只能在真实三模式handoff文件及SHA产生后发布，禁止占位伪造。

### RF+DC质量过滤

质量过滤与接口输运共享机械几何，不共享科学声明。COMSOL和SIMION各自产生单求解器响应；只有
`workflows/mass_filter_reference/compare_responses.ps1`可显式消费COMSOL、SIMION与L1三个成功run。
跨求解器容差尚未冻结时，比较只能报告`NOT_EVALUATED`，不能宣称数值闭合。

### RF四极杆离子光学→单次反射oa-TOF连接

活动合同为`../config/rf_to_oatof_s2_passive_connector.json`、
`../config/rf_to_oatof_s3_pulse_capture.json`及共享物理端口合同。唯一累积入口为
`../tests/cross_solver/run_s3_cumulative_chain.ps1`。S2 resolved registration决定器件pose和接口面，
共享端口决定法向、孔径与公共电位，S3合同决定frame、clock epoch和目标物种；任一身份冲突失败关闭。
多极杆自身的源释放面、出口孔穿越面、规范交接面和近接口统计面仍按公共multipole术语区分；S2/S3
连接模型中的下游部件面不能反向改名或合并这些上游事件面。

当前功能漏斗、诊断run ID和关闭过程不在本文件重复，统一从同日history快照追溯。单次反射oa-TOF Formal MPH、
SIMION包与SolidWorks装配均未被该候选链修改。

## 开放任务

1. 按根[`COMPONENT_CONNECTION_ARCHITECTURE.md`](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)
   把当前S2/S3迁移为项目端口、公共编排器和connection profile，实例ID固定为
   `rf_quadrupole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`；新旧等价复验通过前保留
   当前活动链，不在本项目复制六/八极杆连接。
2. 若需声明束斑、发散、TOF、能量或逐粒子相空间等价，先为目标效应预注册独立误差预算，再完成
   相应连续量数值资格；不得从当前传输分类PASS外推。
3. 为RF-only、RF+DC及三模式轴向实验分别建立不互相替代的Candidate证据包；不得以功能run晋升。
4. 将当前圆柱机器base升级为机械/CAD权威，补端部、屏蔽、馈通、装配与GUI/CAD同步，再开放Formal门禁。
5. 若恢复RF四极杆离子光学→单次反射oa-TOF接口资格工作，先单独批准目标与指标，再完成连接场数值资格、N=1000、
   脉冲/时间步收敛、分辨率、容差及机械装配；当前功能链不自动进入该阶段。
6. 若恢复碰撞冷却，必须从当前共享几何和新碰撞合同建立独立workflow，不恢复旧150 mm脚本。
7. 迁移`config/project.json`仍指向旧`baseline.json`的注册兼容，并审计剩余
   `finite_3d_transport.json`快照消费者；完成前只读保留。
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
