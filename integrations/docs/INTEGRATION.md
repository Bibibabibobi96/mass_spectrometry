# 统一装配实施状态

返回[集成入口](../README.md)。本页维护当前入口、有效证据、限制与开放动作，组件自身资格归各PROJECT。
状态截至2026-10-27；原始输入和终态仍以各run的manifest为准。早期阶段见
[迁移证据](history/20261026__assembly-migration-execution-evidence.md)，后续重试和门禁过程可从
[收口前固定版本](https://github.com/Bibibabibobi96/mass_spectrometry/blob/09d7dec5a6802f47df791a3239ed75e5b73321fd/integrations/docs/INTEGRATION.md)追溯；不复制另一套全文快照。

## 当前边界

跨项目工作流已迁到根`integrations/`，声明链路的执行、完整批次恢复和已保存模型导出已有实证。
成功执行、数值等价、物理性能和Formal资格分别判断；负结果与原运行身份不因迁移而改写。

| 当前对象 | 已闭合范围 | 保留限制 |
|---|---|---|
| 同项目两个实例N2 | 独立场、工作台、N100 Fly及默认回放 | held-OFF下0检测，不授予正向物理性能 |
| OA→MR及分段IP→MR | 原ID、完整母群、状态及唯一时钟交接 | 旧OA→MR manifest未完整登记父plan；IP原性能门限仍failed |
| 共同静态场与有限脉冲 | strict PA、CPT原生解、完整输出诊断、分阶段恢复 | 跨后端数值等价未获得，缺失状态不补插值 |
| 保存CPT重开导出 | 100粒子×16时刻，重导出差异0 | 不做Compute，不是中途积分checkpoint续算 |
| 组件工程几何与STEP | N2／IP同源构建、孔槽检查、独立冷导入 | 4处原始电极实体交叠，制造／Formal资格未获 |
| GUI运行状态接线 | MR loader与批处理共用碰撞PA预载；代码检查及微型原生验证 | 按本次获准范围不要求人工打开；不追认旧包已完成人工GUI验收 |

三实例N3额外原生验收已取消，不再续接大场；仅保留已发布carrier、局部原生探针和轻量回归。
未来增加实例、拓扑或物理域须按实际请求验收，不能从准备包、缓存命中或现有功能证据推定任意组合可运行。

## 当前多极杆几何边界

可装配多极杆默认裸杆，显式接地圆柱壳只声明内半径、壁厚和两个物理轴向端面；
入口／出口端盖各自可选，每个只声明孔径半径和厚度，与壳连续相接并共用唯一0 V电极。
独立孔板和透镜归外部提供者；不保留内置出口光学、through模型或1 mm绝缘间隙草稿。
零间隙按实际杆端、接地壳及OA孔口判断，允许独立导体互不接触的组合；发生接触须由配方显式修改几何或间隙，没有统一默认距离。

以下N2、机械出口和分段链结果均绑定原冻结几何、输入及资格，不因提供者升级成为新裸杆结果。
旧四处CAD交叠保留为原几何负证据；新壳体CAD与杆对壳核对的范围见[提供者状态](../../projects/rf_multipole_ion_optics/docs/PROJECT.md#当前组件边界与几何)，不能写为整机修复已验收。
源、粒子母群和唯一时钟保持原身份；配方演进不改写历史运行。

## 装配与公共机制

[配方解析](../README.md#配方解析)冻结完整父配方与组件直接位姿；默认运行其全部实例，局部范围必须显式派生。
当前plan的`layout_only`不表示各求解器已支持任意器件；不支持的组件明确拒绝，不自动选择最新整机。
提供者拥有真实几何、电极与物理端口，装配只绑定实例。源保留原6D、ID、母群、出生时间、上游损失、
RF相位和唯一仪器时钟；换范围不重新投影已记录状态或重新采样源。

| 机制 | 实际边界与权威 |
|---|---|
| 位姿、连接、源和驱动 | [连接与驱动标准](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)，科学时序由工作流冻结 |
| 项目提供者与软件投影 | OA／IP／MR发布实际组件；公共接口存在不授予任意相对角或任意拓扑资格 |
| 独立工作场 | 成员级PA复用、实际电极电压及显式COMSOL投影；场、轨迹和数值资格分开 |
| 阶段与完整批恢复 | [统一恢复规则](../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)；不拼接中断粒子片段 |
| 执行与观测 | [公共调度](../../common/README.md#主机资源实现)，普通预算告警不终止健康求解 |
| 完成事实与终态 | [SIMION适配](../../common/simion/README.md#原生完成事实)与[公共收尾](../../common/contracts/README.md)，不把完成行当科学成功 |
| 母群、事件与统计 | [公共释放](../../common/ion_release/README.md)、[分析函数](../../common/analysis/README.md)；科学分母与判据仍由项目定义 |
| 碰撞生命周期 | IP与冷却入口共用HS1加载／冻结／复位；机制复用不授予碰撞物理资格 |

容量目标和最低空闲保护只读[唯一机器政策](../../common/contracts/artifact_capacity_policy.json)。
预算、实测峰值与数组下限分别记录，不用磁盘空闲代替准入，也不以改变网格或母群迁就旧预算。
首场事务恢复允许上下游尚无发布收据；普通飞行批恢复仍要求两份发布来源。未发布事务不能冒充ready资产。

## 单反射整机

[公开owner](../workflows/single_reflection_flight/run.ps1)接收`-Request -ExecutionBudgetPath`，默认执行完整Fly；
`-FieldDesignOnly`、`-WorkbenchOnly`显式选择有限阶段。内部`execute.ps1`只由owner调用，作者格式见
[schema 9](../workflows/single_reflection_flight/schema.json)。request引用冻结父plan、逐实例提供者、显式数值域与场来源。

普通源和`recorded_pre_pulse_state`共用同一装配；未声明`pulse_decision`时消费全部实际timed pre-state，
声明时保持原选择、顺序与绑定。完整批恢复显式绑定前驱manifest，不扫描最新run、不重飞已完成批或重复求场。
held-OFF由原科学mode派生场依赖，仅省略恒0脉冲响应；完整carrier仍保留真实金属mask，timed／discover保持所需响应。

| 冻结运行 | 有效结果 | 不能据此声称 |
|---|---|---|
| [110745单实例](../../../artifacts/projects/instrument_assembly/runs/20261025_110745__sim__simion__single-reflection-flight/summary.json) | 六工作场、100终态、默认回放差异为空；0检测，终态均non_detector_splat_instance_5 | 实例编号不证明真实碰撞实体，未到反射器不代表整机物理性能通过 |
| [134240双实例](../../../artifacts/projects/instrument_assembly/runs/20261026_134240__sim__simion__single-reflection-n2-topology-resume-n100/summary.json) | 100终态、默认回放passed且differences为空；0检测，均non_detector_splat_instance_3；场全部复用且无Refine | 只关闭声明held-OFF功能、母群和回放一致性，不授予分辨率或任意实例数资格 |

N2三批IOB均通过94点核对；原e9／e44世界点查询仍为非电极，但原节点／实例正确且各有4个相邻完整金属cell。
这是区分离散节点、连续金属和世界点占据的验收，不挪点、不改厚度或期望ID制造通过；零厚理想栅不要求实体体积。
生产正填充采用经过原生检查的严格包含语义，孔操作、提供者body和独立fractional导出保持各自身份。
旧`surface=auto`候选、静态ID审计、Fast Adjust访问冲突与未完成Fly的前驱继续保留failed身份，不能被后继success覆盖。

公共首批实测后按10／50／40粒子、最多两路完成基线和回放；18.45 GiB／worker只属于该冻结工况。
N3薄片局部探针与carrier发布不构成完整场、工作台或Fly验收；额外原生范围已取消。

## 共同场与有限脉冲

[共同静态场owner](../workflows/paired_accelerator_static_field/execute.ps1)消费同一OA-only实体、ON电压、边界、数值box和样点。
`-Request -DryRun`仅准备，原生执行另须`-SolverAuthorized`和显式预算。
`-ComsolSourceManifest`选择已保存prepared或solved来源：prepared只补solve，solved只导出，不重建几何／mesh。
同BVP且原采样、CSV与native facts完整匹配时直接借用原导出，不读取／哈希MPH或启动COMSOL；
采样改变或导出缺失才重开保存模型。已声明损坏的输出不静默回退，模型始终归原producer。

[有限脉冲owner](../workflows/paired_accelerator_pulse/execute.ps1)只接受显式static producer、实录源、绝对观察时刻与numerics；
脉冲、物种、原母群和OFF电压从原权威派生。`-PredecessorManifest`按完成事实复用阶段和完整批，
已发布CSV直接分析，保存模型只补缺失导出。完整输出按原ID与时刻外配对，只发布`diagnostic_only`差异。
有限脉冲`prepare.py`已复用公共`strict_json`读取与数值表示检查，删除私有`_read`／`_number`；
重复键、NaN／Infinity和浮点溢出失败关闭，BOM、有限有符号电压与时间、既有正值数值控制保持原合同。
相同惰性身份fixture下，迁移前后完整plan和17个生成文件逐字节相等；真实prepare入口回归覆盖
重复键、非有限值、bool／字符串和超大整数拒绝，见`test_paired_accelerator_pulse_preparation.py`。
此检查未执行求解器，不改变母群、时钟、+1物种限制或跨后端数值资格。

| 运行或来源 | 有效事实 | 限制 |
|---|---|---|
| 235338与[011244恢复](../../../artifacts/projects/instrument_assembly/runs/20261026_011244__sim__cross__paired-accelerator-static-field/summary.json) | 原ES求解与保存完成；后继115点导出复用并success | 235338整run因终态发布failed，不能改称success；数值等价未获 |
| [042142有限脉冲](../../../artifacts/projects/instrument_assembly/runs/20261026_042142__sim__cross__paired-accelerator-pulse/summary.json) | N100 CPT原生解、初态、1600状态与比较发布success | SIMION609可配对／991缺失；旧输入下的诊断结果 |
| [075124后处理](../../../artifacts/projects/instrument_assembly/runs/20261026_075124__sim__cross__paired-accelerator-pulse/summary.json) | 四项阶段复用，只分析和发布 | native_executed=false，不是缺失CSV时的模型重开 |
| [182314 strict静态场](../../../artifacts/projects/instrument_assembly/runs/20261026_182314__sim__cross__paired-static-strict-reuse/summary.json) | strict PA构建、115点采样；借用原COMSOL导出 | COMSOL原生执行false；新PA成员使SIMION批次失效，不使CPT失效 |
| [184444 strict有限脉冲](../../../artifacts/projects/instrument_assembly/runs/20261026_184444__sim__cross__paired-pulse-strict-reuse/summary.json) | 复用CPT解／导出，只补SIMION基线及默认回放；回放差异为空 | COMSOL1600可用，SIMION500可用／1100缺失；不沿用旧609／991 |
| [190255保存CPT导出](../../../artifacts/projects/instrument_assembly/runs/20261026_190255__test__comsol__paired-cpt-export/summary.json) | 实际重开原保存模型，100×16状态严格差异0 | NoCompute／NoGUI／NoMPHcopy，不是积分中途续算 |

strict对照的最大位置差约X=6.7608 mm、Z=5.90176 mm，数值等价仍未取得。
COMSOL Freeze可保留停止后的状态，SIMION停止后不再输出后续观察；有限状态数量不能直接当存活数。
缺态、错时和全母群损失保留，不插值、删粒子或调整物理容差制造一致。原负结果、模型与资格不改写。

已完成源加载器显式验证export-only consumer绑定的原producer和同BVP，不递归扫描祖先；借用模型沿原容量机制保护。
原042142只测到部分工作集的记录不能冒充完整进程树预算；后继公共观察保护不热装到冻结旧run。
当前来源接线、strict PA、仅后处理及保存模型重开均已有各自证据，不再作为“待首次执行”的行动指令。

## 局部前端执行与复核

[裸导引入口](../workflows/local_frontend/execute.ps1)和[冷却入口](../workflows/cooled_frontend/execute.ps1)
各自接收schema 3请求；冻结完整父plan，默认full或显式local，不复制组件内部几何。
从仓库根替换路径运行；以下最后一条会启动商业求解，须有对应科学运行授权及显式预算：

```powershell
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -ValidateOnly
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -PrepareOnly -OutputDirectory "<managed-run>"
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -ExecutionBudgetPath "<budget.json>" -SolverAuthorized
```

`PrepareOnly`只写调用方已建立的受管run，不能用任意空目录或改变owner。二区／三区分别消费真实提供者，
不能把旧八模式整机场当作裸导引场；位置、机械孔与数值carve分别处理，源保持全部原ID和唯一时钟。

三区[165815迁移对照](../../../artifacts/projects/instrument_assembly/runs/20261022_165815__sim__simion__local-bare-guide-oa/summary.json)
已完成N=100、源与规范事件逐值对照、69出口／31损失及新进程默认回放，差异字段0。
只证明冻结局部工况迁移一致，不授予MR接受、整机分辨率或Formal资格。
冷却[220720运行](../../../artifacts/projects/instrument_assembly/runs/20261024_220720__sim__simion__cooled-frontend-population/summary.json)
复用当前公共七场，原100 ID闭合为32出口、36 timeout、32未解析停止，实际峰值并发13；未Refine或复制PA。
其`saved_controls_only`检查不包含第二次完整Fly，不能写为逐轨迹默认回放；未解析停止不归为碰撞实体。

## OA／IP接口准备与绑定

[accelerator_interface入口](../workflows/accelerator_interface/execute.ps1)拥有跨项目准备与绑定；
OA、IP和MR分别拥有自身设计与科学约束。IP设计必须显式提供schema 3 `-MatchingRequestPath`；
`-FinalizeJointWorkbench`只消费设计run已冻结的父plan、matching request及实际源／场，不回读活动默认。
它会建立／重开IOB和做场审计，**不执行Fly**。完整输入参数以该入口为准。

完整MP／IP／MR父plan可派生IP／MR局部范围；同一完整IP接口同时发布guide_inlet与extraction_exit。
MR-local几何、原IP→MR直接位姿和唯一clock保持，不按锚点反算放置。真实115429准备已完成81粒子源的
IOB保存／独立重开及接口场审计；审计完成不等于物理匹配或边缘场截断资格。

## 已准备IP→MR联合飞行

[prepared_joint入口](../workflows/prepared_joint/execute.ps1)消费`-PreparedJointWorkbenchRunPath`与`-ContractPath`。
同入口`-AnalyzeRunPath`从封存原生日志建立新分析run，不重飞、不复制PA或改写原run。
显式前驱恢复以固定完整批为单位，仅执行缺失批，来源和借用控制文件继续绑定原owner。

[oa_mr入口](../workflows/oa_mr/execute.ps1)要求冻结`-CompositionPlanPath`及可选`-LocalScopePath`；
当前支持唯一OA轴向出口→MR入口及相对identity rotation，MR可随父装配共同平移／旋转。
当前提供者为含20电极的完整MR分析器，不再是单入口框。机械1.5 mm接口、源、实际场和直接位姿分别核验。

| 冻结链 | 有效事实 | 身份与资格限制 |
|---|---|---|
| OA→MR 173601 | 100唯一终态、98检测、2电极碰撞、0timeout；10＋90两批，复用静态场 | 原summary复用批数−1保留；不能据此授予任意相对角或Formal |
| 183641、184345两代恢复 | 均0执行／2复用，保持100终态及98／2分类，永久批计划可读 | 不重建IOB、不Fly、不Refine；不改原记录 |
| IP→MR 093701 | 100母群／97交接，23检测、74下游损失、3上游未交接 | 该轮曾隐式Refine，不能称零Refine |
| IP→MR 192240 | 复用115429准备及81交接群，20检测、61下游损失、19上游未交接；无自动Refine | 97群与81群来源不同，幸存者峰宽不是整束性能 |

**旧173601／183641／184345的manifest未完整登记已消费的父plan及local-scope，不能追认配方身份已完整绑定。**
当前owner已补齐永久输入角色及篡改拒绝；修复不改变旧场、源、位姿、飞行结果或manifest。
统计使用最终批计划；完整批恢复按前驱manifest的显式角色定位，不能使用已退出的执行alias。

分段链084802八极杆真实机械出口→095324 IP→115429准备→192240 MR，经25项祖先复核和28份小记录身份核对，
100→81→20检测／61下游损失／19上游未交接的原ID集合互斥闭合。源、母群、ordinal、clock／epoch与绝对时间保持；
初态6D仅有既有序列化口径内的末位差。它关闭声明的分段功能与时钟验收，不必重复同一N100。
交接面为`recorded_stop_plane_not_physical_port`，不表示真实孔面之间连续场／轨迹等价，IP原门限failed保留。

## 真实多极杆→IP状态交接

[multipole_ip入口](../workflows/multipole_ip/execute.ps1)只准备真实出口到接收方的状态交接，
schema 2请求显式引用来源／接收manifest、冻结父plan与可选local。保留原6D、物种、出生／到达时钟及母群；
接收方设计与驱动继续归IP，不以旧出口分布或冷却前端代替真实多极杆源。

100 Da原工况213053：100终态完整，74进入HP、0捕获、0提取，接受检查未通过，无出口群所以未执行MR。
不能把`solver_stop`或径向边界直接命名为实物撞壁，具体机制与联合边缘场仍未获物理资格。
独立524 Da工况095324完成100原ID，81捕获／转移／提取，19未提取；原捕获／提取性能门限仍未通过。
103822及后继192240使用其全部81个真实出口闭合MR交接，保留IP负结果，不重定义母群或改标签为100 Da成功。

## 工程几何与GUI边界

[oaTOF提供者075441](../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261026_075441__test__comsol__geo/summary.json)
完成GeometryOnly保存、独立重开、18项MATLAB Unit及STEP导出：45域／40物理对象，physics／mesh／study为空。
只覆盖完整oaTOF组件，不包含上游多极杆，也不构成SolidWorks或Formal验收。

[093507组件CAD检查](../../../artifacts/projects/instrument_assembly/runs/20261027_093507__test__cad__component-geometry-acceptance/summary.json)
保留394个原世界CSG primitive（385 box、9 cylinder），构建N2两实例74组和IP16组，共90组kernel实体。
直接pose单次投影，IP已世界坐标不二次投影；12孔槽体积遮挡为0。N2／IP STEP冷导入分别74／31对象，
bbox差均0，近似体积差分别−1.6007e-10／+1.4552e-11 mm³。

[几何诊断](../../../artifacts/projects/instrument_assembly/runs/20261027_093507__test__cad__component-geometry-acceptance/results/geometry_kernel.json)
记录冻结旧几何的4处不同native-ID正体积交叠：两个实例各自的shield与exit outercap／exit plate重叠，
每处分别约64.394489／125.770485 mm³。GEM后写拥有相交材料，CAD未做补偿减法或合并电压来隐藏交叠。
`raw_electrode_clearance_qualified=false`、manufacturing／Formal均false；近似体积测量不是制造公差验收。
本轮无mesh／physics／study／Compute／新MPH，也没有重算原仿真。

本次迁移的GUI验收范围按用户更新要求采用实现与代码对等检查，无需实际打开界面。
MR的`load-workbench`与batch Fly共用碰撞PA预载并保持不可Refine状态，见[MR软件说明](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/SIMION.md#事件与分析)。
旧截图失败不再阻断本次代码对等验收；这不追认旧包人工GUI通过，也不将普通PA查询当作Program回调电场。
未来正式资产仍须按[GUI／CAD规则](../../docs/REPOSITORY_ARCHITECTURE.md#gui-与-cad-门禁)完成其适用验收。

## 依赖冻结与门禁

[运行依赖清单](../config/runtime_dependencies.json)与[冻结器](../runtime/dependencies.ps1)按明确owner／consumer复制实际来源。
普通小输入的复制与身份校验统一调用`Copy-VerifiedRunInput`，直接使用其已核验SHA生成来源收据；
集成适配器继续验证提供者边界、显式清单与目标不存在，公共复制失败的实测摘要保留在依赖错误中。
冻结清单已包含PowerShell公共复制入口及直接导入，`prepared_joint`快照可脱离活动仓库继续冻结输入。
源与副本SHA不一致继续失败关闭，报告两条路径及实测摘要，不重试或放宽身份判据；缺依赖不回读活动仓库。
上游只验证实际消费记录，阶段恢复和终态发布复用公共机制。跨父目录执行显式共用同一调度账本。

架构迁移的既有验收见[架构迁移审计](../../docs/history/20261027__repository-architecture-migration.md)；
后续文档与运行边界修复、失败及复验见[系统审查](../../docs/history/20261027__system-maintainability-review.md)。
先前权限、宿主、夹具和发布失败仍按固定源码及原日志解释，focused通过不拼成失败整轮通过。
后续改动按[操作指南](../../docs/OPERATIONS.md#分层门禁)运行适用门禁；软件检查不授予新原生、数值或Formal资格。

## 实施与退出条件

1. 现有声明链路的功能、分段身份与时钟、N2、strict共同场和保存CPT导出已有证据；新输入或新拓扑另验。
2. 保留零检测、100 Da负结果、524 Da IP门限失败及跨后端不等价，不自动扩展为性能优化或更大样本。
3. 工程几何已同源构建和交换，但4处原始交叠未消失；机械无干涉、制造、数值收敛及Formal继续按各自判据闭合。
4. 未请求的N3额外大模型不再续接。科学载荷是否可退役由公共owner、消费者和精确身份决定，不凭run终态或文件年龄删除。
5. 总目标的软件交付以最终提交、适用门禁和独立审查共同确认；本页的局部success不替代完整交付或项目资格。
