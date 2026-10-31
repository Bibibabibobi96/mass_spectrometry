# 统一装配实施状态

返回[集成入口](../README.md)。本页维护当前入口、有效证据、限制与开放动作，组件自身资格归各PROJECT。
状态截至2026-10-30；原始输入和终态仍以各run的manifest为准。早期阶段见
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


`single_reflection_flight/run.ps1` 在科学准备和原生执行前冻结公共 owner 的小执行请求与 run 外 Result，
内部 `execute.ps1` 仅准备、执行与绑定证据；retention、manifest、容量与 seal 由原公共收尾负责。
原入口 `-ResumeFinalization -ResultPath <原result.json>` 不再要求 request／budget，不启动原生程序；
它只恢复已保存的完成事实，不修造缺失 writer 证明，也不改变父 run 终态。

实际 PID／创建身份／退出事实在 exit 或科学 marker 校验前记录；实际 host release 回执独立保留。
未知 writer／未确认 host release 保留资产、容量与执行表示； inherited release 保持真实 null，父租约不被释放。
原科学异常与证据绑定、host、guard、容量及收尾异常分别报告；环境在公共收尾之后恢复。
显式源及其祖先由已绑定 manifest 投影到原容量 owner，不搜索 latest 或跨根猜来源，不重读 PA。

request 的 `verify_saved_workbench_replay` 只能为布尔，默认 false。解析动作冻结到 preparation、runtime
及 workbench，未请求时不要求回放预算、不访问回放父证据、不创建回放目录或第二轮 Fly，状态为 `not_requested`；
显式请求继续执行完整母群与原失败传播。`propagation_scope` 只解释所声明起止，不改变源、场或积分：
记录状态源保留真实体积重启时刻，连续段从快照开始；包含原出生历史时须报告分段接续。
`validation_contract` 只冻结预先声明的判据，准备成功不是求场或科学通过。

该迁移复用既有完整批次 planner、公共 owner 及 HEAD 的兼容 frontend API；不包含全局原生路径投影、
数值 Program／IOB core 的历史再生成或新的场精度资格。111659／121606／192206 等 N100 证据
仅支持其各自冻结代码、粗网格、实际新飞／复用范围；新候选的正常冻结与惰性原生接线另行验证，
不凭旧证据声称当前代码已完成商业求解或完整 GUI 验收。


[公开owner](../workflows/single_reflection_flight/run.ps1)接收`-Request -ExecutionBudgetPath`，默认执行完整Fly；
`-FieldDesignOnly`、`-WorkbenchOnly`显式选择有限阶段。内部`execute.ps1`只由owner调用，作者格式见
[schema 9](../workflows/single_reflection_flight/schema.json)。request引用冻结父plan、逐实例提供者、显式数值域与场来源。

普通源和`recorded_pre_pulse_state`共用同一装配；未声明`pulse_decision`时消费全部实际timed pre-state，
声明时保持原选择、顺序与绑定。完整批恢复显式绑定前驱manifest，不扫描最新run、不重飞已完成批或重复求场。
held-OFF由原科学mode派生场依赖，仅省略恒0脉冲响应；完整carrier仍保留真实金属mask，timed／discover保持所需响应。

工作流内部采用单向依赖：`census`读取原生日志证据，`pulse`派生阶段控制，`continuation`验证父记录并规划
完整批复用，`runtime`物化所需批次；下游发布字段由`downstream_fields`统一验证。各调用保留原母群、
源行顺序、时钟和错误判据；元数据准备不读取PA载荷。已有冻结清单覆盖这些模块，隔离快照可独立导入及执行，
无需新增CLI或恢复状态；这项职责整理不改变科学计算，也不构成性能提升或原生验收声明。

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

局部OA出口的九变量均值与中心协方差调用[公共总体矩](../../common/analysis/README.md)，与IP二变量统计
共用`ddof=0`内核；当前出口群仍按每个原ID等权计算，保留全部出口及既有字段和单位。
这项离线计算收敛不改变原生快照、穿面重建、真实角度定义或历史运行结果。

