# RF 四极杆项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。活动官方源为`official_fixed_100.ion`。分段杆轴向加速和端面加速
已经分别通过COMSOL与SIMION N=100功能复验，四项来源run由
[`family_contract.json`](../../../common/multipole/family_contract.json)冻结。该PASS不授予网格收敛、
跨求解器数值等价、机械或Formal资格。

轴向加速合同已升级为schema v2：默认`axial_acceleration_reference.json`继续使用`uniform`四段参考，
另可通过COMSOL/SIMION公共runner及本项目薄wrapper的`AxialAccelerationContractPath`显式选择
`explicit`逐段合同。新增非等长、非等间隙和非线性电势案例已在两个求解器完成N=100功能复验；
它不替换默认uniform工况，也不提升Candidate、机械或Formal资格。

同一参考四极杆几何承载RF-only传输与RF+DC质量过滤两个已区分的功能模式。求解器无关L1扫描使用
当前79.6 mm杆长和4 mm场半径，理论通带为99.328～103.412 Th，N=256扫描半高通带为
99.5～103.0 Th。迁移前RF-only、稀疏质量扫描和分段加速小样本数值只保留在
[`history/20260723__pre-n100-multipole-functional-evidence.md`](history/20260723__pre-n100-multipole-functional-evidence.md)，
不构成当前Candidate证据。

粒子输入序列化、canonical状态校验和PowerShell run生命周期现由根`common/simion/`与
`common/contracts/`提供；项目内旧入口仅保留兼容包装，不再维护第二份实现。
多极杆公共基础层现已冻结为功能baseline；四极杆继续消费公共杆阵列、RF/DC合同和状态边界，
Mathieu质量过滤、方形出口罩与oaTOF连接仍是本项目专属职责，不因冻结而上移到公共层。

Phase 2已增加求解器无关设计请求与优化治理配置。当前请求锁定本项目`n=2`、4根电极的身份，并把
现有`r0/圆杆比/杆轴向范围`、矩形参考外壳及真空域、矩形孔连接接口、canonical驱动和uniform四段
参考放在同一编译输入中。变量目录的34个数值边界直接指向请求JSON pointer；外壳model和连接器shape
作为受支持且锁定的拓扑约束，不伪装成连续变量。该配置只具备静态编译资格，尚未把任意候选同步到
现有商业求解器或CAD入口。

Phase 4已把求解器入口收口到[`../config/design_profiles.json`](../config/design_profiles.json)：
官方传输与接口就绪共用一个完整非分段request，质量过滤使用独立完整request。公共runner不再接受
任意resolved路径、连接器长度、轴向加速或RF/DC物理覆盖；未绑定evidence contract时只能报告
`UNQUALIFIED`。

RF→oaTOF连接功能任务已经收口。默认1 mm被动连接器的N=100累积S3漏斗为
`100 RF出口→61 oa入口→31脉冲时活动→31局部加速器出口→7探测命中`；0 mm直接共面兼容案例为
`100→77→39→39→9`。两者使用同一统一入口、共享时钟和有限1 µs脉冲，只证明功能和数据链贯通，
不是S2/S3资格PASS、传输率优化、分辨率闭合或Formal整机连接。

该活动链的S3机器合同已升级为schema v2并收紧权威边界：S2 resolved registration唯一决定器件pose、出口/入口面和间距；
共享物理端口唯一决定面法向、孔径与0 V公共参考；S3合同唯一声明`oatof_global`、
`instrument_clock_epoch.v1`及目标`mass_amu + charge_state`调度选择。调度器只从真实S2 oa入口事件派生
脉冲时刻，禁止投影位置、重置时间或把端口中心默认为坐标零点；canonical粒子ID、species ID、质量和
电荷在COMSOL局部出口到SIMION row map之间逐ID复核。COMSOL只发布求解器局部terminal census；冻结的
`analysis/build_s3_local_exit_component_state.py`再以同ID连接来源canonical身份和出口状态，直接复用公共
28列顺序、validator及粒子物理公式生成并立即验证局部出口canonical CSV。任一frame、epoch、表面、孔径、
电势、物种或行映射冲突均在运行或分析前失败关闭。此收紧不改变既有几何、场、脉冲参数和历史功能数值。

面向集成的N=100四极杆接口候选在两个求解器中均100/100传输，但出口束斑、发散和均能未满足暂定
相空间一致性目标。因此独立四极杆的严格跨求解器接口仍为FAIL；该结论与已完成的RF→oaTOF功能链
分别回答“求解器是否一致”和“系统能否贯通”，不能互相替代。

