# 单次反射正交加速飞行时间质量分析器当前状态

本文件维护项目当前事实、资格与开放任务。精确输入以[机器合同](../README.md#机器权威)为准，
执行入口由[项目README](../README.md#活动入口)导航；跨项目整机状态只查[统一集成状态](../../../integrations/docs/INTEGRATION.md)。
Paper 1 专用研究准备API的归属与退出条件见[分析说明](../analysis/README.md#核心分析)。
已闭合的提供者迁移、回归及失败链冻结在[文档收口记录](history/20261026__assembly-documentation-consolidation.md)，
不把实现迁移、局部验证或旧运行自动提升为新整机资格。

## 当前状态

2026-10-31 原生保存与后处理拆分后，退役只锁 COMSOL core 文件位置/参数赋值字符串的重复检查；
探测器显式 x/z 与理论焦面的独立性改由真实纯几何投影行为覆盖，MATLAB resolved loader 与命名入口行为
仍负责非法坐标、派生矛盾及合同消费拒绝。Formal 合同消费/资产身份门禁保留，不将源码布局通过当作原生或科学资格。

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

COMSOL普通构建的绘图现只取原始完整解中的最多50列，不修改释放N或为大母群重跑`sol2`；科学事件和统计仍消费原完整母群。相同主题另移除“末点未靠近探测面就按8倍因子从头重解”的隐式策略：末点接近性不是合法检测事件，也不是时域截断或增量继续的充分证据。既有检测接受和事件窗口门保持；未发生检测事件不自动成为物理损失，未获得新的增量延长许可，不同观察时域须显式冻结新请求。

完整原解在提取／绘图前沿现有model.save写入原定MPH路径，之后同一路径更新GUI节点。原CLI已接通早期已保存解/context及充分CSV的后继分析，并沿公共owner恢复收尾；软件接线已有回归。相称的真实保存／冷重开及其后处理失败零重算验收仍待完成，保存调用和软件通过不能替代该原生证据。旧运行和Formal资格不改写。2026-10-30 R2025b旧版纯行为证据为68项通过、9.3942932秒（公共路径14、绘图3、检测33、solver政策18），无新增原生求解；修改后的当前软件范围以本页后续回归为准，不能沿旧文件身份宣称当前完整套件或新的整机／精度资格。

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
变化仍拒绝；旧 run 缺新窄实现身份时仅沿下述充分冻结证据派生，不修改原 run 或伪造等价证书。

旧基本 `ideal_source_comparison` 可从原 `--resume-from` 入口派生新的只读引用运行：只接受原冻结源码／完整输入、版本环境 identity、终态及每个 checkpoint／完整母群 CSV 均充分的已知 producer。旧 `_settings()` 曾读取活动路径，故每个复用 case 另用父冻结分析合同从原 CSV 精确重验已有峰形指标，不以今日默认值追认。原 CSV 作为显式绝对 input 与原 owner 的 `SourceReferences` 保存，不复制、不改行、不重采样；当前 case 数值实现身份保持不变，旧源码见证明确不是新执行实现。

读取与后继运行沿现有共享 terminal guard、原 owner 保护租约及释放／续租；后继只回到同一明确原 owner 验证，不递归猜历史格式。缺 source／版本环境／输入／owner、未完成 journal 或未封存 writer 均前置拒绝；CSV 不能重现冻结设置指标时保留原数据并报告重分析所需，不伪称旧科学结果已经确认。引用 session 的旧 CSV 新载荷为零；这不宣称原纯分析 workflow 已新增完整存储预算机制。历史 slope-scan／acceptance-theory 旧格式及未证明字节码不在此转换范围。

现代窄依赖与已知旧格式转换分别保留证据；其他未证明 producer 仍明确拒绝，不据此宣称任意旧结果或整个 Goal 已完成。

### 已知旧 Candidate 阶段的派生复用

当前项目投影只接受原公共 owner 已封存的已知 inline producer：原 manifest 必须绑定完整源码、执行 request、原规划与运行阶段参数／环境、独立成功 receipt、完整输出以及公共 writer completion。新 child 逐阶段证明旧命令构造与当前对应 solver 模块等价，再保留明确标为“原生成实现见证、不是本次执行实现”的旧字节、完整现代 context 和推导来源，沿原公共 strict matcher 复用。缺证据、科学实现／输入漂移或未知 writer 明确阻断；父终态不改写，不通过删键或今日默认值追认。

合法CPython缓存沿现`derive_candidate_source_closure(..., embedded_candidate_plan=True)`消费原manifest绑定的`candidate_workflow_plan.json.execution_source_closure`；容器role／身份必须属于原Candidate run，原root仍用于全部generator、dispatch和receipt证明，干净派生闭包只进入新run证据，不执行历史源码或缓存。普通strict verifier不放宽；无绑定、未知extra或损坏缓存继续拒绝。默认独立closure消费者（补偿）保持原合同。

纯软件回归覆盖 COMSOL 前缀及全部三阶段的派生复用、九项主要负例；未新启动商业工具或授予科学资格。旧 owner 必须仍具有原冻结 dispatch plan 和其来源路径；本格式的派生 child 没有原生成功 receipt，后继须显式选择原真正 stage owner，当前不建立递归兼容层。理想源旧比较的转换另行验证，不能据此宣称整个旧结果复用工作包已关闭。

当前公共GATE下的五方法联合首轮保留FAIL（76.055秒）：两个Candidate实际旧owner／缓存消费者、未受管目标拒绝及默认补偿闭包通过，Ideal正例因夹具保留父token却改选资源DB被正确拒绝。修正夹具保留实际同一hoststate，并显式运输一次解析的artifact／execution／hoststate后，仅该失败正例补验通过（19.693秒）；原父数据与完成事实不改写，未重复已绿方法或新增原生调用。

### 冻结 Lua 原生路径运输

受管 Candidate builder在实际Lua脚本argv达到Windows MAX_PATH边界时，沿既有执行alias运输明确冻结代码根；执行位置取本run配置已冻结的`paths.execution_root`，不随今天环境漂移，不复制PA或改变持久输入身份。别名及实际脚本后缀在启动前校验；仅已确认writer结束才清理。纯运输回归不代表新Refine/Fly或GUI资格。

## 反射器补偿公开支路的所有者

保留已有三臂电压补偿研究。原`run_compensation.py`不再原位修改父case，也不再维护
ThreadPoolExecutor、numpy分批或项目私有调度；实际求解参数与固定端点单调拟合保留。
实际来源必须遵守公共standalone消费边界；已发布native family的完整copy不能证明关联解除。
Program和
拟合profile在Fly前冻结，三臂仅使用进程局部环境和既有adjustable开关，批次间不覆盖科学文件。
正式首batch属于本次科学群，公共观测后保留；恢复沿公共whole-unit manifest核验与固定分区
调度，分析失败不重飞。所有小科学输入和原始完成事实随新run发布，父run终态与bytes不改。

默认N1000不变；显式N100消费父已封存ION；不能将结果升格为精度或性能资格。
原standalone缓存缺失时，显式`--numerics-path`由既有producer在同一个新owner中准备实际四实例
runtime，保留fractional ground语义。粗网格作者输入仅改变离散设置；真实几何/电压/原N100源不改。
`SourceIonPath`经原verified-copy边界复制冻结ION，默认producer不传参数仍生成原源。
父已发布native family不被vendor打开；旧逐PA copy、materialize receipt、重复IOB动作已删除。
producer返回原生完成receipt和实际Program/ION/IOB绑定；补偿与candidate共同消费项目
`native_stage_completion`窄适配，原始错误和receipt次错、未知writer继续保留，资源仍由公共owner释放。
粗producer/三臂普通功能仍在验收；计划预算约309.4MiB不能冒充实测内存或精度资格。
2026-10-30的N100粗网格运行`20261030_145031__sim__simion__compensation-coarse-n100`
完成四实例场构建后，父适配误读继承资源退出的null结果，173.183秒以writer未知停止，未Fly；
原记录和保护保留。`20261030_145701__sim__simion__compensation-coarse-n100-r2`越过该断点，
但冻结Lua路径长261字符时原生验证无法打开文件，许可正常释放并发布failed终态，仍未Fly。
继承退出合同已有真实公共函数回归；长Lua输入沿公共执行别名运输，持久IOB/PA仍做规范路径验证。
随后`20261030_150210__sim__simion__compensation-coarse-n100-r3`越过IOB验证、导出与拟合，
首批因SIMION预分配容量10不被支持而在实际飞行前退出。已沿既有入口规则改为最少100个预分配槽，
实际首批仍是原10行源，ID和分区不变；失败前驱不改写。
`20261030_150614__sim__simion__compensation-coarse-n100-r4`正常完成三臂各N100、各14完整批次，
每臂100探测记录；公开命令墙钟368.618秒。加速器与反射器响应复用已发布standalone缓存，新增响应Refine为0；
必要私有controller、ground及IOB准备仍实际执行，不计为零原生运行。仅支持粗网格三臂功能贯通，
不授予场精度、分辨率或补偿算法性能资格。
全复用`20261030_152653__sim__simion__compensation-reuse-r2`沿原CLI显式父manifest完成，墙钟63.972秒：
42完整批次引用、0原生启动、0新IOB/PA，父manifest身份不变，三臂分析均保持完整100 ID。
首次全复用检查因父代码目录多出17个生产子进程生成的CPython缓存而失败；严格验证器保持拒绝extra。
后继run只对manifest已绑定且与冻结源码静态编译字段一致的缓存生成独立父闭包派生证据，不执行字节码、
不删除父文件或覆盖本次源码；未来子进程禁写字节码。缺失或不一致证据继续拒绝。
运行和恢复命令见[分析API](../analysis/README.md#反射器电压补偿运行与恢复)。

本次公共路径、异常和跨根Result修订以软件行为验收：首轮44项联合运行保留FAIL（52.841秒），其中未受夹具修订影响的28项通过；修正临时仓库Python绑定及旧路径夹具后，两模块16项补验通过（66.344秒）。释放失败保留对象形式的主异常和独立次错，原CLI按原Result定位冻结根恢复，不重飞。上述20261030原生记录仅支持各自冻结实现，不自动变成本次新源码的原生或科学资格。

旧理想比较的reference-only恢复仅写入公共路径上下文选定的`projects/<本项目>`受管目录；`MASS_SPECTROMETRY_ARTIFACT_ROOT`可选择非默认短根。每个新run冻结本次实际paths，运行内不重读环境默认。此新legacy分支不把任意Python API输出目录自动当容量owner；未受管目标在租约/CSV读取前明确拒绝，普通非legacy API行为不变。跨根来源仍要求公共SourceReferences已有充分冻结capacity-owner证据；无该证据的旧源不按目录猜根。

## 局部理想场诊断与重分析

`simion/workbench/run_ideal_field_diagnostic.ps1`的正常运行只准备一次实际消费的隔离SIMION runtime，
并通过`verify_geometry_contract.ps1 -PreparedRuntime`核对该runtime的IOB、Program、几何、优先级与场；
使用其自带冻结resolved合同，不先物化另一份验证副本。正常物化前仍执行既有Formal可读性guard，`formal_revalidation_pending`提前拒绝；局部runtime核对不授予Formal资格。完整CAD、COMSOL与历史Formal资格仍由
`workflows/formal_reference/verify_geometry_contract.ps1`默认显式入口验证，不是局部诊断前置。

重分析使用原入口的`-AnalyzeOnly -SourceRunPath <已封存诊断run> -RunId <新analysis ID>`。
它在公共终态消费guard内按父manifest的consumer projection核对并冻结实际24份日志、4份ION及父控制，
继承父N和seed，只做日志分析与新结果发布；不生成ION、不准入SIMION、不物化PA，
也不要求未消费的当前Formal、CAD、MPH或SIMION安装存在。缺日志或源身份不匹配明确失败。
这两条路径都不重新授予Formal资格；分析沿既有出生相对时钟、母群和Gaussian proxy定义。

`mass_spectrum_candidate`仅把原纯几何新鲜度移到正常新run的实际prepare：原Formal可读guard先执行，pending仍拒绝；guard允许后冻结原纯resolver及实际输入并检查同snapshot的resolved。Resume／ReanalyzeOnly继续消费该run记录的冻结输入，不重新绑定今天baseline。未调用sync、跨求解器资格、GUI或CAD，也未解锁Formal；本次软件回归不能替代该入口缺少的科学验收。

两个入口的新run沿公共workspace resolver选择根，并向原NewRunPackage传同一PathContext；原生别名显式使用该冻结执行根，嵌套调用沿同一主机状态，退出后恢复调用者环境。科学结果合并进原包配置，保留paths、schema、容量owner与其它公共字段。质量谱续跑只接受原run记录的完整paths及匹配的run/root/容量身份；较早记录缺少这些证据时明确阻断并给下一动作，不以今日默认补造旧根。

质量谱封存记录的后继分析与恢复，见[质量谱封存记录重分析](#质量谱封存记录重分析)。

### 完整软件验证分片

项目软件验证从公共`common/verify.ps1 -Scope Owner -Owner single_reflection_oa_tof_mass_analyzer`进入。源码／fixture／Owner／Repository范围沿公共GetGateRepositoryTestPartitions使用4个计权分片；原发布新鲜度、几何检查与理论前置执行一次，分片依赖此前置通过，保留实际测试的PS／Lua及公共owner接线责任。原Candidate／Formal物理与发布动作保持，拒绝混入软件分片参数。direct SelectedTestModules默认先跑原前置；内部PreflightValidated只供已完成同轮前置的调度。

20261031终态旧完整范围为PASS：公开summary833.605112秒，SFI stage750.056879秒／execution736.4489991秒。69个原analysis模块已计时测试合计727.917333秒；权重来自该轮完整test_durations，不把stage或并行耗时相加。热点candidate_design259.299669、managed_candidate_pa145.080768、radial_compaction_campaign66.727523、compensation_powershell_adapter57.008262秒。分片只是相同职责的调度，尚未实测新完整Owner公墙，不能据规划时间宣称达到5分钟。

完整测试集合统一按tests递归，显式纳入原discover tests/analysis漏掉的根直属与simion各1个既有模块，加本主题薄接线测试；模块union随实际文件派生、不硬编码数量。纯Changed仅现存测试模块仍保已验证快路径，fixture／删除／未知范围不静默减为小测试。原单次顺序discover实现被同一模块集合／显式分片调用替代，不删有效测试或另建scheduler。

当前1c9f9f1c源码包含analysis69＋原根／simion各1，加本主题薄test为72模块，集合始终动态发现。先前5756ca42独立闭包曾为70模块；初始三片旧权重规划259.299669／232.138514／232.138435秒仅记录历史规划，不是当前模块时长预测。candidate模块后来增加legacy正例（另有Root36.360／27.225秒单独补验）及负例，旧259秒不能精确预测当前成本；不强改权重制造达标。完整Owner公墙及资源等待仍待实测，实际CPU预算可能只允许两个分片同时运行。原漏simion模块会通过SIMION官方CLI仅执行pure Lua回调（无PA／Refine／Fly），后续完整运行须单列该进程事实，不称零SIMION启动。

本主题独立闭包小回归：真实项目PS入口与公共selector／partition薄4项通过9.267秒；原角色选择／失败释放及纵向解析理论代表2项通过4.303秒（逐项4.294660／0.008015）；显式false资格参数拒绝扩充后仅受影响方法再验5.816秒。公共GATE自然释放；未执行新完整Owner或商业／Lua原生验证，完整性能目标尚待实测。

2026-10-31 新完整Owner轮仍为FAIL：外层公开命令486.585582秒，643条逐测试计时；前置与两个分片通过，分片02的一项observer故障注入失败。三个分片execution分别452.315889／372.154132／411.919764秒，资源等待约2.1秒／片。真实SIMION只执行一次既有官方Lua合同测试（0.093274秒），没有Refine或Fly。原失败轮不被定向修复追认为PASS；该fixture实际误导入正式observer的问题已独立复现并修复，仍需最终联合回归。旧833.605112秒轮与新轮覆盖不同且有并行背景任务，不计算加速倍数；当前公开Owner仍超过5分钟目标，candidate重复完整准备与新增mass恢复测试权重失衡继续处理。原summary、逐测试、外层wall与日志位于本主题`agent4/rebase_1c9/root_owner_r2*`，不以规划权重代替实测。

候选旧资产8类拒绝回归继续保留；7类改为同一真实冻结准备上的严格projector负例，unknown writer仍经完整公共owner失败传播。完整失败执行8→1、子准备8→2；该方法旧完整Owner中76.437936秒，修后定向40.990342秒通过，背景负载不同不宣称公平倍速。原完整owner正例与cache正例不变，最终Owner预算仍待联合实测。

2026-10-31 四分区完整Owner已PASS：643条逐测试计时，公开墙钟304.537123秒，summary302.817740秒；仍超5分钟目标4.537123秒，性能未达标。各片execution275.144611／255.513878／249.077378／261.496516秒，前置7.089548秒。正常公共GATE自然释放，既有SIMION仅一次pure Lua合同检查，0 Refine／Fly。随后只按该PASS轮74个模块的实际方法耗时更新既有catalog权重，测试和资源预算不变；新权重规划约255.45秒／片，不是新的实测墙钟。原失败486.585582秒轮保留，背景负载和单项修复不同，不计算公平提速倍数。完整证据为该主题`agent4/root_owner_r3_summary.json`及`root_owner_r3_wall.json`。

相同74模块／643测试、四片各2 CPU／2 GiB预算的重权复测已PASS：公开墙钟289.686529秒（4分49.69秒），summary288.056752秒；四片execution257.655101／260.978308／258.380666／263.218780秒，资源等待约1.87秒／片。本机16逻辑CPU参考环境达到代表性Owner不超过5分钟的目标；仅权重变化的前轮304.537123秒同为PASS，减少14.850594秒。此结论只针对本Owner软件范围，不代表宽范围／完整Repository预算或科学资格。两轮完整记录在该主题`agent4/root_owner_r3*`、`root_owner_r4*`，失败r2轮仍保持FAIL。

### 质量谱封存记录重分析

`mass_spectrum_candidate -ReanalyzeOnly`使用显式`-SourceRunPath`和新的`-RunId`创建后继分析run；父run的输入、CSV、报告、配置、summary与manifest只读，不再执行原位预检或重新发布。其准入先核对实际消费的小记录和原容量owner的ready封存；checkpoint还须`-SourceStoppedReceiptPath`指向原owner已生成的停止receipt。只有运行中的interrupted标记、未知writer、writing范围、缺失或篡改记录均拒绝，并要求回原owner补齐收尾／封存，不由分析入口伪造停写证明。跨根来源沿公共SourceReferences绑定明确manifest与原owner，不猜父根。

重分析直接调用原`analysis.mass_spectrum.analyze_mass_spectrum`，保留每物种COMSOL完整检测、SIMION全母群检测、精确ID／物种／电荷及原峰形、校准和绘图规则。冻结小Python闭包和父manifest绑定的resolved资源，因reference分析在import时读取该几何中的detector中心，不能换用今天默认值。原CSV受保护引用；PA、MPH及ION不复制、不重新物化、无求场或Fly，也不读取未消费的今日Formal资产，今日Formal不可用不阻断充分封存记录的分析。原`ResumeAfterComsol`仍是既有执行续跑，不属于这条新分析路径。

原入口示例（从仓库根执行；8MiB是本次显式小代码／metadata／图表／收尾承诺示例，按实际输入与余量选择，不是隐藏默认或父求解预算）：

```powershell
.\projects\single_reflection_oa_tof_mass_analyzer\workflows\mass_spectrum_candidate\run_mass_spectrum_candidate.ps1 `
  -ReanalyzeOnly -SourceRunPath 'D:\artifacts\projects\single_reflection_oa_tof_mass_analyzer\runs\<sealed-parent>' `
  -RunId '<new-analysis-run-id>' -AnalysisNewBytes 8388608 -PythonExe .\.venv\Scripts\python.exe
```

分析进程的argv文件、cwd、环境和日志沿运行包的`Get-RunNativeExecutionContext`投影；Python支持的持久深源码import root保持原冻结身份，临时alias由公共owner收尾，不复制源码根。公共GATE普通轻量策略负责CPU／内存准入；分析Python进程沿现有observer记录真实PID、启动、退出及host释放。该调度承诺不是新增硬进程内存帽；现有物理危险监测仍适用。小Result默认在项目`scratch/workflow_results/<RunId>/result.json`。收尾中断使用同CLI的`-ResumeFinalization -RunId <analysis-id> [-ResultPath <原Result>]`，只恢复公共owner收尾，不重分析、不启动求解器；显式Result绑定原冻结根，不随今日根改变。分析本身失败则用原充分父记录创建另一个新分析run。主异常、收尾异常和未确认释放分别保留，不把host释放未知当作粒子或科学结论。

产物仍为六项质量谱CSV／metrics／PNG及本run公共summary、manifest、Result；原有candidate边界、`resolution_claim_allowed=false`及未资格化的时钟说明保持，软件成功不授予新的Formal或全链资格。旧host-role矩阵中缺少封存父输入的伪分析case由`test_mass_spectrum_input_admission`实际公开CLI→分析→公共GATE释放和恢复测试替代；普通mass/SIMION角色case保留。

### Candidate测试职责与分片边界

原candidate88个测试按相同class／method名迁至设计20、工作流64、legacy复用4；完整test ID的module前缀相应改变，不伪称旧完整字符串未变。原12个非test helper及inline legacy freezer仅由不继承TestCase的fixture mixin共享，支持模块没有test_方法，消费者不导入／继承任何旧TestCase。保留最新legacy8→2准备优化及所有原断言、故障／母群／源身份行为。公共发现自然枚举3模块，单独软件runner／并发器没有增加。

4片计权沿现catalog和GetGateRepositoryTestPartitions；新3模块权重来自既存643timing对原88case的分组聚合：设计2.165402、workflow280.454321、legacy164.302084秒。该轮早于最新legacy去重复，背景负载不同，权重仅历史调度提示，不称当前精确预测。旧643轮全部已计时测试1219.428485秒，理想4路均分仍约304.857秒，未计前置／启动／准入；拆模块消除446.9秒单模块瓶颈，不单凭规划宣称Owner≤5分钟。现本机16logicalCPU与每GATE2CPU／2GiB原则上可准入4片，但实际可用CPU／内存／互斥与CI环境仍由原公共机制决定；未擅自降低预算或套用跨环境速度。后续仅以安静环境完整Owner真实墙钟验收。

catalog所有模块权重现统一来自同一643轮完整test_durations；原单模块candidate权重替换为88方法的分组总和，未把不同负载的新定向结果混为精确预测。软件迁移证据为88原方法AST／12helper AST一致、unittest真实discovery及全限定module load均88唯一，完整old→newID映射一对一。拆分代表设计1项1.115214秒、工作流及原8类legacy拒绝的3项65.291秒（7.910438／40.598032／16.782589）通过；纯fixture位于已分类test_support。初始隔离闭包缺原声明小文档导致3ERROR，补该原Git文档后通过，候选源码未改。两个现公共consumer薄回归保动态count／完整union／父依赖／纯Changed：partition方法0.981284秒通过，公共Planner在单项目实际route fixture中5.944760秒通过。完整catalog库存检查因隔离树不复制大PA而未在该薄fixture冒通过；原失败日志保留，Root最终完整环境另验。未重跑完整Owner／商业工具，不据此宣称性能目标已达。

### Candidate COMSOL 后处理恢复

正常结构 Candidate 在完整 `sol2` 保存后记录实际解标签、输出时间、母群及冻结科学输入的后处理 context；正常与冷提取使用同一 MATLAB 后处理实现，原事件窗口与全部100粒子命中要求保持。`FieldDesignOnly` 不构成粒子完成证据；质量谱及 Formal 的独立 retrace 不属于此入口。

原 `run_candidate.py --postprocess-from <封存父run> --run-id <新identity>` 创建仅 COMSOL 后处理子run。充分封存CSV可直接运行原Python分析；缺CSV但完整保存解、原生停止、manifest、冻结输入及context充分时，冷开父MPH只提取，不求场、不重飞、不另存父模型。父模型只通过公共 SourceReferences 保护引用；子run只发布实际小CSV、PNG和分析结果，不宣称完整 Candidate 或后继复用 READY。缺依赖、未知writer或保存尺寸/解时间/母群不符均拒绝，不自动求解。

冷提取完成而分析失败的封存后处理子run也可作为同一入口的显式父：仅消费充分CSV，直接绑定原science owner与实际CSV exporter的一跳manifest及原母群ION，不递归寻找模型、不要求原MPH仍存在、不借今日默认补物理。新child沿公共SourceReferences同时保护实际父、science与export owner，原父全记录只读。收尾使用原CLI `--resume-finalization <子run>`，不重分析、不启动原生进程。

该模式冻结本次明确分析合同和父绑定的几何资源，沿原 `analyze_comsol_detector_events` 分析，不使用今日几何补旧输入。正常完整stage复用时还比较原实际分析权威：相同才复用旧分析；改变或旧authority缺失但事件充分时只重分析，保原native结果，不重飞。分析实现源码仍属于原整个COMSOL stage source集合，相关改变的过度失效尚未收口，不能称完全因果复用已完成。

跨根保护使用公共 `capacity.source_references`；仅需冷模型时声明 `prepared.native_input_paths`，实际MATLAB输入从公共source execution context唯一投影，持久request/results保持原canonical身份，输出保持child执行表示。项目不另建alias或复制模型；公共源运输的软件接线不等于真实深路径COMSOL冷开已经验收。新字节承诺来自显式父 Candidate runtime 的 `artifact_capacity.evidence_bytes`，既有CPU/内存准入仍适用；这不是新增COMSOL硬时间/RSS帽。失败保原数据身份与unknown有效性，不因后处理异常宣称物理数据无效。

普通与冷后处理现沿同一公共helper对原提取时间向量作两遍有界API读取，保留跨窗相邻状态与完整母群统计，检测分类由同一项目reducer实现。实际COMSOL分窗、模型冷开、源身份与零求解仍需相称原生验收；软件测试不授予精度、完整传输或Formal资格。

冷提取的完整 detector CSV／request 经原全母群检查及公共 stopped-writer／release 验证后，先记入本次 evidence，再进入 Python 分析；分析失败不丢失已完成导出事实。恢复提示引用本失败 child 的 CSV，而非再次冷开原 MPH；须先完成该 child 的公共封存，原 CLI 的 ResumeFinalization 仍只收尾。未知 writer 不给出可重开提示，保留原保护。此接线以明确软件替身的冷边界、真实公共 owner／原 CLI 分析与父只读回归验证，不是 COMSOL 冷开或科学资格证据。


2026-10-31 当前公共源路径运输与OA恢复提示整合后，Root在正常权限／独立任务TEMP运行两项实际CLI恢复回归通过：测试64.754秒，公开墙钟68.7278秒，GATE正常释放。覆盖软件替身冷边界后的分析故障→公共failed封存→按提示从本child的CSV新建零原生分析→Resume，以及未知writer提示。此前最终重复轮265.617秒FAIL保留：第二CLI容量已满足，启动调用返回0xC0000005，prepared未启动，随后超时／临时清理失败；该轮不被本次PASS改写。PID33388的退出尚未确认，原运行及公共保护不擅自清理。此为软件恢复证据，不是新的COMSOL求解或科学资格。


### COMSOL已解数据的两遍有界读取

正常／冷提取共用后处理沿原exact extract_times向量分成256行API窗，并以同一项目科学reducer两遍处理。首遍保留全母群全局转向点、有效范围／缺口、最终XYZ及128ULP坐标尺度；次遍累计末端suffix、零点后负侧确认的最早穿越及原接近段，最后沿原优先级及8ULP时间界分类。原oatof_extract_detector_arrivals成为同一实现的薄数组adapter，原检测半径、冻结容差、0.5mm接近窗及事件／状态语义不变，未知不推断物理损失。逐ID事件行号仍指向原查询向量。

客户端不再分配M×N的三坐标矩阵或MAT spool；仅保留单API窗、O(N)统计及原始前min(N,50)列XZ绘图，全部粒子仍参与检测、穿透深度和原细窗口门。W256／N5000的257行三坐标数值载荷约30.84MB，不等于进程RSS预算或自动内存优化。两遍约2*ceil(M/256)次API调用，可能增加读取成本；这是有界性改造，不宣称提速。原数据集、源、查询时刻binary64值和精度、求解与接受条件保持，不触发重求或降低采样。

原33项检测事件物理矩阵经薄adapter／唯一reducer通过（MCP外层1.2701544秒）；该首轮尚未覆盖分窗及大N helper。原owner随后以MCP验证完整两类46项（36项检测／10项绘图与真实共享helper，包括N100／1000／5000按请求窗生成），0 Failed／0 Incomplete，外层13.4216991秒；全部母群事件和50列绘图检查通过，公共GATE自然释放。CodeAnalyzer的helper／adapter／两测试无问题，reducer仅未用survey局部t赋值，随后机械删除，不改算法。实际COMSOL保存解冷读及进程RSS仍待相称验收，未据纯夹具授予数值、完整传输或Formal资格。


Root补充在实际公共freezer生成的150源闭包中，以冻结comsol目录作为MATLAB当前目录，执行前后确认postprocess／array adapter／reducer三个生产函数均来自冻结树：两类46项PASS，公开MCP墙钟11.8644秒；现有Python冻结依赖薄回归1项PASS1.595秒，GATE均已释放。独立一次性旧HEAD oracle对120个小矩阵／240条轨迹作942次完整result比较（多窗及重叠），全相等、1.6579秒；旧函数仅供scratch对照，不进入生产或建立第二分类器。此为软件语义与冻结接线验收，真实COMSOL API时间窗／RSS仍未验证，也不宣称两遍读取提速。

Candidate 编译器可显式接收 solver_numerics_contract（编译 CLI 为 --solver-numerics-contract）；省略时仍使用原项目数值合同。选择的纯 JSON 原字节只冻结一次到 candidate_solver_numerics.json，现 resolved 输入身份及实际消费者继续绑定该副本，后续不重读外部源或默认值；物理 baseline、源、粒子数及现 profile 支持域不因此改变。唯一数值层校验检查原 role／顶层键／求解采样 policy，并拒绝非真实整数1的版本及现五个网格／时间步键的非有限、非正数和 bool。粗网格属于明确功能验收配置，不授予精度、收敛或 Formal 资格；正常 workflow 的公开参数运输随其真实 consumer 接线验证，不能仅凭编译器 API 宣称完整原生链已通过。

差异报告的 provenance.formal_solver_numerics 是原 Formal 数值比较基准，provenance.solver_numerics 才是本次选入的实际数值源；执行仍绑定冻结副本。zero_change_reference_reproduction 仅在物理设计未变且实际冻结数值身份也等于该比较基准时为 true，显式粗网格不能误标为原数值复现。

Root 验证显式数值编译主题：正式 common/verify.ps1 对完整 test_candidate_design 模块及必要前置 PASS，25 项测试 4.269 秒；冻结外部字节、默认物理不变、真实编译 CLI、非法版本和网格／采样值拒绝均覆盖。该范围不代表完整 Owner／Repository 或原生求解验收；最新 1a428 CI 的五项 Candidate 失败仍独立处理。

### Candidate 显式数值输入与运行根

正常结构 Candidate 入口可用 `--solver-numerics-contract <只读JSON>` 显式选择既有数值合同；不提供时保持原默认。实际选择一次冻结为 `candidate_solver_numerics.json`，由同一个 resolved 编译器和后续 COMSOL 真实消费。它不是新的 profile，也不扩大现有 ValidatedStructural 的 midgrid-only 物理支持域；仅改变数值输入不授予 Formal 或精度资格。差异报告绑定实际数值来源，显式非基准数值不能称零变化 Formal reference reproduction。

从仓库根可先执行正常入口纯准备（请求仍须满足原批准和相邻 `candidate_proposal.json` 绑定，所选运行根须具有现已登记的非Formal模板）：

```powershell
.\.venv\Scripts\python.exe -m projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate `
  --request '<approved-request.json>' --run-id '<new-valid-run-id>' --particle-source-seed 20260720 `
  --solver-numerics-contract '<explicit-numerics.json>' --dry-run
```

执行时去掉 `--dry-run` 并按原入口提供 `--simion-exe`。CLI、runtime 模板检查和纯 prepare 默认运行根统一消费 `common.paths.resolve_workspace_paths`，包括既有 `MASS_SPECTROMETRY_ARTIFACT_ROOT`；显式传入的项目根优先，已冻结 run/Resume 不按今日默认值改根。源码快照位置不再反向决定新输出根；缺登记模板仍明确拒绝，不跨根搜索同名资产。`--postprocess-from` 和 `--resume-finalization` 拒绝新的数值或执行选择，不默默忽略它们。

独立冻结软件回归经公共 GATE 2 CPU／2 GiB：正常 CLI 真实编译、非默认产物根、显式数值字节与 authority 对齐，以及两种分析／收尾选择冲突拒绝，共2项通过2.779秒；补实际 reproduction=false／来源绑定断言后仅受影响正常入口方法复验2.603秒。均未启动商业程序、求场、Fly 或发布正式资产，dry-run成功仅表示该准备范围完成。


### Candidate 原生保存与后处理实现边界

完整 COMSOL core 的几何／求场／粒子及早期 raw-save 前缀原样迁入唯一 oatof_build_saved_particle_solution；save 与 context 两个既有局部函数也迁为唯一 helper。normal core 仍实际调用该实现，GeometryOnly／FieldDesignOnly 早返与原保存次序不变；后处理后同路径更新 GUI 的行为仍保留。此拆分不单独证明阶段因果复用已闭合，尤其不能忽略 GUI 尾部的实际科学状态及再次保存。

正常 Candidate task 与已准入的冷提取共用原有的100粒子／全命中、环数、六段时间 token 及 pdset1→sol2只读检查。六token检查同时修复原scalar contains多pattern只需任一匹配的实现缺陷，逐项缺失仍拒绝；物理要求没有放宽。新纯测试由原正式MATLAB测试runner默认发现。命名入口只以canonical OutputModelPath校验允许根，实际写入保留公共owner提供的执行表示。

Root纯MATLAB首轮28项为22PASS／6FAIL（29.484秒）：五项夹具误期望非空assert identifier，另一个时间token用例揭示上述真实缺陷。修后仅重跑validator，12项PASS（外层3.809秒）；前轮ArtifactContext11项与PlotView10项已PASS，distinct覆盖合计33项，不将两轮误称同轮全绿。相对9ba的929行前缀除两个helper调用名外全文相同，原数值／物理及保存顺序保持。尚未执行本实现的真实COMSOL求解／保存冷重开或GUI验收；这些软件证据不授精度、完整Candidate、Formal或整个Goal资格。

整合后原正式 MATLAB 软件测试 runner 实跑82／82 PASS，MCP外层19.523秒，包含新validator默认接线；它是软件runner，不是Formal科学资格。实际冻结闭包回归PASS2.128秒、冷任务运输回归PASS3.643秒；首次第二方法误用类名导致发现错误，修正类名后仅补跑该方法，不计原错误为通过。新core与validator Code Analyzer无问题，搬移builder仅有输出初始化的未用赋值提示。


### Candidate COMSOL 原生临时目录与冷提取容量

只需已有CSV的后处理仍仅承诺原冻结runtime的evidence_bytes（当前合同64MiB），不启动COMSOL、不把父MPH算作新复制。确需冷开时，沿同一现有容量请求额外保留父已冻结的comsol_bytes工程余量（当前合同4GiB），用于实际原生temporary／recovery写入；这是沿已有预算的保守工程承诺，不是已测冷开峰值，不保证任意模型都可容纳。模型记录本身超过该余量时在商业启动前拒绝，要求明确重新评估请求，不能以无另存父MPH推断零临时写。原输入与parent manifest不改写，生产minimum free、物理资格与CPU／内存策略不变。

normal build／sync、CAD的COMSOL打开及cold后处理均向既有launcher传入公共owner提供的执行run目录作为RunDir，使实际temporary／recovery归本run并进入runtime_storage观测；项目不新建临时目录平台或alias。公共路径运输的其余边界仍按正常owner负责，此处不以运输软件测试冒充COMSOL已开模型。

独立HEAD闭包经公共GATE 2CPU／2GiB定向3方法PASS14.535秒（预算9.064／normal1.910／cold运输3.561），随后仅追加真实CAD命令边界sentinel断言的normal方法复验PASS1.935秒；无商业启动。测试使用明确opaque3B元数据载荷，验证原预算／拒绝不足余量、CSV轻量分支、完整请求冻结、父字节不变和真实argv，不代表有效MPH或求解。首轮FAIL5.652秒保留：隔离源码缺已提交reducer及cold fixture错误compact保留类；补真实声明依赖、首次fixture发布前使用原solver_review类后通过，未放宽生产政策。真实native临时峰值与硬资源限制仍以正常入口实际观测／显式请求为准。


### 2026-10-31 候选分析合同测试接线

候选计划和发布测试核对实际冻结的 `candidate_analysis_contract.json`、来源闭包与 manifest 身份。
原锁定 MATLAB core 内导出调用位置的字符串测试退役；Python 指标与非法 metric owner 拒绝行为保留，
保存模型验证另由现有 MATLAB 行为套件承担。两项候选测试及整个 detector 分析模块共4项通过（8.741秒），
公开命令墙钟14.938秒；这是软件定向验证，不代表最终 CI、原生求解或科学资格完成。