局部前端的响应选择只验证小收据及其manifest身份、命名、响应集合和大小；PA字节由公共物化入口在
首次消费时完整核验。三个工作点共用同一组从首次核验起持续受护的只读私有副本，输出仍分别新建、核验；
`source_verification_after_native`记录连续源guard的身份确认，不表示再次全文读取。单反射IOB持久副本
沿公共发布入口转交实际目标guard，后续保护复用同一身份；已有产物和独立消费者仍按原边界完整验证。
软件夹具中97 B及8 MiB以上文件的复制／发布／保护均由5次身份全读降为2次；五／六输入的三个工作点
物化夹具分别由23／27次降为10／12次，另验证metadata选择不读PA而仍读取小收据。计数不含复制及原生
composer读取，不代表物理磁盘流量或运行倍速。
[小型真实SIMION三工作点验收](../../../artifacts/projects/instrument_assembly/runs/20261029_062052__test__simion__h1-h2-three-workpoints/summary.json)
已完成：19次CLI正常退出，三个工作点各343节点的potential／mask／grid及两采样点在冻结BASE／NEW间相等，
60次保护探针拒绝写入，源即时和延迟身份不变。小PA日志有尺寸小于11的精度警告；此结果只证明传输／
代数等价和保护，不证明场精度、大PA吞吐、Fly或GUI资格。完整测量边界见[指南验收记录](../../docs/history/20261029__system-guide-complete-review.md#实测收益与边界)。
观察器明确报告直接原生根退出未知时保留该组临时输入，将精确目录附于原异常供owner处理；不执行
输入清理，也不声称PowerShell退出后FileShare句柄仍然保持。

局部OA与IP的穿面适配器直接消费[公共有界穿面内核](../../common/analysis/plane_crossings.py)，
局部OA不再构造IP配置或调用IP穿面适配器。原生事件白名单、instance=1、寿命截断、同刻六维精确去重、
脉冲后选择与原CSV／raw-log锚点仍由局部适配器保持；插值使用原mm／μs字段，z=0只取实测出口。
公共内核只接受相邻记录夹持的正向事件，最大间隔为冻结采样间隔加最大步长，保留1e-12 μs既有判定余量。
出口坐标在旧记录容差内也不能支持越过其实际位置的外推；这种情况保留unknown诊断缺口而非物理损失。
结果的`crossing_reconstruction`记录方法版本与首次穿越选择，不证明未采样区间中没有转折。
冻结清单包含公共内核；脱离活动仓库的局部快照能实际计算穿面，缺该模块时失败关闭。

局部OA共享时刻census接入[公共母群核算](../../common/analysis/particle_census.py)，
保留真实shared-time观测与原32 ULP端点政策；没有支持记录时仍为numerical_unsupported，
不借用IP显示插值，不由缺终态推断存活。legacy already_loss仅指非出口终态，实际图标为Non-exit terminal，
不表示已证实撞壁。分类与出口比例保持完整原始母群及显式分母，缺观测不从分母移除。

束宽、真角度发射度、时间相关与零场预测现直接调用[公共beam方法](../../common/analysis/beam_focus_diagnostics.py)，
不再从IP导入实现。局部源按现有生成合同显式全1权重；这不声明支持外来canonical非等权注入。
固定出口群、各面缺测与全部原始ID保持；场内实际观测和出口后零场反事实继续分开，图只读prepared结果。
图形保存复用[公共导出](../../common/analysis/figure_export.py)，保持原PNG／SVG、190 DPI、白底和文件名，
实际导出记录写入focus summary；不改写其他phase summary，路径冲突或失败不覆盖既有文件。

## OA／IP接口准备与绑定

[accelerator_interface入口](../workflows/accelerator_interface/execute.ps1)拥有跨项目准备与绑定；
OA、IP和MR分别拥有自身设计与科学约束。IP设计必须显式提供schema 3 `-MatchingRequestPath`；
`-FinalizeJointWorkbench`只消费设计run已冻结的父plan、matching request及实际源／场，不回读活动默认。
它会建立／重开IOB和做场审计，**不执行Fly**。完整输入参数以该入口为准。

同一入口的`-FullJoint`显式选择IP完整链，须提供`-IonProcessorRunPath`、
`-ReferenceMrRunPath`、`-ContractPath`，并分别提供新设计的`-MatchingRequestPath`或
已有设计的`-PreparedInterfaceRunPath`、新场的`-FieldRequestPath`或已有场的`-JointFieldRunPath`。
场请求由作者指定局部数值域、surface容量预估及符合仓库规则的新场run_id；各层计算预算沿设计冻结的
参考数值计划使用。入口将replacement assembly路径绑定到
新设计run，再依次调用MR场owner、Finalize及prepared-joint飞行／分析owner。各阶段保留自己的
run和终态；失败输出阶段及各run路径，后续恢复沿对应owner入口进行，不改写前驱。
可将`-ContinuationPredecessorManifestPath`传给prepared-joint整批恢复；已有场仍由Finalize校验与设计和源的身份。
也可直接给`-PreparedJointWorkbenchRunPath`与`-ContractPath`，跳过设计、求场及IOB重建，
由prepared-joint校验原绑定和恢复批次；全部批次有效时不启动Fly。入口输出失败阶段和各阶段／总耗时。
IP源的真实出口为零时，准备run保留完整母群census及源科学状态，结果标记`zero_exit`；
完整链在此停止匹配、求场和Fly，零出口不是物理性能通过。
该模式从显式实测IP源开始，以状态交接而非连续Fly到MR；不能据调度成功声称物理匹配或Formal资格。
准备结果保留设计、场计划与真实源交接；不再生成无生产消费者的独立IP重飞recipe。
仅当实验明确改变上游工作点时才由IP入口产生新实测源，既有状态不会因准备新联合场而重新采样或缩放。

`-FullJoint -MultipoleIpRequestPath`也可从已封存的真实MP出口接续：调用者同时显式提供
`-MultipoleIpRunId`、`-IonProcessorRunId`和`-IonProcessorConfigurationDirectory`，可选
`-IonProcessorFieldRunPath`复用符合IP owner检查的原生场。入口先校验准备run绑定的接收几何与
IP配置，再传递原始母群；MP零出口直接报告并停止。`-ContinueOnIpScientificFailure`只允许
原生与诊断已完整但科学门限未通过的结果继续，执行错误或未知状态仍失败关闭。源request仍显式绑定
MP run、case、接收器、父plan、物种及权重，不能从参考MR或历史结果推测；这是分段状态交接。
该分支恢复IP阶段时使用独立的`-IonProcessorContinuationPredecessorManifestPath <IP原manifest>`，
同时提供原已发布的MP→IP准备RunId、未变请求与接收配置，以及新的IP RunId。
入口复用经验证的源准备，IP owner按原完整分区补缺；不重做已完成批，也不把它称为原生积分checkpoint。
恢复后的源须重新绑定新接口设计，不能混用旧源设计或另一个IP场。下游Fly恢复仍用独立的
`-ContinuationPredecessorManifestPath`；参数和适用边界见[IP恢复说明](../../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md#原批分区恢复)。

完整MP／IP／MR父plan可派生IP／MR局部范围；同一完整IP接口同时发布guide_inlet与extraction_exit。
MR-local几何、原IP→MR直接位姿和唯一clock保持，不按锚点反算放置。真实115429准备已完成81粒子源的
IOB保存／独立重开及接口场审计；审计完成不等于物理匹配或边缘场截断资格。

## 已准备IP→MR联合飞行

[prepared_joint入口](../workflows/prepared_joint/execute.ps1)消费`-PreparedJointWorkbenchRunPath`与`-ContractPath`。
同入口`-AnalyzeRunPath`从封存原生日志建立新分析run，不重飞、不复制PA或改写原run。
两条原CLI的`-ResumeFinalization -RunId <原run_id> [-ResultPath <小Result>]`沿公共PowerShell owner收尾；
默认Result位于`artifacts/projects/instrument_assembly/scratch/workflow_results/<run_id>/result.json`。
该模式直接读取原run冻结的execution request与实际停写／host释放事实，不重做准备、Fly或分析，也不要求重传科学输入。
正常流程在retention／发布前持久保存小完成记录；收尾失败可原命令重试，未知writer先确认完成。
继承容量会话不由child减承诺或释放；heavy child只发布自己的终态，Result明确提示`parent_capacity_owner_finalize`，
不把父owner尚未封存的载荷报告为收尾完成。外层`accelerator_interface/execute.ps1 -FullJoint -ResumeFinalization -RunId <原flight_run_id>`
透传同一恢复命令，跳过设计、场和源阶段。

显式前驱恢复以固定完整批为单位，仅执行缺失批，来源和借用控制文件继续绑定原owner。
全批复用不申请或释放不存在的SIMION重型租约；批次执行器异常且写入者未确认停止时保留保护，
不做终态发布或retention。该项为软件行为回归，不代表新原生求解或物理资格。

[oa_mr入口](../workflows/oa_mr/execute.ps1)要求冻结`-CompositionPlanPath`及可选`-LocalScopePath`；
当前支持唯一OA轴向出口→MR入口及相对identity rotation，MR可随父装配共同平移／旋转。
当前提供者为含20电极的完整MR分析器，不再是单入口框。机械1.5 mm接口、源、实际场和直接位姿分别核验。

OA→MR owner的异常收尾保留原科学错误，guard、runtime、host、临时目录和别名的独立失败逐项报告，
不让前一项掩盖主错或跳过其他安全释放。原生根实际等待完成后才记录停写，非零退出仍可具有这一事实；
观察异常或公共调用未返回完成证据则保持未知，不执行retention、终态发布、活输入清理或撤销容量保护。
PowerShell退出不代表FileShare句柄继续存在。容量封存还要求终态发布完成、自身容量session已释放，
自有host token必须由真实release收据确认，继承token不冒充本run已释放；封存失败不改写科学终态。
相关实际catch/finally故障矩阵与小型原生进程替身测试只验证软件收尾，不构成新的SIMION物理验收。

本轮正常FullJoint[复用记录](../../../artifacts/projects/instrument_assembly/runs/20261030_014500__sim__simion__ip-mr-joint-9a6ef3c4/summary.json)
在故意不存在的SIMION路径下完成，actual native=0、完整复用2批，无原生IOB重建；原母群100、转交81、未转交19。
入口总墙钟86.044秒，准备37.435秒、飞行阶段0.012秒、分析38.962秒；首次run外Result记录到公共收尾结束共82.870秒，
且`terminal_published`／`capacity_finalized`均true。该计时与旧轮并发大场的资源等待不同，不据此宣称同环境加速倍数。
真实起点是原上游状态，采用状态重启及下游联合场，不能表述为全程continuous Fly；科学结果仍为`candidate_only`。
当前`instrument_assembly`设计已进入新场编译器；`20261029_224600__build__simion__ip-mr-field-coreflow-c3e10d46`
的parent Refine完成855.49秒，后续covered_local由用户主动停止，owner以failed保留，属于主动中止而非科学或数值FAIL；不重启大场。
最新验收按用户授权采用快速小／粗软件机制验证，未获得全尺度精度资格。
RF的9³、N1 fresh＋reuse原生机制验收（66.228秒）只见[RF项目记录](../../projects/rf_multipole_ion_optics/docs/PROJECT.md)，
不替代本集成链的科学资格；既有历史L2结果也不冒充本轮最终联合回归。


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
OA的`sectioned_geometry`是assembly interface、bare-three-zone adapter和single-flight frontend共同使用的纯几何依赖；
清单按这三个现有提供者的实际consumer并集冻结，OA→MR和单反射快照均可脱离活动仓库准备。
清单仅冻结实际消费源码；finite-interval独立设计编译器仍归OA理论API，local／cooled未调用，不再重复携带。
普通小输入的复制与身份校验统一调用`Copy-VerifiedRunInput`，直接使用其已核验SHA生成来源收据；
集成适配器继续验证提供者边界、显式清单与目标不存在，公共复制失败的实测摘要保留在依赖错误中。
冻结清单已包含PowerShell公共复制入口及直接导入，`prepared_joint`快照可脱离活动仓库继续冻结输入。
容量owner共享的cache命名合同和GUI来源投影也按实际consumer冻结；隔离快照回归直接导入这些owner，
并执行退役的惰性GUI保护查询，不靠活动仓库补齐依赖。
源与副本SHA不一致继续失败关闭，报告两条路径及实测摘要，不重试或放宽身份判据；缺依赖不回读活动仓库。
上游只验证实际消费记录，阶段恢复和终态发布复用公共机制。跨父目录执行显式共用同一调度账本。

架构迁移的既有验收见[架构迁移审计](../../docs/history/20261027__repository-architecture-migration.md)；
后续文档与运行边界修复、失败及复验见[系统审查](../../docs/history/20261027__system-maintainability-review.md)。
先前权限、宿主、夹具和发布失败仍按固定源码及原日志解释，focused通过不拼成失败整轮通过。
后续改动按[操作指南](../../docs/OPERATIONS.md#软件验证与科学证据)运行适用门禁；软件检查不授予新原生、数值或Formal资格。
本轮最终L1为24/24阶段通过、1337.500秒。完整L2主体44/45阶段通过、1578.351秒，RF失败责任阶段
修正后以正式quadrupole Static完整复验通过（298.011秒）；原失败整轮不改写为PASS。
正常FullJoint的原CLI重复收尾4.401秒通过，子summary／manifest及父manifest字节均未改；不重飞、不求场。
集成测试入口的模块枚举及L1选择边界见[入口说明](../README.md#活动工作流)；
未执行模块和未选阶段不计为通过，机器摘要只记录本轮实际阶段结果。

## 实施与退出条件

1. 现有声明链路的功能、分段身份与时钟、N2、strict共同场和保存CPT导出已有证据；新输入或新拓扑另验。
2. 保留零检测、100 Da负结果、524 Da IP门限失败及跨后端不等价，不自动扩展为性能优化或更大样本。
3. 工程几何已同源构建和交换，但4处原始交叠未消失；机械无干涉、制造、数值收敛及Formal继续按各自判据闭合。
4. 未请求的N3额外大模型不再续接。科学载荷是否可退役由公共owner、消费者和精确身份决定，不凭run终态或文件年龄删除。
5. 总目标的软件交付以最终提交、适用门禁和独立审查共同确认；本页的局部success不替代完整交付或项目资格。

## 已完成首批后的资源恢复

首批自然退出且原分区与退出事实已由前驱终态绑定时，若重规划失败，恢复计划保留首批。
有真实观测值时沿现有 scheduler 重建余下区间；缺观测时，缺失区间不超过原首批，先观察
首个缺批，再按实际资源画像和CPU／内存约束校准计划。未确认首批自然退出时不视为可复用。

IP→MR 的 FullJoint 在求场前验证设计 manifest 绑定的来源 receipt、粒子状态、时钟与共同脉冲。
仅已知 v1 zero-birth 到严格验证的 v2 common-pulse 分析升级受支持；其他 Fly 依赖仍保持冻结。
预检通过只表示输入合同成立，不表示已求场或通过科学资格。

## 机器能力发现

现有 integration registry 声明 recipe、workflow 和模拟路径，公共编译器直接派生查询视图，
不把装配注册为器件项目。实际源起点、状态重启和场耦合仍由所选 recipe 与原 workflow 报告。

## Paired 静场／脉冲的公共收尾

`paired_accelerator_static_field/execute.ps1` 与 `paired_accelerator_pulse/execute.ps1` 使用公共
run_artifact_workflow owner，保存实际原生完成／释放事实、run 外小 Result 和稳定的冻结输入路径。
原入口的 `-ResumeFinalization -ResultPath <原Result>` 只恢复公共收尾，不进入源、求场或飞行；
失败 Result 保留原始失败与收尾原因，未知 writer／未确认 host release 不释放保护、不发布终态。
显式父 manifest 仅引用已绑定完成证据；静场已有完整同身份导出可跳过相应原生采样／求解。
源、物理支持域、商业授权和原父终态保持原合同。DryRun 只证明准备，诊断成功不授予数值／科学资格。

## Local/cooled 正常执行与独立场复用

两原CLI使用公共run_artifact_workflow owner和run外小Result；`-ResumeFinalization -ResultPath <原Result>`
仅推进未完成收尾，未知writer／host release继续保留保护，原始与cleanup异常分别保留。
正常科学Fly与保存工作台资格分开：默认不再附加第二轮全母群Fly；显式`verify_saved_workbench_replay=true`
才执行相应确定性回放，随机碰撞仍验证saved controls，summary如实区分`not_requested`、controls与实际Fly。
cooled七个普通Laplace工作场使用原缓存事务逐成员命名，受保护原成员可直接跨generation引用，不建聚合PA副本。
固定geometry/operator/grid/solver仅改合法OA pulse工作电压，其余六场保持复用；有充分线性证据时pulse可按系数投影。
GEM、真实边界、网格或数值改变仍使受影响成员失效；源母群、分析和显示不被误当场求解身份。
同字段owner的小采样与引用式probe记录保留原manifest绑定及raw数据，analysis／reference沿真实比例读取，不改写原CSV。
seed／placeholder沿[公共小配套冻结](../../common/simion/README.md#共用工作台种子与独立场成员)复用，
科学身份用单反射既有field_plan提供者；未新增万能runner、字段注册表或历史搜索。准备、软件接线与真实科学资格分别报告。

既有正常field-only证据限定为开发网格0.5/0.5/0.2mm、准备N=100源而未Fly／GUI：
[040843原生成员构建](../../../artifacts/projects/instrument_assembly/runs/20261031_040843__build__simion__cooled-frontend-fielddesign/summary.json)
的Refine／导出／验证各7次、gem2pa一次；member阶段189.636秒，probe7次／258603408 B私有运输／18.443秒，聚合搬运0。
[041904后继线性复用](../../../artifacts/projects/instrument_assembly/runs/20261031_041904__build__simion__cooled-frontend-fielddesign/summary.json)
仅将OA向量减半，保留其余operator；Refine、原生operation和probe／聚合PA运输均0，七原generation及七原CSV直引，pulse绝对scale=0.5。
它们只证明该冻结场构建、静态probe和受保护成员复用；不证明粒子冷却、N=100轨迹功能或整机科学资格。
本提交新增的收尾参数拒绝与seed运输顺序由软件回归验证，没有重跑上述Refine，也不以fixture零native替代真实科学Fly。

### 同步已冻结的理想栅接口审计源码

`111659`原生实际冻结builder包含OA出口／reflectron入口的grounded-sheet与有界endpoint检查，
b18源码尚未包含该部分。本次从当前同一core前向还原无路径transport的CLI builder，
与该run冻结builder完整18311字节相等；runtime按同一resolved几何提供两组五点接口声明。
这同步已取得原生审计的源码，不新增场或Fly，不把诊断变化当成场／轨迹科学identity。
既有理想0V栅与粗网格适用范围保持；软件负例覆盖缺失声明、非电极、非零势／非有限场、
坐标二进制roundoff与真实越界，不能扩称有限边缘场或Formal资格。
