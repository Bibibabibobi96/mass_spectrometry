# 单次反射正交加速飞行时间质量分析器当前状态

本文件维护项目当前事实、资格与开放任务。精确输入以[机器合同](../README.md#机器权威)为准，
执行入口由[项目README](../README.md#活动入口)导航；跨项目整机状态只查[统一集成状态](../../../integrations/docs/INTEGRATION.md)。
已闭合的提供者迁移、回归及失败链冻结在[文档收口记录](history/20261026__assembly-documentation-consolidation.md)，
不把实现迁移、局部验证或旧运行自动提升为新整机资格。

## 当前状态

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
| [完整组件几何保存、重开及STEP][geometry-only-evidence] | 45域／40物理对象，整包及独立STEP发布，geometry_save_reopen_step_only | 上游多极杆、SolidWorks、GUI、ES/CPT/Fly及Formal；GUI按用户决定暂缓 |
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
旧连接证据查[已退役集成记录](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20261024__legacy-family-retirement.md)，
新装配状态查[统一集成状态](../../../integrations/docs/INTEGRATION.md)。三区真实PA及源敏感性的有效范围见
[完成快照](history/20260823__three-zone-completed-results-snapshot.md)，不继承为当前Formal。
理想源的[残差／束宽](history/20260827__ideal-source-residual-and-width-comparison.md)与
[斜率比较](history/20260827__synthetic-affine-slope-scan.md)仅证明受控一维机制，不授权真实三维接受或性能声明。

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
