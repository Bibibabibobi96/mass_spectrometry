# 单次反射正交加速飞行时间质量分析器当前状态

本文件是项目当前事实、资格与开放任务的唯一权威。机器精确值分别由`../config/`中的物理、数值、
resolved、分析和资产合同管理；实现细节见[`COMSOL.md`](COMSOL.md)、[`SIMION.md`](SIMION.md)与
[`CAD.md`](CAD.md)。2026-07-28以前的完整状态和时间线冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 当前状态

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

## 已知兼容边界

- COMSOL 6.4当前模型在极小求解粒子数路径存在非单调原生不稳定；日常使用N=100，逻辑小样本仅在
  无粒子间耦合时由同源N=100承载后分析前缀。该绕行不属于开放调查。
- SIMION四个理想透明栅统一使用官方零grid-unit厚度的一行raw-PA电极点并由引擎原生穿越；任何Program
  epsilon越层、粒子位移或TOF补偿均被静态门禁禁止。Candidate SIMION门禁保存raw-PA行数与冻结单粒子
  `1/1/2/2`穿越receipt；真实丝网必须使用独立物理profile。Candidate run
  `20260813_160656__gate__simion__native-ideal-grid__smoke`已以SIMION 2020真实构建和飞行闭合该门禁：
  grid1/grid2/entgrid/midgrid分别仅占raw row `260/596/0/480`，冻结单粒子原生穿越`1/1/2/2`并命中探测器。
- 当前许可证不能使用SIMION 2026 `.wgem`，Candidate使用已验收的SIMION 2020 legacy-GEM四槽模板；
  许可证升级并完成隔离GUI/结构复验前不迁移路线。

详细失败矩阵与已关闭调查只在history保存，不作为current开放任务。

## 开放任务

1. **复现交付。** 按需从自包含Formal目录生成不含日志和收敛参考的ZIP及独立SHA；ZIP不是第二资产权威。
2. **按需求启动的物理候选。** 轴对称圆形加速器、真实丝网、制造/装配误差预算和二维轴对称混合
   COMSOL模型均暂缓；任何一项启动都须重新闭合理论、三维场、传输、网格、跨求解器与CAD。
3. **整合图形诊断能力。** 盘点活动COMSOL、SIMION、跨求解器与集成图形，合并重复的几何、轨迹、
   检查点、相空间、TOF和场诊断；为保留能力建立单一版本化能力目录、固定输入/输出角色和统一分析
   run生命周期，未入目录的实现须归类为测试、迁移历史或删除候选。关闭条件是活动入口不再各自维护
   重叠绘图代码，campaign只声明能力ID和受控参数，且现有Formal/Candidate证据不被重写。
4. **COMSOL canonical 指标迁移。** 现有 MATLAB/COMSOL 链既生成 GUI 用 Gaussian/KDE FWHM，又在
   全链 Formal 测试中独立计算并断言 resolution；SIMION 单飞链的 canonical 分析在 Python。先为同一
   冻结 detector-arrival 表建立 Python 指标与现有 COMSOL Formal 数值的 parity fixture，再将 COMSOL
   导出接入该 Python 分析器，最后才移除 MATLAB 中决定资格的重复计算。关闭条件是两条链共享同一
   已版本化指标实现或有明确的非权威 GUI 派生物，并以真实 COMSOL golden 证明 FWHM、R、单位、时钟
   与 Formal 判定未退化；不得靠重写历史结果或调宽容差达成。
5. **JASMS Paper 1证据闭合。** 按
   [`publication/paper_1_jasms/validation_and_evidence_plan.md`](publication/paper_1_jasms/validation_and_evidence_plan.md)
   继续完成人工核心全文逐式claim chart、预注册源分布、条件可聚焦性实现、公平再优化、消融、三质量与
   三维跨求解器验证；2026-08-25定向论文/引用链/专利族预审已完成并把候选主贡献收窄为J2/J3，见
   [`publication/prior_art_search_audit_20260825.md`](publication/prior_art_search_audit_20260825.md)，但该预审
   不等于专业FTO或novelty gate关闭；
   实时缺口只查
   [`publication/paper_1_jasms/evidence_matrix.md`](publication/paper_1_jasms/evidence_matrix.md)。关闭条件是候选
   主张通过prior-art gate，预测量能在锁定测试集区分可修正切向失配与不可修正条件厚度，并以受控统计、
   传输率、峰形尾部、数值收敛和独立三维复核支持；当前Formal结果不自动满足该条件。
6. **Analytical Chemistry Paper 2新工作。** 只有Paper 1核心诊断与知识产权顺序闭合后，才按
   [`publication/paper_2_analytical_chemistry/validation_and_evidence_plan.md`](publication/paper_2_analytical_chemistry/validation_and_evidence_plan.md)
   开展上游条件器、条件器—分析器联合鲁棒设计、样机/实验源测量与应用终点验证。关闭条件是产生不依赖
   Paper 1数据复用的独立实验资产、可复现工作流和相对于固定分析器基线的应用收益；当前仓库没有为硬件、
   商业求解器大规模运行或投稿作出授权。

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