跨求解器分析现已拆成两个不可切换的声明入口：无碰撞部件回归只消费
`transport_no_collision`证据并要求完整handoff；接口就绪只消费
`transport_interface_readiness`证据并遵循接口合同的最低样本量和相空间目标。二者共享不含求解器、
mode和阈值的粒子事件计算内核，但分别发布schema v2结果；集成消费者必须同时显式提供两份结果，
不再接受旧版混合报告，也不能用粒子数隐式切换结论。

### RF→oaTOF当前活动入口与资格边界

当前活动机器合同为[`../config/rf_to_oatof_s2_passive_connector.json`](../config/rf_to_oatof_s2_passive_connector.json)
和[`../config/rf_to_oatof_s3_pulse_capture.json`](../config/rf_to_oatof_s3_pulse_capture.json)，累积执行入口为
[`../tests/cross_solver/run_s3_cumulative_chain.ps1`](../tests/cross_solver/run_s3_cumulative_chain.ps1)。候选COMSOL
几何已经真实切出`1.0×0.9 mm` oaTOF侧孔；1 mm案例包含独立接地圆柱连接器真空域，0 mm案例按同一
合同直接共面。两种拓扑均已参与真实场和N=100粒子求解，不是后处理投影出来的“虚拟孔”。

当前证据层级固定如下：

| 对象 | 已实现/功能证据 | 尚未获得 |
|---|---|---|
| COMSOL侧孔与被动连接器 | 1 mm为`61/100`过孔，0 mm为`77/100`过孔；损失按端壁归因 | 候选功能MPH的GUI重开/Compute、网格与场泄漏资格、最低传输率、机械参数 |
| S3共享时钟链 | 1 mm为`100→61→31→31→7`，0 mm为`100→77→39→39→9`；两条run manifest均为success | 脉冲/时间步收敛、N=1000、分辨率、容差和stage PASS |
| SIMION | 从COMSOL真实局部加速器出口canonical状态续算到只读oaTOF分析器，保持粒子身份、三维速度和全局时钟 | SIMION独立侧孔/连接器几何及连接场等价 |
| CAD/Formal | 无 | 侧孔、连接器、壁厚、法兰和装配同步；Formal asset manifest |

因此“physical port/connector/S3 candidate implemented”和“N=100 functional PASS”成立，但S2、S3与整机
资格仍为BLOCKED，且没有修改oaTOF Formal MPH、SIMION包或SolidWorks装配。活动物理值只由
[`../config/rf_to_oatof_shared_physical_port_joint_geometry.json`](../config/rf_to_oatof_shared_physical_port_joint_geometry.json)
提供；S2是统一S3链的内部被动连接器步骤，唯一累积入口是
[`../tests/cross_solver/run_s3_cumulative_chain.ps1`](../tests/cross_solver/run_s3_cumulative_chain.ps1)。旧阶段
执行器与独立build-only/审计入口已退役；活动关系由
[`../config/rf_to_oatof_interface_stages.json`](../config/rf_to_oatof_interface_stages.json)固定为一个内部
被动连接器步骤和一个公开累积入口。退役证据只在
[`history/20260722_rf-validation-and-s1-integration.md`](history/20260722_rf-validation-and-s1-integration.md)
追溯；既有artifacts不得提升当前资格。

## 资格与系统边界

- 参数链固定为`baseline + particle source + mode + interface → resolved → COMSOL/SIMION`；生成资产和
  结果不得反写机器参数。
- `transport_no_collision`与`transport_interface_readiness`统一使用N=100功能档；后者是在同一硬件上的
  接口资格叠加，不是第二套四极杆。
- `mass_filter_reference`通过L0理论/电压语义、L1有限长度扫描及SIMION、COMSOL有限几何功能扫描；
  尚未完成网格、数值一致性或质量分辨能力资格。
- 碰撞模型尚未建立；旧150 mm碰撞脚本是拒绝执行短桩，不属于当前几何或物理合同。
- 当前S3使用COMSOL局部联合模型和只读oaTOF SIMION Formal场顺序续算，不建立全尺寸联合场、不修改
  oaTOF Formal资产，也不声明求解器交界处的场值连续性资格。

| 层级 | 当前能力 | 当前状态 |
|---|---|---|
| Static | 配置派生、生成资产同步、理论和纯分析测试 | PASS |
| Candidate | 指定mode的双求解器manifest、事件合同和功能比较 | 可执行；严格接口证据为FAIL |
| Formal | 机械正式几何、CAD/装配同步及完整复验 | BLOCKED |

## 机器权威与执行入口

### 接口输运与质量过滤的架构边界

接口输运与质量过滤共享同一四极杆机械模板和SIMION执行机制，但回答不同科学问题，必须保持独立
workflow。两者不得通过`Mode`分支互相切换，也不得互相消费run作为本workflow证据：

