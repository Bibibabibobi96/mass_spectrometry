# 单次反射正交加速飞行时间质量分析器当前状态

本文件是项目当前事实、资格与开放任务的唯一权威。机器精确值分别由[`config/`](../config/)中的物理、数值、
resolved、分析和资产合同管理；实现细节见[`COMSOL.md`](COMSOL.md)、[`SIMION.md`](SIMION.md)与
[`CAD.md`](CAD.md)。2026-07-28以前的完整状态和时间线冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 当前状态

- Candidate 准备直接把三份 SIMION 文本登记到现有 run_config 输入身份，不再生成或重写第二份
  `candidate_consumption_plan.json`。原子启动继续逐份拒绝文本篡改；COMSOL/CAD 模型路径由现有
  workflow plan 声明，builder、GUI 和径向 campaign 的文本路径不变。
  冻结源码路径解析只检查登记和路径边界；完整源码／Python 身份及目录扫描留在冻结完成、
  启动／物化、每个执行 stage 入口和成功发布前，不因同一 stage 多次取路径重复执行。

- 静态门禁覆盖隐藏 Windows 宿主的非法参数拒绝；分析测试失败时立即拒绝，不发布项目 PASS。
- 项目门禁与输入准备使用轻许可；独立入口在调用商业子流程前交还自己的轻许可，由子流程管理实际阶段。
  几何builder只在refine（含内部执行refine的Lua调用）阶段占重许可，飞行占重许可，结束后回到轻后处理。
  嵌套调用保留父许可，父轻许可不能被子流程擅自升级。异常路径释放本层许可；这项调整不改变几何、数值或既有资格。

