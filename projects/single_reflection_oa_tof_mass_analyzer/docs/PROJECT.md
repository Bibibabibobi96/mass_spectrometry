# 单次反射正交加速飞行时间质量分析器当前状态

本文件维护项目当前事实、资格与开放任务。精确输入以[机器合同](../README.md#机器权威)为准，
执行入口由[项目README](../README.md#活动入口)导航；跨项目整机状态只查[统一集成状态](../../../integrations/docs/INTEGRATION.md)。
Paper 1 专用研究准备API的归属与退出条件见[分析说明](../analysis/README.md#核心分析)。
已闭合的提供者迁移、回归及失败链冻结在[文档收口记录](history/20261026__assembly-documentation-consolidation.md)，
不把实现迁移、局部验证或旧运行自动提升为新整机资格。

## 当前状态

2026-10-31 执行 profile 的职责字段演进后，既有 `sync_geometry_contract` 同步器现同步活动作者表的
显式 execution profile 来源绑定；只接受固定 `config/execution_profiles.json`，不手填摘要或跳过身份校验。
已退役 campaign 的状态、执行授权、科学行与旧 run 冻结副本不变；状态查询可用不表示允许重新执行。
理想源入口测试按实际 analyze 动作、工具、输入、seed／run 绑定及输出验收，不再读取已退役的验证等级字段。
这项维护只修复源码／合同 CI，不产生商业求解、科学资格或重新授权。

2026-10-31 已沿既有 `run_theory --refresh-authorities` 刷新活动 three-zone funnel v1／v2 的
OA geometry 来源绑定，仅更新该来源的 LF 字节数与 SHA；科学字段和对象外文本均保持不变。
修复前 CI 41149973792（320.267秒）因 geometry authority byte count 漂移失败；当前两相关模块
18项纯软件回归通过（16.534秒），覆盖原拒绝漂移与刷新幂等。此为活动作者合同的新鲜度维护，
不改旧 run／receipt，不执行原生求解，也不提升现有科学资格。

ION 生成入口支持显式 `-PythonExe`，其次使用 `SIMULATION_PYTHON_EXE`，否则使用仓库 Python 3.11 环境；所选文件缺失即拒绝。Candidate 冻结源码时仍将该选择绑定为本次唯一解释器，不在后续运行重新选择。受管进程按真实 worker PID、创建身份、握手、退出和输出排空确认归属；系统 Python 的 worker 与 launcher 同 PID 合法，venv 也可能不同，不能用 PID 不等代替归属证据。

径向紧凑化及结构Candidate的公共owner Result保留在项目scratch的`workflow_results/<run_id>/result.json`；
原入口的finalization-only恢复使用该Result与run内冻结request，不重飞或改变父运行的科学终态。
显式PA交接Result仍由调用者指定。该软件接线不构成新求解或Formal验收。

本项目当前生命周期、capability与Formal asset状态为`formal`，限于原子发布的524 Da、+1设计：
双级环栈反射镜（10+5环），初始能量`5±0.4 eV`。Formal坐标以检测器有效面中心和精确一阶时间焦点
为`z=0`，`+z`从加速器指向反射器；SIMION局部PA通过IOB变换映射到同一坐标。

2026-07-29以零物理变化的同源N=1000输入完成vNext发布；[项目身份](../config/project.json)、
[Formal资产](../config/formal_assets.json)、[验证合同](../config/formal_validation.json)和
[SIMION稳定入口](../config/simion_stable_entry.json)共同冻结该release，GUI/CAD证据由独立run及SHA绑定。
2026-07-20旧基线保持历史身份；[零变化发布请求](history/20260729__formal-vnext-zero-change-requests.md)已归档。
2026-08-02的PA漂移已从原validation run精确恢复；当前SIMION入口只运行manifest验证后的scratch副本，
处置见[恢复证据](history/20260802__formal-simion-integrity-recovery.md)。

Formal加速器为闭合屏蔽结构，没有RF注入侧孔。新连接使用run-local组合几何，不修改原baseline、
MPH、SIMION包或CAD；原Formal、Candidate组件与新整机分别验收。
反射器调压现使用官方`pa:fast_adjust`；[隔离诊断][reflectron-api-isolation]保留旧CLI访问冲突的failed终态，
API调压、保存与独立重开通过，后继整机已越过该调压点。官方依据为
[PA API说明](https://simion.com/info/ram_and_memory.html)（2026-10-26核验，接口自8.1提供）。
该替换不改变几何、原电压或精度，也未定位供应商内部崩溃原因；整链零检测命中等结论归统一集成状态。

## 统一组装迁移任务

职责与切换门禁见[组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)，
阶段依赖见[统一组装计划](../../../docs/ROADMAP.md#统一组装迁移计划)。本项目保留反射器、仪器布局、
加速器—反射器联合聚焦、检测及自身验收；跨项目适配、母群、驱动和时钟编排归integration。
纯二区／三区计算与器件构建由独立OA项目提供，依赖见[accelerator_dependency.json](../config/accelerator_dependency.json)；
新运行须冻结实际提供者源码，不能只冻结本项目薄适配器。

| 对外边界 | 当前权威与限制 |
|---|---|
| 完整器件几何与机械接口 | [assembly_interface.py](../analysis/assembly_interface.py)消费最终resolved及实际OA投影；共用外罩保持一个物理身份。侧孔来自显式请求，不能从源或Formal required port推定；圆柱variant不具备该平面机械接口，明确拒绝 |
| 加速器几何与候选布局 | [accelerator_geometry.py](../analysis/accelerator_geometry.py)与[single_flight_layout_profiles.json](../config/single_flight_layout_profiles.json)发布真实几何及显式设计条件；设计相空间不替代实际母群、出生时钟或脉冲计划 |
| ON电压 | [accelerator_electrical.py](../analysis/accelerator_electrical.py)从最终resolved发布语义电极电压与有序环分压，拒绝拓扑冲突及越界外推；OFF电压和脉冲时序由实验显式声明 |
| PA实例与检测器 | [geometry_contract.py](../analysis/geometry_contract.py)派生实例、网格及采样点；真实机械检测器与数值终止标记分开。Candidate标记只用于反射回程，不能用于遮挡出射束 |
| 分析器组件 | [Candidate Lua组件](../simion/workbench/candidates/oatof_analyzer_component.lua)提供几何、场、电压和检测hooks；Workbench、callback、原生clock及停止调度由调用workflow拥有，`post_pulse_observation_window_us=false`可关闭组件观察窗 |
| COMSOL输入 | [模型合同](COMSOL.md#模型与合同)区分配对几何／电压投影、显式SideOpening、ION表与Cartesian源；GeometryOnly、FieldDesignOnly与粒子运行各有范围，不能互相代替 |

`accelerator_side_shield`及provider-local物理ID `1`仅表示方形加速器连续侧屏蔽与后壁，不是整机电极表或PA编号。
机械接口消费实际孔径投影，不能把粗场／主场参考孔径当作真实开口。提供者位姿只由冻结装配消费、核对，
不在Program中重算覆盖；共同源、绝对时钟及实际场链仍须由所选workflow验收。

下列证据只支持各自范围；闭合过程及测试明细见上述文档收口记录：

| 验证 | 可支持的当前结论 | 尚未证明 |
|---|---|---|
| 提供者与冻结Candidate回归 | 几何、电压、半cell网格、源码闭包及退出码保真；既有baseline序列化保持 | 新Refine/Fly或Formal资格；旧12位电压文本构建场不能自动继承新源码资格 |
| 共同静态场比较 | 按唯一point_id对齐完整坐标／电场，比较与显示机制闭合 | 没有获批容差时仅为COMPARISON_COMPLETE，不判场等价 |
| [完整组件几何保存、重开及STEP][geometry-only-evidence] | 45域／40物理对象，整包及独立STEP发布，geometry_save_reopen_step_only | 上游多极杆、SolidWorks、ES/CPT/Fly及Formal；该run未做人工GUI，当前代码对等与CAD范围见[集成交付边界](../../../integrations/docs/INTEGRATION.md#工程几何与gui边界) |
| OA-only共同场有限脉冲 | [消费者](../comsol/run_paired_accelerator_pulse.m)已读取已解ES和实录Cartesian源；真实N100 CPT及状态导出见[集成状态](../../../integrations/docs/INTEGRATION.md#共同场与有限脉冲) | 完整反射器仪器、RF等价、检测命中、GUI/CAD或Formal资格 |
| 有限ON/OFF微例程 | 具名均匀场单粒子解析对照及保存重开通过，失败前驱原样保留 | 仪器默认数值配置或通用误差界；操作与冻结判据见[COMSOL说明](COMSOL.md#有限脉冲微型回归) |

仍需在所选配方中核对分析器与OA实例边界，避免重复装入加速器；关闭条件是原分段／连续工作流的
冻结输入、端口、驱动、事件、母群与时钟经相称对照一致，调用、身份和实际场链同步切换。
各链已完成与未完成项以统一集成状态为准，独立器件或局部前端通过不授予新整机或Formal资格。

## 物理与几何基线

精确参数、公式和舍入规则只认`../config/baseline.json`、`../config/resolved_geometry.json`及
`theory/`。用于识别设计的摘要为：

| 对象 | 当前设计 |
|---|---|
| 三栅加速器间距 | `d1=3.0 mm`、`d2=16.8 mm` |
| 反射器 | 一级120 mm；二级工程长度96.1563 mm |
| 反射器电位 | 一级压降1628.8001 V；背板2531.1999 V |
| 屏蔽罩 | 内半径350 mm；侧壁和端盖厚10 mm |
| 检测有效面 | 全局`z=0`、半径40 mm |
| SIMION日常加速器网格 | `xy=0.25 mm`、`z=0.05 mm`；`z=0.025 mm`仅为收敛参考 |

这些摘要不能用于重建求解器模型。修改焦点、电压或长度前必须重算理论并同步COMSOL、SIMION和CAD。

## 冻结验证记录

`../config/formal_validation.json`冻结的当前vNext同源N=1000结果为：

| 指标 | COMSOL | SIMION |
|---|---:|---:|
| 命中 | 1000/1000 | 1000/1000 |
| 平均TOF (us) | 71.35281164 | 71.35361153 |
| 直接质量FWHM (Da) | 0.01312031696 | 0.01099407843 |
| 质量分辨率R | 39938.06 | 47662.02 |

两端平均TOF差`0.79989 ns`，逐粒子TOF RMS差`1.06557 ns`，落点RMS差`0.30225 mm`。该release
通过冻结的Formal验证合同与独立GUI/CAD evidence；它是当前拆层合同下的可信Formal参考点，
不把单一分辨率差异解释为需要通过单独调网格、时间步或quality追平的目标。

质量分辨率统一定义为`R=m/FWHM_m`；窄峰时间域等价式为`R=T/(2·FWHM_t)`。近似高斯时才允许以
`2.3548×sigma`代替直接半高宽。

分辨率的唯一飞行时间时钟定义为

$$
t_{\mathrm{TOF}}=t_{\mathrm{detector}}-t_{\mathrm{pulse,effective}}.
$$

正交加速脉冲的有效提取时刻是oa-TOF时间零点。多极杆中脉冲前的离子生成、驻留和传输时间不得
计入oa-TOF分辨率，只能通过脉冲瞬间的位置、速度、能量和相位空间分布影响结果。absolute
instrument clock仅用于调度与诊断，禁止作为分辨率声明；集成分析输出必须保持
`instrument_clock_peak_is_resolution_claim=false`。

2026-08-27 connector-gap工作点对照的旧派生报告曾误用absolute instrument clock；其R与无符号
差异区间已由[脉冲相对时钟勘误与新派生证据](publication/paper_1_jasms/connector_gap_working_point_mechanism_20260827.md)
替代。直接FWHM、粒子命中及原始轨迹不变；收益区间现为以继承工作点为分母的有符号配对统计。
该修正不改变524 Da Formal资产，也不把单源100 Th对照升级为通用算法优越性证据。

## 当前能力与边界

辅助`solver_diagnostics.analyze_simion_log`只报告出生相对时间的Gaussian proxy：新输出使用
`GaussianProxyFwhmTofNs`与`GaussianProxyTimeEquivalentResolution`，替代旧的`FwhmTofNs`／
`ResolutionFwhm`歧义字段。方法标签、时间参考和`ResolutionClaim=false`随结果发布，不能用于上文的
脉冲相对分辨率声明。缺失事件保留为`not_observed`母群成员；允许不完整census不再放松唯一ID约束。
无命中、单个命中与零方差分别有状态，未观测粒子不被推断为物理损失。历史冻结输出保持原身份。
辅助摘要现对全部状态发布`analysis_metadata`，明确样本sigma为`ddof=1`、等ID单位权重及各自样本数／
权重和／有效数；命中峰宽、全部实录穿面宽度与非命中源统计有独立群范围。方法、单位、实际穿面选择和
出生相对时间随同保留，原Gaussian proxy标量不变，不补造脉冲epoch或质量分辨率资格。
ION电荷与五质量CSV／mode共用该诊断模块的精确整数校验：文本按十进制解析，允许正负非零整数及
整数小数／指数编码，拒绝分数、布尔、零和非有限值；不会先经浮点截断把`1.5`改成`1`。

峰形比较和配对bootstrap已接入[公共显式ID合同](../../../common/analysis/README.md)：通用比较入口
不再由等长数组或自动编号推断配对。合法配对的数值定义与随机重采样保持不变，五质量分析仍只比较分布。
该修复关闭通用入口的错误使用路径；既有Formal入口已声明同源配对，历史结果及资格不因此改写。

通用reference分析的新结果已显式标识`nominal_mean_relative_square_v1`名义相对质量映射，保留
原Da数值与CSV列；其输入TOF的时钟资格为`unspecified`，不能仅凭此入口取得脉冲相对或绝对标定资格。
五质量分析明确采用`sqrt_mz_affine_centroid_fit_v1`：每个求解器对同批物种质心拟合
`sqrt(m/z)=a*tof_us+b`并检查同批残差，拟合`-b/a`不代表测得的脉冲epoch。图中m/z单位修正为Th，
非整数电荷在转换前失败关闭，`resolution_claim_allowed=false`保持不变。
同批质心拟合现要求有限正值的一维TOF／m/z输入，并核对
[NumPy `polyfit`原生秩诊断](https://numpy.org/doc/2.4/reference/generated/numpy.polyfit.html)：
一次模型须为秩2，沿用原默认`rcond`，不新增接受容差。质心TOF无法区分、数值秩不足、零斜率或
非有限计算结果在结果写入前拒绝；重复质心只要设计仍满秩可以保留，合法旧拟合系数和残差不变。
五质量CSV同时拒绝整数转换前的分数／布尔／非有限／非正／重复原ID；COMSOL局部ID和SIMION混合源
全局ID分别按对应母群上界校验，COMSOL缺原ID不能自动补号。两求解器含非命中行的物种数量均不得超过
声明emitted，未知或歧义物种也拒绝；无效输入在写结果前失败。保留合法非连续命中ID，不按观察行重编号。
后续独立复核发现已验证ID被二次CSV推断转浮点的路径，现由reference导入边界统一精确整数解析：
ID列保留词法，COMSOL母群校验与命中筛选使用同一源表。大于2^53、int64最大值及整数小数／指数编码
在筛选和CSV输出中保持原值；高精度分数、越界和不同编码的重复ID均拒绝。泛用缺ID导入的生成标志和
禁止生成ID配对边界保持，不能把外部Excel已舍入的数值恢复成原始ID。
这轮修改补齐结果语义，不重算冻结分析合同、历史receipt或524 Da Formal资产。
求解器无关验证包含29项峰形/reference/五质量测试与17项相邻密度、Formal布局及COMSOL事件分析测试。
对B3前的只读源码快照作同输入内存对照：6组质心拟合、31粒子reference和每求解器25粒子的五物种分析
保留全部既有结果字段，5份CSV逐字节一致。新增元数据与图标签不构成真实求解器、独立校准或Formal复验。

最终输入审计后的峰形/reference/五质量模块41项通过；辅助诊断模块19项通过，合计60项、无失败或跳过，含真实PowerShell包装器，
包装器复用既有`SIMULATION_PYTHON_EXE`与Python 3.11校验，不因隔离树缺本地`.venv`跳过。
完整项目回归另发现该赋值变化未同步候选源码冻结器，导致33项共同报错；现冻结器精确替换当前
整块赋值，冻结副本不允许环境变量覆盖绑定解释器。长期测试实际冻结完整closure，再以无效环境
解释器运行冻结包装器仍成功；16项辅助诊断回归通过。修复后的完整Static门禁478项中476通过、
2项skip（194.275秒，总198.677秒），未运行真实求解器或重写正式资产。
新增Python CLI实际验证分数ID及超额物种在写结果前失败、空诊断完整JSON可序列化。
实函数覆盖两求解器原ID、合法非连续编码、非命中行上界、未知物种及四种proxy状态，原有峰形／配对／
质谱输出回归保持通过。精确ID修复另对普通、整数小数、无ID和显式列映射4类旧输入作同输入修前／修后
对照，表值、dtype及导入metadata完全一致。这关闭通用分析入口的非法输入路径，不将缺陷追溯认定为旧Formal结果错误。
`606a0958`基线后的退化拟合／电荷补检先复现两个实际缺陷：各物种相同质心仍报PASS/computed，以及
ION分数电荷被截断。修后两求解器退化质心与真实CLI均在写结果前拒绝；6组合法拟合全部标量和数组、
6种合法ION编码的完整表值／dtype及诊断summary与基线精确一致。此证据仅为求解器无关分析与包装器回归，
没有新增真实求解、独立标定或Formal资格。

| 能力 | 当前范围 | 资格 |
|---|---|---|
| Static合同与候选编译 | baseline/science/numerics分层、resolved与源码冻结 | PASS |
| 结构Candidate | 零变化和`reflectron_midgrid_voltage`、N=100、真实COMSOL/SIMION/CAD receipt | Candidate结构合同；无性能声明 |
| 五质量候选 | 固定10/100/500/1000/2000 Da功能比较 | Candidate；不替代524 Da基线 |
| Formal跨求解器诊断 | 当前冻结资产的轴场、同坐标三维场和代表粒子轨迹 | Diagnostic；不改变Formal资格 |
| 三区加速器理想理论 | 100 Th冻结离散域、精确一维时间和canonical T0—T5漏斗闭合 | Functional / PROVISIONAL / POST_PILOT；solver-free，不改变Formal |
| Formal当前设计 | vNext同源N=1000、COMSOL/SIMION/CAD及GUI证据原子冻结 | Formal |
| RF四极杆离子光学→本项目接口 | 下游只读分析器消费 | 整机Formal BLOCKED |

统一Formal跨求解器诊断已完成真实只读验收，覆盖轴场、同坐标三维场和冻结代表轨迹。它没有预注册
场差接受阈值，成功只表示导出、坐标配对、分析和manifest闭合，不表示场或轨迹等价，也不改变Formal
资格。精确采样数和差异只查run `20260801_011500__analysis__cross__formal-diagnostics`。

Candidate唯一公开入口为`../workflows/design_candidate/run_candidate.py`；必须提供获批request、run ID和
显式seed，依次执行粒子表、COMSOL、SIMION、CAD和结构验收。成功结果固定为
`candidate_accepted_not_promoted`，不含晋升。晋升必须由独立事务完成。

首个声明式midgrid campaign以同seed、N=100完成COMSOL、SIMION、SolidWorks与结构验收。诊断电压
显著破坏时间聚焦而未明显改变最大命中半径，支持保留理论名义值；它不含COMSOL粒子级比较、统计重复
或数值收敛，仍是`candidate_accepted_not_promoted`。完整数值与授权边界见
[`history/20260802__reflectron-midgrid-campaign-authorization.md`](history/20260802__reflectron-midgrid-campaign-authorization.md)。

历史2.2 mm源宽候选仅验证变量合同、理论闭合和run-local PA重构，不改变本项目Formal；
旧连接证据查[已退役集成记录](../../../integrations/docs/history/20261024__legacy-family-retirement.md)，
新装配状态查[统一集成状态](../../../integrations/docs/INTEGRATION.md)。三区真实PA及源敏感性的有效范围见
[完成快照](history/20260823__three-zone-completed-results-snapshot.md)，不继承为当前Formal。
理想源的[残差／束宽](history/20260827__ideal-source-residual-and-width-comparison.md)与
[斜率比较](history/20260827__synthetic-affine-slope-scan.md)仅证明受控一维机制，不授权真实三维接受或性能声明。

径向压缩入口的构建父进程与单次 Fly 均以 1800 s 作耗时告警，不以该阈值终止健康求解。
恢复接口使用新 `--run-id` 与显式 `--resume-from`，读取父运行冻结合同与公共 whole-unit continuation
校验过的完整 Fly 单元。原生退出码为零仍须具有唯一完成记录且 splat 数等于冻结粒子数；分析失败
可以重做分析，错误身份摘要、部分日志和未被父 manifest 绑定的裸 receipt 均不能跳过 Fly。
硬杀后尚未发布的单元按未完成重算；本主题不另建逐单元 checkpoint，以保留现有终态发布和恢复合同。

新建运行可用同一入口的 `--campaign` 选择具名已授权合同，默认合同仍为现有生产配置；任何显式
`--campaign` 与 `--resume-from` 同时使用都会拒绝。续跑不回读活动默认合同，冻结复制期间的输入漂移
也会失败关闭。纯计划运行具有专用 plan summary，并不能作为科学恢复前驱。软件夹具已覆盖跨两代
恢复、只重算未完成单元、父运行字节不变、并发异常汇总及未知进程退出阻止终态发布。
恢复同时要求相同的源码闭包和执行器身份；分析源码升级后不能隐式复用旧单元。这是当前保守合同的
明确成本，不另建跨版本豁免或修改旧终态。

运行先由公共容量 owner 准入并建立新 package，再冻结输入与既有源码闭包。实际科学 worker 只消费
冻结目录，使用公共 READY／ACK 握手确认实际 Python worker 的身份、退出和日志排空；启动器退出
不能代替该证明。worker 的内部完成记录只有在这些事实确认后才原子交给唯一公共终态发布入口。
一个 mode 的所有 case 均有已验证完整单元时，直接在该冻结 worker 重做分析，不启动求解器资源
bridge；尚需 Fly 的混合或全新 case 仍由原整 pool 调度。真实公共 writer 合同回归覆盖全复用时
operations 与 resource releases 均为空，避免给没有启动原生操作的阶段登记孤立释放记录。
软件故障注入已验证“记录已写但 worker 状态未知”不发布、不退役；真实冻结导入回归同时确认了
调度库绝对路径继承，未建立冻结目录私有调度库。
非计划构建还须冻结具名 Candidate runtime 选择、已验证的 layout 注册证据和原同名 IOB／CON 对。
首次准入保护注册与源文件所属 run，实际 builder 消费 `inputs/template` 中的副本；恢复使用父运行
冻结选择，不回读活动 runtime 或最新 template。注册身份复用原 `prepare_candidate_run` 校验入口，
不再为读取验证器反向依赖 design CLI。
共享源码闭包同时补齐容量 policy。冻结目录中的正式 builder `-File` 软件回归已越过实际容量续期、
plan 验证和 cache begin，到首个原生调用由明确 Python 替身退出；这只验证启动前执行依赖与失败传播，
不证明后继 Lua／GEM 或真实 Refine／Fly 已通过。
资源 pool 的新 Python 进程重新导入冻结模块时，也从同一冻结 request 绑定所选解释器和产物根；
真实公共 bridge 回归已验证 Fly 参数不会落到不存在的 `inputs/code/.venv`。分析直接调用既有
`analyze_simion_log`，沿原 CSV 序列化和严格 JSON 规则；与原 CLI 的诊断及 CSV 字节等价，
不再为每次分析启动额外运输进程或保留重复观察日志。
原生普通 `.log`、stderr、完整单元 receipt 与 ION 仍列为 required outputs；这些普通日志已由公共
retention 分类保留，不再误传仅用于特定 batch TRACE 的 `retention_preserve_paths`。
长期回归实际调用公共 retention，验证旧投影被拒且修正后 required 文件逐字节保留。

实际非计划路径预检发现生产 campaign 的旧 seed `20260713` 与其绑定的 D300 母群 SHA 不一致。
现仅将该 seed 修为具名 reference run 所记录的 `20260729`，母群 SHA、阈值与物理设计保持原值。
`20260810_121500__benchmark__cross__cpu-formal-n1000` 的 `run_config` 与其前驱
`20260729_112246__sim__cross__vnext-n1000-r2` 均记录该 seed；现公共生成器逐字节重建同一
N1000 母群（`D3004697…7179`）及 N100 前缀（`3BD65B6C…F26D`）。长期回归走实际 case 准备及
ION 生成入口，旧 seed 无法满足母群 SHA；其他合同的 seed 未改。

PA 路线保留原物理设置：仅 surface=none 的 accelerator／reflectron 使用公共 raw 与 standalone
response 缓存，随后构造当前运行的私有 family；fractional 的 tube／detector 每个新运行从冻结 GEM
重新构建。容量预算计入全部潜在 case，共用一个持续 session。既有 ThreadPool 只执行共享调度器
批准的波次，SIMION 资源 profile 来自实际原生进程，不能由 PowerShell 包装进程峰值代替。
完成判据分别保留直接 SIMION 进程自然退出、实际 Python worker 同句柄退出与双流排空，以及
资源 owner 的释放事实；worker 非零不能被 native 零退出码覆盖。当前受护输入句柄只覆盖其
PowerShell owner 存活期，未知退出阻止发布和退役，不声明句柄跨 owner 退出仍保持。
未发布PA交接沿同一builder的显式`ProducerHandoffPath`消费冻结映射。共享prepare helper保留原公共owner
Result的完整字节，并将其中实际`stopped_payload_receipt`确定性投影给公共六字段交接合同；每次消费均
核对投影原值、前驱manifest、当前session与保护范围，不从`resume-from`或文件存在推断授权。
现有设计入口`workflows/design_candidate/run_candidate.py`与径向入口
`workflows/radial_compaction/run_campaign.py`均接受重复的
`--pa-producer-handoff TRANSACTION OWNER_RESULT`。准入前用同一prepare helper轻验小证据：精确重复去重，
同key冲突或不属于本次全部编译plan的key拒绝；前驱与原验证证据所属run进入同一容量保护范围。
准入后只冻结一次并将全部小输入登记到run manifest，builder验证整份映射后仅消费当前case的key交集。
容量承诺仍覆盖全计划，部分单元重建不会借交接缩减预算。
生产者需在启动时显式给`--pa-handoff-output RUN_EXTERNAL_RESULT`，公共owner直接将原始Result写到该新路径，
成功或已确认停写的失败均保留原字节；不会将派生receipt冒充原输出。该选项预声明`solver_review`与用途，
径向默认`compact`保持不变，设计入口原`solver_review`保持。两个交接选项均不允许与`--dry-run`组合；
consumer输入与既有父run恢复独立，父run参数本身不授权PA交接。
构建completion按component绑定cache key、完整响应命名空间及实际构建／导出operation IDs；只有全部
native与实际Python worker成功退出且双流已排空才记录完成集合。完整未发布库存经原官方私有family
重组与逐响应verifier验证后发布，不重复heavy response Refine；原prepared验证证据有效且被前驱
manifest绑定时直接沿公共发布阶段继续。未封存且缺成员的component整体重做，不复用其部分响应。
完整原scratch在Refine／导出后、verification或成员移动时中断，可重跑原全响应验证再移入发布payload。
再次交接只在新completion引用本run inputs内的原始build completion；引用由当前manifest绑定并在下次
冻结时保持扁平，原run身份与原operation不变，新completion仅记录自己实际执行的验证与worker。
已封存却没有原科学完成证明的库存明确拒绝，保留原owner和只读成员；处置须沿现有公共显式取消合同，
普通交接不冒充用户取消。旧run缺少上述completion绑定时不追认科学成功。该接线的软件夹具使用惰性
原生命令替身，只验证身份、调度与发布时序；真实交接场等价和GUI验收单独执行并记录。
2026-10-28 的[正式 CLI 计划运行][radial-owner-dry-run]已贯通真实容量准入、两层实际 Python worker、
compact retention、终态 manifest 和账本收尾：10 个静态 case，0 Fly／0 Refine，命令墙钟 28.394670 s；
独立完整 manifest 验证覆盖 70 个输出，账本为 ready，租约已释放，保留 5,506,448 B 小证据。
该轮只证明计划运行的 metadata 链，不提供真实 PA、Fly 或 GUI 验收结论，不改变 Formal。
首个 N100 实际入口在启动原生工具前暴露了缺失冻结 runtime 配置，保留的
`20261029_000006__test__simion__radial-n100-first` 为 failed 终态，0 Fly／0 Refine；
独立完整 manifest 验证通过 16 个输出，容量 lease 已释放、账本 ready。该失败促成上述模板输入闭合，
不以软件修复或失败收尾通过替代下一新 run 的真实 PA/Fly 验收。
随后 `20261029_001733__test__simion__radial-n100-first-r2` 以原网格、电压、quality 8 与 D300 母群的
N100 前缀完成 shield260 的实际场及原条件自然触发的四个理想场归因模式，每个模式 100 splats、
原生退出码 0；`best_accepted_case=null`，仍是原接受阈值下的负结果，不授予 Candidate／Formal 资格。
首次完整命令为 420.236871 s、exit 1：原生工作已完成，但普通日志被误传为特殊 TRACE 保留路径，
因此公共 retention 在创建任何收据前拒绝收尾。该未封存运行经一次明确授权的 metadata 更正，
仅清空该列表并列入原 completion 字节备份及字段差异审计；科学 summary、五份原生日志、输入与
143 个源码文件保持原身份。更正耗时 3.102785 s，既有 owner 的 finalization-only 收尾耗时
9.394539 s、exit 0，未再构建或 Fly。独立完整 manifest 验证通过 558 个输出；公共 compact
删除 38 个可重建私有载荷、释放 1,275,410,616 B，账本 ready，原容量 lease 已释放。
714 个保留原文件 SHA 核对一致，原 completion 与更正审计保存在该 run 的 `results/` 并由终态
manifest 绑定。此轮只作为含历史收尾缺陷的构建成本参照；后继同源码重复运行、显式恢复及 GUI
验收须分别报告，不能把其总墙钟差全解释为缓存收益。
同一修复后源码与冻结 context 的 `20261029_005100__test__simion__radial-n100-warm-a` 和
`20261029_010000__test__simion__radial-n100-warm-b` 随后分别以 243.841993 s、252.231317 s
自然完成全链，均为 exit 0，独立完整 manifest 各验证 280 个输出。每轮两个 heavy cache 命中，
ground 保持 fresh；六条原生 Refine 完成记录来自两个私有 controller 与 ground 的四次解，
不把 warm 运行称为零 Refine。五份粒子 CSV 字节相等，canonical 指标精确相等；诊断仅有三个
run 路径字段不同。两轮 best accepted case 均为空、容量已释放，实际保留 4,483,222／4,483,225 B。
随后显式父 B 的 `20261029_010500__analysis__python__radial-n100-reanalysis` 已证实零原生构建／
Fly／Refine 和父全部 442 个文件 SHA 不变，但 70.673763 s 后因旧调用方留下五个孤立资源释放
记录而被公共 owner 拒绝首次封存，不能把该原命令列为完整恢复 PASS。经明确授权，一次性更正
仅把五个已经真实启动、同句柄退出的 analysis PS bridge 证据投影为相应操作，并保留原 completion
字节和审计；没有补造原生操作、改变科学结果或资源释放事实。更正 2.851977 s、既有 owner
finalization-only 收尾 7.231395 s、exit 0；独立完整 manifest 验证 33 个输出，父 442 与子 190 个
原文件 SHA 不变、五份 CSV 和指标相等，账本 ready、原 lease 释放，保留 3,560,082 B。
上述全复用分支修复与公共 writer 合同回归已通过 49 项软件测试。后续真实部分构建故障与 prepared
发布故障保留原失败，未完整导出的组件整体重建；发布前遗漏的 key recovery 容量登记由原 cache
owner 修复。修后 [P3 恢复][radial-p3-recovery] 以新 run 自然完成，重用原两组 heavy response，
仍实际构建私有 controller 与 ground，并完成同源 N100 的五种模式。CSV 与 canonical 指标与前驱
一致，实际活动缓存／run 记账闭合；这不将 retired transaction 的历史 bytes 当作当前 journal 盘占。
[P4 重分析][radial-p4-reanalysis] 随后从该冻结父运行自然闭合，零 Build／Fly／Refine，五模式在同一
frozen worker 内分析，未登记孤立的 native operation／release；父输入、CSV 和指标保持原身份。
两轮仍为 best accepted case 为空的功能验收，不晋升 Candidate／Formal。用户已取消本次截图故障排查及
截图依赖的 GUI 复验；原 GUI r3 保持 failed／未验收，不留作本轮后续任务。其私有 PA 经用户精确批准后
由[原 owner 退役][radial-gui-retirement]，保留全部小证据与重建输入；保留 IOB 须重建 PA 后才能再用。
命令行通过不代替截图与四实例实际检查，不授予新的 GUI 等价或 Formal 资格；跨版本恢复校验未降低。

径向完整批恢复区分只在Fly后使用的公共峰指标、求解器日志诊断和径向分析模块；
单次Fly的日志分析、CSV及峰指标发布已从混合driver移入径向分析模块。它们变化时重做分析，保留已封存完整Fly单元；
科学输入、SIMION、Python和其余执行源码身份仍须匹配，新运行记录自身context并引用前驱收据。
当前driver同时负责物理执行和分析，其任何代码变化仍使旧driver的恢复被拒绝；不能把这两项模块的
豁免推广到混合职责源码，也不能宣称全部场／飞行／分析依赖已拆分。上述接线为软件行为回归，
不追认不同driver的历史结果可恢复或授予新的原生资格。

## 已知兼容边界

现有 Formal MPH 保持 Generalized-α／Strict；源码修复及下列诊断候选不追溯修改资产身份或资格。

| COMSOL 当前结论 | 已验证范围与限制 |
|---|---|
| 活动步策略与检测器实现修复 | 构造、重追迹、只读核验共用活动算法策略；零／近零平台、伪穿越和冻结查询下界修复有 57 项 MATLAB 回归。原窗 100 个平面事件复提取不证明有限有效面命中或时间收敛 |
| 同一 FEM、同组 N100 时间参考 | 校准最大 TOF 差 0.117375 ps，通过后同配置重复最大差 0.017286 ps；事件与采样状态门通过。只支持该时间协议，不是电场空间收敛或绝对物理误差界 |
| 真实主链合并读取 | 局部约快 2.76 倍，该次完整流程缩短约 2.82%；单次配对包含求解波动，不证明稳定整体收益。未通过的旧配置、手动缩放、稀疏输出及逐值一致性诊断保留原失败 |
| 稀疏事件读取限制 | 准确 st 不保证 Counter 完整或晚期坐标准确；已定位输出保存及边界归属链，未识别内部公式。StoreExtra、Counter 创建时机和单插时刻的结果均保留，不能作为任意模型的通用修复 |
| 原生五辅助变量候选 | GA／Newtonian 在原稀疏 N100、真实两壁面 50/50、同配置重复和保存重开范围通过；重复终态 CSV 字节相同。DP5 晚期辅助记录丢失／失真，交点读取候选因身份通道不一致被拒用；尚未接入生产或获得整机资格 |
| 小模型读取与曲面表示已隔离 | 平面 GA 两种方程形式终态均正确，DP5 两种均丢失终态辅助记录，排除仅由方程形式造成。解析球面二／四／六次表示的原生时间误差约 605／5.07／0.256 ps，六次 GA 终态通过、DP5 仍失败；粗线性边界将 12 个 CAD 内源排除出离散域并未释放。均只证明具名解析夹具，不是整机精度或默认参数 |
| 极小粒子数兼容绕行 | COMSOL 6.4 当前模型存在非单调原生不稳定；日常用同源 N100，无粒子间耦合时才能分析其小样本前缀。调查已关闭，不据此继续扫描极小 N |

参考、完整流程成本、失败候选和复现分别查[修复后完成记录](history/20261021__oatof-cpt-fixed-policy-reference-and-full-flow.md)
及[原生事件候选记录](history/20261022__sparse-counter-cause-and-native-event-reader.md)；更早阶段由这些快照回溯。
小模型控制变量、12 次 Compute、全部负结果与复现见[曲面与方程形式隔离](history/20261022__curved-events-and-formulation-isolation.md)。
COMSOL 实施步骤只在 COMSOL 文档维护，完整逐轮矩阵不再进入当前状态页。

- SIMION四个理想透明栅统一使用官方零grid-unit厚度的一行raw-PA电极点并由引擎原生穿越；任何Program
  epsilon越层、粒子位移或TOF补偿均被静态门禁禁止。Candidate SIMION门禁保存raw-PA行数与冻结单粒子
  `1/1/2/2`穿越receipt；真实丝网必须使用独立物理profile。Candidate run
  `20260813_160656__gate__simion__native-ideal-grid__smoke`已以SIMION 2020真实构建和飞行闭合该门禁：
  grid1/grid2/entgrid/midgrid分别仅占raw row `260/596/0/480`，冻结单粒子原生穿越`1/1/2/2`并命中探测器。
- 当前许可证不能使用SIMION 2026 `.wgem`，Candidate使用已验收的SIMION 2020 legacy-GEM四槽模板；
  许可证升级并完成隔离GUI/结构复验前不迁移路线。

详细失败矩阵与已关闭调查只在history保存，不作为current开放任务。

## 理想场探索的已验证范围

残差／束宽与仿射斜率比较仅证明受控一维机制。理论宽束重设计采用聚焦方程反求场强与长度，
再做独立粒子检验；原 2.8 mm 结果只约束原参数，不能作为三区结构上限。

| 冻结扫描 | 可支持的结论 | 证据 |
|---|---|---|
| 200 mm 总长 | 声明离散域内总体最大已测通过宽度 4.0 mm；三次独立 5000 粒子重复为 3.6 mm | [200 mm 快照](history/20260827__200mm-ideal-acceptance-scan.md) |
| 300 mm 总长 | 公平对照的 4.0 mm 冻结候选通过总体及三组粒子检查；支持总长是该受限域的有效自由度 | [300 mm 快照](history/20260827__300mm-ideal-acceptance-scan.md) |

最大已测宽度、单一冻结设计的接受范围与连续域全局上界是不同结论。上述证据不证明长度单调更优、
真实三维孔径接受或实测性能。重现与配置选择见[分析入口](../analysis/README.md#自动理想场比较)。

## 开放任务

1. **复现交付。** 按需从自包含Formal目录生成不含日志和收敛参考的ZIP及独立SHA；ZIP不是第二资产权威。
2. **按需求启动的物理候选。** 轴对称圆形加速器、真实丝网、制造/装配误差预算和二维轴对称混合
   COMSOL模型均暂缓；任何一项启动都须重新闭合理论、三维场、传输、网格、跨求解器与CAD。
3. **整合图形诊断能力。** 盘点活动COMSOL、SIMION、跨求解器与集成图形，合并重复的几何、轨迹、
   检查点、相空间、TOF和场诊断；为保留能力建立单一版本化能力目录、固定输入/输出角色和统一分析
   run生命周期，未入目录的实现须归类为测试、迁移历史或删除候选。关闭条件是活动入口不再各自维护
   重叠绘图代码，campaign只声明能力ID和受控参数，且现有Formal/Candidate证据不被重写。
4. **COMSOL 指标迁移的证据验收。** 当前实现已由 MATLAB 导出终态事件、Python 发布 canonical 指标，
   不再把实现迁移列为未做。仍需核对同一冻结 detector-arrival 表的 parity fixture 与真实 COMSOL
   golden 是否完整绑定；关闭条件是 FWHM、R、单位、时钟和 Formal 判定的等价性均有可追溯验收。
   在核验前不因源码迁移重写历史结果或宣称新 Formal 复验完成。
5. **JASMS Paper 1证据闭合。** 按
   [`publication/paper_1_jasms/validation_and_evidence_plan.md`](publication/paper_1_jasms/validation_and_evidence_plan.md)
   完成剩余先行工作、前瞻源输入、公平比较与独立验证；具体阶段、已完成证据及缺口只在发表目录维护。
   实时缺口只查
   [`publication/paper_1_jasms/evidence_matrix.md`](publication/paper_1_jasms/evidence_matrix.md)。关闭条件是候选
   主张通过prior-art gate，预测量能在锁定测试集区分可修正切向失配与不可修正条件厚度，并以受控统计、
   传输率、峰形尾部、数值收敛和独立三维复核支持；当前Formal结果不自动满足该条件。
6. **Analytical Chemistry Paper 2新工作。** 只有Paper 1核心诊断与知识产权顺序闭合后，才按
   [`publication/paper_2_analytical_chemistry/validation_and_evidence_plan.md`](publication/paper_2_analytical_chemistry/validation_and_evidence_plan.md)
   开展上游条件器、条件器—分析器联合鲁棒设计、样机/实验源测量与应用终点验证。关闭条件是产生不依赖
   Paper 1数据复用的独立实验资产、可复现工作流和相对于固定分析器基线的应用收益；当前仓库没有为硬件、
   商业求解器大规模运行或投稿作出授权。

7. **原生 CPT 数值配置与性能落地。** 先声明功能误差预算，再选择生产数值配置，不能直接采用诊断容差。
   关闭条件是目标样本验证、保存重开及 GUI Compute 对等完成并按原发布机制留证，
   不能凭上述 N100 诊断的局部收益更新 Formal。

以上为未完成动作；已闭合的实现及失败前驱见[整治快照](history/20261026__assembly-documentation-consolidation.md)，
更早证据由[项目历史索引](history/README.md)追溯。

## 产物与历史

新活动产物根为`artifacts/projects/single_reflection_oa_tof_mass_analyzer/`。重命名前的Formal、
Candidate run及归档已以原manifest项目身份只读迁入该根的
`archive/20260801_130003__migration-snapshot__repo__oa-tof/legacy-project-root/`。保留证据保持原文件名、
SHA、身份、资格和声明边界；迁移后按根README独立裁剪的可重建重型载荷只由pruning manifest追溯，
不得追加新run。current文档不复制完整run ID清单。旧RF投影诊断只见
[`history/20260727__superseded-rf-handoff-diagnostics.md`](history/20260727__superseded-rf-handoff-diagnostics.md)，
不得恢复为活动生产入口。

[reflectron-api-isolation]: ../../../../artifacts/projects/instrument_assembly/runs/20261026_045007__test__simion__reflectron-api-isolation/summary.json
[geometry-only-evidence]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261026_075441__test__comsol__geo/summary.json
[radial-owner-dry-run]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261028_230441__test__simion__radial-owner-dry-run/summary.json
[radial-p3-recovery]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261029_040300__test__simion__radial-handoff-p3/summary.json
[radial-p4-reanalysis]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261029_073507__test__simion__radial-p4-reanalysis/summary.json
[radial-gui-retirement]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261029_083000__test__simion__radial-p3-gui-r3/solver_review_retirement_receipt.json

## 机器能力与解析输入

profile 分别声明 purpose/action/tools；本次 release 物种由项目 binding 解析，Formal 入口保留其局部资格含义。
能力查询与执行编译见[公共合同](../../../common/contracts/README.md#执行dry-run)；READY 仅描述声明条件。

## 显式研究请求的位置

原 `workflows.experiment_campaign.run_campaign --campaign <JSON路径>` 接受外部只读研究数据。
可用 `python -m projects.single_reflection_oa_tof_mass_analyzer.workflows.experiment_campaign.run_campaign --campaign <JSON路径> --status` 查询。
所有 authority 仍严格相对于本项目，保留其原 SHA、预注册和科学域校验；外部请求不能提供执行代码。
prepare 一次读取并保留本次请求字节，执行在新 managed campaign run 冻结该字节，不受随后改源影响。
读取位置不改变既有输出根、运行身份、商业授权或资格要求。

## 候选与理想源比较的复用依赖

候选 workflow 分别绑定 `candidate_comsol_stage.py`、`candidate_simion_stage.py`、`candidate_cad_stage.py`
中的实际命令、模板选择和完成检查，以及既有输入与求解依赖；`candidate_stage_execution.py`
只保留薄路由和通用参数／报告运输。完整入口仍在 source closure 冻结。CAD 专属参数改变不使已完成的
COMSOL／SIMION 阶段失效；编排入口的报告或收尾文字变化可复用三阶段，
实际执行实现变化失败关闭。旧阶段 receipt 缺少新窄实现身份时不能自动追认；PA 缓存的原物理
身份和消费合同未改变，不能据此推断全部旧 PA 都须重求。当前阶段 receipt 仍包含阶段内分析，
这不是对任意旧分析变更均可复用整个阶段的承诺。

理想源比较将实际 `_settings`、工作点和传播执行移到 `numerical_case.py`；entrypoint 与 plot
保留来源但不再作为数值等价依赖。三类既有比较 role 从本 run 的冻结 analysis contract 核验并读取一次，将不可变 settings 显式传给 case／worker，后续不回读活动合同。完成 case 经原 checkpoint 与 CSV 身份核验后复用，数值源
变化仍拒绝；旧 run 缺新窄实现身份明确受阻，不修改原 run 或伪造等价证书。

现代窄依赖切换是独立软件主题；充分旧证据的新 run 投影仍是必要后续，尚未闭合整个科学复用工作包。