| 边界 | 接口输运 | 质量过滤 |
|---|---|---|
| role / claim | `rf_quadrupole_simion_run_config`；canonical接口传输与跨求解器相空间比较 | `rf_quadrupole_simion_mass_filter_run_config`；RF+DC七质量功能响应 |
| 科学输入 | 配对bundle、canonical10实际消费表、对应ION11、source family、distribution、operating point | 显式基础ION11、由质量模式生成的配对多质量ION11与metadata |
| 稳定输出 | canonical `particle_state.csv`、稀疏轨迹、输运summary及接口比较证据 | canonical `particle_state.csv`、`mass-response__simion.csv`、功能metrics与规范图 |
| provenance | bundle等价、表示、粒子族、分布、latent、N及两表示SHA-256 | 基础ION11、生成质量表、质量集合、每质量N及对应SHA-256 |
| 物理发布 | `resolved_design_official.json` | `resolved_design_mass_filter.json` |
| solver numerics | `simion_solver_numerics.json`中的cell、quality、允许RF步数与最长时间；接口mode只保留诊断N和科学判据 | 同一SIMION数值合同；质量mode只保留质量集合、每质量N和功能判据 |
| profile | 只选择接口workflow并绑定来源身份、明确operating point与solver-numerics合同身份 | 只选择质量过滤workflow并绑定基础ION11与solver-numerics合同身份 |

公共机制只有一套：resolved字段到SIMION run config的编译与序列化、完整Lua字段校验、canonical/ION11
源序列化、GEM/PA/IOB启动、run三件套生命周期、SHA-256与冻结manifest复核分别由邻近shared core负责。
dedicated runner只提供上表中的科学差异并调用core，不维护第二份Lua模板、启动器、生命周期或校验器；
shared core也不得按上述role或workflow名称分支。

共享机制按职责单向调用，禁止合并成万能helper：

| 模块 | 唯一职责 | 禁止内容 |
|---|---|---|
| `runtime/simion_run_config.ps1` | resolved/interface/numerics编译、完整Lua合同校验和序列化 | 进程启动、文件冻结、复制、checksum、run生命周期 |
| `runtime/simion_execution.ps1` | 启动GEM/PA/IOB并飞行 | 科学role/mode选择、配置编译、artifact和生命周期 |
| `runtime/comsol_solver_numerics.ps1` | 校验并编译COMSOL数值合同 | 选择科学workflow、启动COMSOL或写run证据 |
| `runtime/analysis_run_lifecycle.ps1` | 为分析run构建最小可移植来源闭包并登记输入 | 选择科学role、阈值或比较结论 |
| `runtime/cross_solver_analysis_lifecycle.ps1` | 编排跨求解器分析包、冻结输入和完成manifest | 粒子统计、科学判据或求解器执行 |
| `runtime/particle_table_identity.ps1` | 校验接口输运两求解器的配对粒子表示身份 | 运行求解器、比较数值结果或改变粒子源 |
| `runtime/run_artifacts.ps1` | RF项目冻结依赖、manifest-bound复制和失败run收尾 | 科学mode选择、求解器启动或结果判定 |
| `common/contracts/run_artifact_support.ps1` | 通用run三件套、冻结复制、hash inventory和manifest | RF/SIMION科学role、mode分支和科学schema |
| dedicated runner | 声明科学输入/输出并顺序调用上述机制 | 直接`Start-Process`、`Copy-Item`、`Get-FileHash`、内联Lua模板或复制生命周期 |

配置模块只能被runner消费，执行模块不得反向调用配置编译器，artifact模块不得调用求解器或读取科学
schema。Lua validator必须检查本次candidate中冻结、实际交给SIMION的`quad_monolithic.lua`，不能只检查
仓库live副本。模块函数白名单、调用方向及上述禁止项属于blocking；生产脚本LOC和两个runner的文本重复
比例只进入report，用于发现再次膨胀，不设置脆弱的固定行数阈值。

权威层次固定如下：

- `resolved_design_official.json`与`resolved_design_mass_filter.json`分别是两个workflow的唯一运行时物理
  权威；mode中为理论筛选保留的同名RF/DC值必须与对应resolved逐字段门禁一致，求解器不得从mode覆盖。
- `interface_contract.json`唯一规定frame、事件、交接面和状态schema；
  `config/simion_solver_numerics.json`唯一规定SIMION cell、RF步数、quality与最长时间，不复制物理驱动
  或科学验收阈值。