- 理想源比较 [`run_comparison.py`](../workflows/ideal_source_comparison/run_comparison.py) 的实际计算分支
  复用公共 [`host_resource_python`](../../../common/host_resource_python.py) 外层重许可桥接；`--plan` 保持纯规划。
  调度依赖记录为独立的 `execution_source_sha256`，不纳入 `numerical_identity`，也不改变原恢复判据；
  入口源码原有身份检查仍有效，不能据此恢复任意旧版本。
  残差／束宽比较的case计划直接在内存消费，不再另写无人读取的`results/resolved_plan.json`；
  三臂实际电压／解的`working_points.json`、逐case记录以及配置／seed／源码冻结继续保留。
  [`radial_compaction`](../workflows/radial_compaction/run_campaign.py) 和
  [`reflectron_voltage_compensation`](../workflows/reflectron_voltage_compensation/run_compensation.py) 按完整飞行池函数
  申请一次 `flight` 重许可，函数退出后释放；普通准备和最终汇总不占重许可，也不声称有独立轻预算记录。
  已有父重许可只核验继承，父轻许可明确拒绝，不能清除token绕过。PA准备由PS builder负责自身阶段。
  原内部池、规划、观测、错峰、结果复用与续算不变；dry-run不申请飞行许可。本次只做无求解器回归，
  不构成真实OA飞行验收或完整动态调度资格。内部JSON结果只在系统TEMP的
  `host-resource-python-call-`临时目录传递，正常或异常返回均清理，不作为run证据。
  分类与继承见[主机资源调度](../../../docs/OPERATIONS.md#主机资源调度)。
  径向紧凑化不再物化无内容消费者的`contracts/candidate_diff.json`，恢复也不再将其存在性作为marker；
  baseline、resolved及数值合同继续供准备与SIMION builder消费。通用结构Candidate／Formal的同名diff仍参与
  runtime覆盖及零物理变化发布判定，继续保留；本次不改变共享编译器或既有冻结run。

- 分析入口的原始文件身份统一复用 `common/contracts/file_identity.py`，仍按原始字节输出大写 SHA-256，
  不规范化 run 输入的换行；已有不同 JSON 序列化合同保持原身份。理论 CLI 的递归预期值比较复用
  `common/contracts/expected_values.py`，不改变理论公式与容差。此复用只属于无求解器回归，不更新 Formal 资格。
  孔径分析的多项式残差诊断复用 `common/analysis/longitudinal_fit.py`，保留项目单位、字段与样本标准差口径。
- Static门禁通过包模块入口执行反射镜理论自检，使其公共合同导入与正常项目运行一致；活动三区理论合同的
  authority仅由现有authoring刷新入口更新。这些静态与无求解器检查不更新Formal或真实飞行资格。

- 正交加速器领域实现已拆到独立`orthogonal_accelerator`项目：纯二区／三区计算和器件构建从该项目
  调用，当前接口由`../config/accelerator_dependency.json`声明。本项目保留具体仪器参数、装配坐标、
  反射器耦合、整机CAD和整机验收。源码迁移不改既有Formal二进制、原始证据或资格；新的构建与运行
  必须冻结加速器提供项目的源码依赖，不能只冻结旧OA薄适配器。

- 当前批准设计为524 Da、+1正交加速TOF，双级环栈反射镜，一级10环、二级5环；粒子初始能量
  `5±0.4 eV`。
- 统一坐标以检测器有效面中心和精确一阶时间焦点为`z=0`，`+z`从加速器指向反射器。SIMION局部PA
  必须通过IOB变换映射到同一坐标。
- 2026-07-20的耦合纵向baseline是拆层前的历史Formal记录；它仍可追溯，但不再是当前资产身份。
- 科学合同、solver numerics和run instance拆层后，2026-07-29已以零物理变化的同源N=1000输入完成
  vNext验证与原子发布。`../config/project.json`、`formal_assets.json`、`formal_validation.json`和
  `simion_stable_entry.json`共同冻结当前Formal release；COMSOL GUI、SIMION GUI与SolidWorks CAD
  evidence均由独立evidence run及SHA绑定。一次性请求已
  [`归档`](history/20260729__formal-vnext-zero-change-requests.md)，不再是活动入口。
- 2026-08-02逐文件审计发现并从原validation run精确恢复`accelerator.pa2`与`accelerator.pa7`两个Formal
  解数组漂移；恢复后全Formal哈希与运行时门禁通过，四份Formal合同及既有资格身份未改变。SIMION活动
  入口现只运行manifest验证后的scratch副本，完整处置见
  [`history快照`](history/20260802__formal-simion-integrity-recovery.md)。
- 当前Formal加速器为闭合屏蔽结构，没有RF注入侧孔。RF多极杆连接使用run-local组合几何，不修改
  本项目baseline、MPH、SIMION包或CAD。连接策略、接地屏蔽、当前结果与资格边界只查
  [integration当前文档](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)。
- integration single-flight现通过项目Candidate
  `simion/workbench/candidates/oatof_analyzer_component.lua`调用oaTOF实例、基础场、静态电压与detector
  纯hooks；组件不声明Workbench/callback、电极setter、pulse时序或SIMION原生时钟。历史Formal Program
  字节未修改，仍只服务项目Formal与staged analyzer transport；该组件及唯一integration assembler的
  直接Lua验证不改变本项目Formal资格。
  Candidate组件的探测器数值标记只用于反射回程：到达反射器入口前不参与粒子终止，
  检测事件还要求负z速度；它不是允许遮挡出射束的机械探测器模型。具体实现与复验边界见SIMION文档。
- RF母样本到oaTOF粒子状态和SIMION方向角的连接专用adapter现由integration唯一拥有；本项目不再保存
  `analysis/rf_handoff_adapter.py`副本。required port、resolved几何和项目分析器组件仍是本项目对外边界，
  该所有权整理不改变粒子状态、时钟、Formal资产或资格。

当前生命周期、capability与Formal asset状态均为`formal`。历史资产和旧结论只按其原始manifest
身份保留，不能替代或改写当前release。

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

同资产CPU复测确认换用i9-9900K可缩短COMSOL粒子重追迹、SIMION Fly和PA Refine墙钟时间，且不改变
已核验的粒子结果；它只属于性能证据，不改变Formal身份。精确时序与哈希见run
`20260810_121500__benchmark__cross__cpu-formal-n1000`的manifest和summary。

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

跨项目2.2 mm理论源宽候选只验证了变量合同、理论闭合和run-local PA自动重构；没有修改本项目Formal，
也不改变Formal资格。完整结果只查
[integration当前文档](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)。

2026-08-17三区理论、真实PA验证和源臂敏感性已经完成，属于历史证据而非当前Formal状态；完整数字、
公式、run/manifest和限制已冻结到
[`20260823完成结果快照`](history/20260823__three-zone-completed-results-snapshot.md)。当前文档只保留
能力边界和开放任务，不在current层重复已完成实验叙事。

理想场数值源的残差/束宽扫描和仿射斜率机制比较均为已冻结的历史证据；它们只说明受控一维条件下的
机制，不授权实际三维孔径传输、分辨率或性能声明。数值、输入、负对照和适用边界分别见
[残差与束宽完成快照](history/20260827__ideal-source-residual-and-width-comparison.md)与
[斜率扫描快照](history/20260827__synthetic-affine-slope-scan.md)。

## 已知兼容边界

现有 Formal MPH 保持 Generalized-α／Strict；源码修复及下列诊断候选不追溯修改资产身份或资格。

| COMSOL 当前结论 | 已验证范围与限制 |
|---|---|
| 活动步策略与检测器实现修复 | 构造、重追迹、只读核验共用活动算法策略；零／近零平台、伪穿越和冻结查询下界修复有 57 项 MATLAB 回归。原窗 100 个平面事件复提取不证明有限有效面命中或时间收敛 |
| 同一 FEM、同组 N100 时间参考 | 校准最大 TOF 差 0.117375 ps，通过后同配置重复最大差 0.017286 ps；事件与采样状态门通过。只支持该时间协议，不是电场空间收敛或绝对物理误差界 |
| 真实主链合并读取 | 局部约快 2.76 倍，本次完整流程缩短约 2.82%；单次配对包含求解波动，不证明稳定整体收益。未通过的旧配置、手动缩放、稀疏输出及逐值一致性诊断保留原失败 |
| 稀疏事件读取限制 | 准确 st 不保证 Counter 完整或晚期坐标准确；已定位输出保存及边界归属链，未识别内部公式。StoreExtra、Counter 创建时机和单插时刻的结果均保留，不能作为任意模型的通用修复 |
| 原生五辅助变量候选 | GA／Newtonian 在原稀疏 N100、真实两壁面 50/50、同配置重复和保存重开范围通过；重复终态 CSV 字节相同。DP5 晚期辅助零值、交点身份未闭合仍为负结果；尚未接入生产或获得整机资格 |
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
   不能凭本次 N100 局部收益更新 Formal。

开放任务只写未完成动作和关闭条件。已完成的Candidate bootstrap、路径修复、receipt治理、历史失败
run和非零变量复验全部冻结在同日PROJECT history快照。

## 产物与历史

新活动产物根为`artifacts/projects/single_reflection_oa_tof_mass_analyzer/`。重命名前的Formal、
Candidate run及归档已以原manifest项目身份只读迁入该根的
`archive/20260801_130003__migration-snapshot__repo__oa-tof/legacy-project-root/`。保留证据保持原文件名、
SHA、身份、资格和声明边界；迁移后按根README独立裁剪的可重建重型载荷只由pruning manifest追溯，
不得追加新run。current文档不复制完整run ID清单。旧RF投影诊断只见
[`history/20260727__superseded-rf-handoff-diagnostics.md`](history/20260727__superseded-rf-handoff-diagnostics.md)，
不得恢复为活动生产入口。