- `config/comsol_solver_numerics.json`唯一规定活动COMSOL网格、RF时间离散和最长时间。`baseline`
  是普通interface profile唯一允许的生产数值身份；`time_refined_160`只能由
  `same_solver_numerical_convergence`授权选择。interface mode不再保存COMSOL最长时间、网格或步数，
  runner CLI也不接受数值标量覆盖。schema、role、ID、current状态和重算逻辑SHA-256必须同时匹配仓库
  权威；外部路径不能自授身份。冻结后的PowerShell编译器是唯一profile validator/compiler，MATLAB
  只消费完整`compiled_solver_numerics`并做最小类型/范围防御，同时核对compiled envelope与顶层冻结
  identity/数值镜像；它不理解合同profile注册表或授权选择规则。
- 配对bundle metadata是接口两种粒子表示及其等价关系的权威；质量过滤mode只规定质量集合、每质量N和
  功能阈值，生成的多质量ION11必须在本次run冻结。
- `execution_profiles.json`只绑定workflow身份、输入身份和明确实验变量；路径、run ID、种子等实例值
  冻结进run config，profile不得内嵌resolved中的RF、DC、频率、静态电极或几何标量。
- 静态门禁必须验证入口无`Mode`参数、profile无重复物理标量、shared core无role/workflow分支、两个
  workflow均经同一完整Lua合同编译/校验，并在缺失物理字段时于商业运行前失败关闭。

COMSOL接口入口同样固定为单用途。`tests/comsol/run_transport_candidate.ps1`从冻结的official resolved、
interface contract、interface scientific mode、配对bundle和唯一COMSOL numerics合同在内存编译本次
scientific spec；`comsol/ms_rf_quadrupole_interface_transport.m`复核RF-only、无碰撞、无静态端场及科学
阈值后，才调用workflow中性的`ms_rf_quadrupole_no_collision.m`。共享solver不读取`Mode`、不选择claim或
gate；质量过滤legacy入口只把独立质量case交给同一场/粒子机制，仍保持report-only迁移边界。

COMSOL interface run在创建目录时先写`interrupted`三件套，冻结并验证全部输入后再次复核initialization
manifest；随后才允许LiveLink启动。任一配置、启动、GUI Compute、状态合同或manifest错误都由同一顶层
`catch/finally`写成可复核的`failed`三件套并恢复环境。该生命周期变更只有静态与纯合同回归证据，尚未
执行新的COMSOL求解或GUI复验。

`execution_profiles.json`的两类跨求解器分析也不再用`Mode`切换：普通无碰撞profile固定调用
`verify_no_collision_candidate.ps1`，接口profile固定调用`verify_transport_candidate.ps1`。两者只接收各自
来源run身份；科学合同和数值合同从已验证来源run config及manifest读取，不由比较入口重新指定。

### 架构门禁推广与债务棘轮

架构门禁按workflow inventory逐步升级，不把既有入口一次性变成全库阻断项：

| inventory项 | 当前等级 | 当前审计结论 | 升级条件 |
|---|---|---|---|
| `transport_interface_readiness_candidate` | blocking | dedicated COMSOL/SIMION入口；SIMION共享完整配置、启动和生命周期core；显式绑定operating point与数值合同 | 保持blocking |
| `mass_filter_simion_functional_reference` | blocking | dedicated SIMION入口；与接口workflow复用同一机制core；科学源与输出独立 | 保持blocking |
| `transport_no_collision_candidate` | report-only | 仍直接调用历史`common/multipole`求解器入口；SIMION入口内联数值快照、Lua模板与启动流程 | 迁移为窄dedicated入口、共享core并注册唯一数值合同后升级 |
| `quadrupole_collision_cooling` | report-only / absent | capability为prototype且尚无活动mode或execution profile | 首个活动profile合入前必须完成注册并直接以blocking启用 |

report-only扫描至少列出：workflow声明及科学role、run入口、调用的shared mechanism、物理/数值/源合同
身份、稳定输出schema和provenance。扫描结果采用债务棘轮：已登记的存量finding不阻断，但新增profile、
新入口或扩大既有finding必须失败；修复一项后从allowlist删除，不得恢复。

配置权威注册优先扩展现有`execution_profiles.json`的profile记录，不新增平行“总配置”。注册项只保存
合同身份与唯一权威路径，不复制物理或数值标量；运行时binding必须与注册身份匹配并把实际文件及
SHA-256冻结进run。升级顺序为：inventory覆盖全部活动profile → 新增/修改workflow阻断 →
迁移`transport_no_collision`存量入口 → 所有candidate/static profile统一blocking。prototype且无活动
profile的能力只做存在性报告，直到首次实现。

- 历史人工几何输入：[`../config/baseline.json`](../config/baseline.json)；求解器不得直接消费。
- 官方N=100源：[`../config/official_particle_source.json`](../config/official_particle_source.json)和
  [`../config/particles/official_fixed_100.ion`](../config/particles/official_fixed_100.ion)
- 官方与接口profile共用的解析发布、以及质量过滤解析发布：
  [`../config/resolved_design_official.json`](../config/resolved_design_official.json)、
  [`../config/resolved_design_mass_filter.json`](../config/resolved_design_mass_filter.json)
- 旧`resolved_design_interface.json`仅迁移期保留，不再有活动消费者。上述两份活动发布是器件、接口面、
  驱动、静态电极和粒子源的唯一运行时物理权威；COMSOL、SIMION、L1、
  网格/屏蔽验证及RF→oaTOF空间装配均直接读canonical字段，不允许从baseline、mode或求解器尺寸反推。
- 设计profile注册：[`../config/design_profiles.json`](../config/design_profiles.json)
- 模式：[`../config/modes/`](../config/modes)
- 显式分段功能合同：
  [`../config/modes/axial_acceleration_explicit_functional_test.json`](../config/modes/axial_acceleration_explicit_functional_test.json)
- 三项目共享运行合同：[`../../../common/multipole/family_contract.json`](../../../common/multipole/family_contract.json)
- 事件与交接面：[`../config/interface_contract.json`](../config/interface_contract.json)
- 连接基础合同与拓扑案例：[`../config/rf_to_oatof_s2_passive_connector.json`](../config/rf_to_oatof_s2_passive_connector.json)
  和[`../config/rf_to_oatof_connector_cases.json`](../config/rf_to_oatof_connector_cases.json)
- 执行组合：[`../config/execution_profiles.json`](../config/execution_profiles.json)
- Phase 2设计请求与治理：
  [`../config/requests/baseline.json`](../config/requests/baseline.json)、
  [`../config/design_variables.json`](../config/design_variables.json)和
  [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- 当前累积S3入口：[`../tests/cross_solver/run_s3_cumulative_chain.ps1`](../tests/cross_solver/run_s3_cumulative_chain.ps1)
- 项目总门禁：[`../verify_project.ps1`](../verify_project.ps1)

人工只修改源合同；解析器生成发布文件，MATLAB和SIMION只消费解析结果。求解器不得在缺字段时回退到
硬编码值。跨阶段运行必须显式引用来源manifest，不能从共享结果目录猜来源。

RF局部轴向面固定为：杆端`z=85.4 mm`、组件出口handoff面`z=90.2 mm`、独立传输检测面
`z=95.2 mm`。连接链使用距杆端4.8 mm的handoff面，不使用距杆端9.8 mm的独立检测面。

## 当前参考参数

- 来源几何：SIMION 2020 `examples/quad/quad_monolithic.gem`。
- 总长95.2 mm；杆段`z=5.8～85.4 mm`、长79.6 mm；`r0=4 mm`；圆杆半径4.592 mm。
- 入口孔半径1.2 mm；出口/独立检测器半径3.6 mm；SIMION PA单元0.2 mm。
- 官方粒子：100个100 amu、+1离子；birth 0～0.909091 µs；横向位置±0.05 mm；1.8～2.2 eV；
  绕工作台`+x`的填充5°圆锥。
- 传输波形：两组对置杆`±139.81792 V peak`、1.1 MHz；DC、轴偏置和静态端电极均0 V；无碰撞。
- Mathieu参考：`q=0.7060233`。
- 当前回归数值：COMSOL mesh auto level 1、80 RF步/周期；SIMION quality 10、40 RF步/周期。

IOB位置映射为PA `x→工作台z`、PA `y→工作台−y`、PA `z→工作台x`；速度合同为
`v_comsol=(-vSim_y,-vSim_z,vSim_x)`。位置和速度使用同一冻结右手变换语义，时间不变。

## 已验证能力

### 四极杆回归与接口

| 工况 | COMSOL | SIMION | 当前结论 |
|---|---|---|---|
| N=100严格接口 | RMS束斑0.48370 mm，发散6.43944°，均能1.94555 eV | RMS束斑0.35993 mm，发散4.93210°，均能1.99973 eV | 传输率/TOF PASS；相空间FAIL |

N=100差异从入口边缘注入并在出口边缘放大，主要来自边缘场离散及相位敏感传播。是否继续边缘加密由
下游功能敏感性决定，不能通过调RF参数或选择更接近另一求解器的网格掩盖。

### 质量过滤L0

100 Th参考点为`q=0.7060233010`、`a=0.2298878277`；组间DC差值`45.5260298794 V`，不能把单杆组
相对`−8 V`公共偏置的`22.7630149397 V`误作组间差值。固定`U/V=0.162804703`扫描线的理想稳定区给出
`R_stab=24.8197`。这些值只验证解析理论和电压合同，不构成真实质量峰资格。

### 质量过滤L1与双求解器功能扫描

权威功能run为`20260722_201222__analysis__python__mass-filter-l1__n256`。它按官方源包络固定随机种子，
对94～108 Th以0.5 Th步长逐点推进256个粒子；理论带内最低透过率100%，扫描两端透过率0%，观测
半高边界与理论边界偏差均小于一个扫描步长。当前结论是“同一硬件几何可承载RF+DC质量过滤功能”，
不是“质量分辨率已闭合”或“真实边缘场已验证”。

迁移前SIMION/COMSOL七质量小样本功能扫描只保留在日期化history。当前只据此保留“有限几何入口曾
产生预期质量选择响应”的历史边界，不报告Candidate、质量分辨率或跨求解器数值一致性。

### 可定制分段轴向加速

schema v2显式功能合同把79.6 mm杆长分为`10/20/48.6 mm`三段，段间隙为`0.2/0.8 mm`，三段公共模
电势为`0/-0.7/-3 V`；长度与间隙总和精确守恒杆长。100 amu、+1离子的理论平均输出能量为
`4.997580680 eV`。真实运行结果为：

| 求解器 | 权威run | 传输 | 平均输出能量 (eV) | 对照平均能量 (eV) | 平均增益 (eV) | 相对理论绝对误差 (eV) |
|---|---|---:|---:|---:|---:|---:|
| SIMION | `20260723_230600__sim__simion__rf-quadrupole-explicit-axial__n100__r05` | 100/100 | 5.004724759 | — | 3.002904736 | 0.007144080 |
| COMSOL | `20260723_231100__sim__comsol__rf-quadrupole-explicit-axial__n100__r02` | 100/100 | 5.007312018 | 2.029518929 | 2.977793089 | 0.009731339 |

两次run均只证明同一公共解析合同、分段几何和电势可由对应求解器执行；COMSOL run明确记录
`formal=false`。这些结果没有比较两求解器的网格或逐粒子数值等价，也没有证明当前三段方案优于
uniform四段参考。

显式轴向加速的配对证据入口已进一步失败关闭：旧SIMION `r05`没有物理handoff事件，旧COMSOL `r02`
只导出轴向场开启arm的canonical状态，因此两者仍保留上述N=100功能能量证据，但都被
`axial_acceleration_explicit_paired_diagnostic.json`明确排除在同面配对声明之外。当前公共COMSOL入口
在该显式合同时要求同一次求解分别导出`axial_acceleration_rf_on`和`zero_axial_drop_rf_on`状态；两份
状态必须各自通过canonical合同并在`z=90.2 mm`为全部来源ID提供handoff，随后才生成配对审计和逐粒子
CSV。审计直接消费canonical状态已有的发散角、径向位置和动能列，报告各arm的RMS/p95发散、RMS半径、
平均/样本标准差能量及field-on减field-off逐粒子差，不在PowerShell或分析器中重算求解器物理。该入口
尚未执行新的COMSOL商业求解，故目前没有新的数值结论，也不能据源码变更声称杆内加速已通过同面发散
比较。

### RF→oaTOF累积S3

| 案例 | 间距 | 脉冲起点 (µs) | 粒子漏斗 | 权威跨求解器run |
|---|---:|---:|---|---|
| 默认 | 1 mm | 36.112152843 | `100→61→31→31→7` | `20260724_205559__sim__cross__rf-oatof-s3-end-to-end-gap1__n100` |
| 兼容 | 0 mm | 35.831620768 | `100→77→39→39→9` | `20260722_164341__sim__cross__rf-oatof-s3-end-to-end-gap0__n100` |

真实入口孔为`1.0×0.9 mm`。z向0.9 mm是当前oa耦合理论1.0 mm完整宽度上限的90%设计值；孔径只
裁剪几何通过率，不消除粒子`vz`或保证下游束斑。默认1 mm和兼容0 mm从同一基础合同派生，不能把计数
差直接解释为性能优劣。

canonical接口保存粒子身份、物种、frame、clock epoch、全局时间、三维位置和三维速度；动能、发散、
RF相位和局部历时按需派生。连续束粒子按各自时刻进入0 V预脉冲场，所选物种随后接受一个共享1 µs
脉冲；这不是积累或压缩。

0 mm直接共面时先在精确物理面按孔径分类，孔外粒子直接记为壁损失。孔内粒子暂使用`0.001 mm`下游
数值重启并同步推进启动时刻和三维位置；该值不参与物理几何或通过率判定。

S2/S3运行依赖的中央合同已升级为consumer-scoped schema v2：同一
`config/rf_to_oatof_s2_dependencies.json`按`S2 passive connector`、`S3 pulse capture`和
`S3 end-to-end`声明项目提供方、仓库相对provider根、源码路径及保持原目录结构的run-input快照路径；
仓库公共合同与COMSOL启动包装器使用显式`repository_common`scope，不伪装成项目提供方。RF项目
`Copy-RfFrozenDependency`现可安全创建嵌套快照，并在复制前拒绝provider/source/destination越界、在
复制后核对源与副本SHA-256。oa baseline和COMSOL builder暂时同时生成显式、同SHA的顶层兼容副本，
供MATLAB任务按既有环境变量读取；Python resolver、validator和handoff只使用保持仓库相对结构的nested
snapshot，兼容副本不是第二参数权威。当前S2场/粒子runner已按`s2_passive_connector`筛选依赖，并让
resolver、validator、handoff以及interrupted/success/failed manifest子进程统一从snapshot cwd、
`PYTHONPATH`和`PYTHONNOUSERSITE=1`执行。`New-RfRunPackage`、runner与support装载以及依赖复制本身仍是
snapshot建立前的live bootstrap；冻结完成后才禁止live provider process/module path。该边界已通过
poison与post-freeze失败恢复纯分析测试。S3 pulse capture与end-to-end runner
现已按各自consumer迁移到冻结依赖、来源manifest身份和snapshot Python/manifest闭包；累积runner还会
用end-to-end run内的冻结verifier强校验三阶段manifest。迁移后的1 mm真实链已由统一累积入口在同一
`20260724_205559`时间戳下完成COMSOL S2、COMSOL S3和SIMION E2E商业复验：S2为`61/100`，
S3局部出口为`31/100`，SIMION检测面穿越/命中为`7/31`，E2E manifest为success且12项输出复核通过。
该证据只关闭N=100功能链和snapshot隔离，不授权S2/S3 stage PASS、N=1000、收敛、分辨率或Formal声明。

### S3脉冲前checkpoint派生诊断

求解器无关runner只消费来源S3 run已由manifest冻结的resolved状态和registration，不从当前项目目录
重新解析几何、位姿、frame、时钟或物理参数，也不修改来源run。metrics、逐粒子CSV和图是派生证据，
不是新的参数权威。当前N=100主/对照结果为：

| 案例 | analysis run | 脉冲时刻 (µs) | `出口→schedule cohort→脉冲前活动` | 脉冲前损失 | 活动束斑RMS y/z (mm) | 活动总发散RMS (°) | 活动均能 (eV) | 理想源体积内 | 同ID `Δv_z` RMS (m/s) |
|---|---|---:|---|---|---:|---:|---:|---:|---:|
| gap1主案例 | `20260724_210125__analysis__python__rf-oatof-checkpoint-gap1__n100` | 36.112152843 | `100→32→31` | 39孔壁+30加速器/边界 | 0.745190/0.668777 | 4.062001 | 5.012000 | 3/31 | 188.141225 |
| gap0对照 | `20260723_171419__analysis__python__rf-oatof-checkpoint-gap0__n100__r02` | 35.831620768 | `100→40→39` | 23孔壁+38加速器/边界 | 0.806445/0.830448 | 6.119182 | 5.038705 | 3/39 | 301.439136 |

两案都保留全部100个来源ID，未从指标中删除粒子；活动集合全部属于各自schedule cohort，且各有1个
cohort粒子在脉冲前损失。逐粒子残差以真实COMSOL脉冲左极限状态减去同ID无场弹道预测；明显非零的
`Δv_z`证明当前局部接口输运在脉冲前不能用纯弹道替代。它不能把差异单独归因于RF边缘场、连接器间距
或`0.001 mm`数值重启，也不能把gap1与gap0的不同幸存集合和脉冲时刻解释为受控性能排名。没有网格、
场、时序、N=1000或主动光学扫描，故两案都保持`stage_passed=false`、`formal_gate_passed=false`。

两张重新派生的运行诊断PNG均为2622×1937、189.992 dpi；原生尺寸下标题、frame/平面、单位、损失标记、
物理孔和理想源框可读且无裁剪。面板C现在用蓝色圆点、橙色方点和绿色三角点双重编码x/y/z位置残差，
并提供明确的`Δx/Δy/Δz`分量图例；图例位于无数据区，不遮挡观测。重新派生没有修改来源sim run，
逐粒子CSV与前一版分别保持相同SHA-256，metrics除新run内冻结输入的绝对路径外无数值变化。图审缺口
已经关闭，但该图的生命周期仍是run诊断，不因此成为报告/发表图，也不提升S3或Formal资格。首次
`20260723_164157__analysis__python__rf-oatof-checkpoint-gap1__n100`因未冻结绘图模块依赖而在分析启动前
失败，已保存并复验`failed` manifest；它不具备物理或阈值结论资格。

当前checkpoint诊断合同已升级为schema v2，但没有另建分析或绘图入口。现有runner除成功S3来源manifest
外，还要求调用方显式指定一个成功的end-to-end run，并校验其`source_run_id`、manifest和run config确实
绑定同一S3来源；S2真实oa入口状态、S3局部加速器出口canonical状态、SIMION row map和下游状态均按哈希
冻结进同一派生analysis run。诊断表按`particle_id`贯通`RF出口→S2/oa入口→S3脉冲左极限→局部出口→
探测器`，并把全部来源ID失败关闭地划入互斥穷尽的孔壁损失、脉冲前损失、脉冲后局部出口损失、局部
出口但未命中和探测命中类别；嵌套stage membership另列并统一使用RF出口N为分母，不与互斥结果相加。

运行诊断图仍使用同一checkpoint入口和稳定文件名。几何只从冻结的resolved S2 registration、shared
target-entry surface及物理矩形孔准备；oaTOF baseline particle-source box只作为ideal reference volume
语境，重新按活动粒子计算计数、分母和比例，不解释为物理孔径。各几何面板保持同一已解析变换和等比例，
类别同时使用颜色与marker/hatch，并明确frame、clock epoch、脉冲时刻、单位、N和分母。该源码与合同
增强已由受管run `20260724_210125__analysis__python__rf-oatof-checkpoint-gap1__n100`消费同一
`20260724_205559` S3/E2E来源并冻结为5项输出；stage membership为`100→61→31→31→7`，互斥结果为
`39+30+0+24+7=100`，没有从指标中删除粒子，也没有重新运行求解器。
该增强不增加网格、时序、N=1000、分辨率或Formal证据，`stage_passed`与`formal_gate_passed`仍为false。

## 开放任务

1. 连接功能任务已关闭；不自动进入S4。若恢复接口工作，先单独批准S3资格指标和最低通过率，再决定
   是否需要N=1000、网格收敛、分辨率或公差研究。
2. 研究COMSOL原生接口面或连续真空内部边界初始化，最终删除`0.001 mm`数值重启偏移。
3. 当前RF参考几何没有正式连续接地侧壁；机械半径、壁厚、馈通和CAD同步仍未选择。
4. 碰撞冷却仍是独立后续功能；质量过滤的下一步仅在另行批准后开展网格、稠密质量扫描、数值一致性
   或分辨能力资格，不能复用当前功能PASS代替，也不新建几何项目。
5. 两类轴向加速已完成COMSOL/SIMION N=100功能复验；后续若获批，再比较恒定2 eV、恒定5 eV和杆内
   `2→5 eV`对oaTOF接口的功能比较。仍禁止在handoff处重写速度伪造加速。
6. uniform四段和explicit三段都只是已通过功能复验的参考；分段数量、各段长度/间隙/电势、馈电、
   屏蔽连续性、局部网格和机械实现尚未优化，不得把任一案例当作正式硬件选择。
7. 为生产入口补齐通用异常收尾协议及求解器包装器属于平台任务；第二个项目复用前不提前抽到`common/`。

## 产物与历史

运行产物只进入`artifacts/projects/rf_quadrupole_collision_cooling/runs/<run_id>/`。成功、失败和中断run均
保存根级`run_config.json + summary.json + run_manifest.json`；跨求解器run引用来源manifest，不复制大结果。
同求解器数值比较也只冻结caller显式声明的最小role闭包：无路径来源identity、必要配置/粒子源、小型
结果表及SIMION PA identity inventory；不复制完整source manifest、未消费的MPH、PA本体或日志。

历史只供追溯，不覆盖本页：

- [`history/20260722_rf-validation-and-s1-integration.md`](history/20260722_rf-validation-and-s1-integration.md)：
  RF验证、网格调查和S1集成演进；
- [`history/20260722_rf-mesh-strategy-screen.md`](history/20260722_rf-mesh-strategy-screen.md)：
  已关闭的扫掠网格策略筛选；
- [`history/20260722__rf-oatof-s2-s3-functional-closure.md`](history/20260722__rf-oatof-s2-s3-functional-closure.md)：
  S2–S3连接功能闭环与最终证据；
- [`history/20260723__pre-n100-multipole-functional-evidence.md`](history/20260723__pre-n100-multipole-functional-evidence.md)：
  N=100规范生效前的RF-only、质量扫描和分段加速功能证据。
