## Installed recorded-focus analysis and bounded adjustment

The sole recorded closed-two-zone focus analyzer is `msplatform.workflows.oa_focus_analysis`;
its bounded voltage-decision state machine is `msplatform.workflows.oa_focus_fast_adjust`.
Current analyzer and controller-state records use protocol revision 2. Their
validated profile-content SHA is a scientific authority bound at initialization and
checked when consuming state or analysis. Revision-1 historical files are retained
unchanged but are not accepted for a new controller continuation; there is no fallback.
Both require explicit geometry-profile content in Python and an explicit component
contract on their CLI. They use the existing campaign validator and ideal two-zone
formula, without selecting a project default. The native trial loop remains in its
existing PowerShell runner and invokes the installed modules through the shared
frozen Python transport. Raw events, original release/clock identities, full cohort,
unknown/not-reached distinction, hard energy gates and bounded correction policy
are preserved. MR energy-reference evaluation uses the gaps of its actual frozen
provider plan, not a checkout profile. This source migration is not native qualification.

# 正交脉冲加速器项目状态

## Installed legacy closed-focus PA planning

`msplatform.backends.simion.oa_focus_plan` is the sole closed two-zone focus PA
planner. Its CLI requires explicit campaign, component-contract and three-axis
`--mesh-mm-per-gu` inputs; its Python API requires explicit profile content and mesh.
The shared campaign validator is owned by
`msplatform.components.orthogonal_accelerator.focus_campaign`; project file readers
select their declared profile, while the installed operation reads no project default.

The current MR OA-provider request explicitly declares `numerics.mesh_mm_per_gu`.
The component workflow passes that author value into the PA plan and forwards the
resolved mesh to its PA child. It keeps the existing two flight-numerics fields in
the campaign: mesh is not inserted into historical campaign/projection documents.
The former unreachable projection mesh fallback has been removed. Explicit
`[0.25, 0.25, 0.1]` reproduces the original nineteen-electrode, x-mirrored half-domain
plan; other finite positive meshes remain subject to the existing grid/enclosure
checks, including exact mirrored half-span alignment.

The existing leaf Python freezer now lives once in `simion/focus_python.ps1` and
serves flight and PA-plan preparation with explicit input-name lists. The PA planner
runs through that frozen `-I` execution boundary; cache/native lifecycle remains
with its existing runner. This migration and software regression do not establish
new native build, Refine, Fly, convergence or qualification. Legacy parent-coupled/Dirichlet workflows and the separately recorded seed-helper
consumer migration remain open.


Current API2/API3 implementation declarations now name the installed
`src/msplatform/backends/simion/accelerator_renderer.py` directly. The provider reader
resolves that explicit package namespace from the source root while preserving
project-relative declarations in historical frozen contracts. Scientific roles,
variants, geometry requests and old frozen bytes are unchanged; no deleted
forwarder is restored. Candidate and reflectron source freezing use the canonical
renderer and its installed dependency closure.

Component-focus flight preparation now selects its three-instance structural IOB from the installed
SIMION resource owner. The template bytes, placeholder PA inputs and scientific flight configuration
are unchanged; this path migration does not establish a new OA native-flight result.

本页维护独立器件的能力、资格和开放动作。理论、源码和操作从[项目入口](../README.md)进入；
完整迁移、组件实验及实现修复记录见[文档收口里程碑](history/20261026__assembly-documentation-consolidation.md)。

The accelerator-only three-zone ideal theory has its sole implementation in
`msplatform.components.orthogonal_accelerator.three_zone_ideal_theory`; the old project
implementation is retired. Signed affine source, local extraction coordinates, exact transit
and derivative formulas are unchanged. Instrument reflectron/total-time theory remains
with its instrument. Only the current v2 author campaign source-authority records are refreshed;
the retained historical v1 file keeps its exact pre-migration bytes and is rejected for current execution. This migration grants no new native or scientific qualification.

## 部件职责与输入权威

本项目提供二区／三区正交脉冲加速器的局部理论、参数化几何、电极身份和独立验证。
二区／三区是结构变体，各自保持冻结请求、几何与证据身份，不能用一种变体的通过替代另一种。
仪器项目保留系统布局约束和联合聚焦；跨组件装配、执行与链路证据归[统一集成](../../../integrations/README.md)。
本项目不继承 oa-TOF 或 MR-TOF 的资格。
时间聚焦与组件实验直接使用安装`particle_physics`实现，旧公共桥已退役；理论常数、单位及资格不变。

| 对象 | 唯一入口与边界 |
|---|---|
| 公共发现、结构变体与能力 | [project.json](../config/project.json)，二区／三区分别登记，不能隐式代选 |
| 器件API、变体和具名几何profile | [component_contract_v3.json](../config/component_contract_v3.json)；旧API2来源保留原合同 |
| 机械端口与物理电极视图 | `msplatform.components.orthogonal_accelerator.assembly_interface`拥有唯一实现；[项目适配器](../analysis/assembly_interface.py)只加载具名profile |
| 组件焦点实验 | [two_zone_component_focus_campaign.json](../config/two_zone_component_focus_campaign.json) |
| 二区／三区及有符号源理论 | [理论导航](theory/README.md) |
| 独立构建、飞行与验收 | [项目执行入口](../README.md#阅读与入口) |

当前交付是可调用器件机制与具名profile，尚无覆盖两种变体的独立器件baseline。
旧OA电压、MR孔径及测试样例不是本项目隐含默认硬件。各API显式声明局部轴、单位与变体；
消费者负责正规刚体映射，位置含平移、速度只旋转。第一时间焦面、自由飞行观察面和机械检测器分别解释。

## 当前能力

当前科学电极字段为`electrode_group_id`，主组为repeller、intermediate_grid_1、
可选intermediate_grid_2、exit_grid；组件接口默认3，显式旧接口1/2保持原义。
旧component API2/theory的grid2表示第二中间栅，旧sectioned geometry schema1的grid2_z_mm和
accelerator_grid2_id表示出口，转换按来源/版本选择，不作全局替换。新API3合同与旧API2资源分别保留。
角色、面、独立电位和旧来源的32项软件回归通过（1.696秒），未新增原生驱动或独立器件资格。

三区理论的时间尺度公开名为`time_scale_s_sqrt_v_per_mm`，数值仍为原系数；
理论提取位置从排斥极参考面朝出口为正，单位mm。该一维坐标与机械frame的原点映射显式区分；
机械平移不能进入速度。独立SI分段运动与非零原点等9项理论回归通过（0.108秒）。

P2电极拓扑API为`analysis.electrode_topology.build_electrode_topology`：消费现有二区机械
resolved或三区领域文档，以稳定角色和环序号发布科学组；member_refs只引用真实几何构成参数。
显式voltage_sources指向调用方已有source_document，不复制电压或另造源身份；调用方继续冻结其
单位、时钟和来源。成员参数引用不等于独立制造实体，理想透明sheet仍保持其原零厚语义。
二区真实campaign及三区机械拓扑、编号置换与相邻机制软件回归通过；三区生产驱动和新装配消费者
尚待接线。现schema1接口、几何编译和原生renderer未因此切换，不增加两种变体的独立baseline资格。

| 能力 | 已有范围 | 不包含 |
|---|---|---|
| 解析理论 | 二区时间焦距、位置—速度相关导数、三区精确局部时间及固定净增益灵敏度 | 三维边缘场、实际丝网和仪器位姿选择 |
| SIMION几何 | 二区／三区、方／圆截面、环／屏蔽、显式侧孔及原生PA构建 | 任意拓扑或未声明的隐藏尺寸、电压 |
| COMSOL几何 | 同源实体及零厚栅构造；当前装配消费支持方形截面 | 三区新装配的真实求解、保存重开与GUI验收 |
| 机械接口 | 两种变体的真实端面、截面、外法向、壁厚及物理电极身份；直接消费者纯回归通过 | 孔内整面电位、源、时钟或粒子交接资格 |
| 普通安装独立provider／CAD | `oa_two_three_geometric_v1`显式消费两变体requirements／profile内容，支持多实例、局部scope、同源STEP与冷读 | 原项目未闭合的场、轨迹、数值、GUI／正式CAD和资格 |
| 封闭二区组件实验 | 具名源、完整电极电压、-z焦面、真实N100出口与候选收据 | 独立全变体Candidate/Formal或整机分辨率 |

几何由提供者单次解析发布，消费者不重画电极或用局部PA编号作为全局物理身份。
封闭二区只发布实际轴向出口；选择侧孔的独立几何才发布侧入口。三区保留真实侧口和理想零厚栅面，
不将数值bounds或理想sheet冒充机械法兰。COMSOL的零厚栅应保持内部电位面语义，不能改成有厚碰撞实体。

封闭二区可用SIMION的planar x镜像存储半域；物理跨度、存储跨度、镜像面和IOB原点均进入身份。
带侧孔几何不复用封闭PA资格。提供者机制的调用与冻结闭包回归不等于新的原生场或飞行验收。

The SIMION negative-y side-opening subtraction now rejects numerical padding that
would cut the opposite wall, including the emitted GEM coordinates. Padding ending
at the opposite inner face remains valid under the existing strict-interior cut.
This preserves the canonical opening and valid GEM bytes; it does not enlarge the
opening or change component dimensions to accommodate a grid. Software boundary
regression is separate from native occupancy and field qualification.

### 机械模型与求解器投影

`analysis/two_zone_geometry.py`公开`load_geometry_profile`与`resolve_closed_two_zone_geometry`，
拥有封闭二区物理profile、源包络、屏蔽/栅框/环及侧口解析；三区显式机械解析由
`analysis/sectioned_geometry.py`拥有。装配接口、聚焦分析、SIMION及经canonical数据消费的CAD/采样
共用这些模型，不另存器件尺寸。SIMION adapter只校验本次PA网格/包络、投影原点并发射GEM；
`resolve_closed_two_zone_electrodes`允许实际装配取得已校验PA投影，不先生成再丢弃一份独立PA GEM。

二区机械接口使用已有`orthogonal_accelerator_exit_origin_v1`：出口z=0，当前profile首区侧口z=32 mm。
旧`accelerator_centered_transverse_local_z_mm`接口把PA留白混入机械坐标；campaign中的6 mm来自
`focus_padding - focus_offset`，不是新增机械尺寸。机械接口不再消费`local_pa`的span、mesh、margin或原点；
非法机械输入仍拒绝，非法PA在SIMION准备边界拒绝。默认独立PA仍投影到出口z=6 mm，原默认GEM、
布局及PA坐标canonical电极保持相同；改变数值原点只改变该投影，不移动机械接口。

两份活动二区composition plan已沿原compiler重编：机械坐标减去旧PA平移，同时位姿增加旋转后的平移，
世界端口、法向和间隙不变。装配adapter将机械pose转换为canonical PA pose一次，CAD与电位采样继续
消费canonical数据对应的同一pose。旧封存run和旧frame记录不改写，不能将旧PA坐标直接当新机械frame；
新活动plan使用机械frame；MR消费者对已有合法PA frame按其原坐标显式解释，未知frame拒绝。
跨frame接口比较先投影到同一声明frame，不改写旧plan；其他provider物理接口不匹配仍拒绝。
本次纯软件几何/依赖等价不授予新求场、Fly、GUI/CAD或科学资格，也不因机械frame命名迁移自动重Refine。

### 组件工作流与验收

`msplatform.backends.simion.oa_focus_source` 直接调用 `msplatform.ion_release` 的释放校验、
`msplatform.contracts.particle_physics` 的动能函数及 `msplatform.io.file_identity` 的文件身份函数；
相邻测试核对实际函数来源。组件聚焦CSV writer现直接冻结安装SIMION backend的`scientific_event_csv.lua`；
列顺序、精度和原文件身份保持，不再读取旧common/simion副本。跨 RF、OA、布局适配和 MR 的 78 项行为测试通过（7.326 秒），
布局及 MR 同时验证拒绝旧桥后仍能执行真实计算；本轮未新增原生求解或科学资格。

源投影的软件回归在 `test_component_focus_simion_source.py` 使用规范 `msplatform.ion_release` 的七粒子受控输入，
逐行核对原ID、非零出生时间的秒到微秒换算、三维速度的 m/s 到 mm/μs 换算、出口平移、
真实 FLY2/Lua 文本和来源/输出字节身份；campaign 或 provider 不一致仍拒绝。
该文件六项测试通过，仅证明软件投影与身份保持，不替代下述 N100 原生组件验收。

`simion/run_component_focus_workflow.ps1`消费窄器件request与公共ion-release spec，先冻结
profile、campaign和plan，再复用既有PA cache runner与flight runner，发布绑定两个子manifest的父receipt。
源速度、能量和粒子状态只进入flight，不进入PA几何身份；不复制另一套释放器或响应库。

封闭二区组件合同要求完整N100按负z方向穿过声明焦面，保留全粒子终态和事件身份；
100%传输是硬门，1.5 ns峰峰时间阈值与带符号横向速度判据按campaign解释，横向RMS只作诊断。
理论首区位置从repeller向出口计量，器件以出口为原点；释放前校验完整圆柱母群位于首区。

原生场未通过时，同一PA、源、电压与数值设置下的一区／二区／全理想场对照只用于定位有限场贡献。
获准的Fast Adjust控制器只在请求给定首区压降范围内串行试飞，复用已发布私有runtime；
搜索耗尽不能发布MR接受收据，不能以追加Refine、缩源或忽略失败粒子制造通过。

### 焦面事件与同面参考修正

2026-10-30复核确认旧`component_focus.lua`在`tstep_adjust`内按空间容差提前记录focus，
故旧焦面时间不能直接用于解释有限几何色散。当前`tstep_adjust`只调步长；`other_actions`仅在
同一粒子实际相邻状态夹持声明平面、时间递增且两端均向负z运动时产生一次事件，保留端点与6D插值。
求解器无关诊断复用`accelerator_time_focus.time_to_fixed_plane_s`，负offset对应同观察面的正自由漂移距离；
该参考明确为二区均匀场加出口后无场漂移，不声称下游原生边缘场消失。

理想对照只配对实际有效focus命中的相同particle ID，并在release birth微秒时钟上计算理想到达；
源事件时间须与公共release相符，focus须在该ID的source至terminal时间区间内。
`ideal_field_contrast.particle_pairs`保留逐ID实际/理想到达、差值或显式传播错误；差值统计同时给出配对数。
只有至少两对且所有请求ID均可传播时，才报告同群宽度；零命中不可判断，单命中仅提供到达差，
理想传播失败不会静默缩群。主结果完整母群、未到达数量、传输率分母及完整传输硬门保持不变。
原先0.05ns宽差直接归因有限几何的分支已删除；现在默认仅报告观察差异、原因待查，
没有同群同面同钟、相称数值收敛及误差预算时，不解释为具体有限几何机制或分辨率资格。

官方路径核对：SIMION 2020随附`examples/test_plane/testplanelib.lua`（文件标记v2014-04-21，2017版权），
以及2026-10-30查阅的[SIMION Test Plane](https://simion.com/info/test_plane.html)。飞行入口冻结安装目录中的
官方库，按官方要求调用其`tstep_adjust`和`other_actions`；官方库负责落面步长，项目薄适配补齐方向、
相邻状态、完整事件和唯一记录语义。该库仅在PA实例内收到回调，声明的出口和焦面必须仍在冻结PA域内。
六类离线测试执行真实生产Lua和已安装官方库，覆盖容差内未穿面、精确端点、跨越、方向、去重和交错粒子；
它们不是原生Fly证据。解析回归覆盖offset=0、−10mm及非零源轴向速度和m/q，原先重复传播公式已删除。

历史`20261013_110000__sim__simion__mrtof-k255-private-oa-source__n100`的封存事件含完整N100母群，
offset=0且独立exit是同面、同钟的负z穿面。新分析run
`20261030_063000__analysis__python__oa-focus-exit-correction`复用exit纠正focus，未重飞；
原run的manifest和summary字节保持不变。逐粒子旧focus提前0.06957735–2.45866176ns，
时间峰峰值由2.92810890ns修正为1.14999614ns；这纠正旧诊断，不增加器件或整机资格。
新run的`results/correction_audit.json`保留每ID原值、纠正值与采用条件。

生产Lua另在相同N100源、电压及90×139×501原生网格上完成两档步长验收：
`20261030_064000__sim__simion__oa-focus-step-500ps`与
`20261030_064100__sim__simion__oa-focus-step-250ps`，最大步长分别0.0005、0.00025µs。
两者均100/100穿面，每ID的focus与同面exit时间完全一致；时间峰峰值分别1.150012760、
1.150012470ns，最大逐ID时间差约1.28fs。原生Fly分别1.82、3.21秒，完整入口分别13.745、13.917秒。
`20261030_070000__analysis__python__oa-focus-step-convergence`保存逐状态最大差和范围；
这是固定空间网格上的事件步长验证，不提供空间网格收敛或整机分辨率资格。
两次Fly共用新建的同几何场`20261030_065000__build__simion__oa-focus-callback-field`，
存储网格0.25×0.25×0.1mm、x镜像、物理域44.5×34.5×50mm；原生0..19响应Refine约43秒，
Fly阶段没有重Refine。旧cache已退役且残存runtime归failed owner、没有完整载荷封存身份，
因此本轮没有绕过复用校验，而按原provider入口新建了这一小场。

修订诊断以封存250ps N100事件新建
`20261030_101830__analysis__python__oa-focus-paired-reference`，原run的manifest和summary字节不变、
本次native次数0。100/100实际命中均有理想配对，传播失败0；同群实际/理想时间峰峰值分别
1.150012470/1.110791690ns，逐ID实际减理想到达差的平均值0.283628162ns、范围
0.246251676–0.323590218ns。这些是该参考下的描述性差异，原因尚未归因。
纯分析回归覆盖非零offset、零/单/部分/完整命中、同钟验证和理想传播失败；没有新增商业求解。

未命中焦面只记 `not_reached_focus_particle_count` 与原ID，不推断真实死亡；旧
`loss_particle_count` 保留为该计数的显式兼容别名，其语义字段声明非物理损失。
传输分母为本次实际释放群，另保留 release 的原母群规模；例如N100抽样来自1000母群，
未模拟的900不算损失，也不据此报告完整母群效率。本轮软件回归使用实际安装的
SIMION 2020所附Lua 5.1.5和官方 `testplanelib.lua`；不把历史反例的Lua 5.4当作本机事实。

### 已闭合组件证据

2026-10-03的注册缓存提供者保持原冻结请求、释放、几何、网格和电压，完成15环／19电极真实构建，
N100全部穿过出口；后续私有runtime恢复及K=25.5、23.5工况也各自完成100/100。
三轴出口残差通过各自冻结的0.05 V/q门槛；不同K的源与资格分别绑定，不相互借用。
原9环及仅减薄框的负结果、15环演进、准确数值、run与SHA见[收口前证据](history/20261026__assembly-documentation-consolidation.md)。
“十五环仍待首次N100”的旧步骤已被这些证据接替，不再作为当前下一步。

PA发布沿[公共缓存事务](../../../common/simion/README.md#pa-缓存与工作点)。现有cache HIT及显式
runtime checkpoint复用已经使用，但未发布事务的跨run重入仍未全覆盖；不能由HIT推定中断恢复完成。
旧私有缓存根是否可退役取决于实际消费者、GUI及公共owner记录。

组件PA的构建、standalone导出及原生验证共用同一SIMION资源租约，验证退出后才释放并进入缓存发布。
验证非零退出同样先结束该租约，再由原入口记录失败；不增加进程包装或改动物理参数。
小型软件夹具执行真实PowerShell分支和显式原生替身，校验成功／非零分支的准入、释放及发布顺序；
该回归不新增原生场或组件聚焦资格。

## 统一组装迁移任务

本地机械接口已由直属装配消费；完整接口收敛、驱动绑定和相称真实验收继续按
[统一组装计划](../../../docs/ROADMAP.md#统一组装迁移计划)及[集成状态](../../../integrations/docs/INTEGRATION.md)维护。
同源导引接入的二区／三区局部N100和各自默认文件重放已闭合，其母群、场、脉冲及损失属于集成证据，
不能用封闭组件100%传输替代，也不反授独立器件或MR资格。

| 层级 | 当前结论 |
|---|---|
| 解析、几何编译、接口与消费者回归 | 在声明变体和输入范围内通过 |
| 原生构建、组件功能 | 有具名样例和封闭二区证据；不是完整独立baseline |
| 初次迁移run | 求解完成但整体因容量治理失败，保留失败身份 |
| COMSOL新投影 | 纯回归及静态接线；新几何／选择集／保存重开尚未验收 |
| 数值收敛、独立GUI/CAD、Candidate／Formal | 未完成，BLOCKED |

旧迁移细节见[迁移记录](history/20260911__component-migration-evidence.md)。

## 开放任务

1. 冻结独立器件baseline及两种变体的完整同源几何、数值合同，证明显式身份与重建一致。
2. 对实际声明补齐真实场、完整源穿越、空间／时间离散证据；解析与迁移样例不能代替。
3. 完成各变体GUI重开、CAD交付与资产身份后，再申请相应资格。
4. 完成提供者几何／驱动在实际消费者中的冻结对照；整机结论只写所属PROJECT或INTEGRATION。
5. 沿[统一恢复规则](../../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)补齐未发布PA事务重入：
   新run显式绑定原owner，中断构建、待验证及待发布阶段均可恢复，不重复已完成响应且不改写旧证据。

## 产物

独立器件新运行归`artifacts/projects/orthogonal_accelerator/`。既有OA/MR run、冻结包与Formal资产
保持原owner及身份。

## 机器能力与解析输入

execution profile 由纯几何与 release 解析器绑定本次结构、质量和电荷；准备状态不表示 SIMION 运行完成。
能力查询与执行编译见[公共合同](../../../common/contracts/README.md#执行dry-run)；READY 仅描述声明条件。

## 公共科学CSV接线

组件焦面事件使用公共 scientific_event_csv writer／scientific_event_io 流式 reader；列顺序、12位有效数字、每ID时钟、原母群与原物理门槛保持。飞行入口冻结实际 writer companion 并纳入结果 manifest，项目继续拥有穿面、步长及终止政策。

正常入口 `20261031_235000__sim__simion__oa-focus-csv-wiring` 复用既有私有 Fast Adjust 场，
实际执行1次 IOB 构建、1次 Fly（3.10秒）、0 Refine，公开墙钟12.771秒。
400行事件的 source／exit／focus／terminal 各100个原ID，同面 exit／focus 的时刻与6D一致；
分析得到100个有效配对。原母群1000中的另900个未模拟，不计为损失。
该记录验证 CSV 运输，不授予空间／时间收敛或整机科学资格；当时 Python 仍从活动源码执行。

只读该封存源的N100／400行／38,029 B事件CSV，Python 3.11一次仪表化正式分析CLI得到
与原分析整个JSON语义相同的结果：CLI主体0.3220005秒，`analyze`累计0.0732142秒，
含准入／观察／释放的内部驱动11.8784724秒、完整外层pwsh调用13.1354678秒。
Python进程OS lifetime峰值工作集33,173,504 B包含解释器／import／profile；500 ms进程树
采样峰值15,687,680 B仅为采样值，不替代OS峰值，也不代表函数独占RSS。
该次runpy＋cProfile计时含仪表开销，无未仪表化对照或提速结论；原run不改，新增原生调用0，
母群1000／实际模拟100及未模拟900非损失的口径保持，不增加空间精度或科学资格。
[测量范围与原始证据](../../../../artifacts/projects/orthogonal_accelerator/scratch/20261101__csv-analysis-cost/agent3/READOUT.md)
保留实际输入、结果比较、计时与内存收据。

### 冻结 Python 真实执行

2026-11-01，飞行入口改由公共 `enumerate_python_sources` 展开4个小包及显式几何 JSON，
删除两个未被执行的单文件存档；实际源生成、SIMION 源投影和分析均从同一冻结目录运行，
不回退活动仓库。冻结输入逐文件登记到原 run 配置，实际模块来源写入 `results/python_execution.json`。
不依赖场的导入与几何资源读取在两个原生命令前完成。
两项隔离测试通过7.238秒，覆盖封存 N100 CSV 的真实准备／分析等价、manifest 绑定及缺代码／资源拒绝；
中文源码路径和 ASCII 调用方编码的受影响正例补验通过3.608秒，编码设置恢复。
这些软件补验未新增 Fly／Refine；原物理、容量与进程归属政策保持。

### P3 可安装纯 provider 切片

二区机械几何、三区机械投影、电极拓扑及理想加速器数学的唯一实现迁入
`msplatform.components.orthogonal_accelerator`。项目入口保留文件读取与 CLI；
二区规范函数接收显式物理 profile，不从安装包倒读项目配置。原型能力边界、
坐标、尺寸、电压公式与原 GEM 输出金标准保持，不因迁移新增场或轨迹资格。

公共 GATE 的 OA/完整 TOF 相邻十模块共 93 项通过（10.420 秒、无 skip），
包括原几何输出与非零物理参数回归。此为软件层证据；普通安装整合和 P3 全目标另行验收。

### 可安装COMSOL原生资源切片

方形加速器的实体与零厚栅COMSOL helper已迁入`msplatform.backends.comsol/matlab/`，由oa-TOF静态场、
候选和Formal几何入口共同消费；旧项目副本已退役。迁移保持原几何构造与调用参数，不授予新的原生场、
保存重开、GUI/CAD或独立器件资格。

### P4 公共装配边界与圆柱侧孔修正

独立评审复现的公开`Assembly`构造旁路已关闭：直接构造和正常`assemble`均重新执行提供者同源校验，
10 mm环厚等不合理设计在父布局编译及STEP导出前拒绝。圆柱截面的侧孔切刀延伸穿过曲面内壁，
不再仅到名义内壁；偏离孔中心线1 mm的真实CadQuery源实体与导出后冷读STEP探针均不为金属。
方形投影字节金标准不变，仅有意更新受修正影响的五个圆柱哈希。这些是几何及负例软件证据，
不是圆柱OA的原生场、粒子、GUI或Formal验收。

### Installed standalone raw geometry slice

The existing two-zone CSG and rectangular primitives, and the bare three-zone adapter,
now reside in `msplatform.backends.simion`. Repository callers load their existing named
physical profile explicitly; installed callers consume their already resolved mechanical
snapshot. The independent compiler does not infer a TOF, source, drive or voltage.
Each selected instance supplies explicit full PA bounds and anisotropic grid pitch.
No mirror is assumed for an asymmetric side opening. Mechanical coordinates remain intact;
the existing IOB compiler transforms each PA origin through the declared rigid pose once.
Scientific electrode groups map to explicit unique native IDs; metal, ideal-sheet, cavity
and side-opening witnesses must survive the actual grid projection.

The existing raw GEM2PA builder, reviewed structural seeds, fractional-surface checks,
source-free IOB save/reopen and public run owner are reused. Official SIMION representation
and long-input facts remain those in `docs/tools/SIMION_REFERENCE.md`; this change introduces
no alternative long-path transport, IOB byte editor, solver or physical accelerator model.
Pure software acceptance and original GEM goldens do not establish native build, GUI/CAD,
field, particle, convergence or Candidate/Formal qualification; the native evidence below is limited to this exact raw-geometry request.
Project-only implementation lists keep their containment rule; canonical package sources
join frozen runs through the existing full `src/msplatform` package enumeration. Legacy MR
analytical source inventories retain their original execution behavior and also record the
moved backend source bytes; this is not a claim of new MR frozen execution qualification.


#### Ordinary-wheel native raw geometry acceptance, 2026-11-09

The combined source epoch was `5c4d5e883d4822ca5c370362f24bc07b8bb4d297` plus the reviewed
Wehnelt and standalone OA worktree slices. Ordinary wheel SHA-256
`f4c3874eb2843c6b19209756272a77c8ba4aac4b46e0c7a17b315b7a582ef573`
passed the actual wheel/sdist installation module (five parents), with original/rebuilt wheel
member bytes equal. A separate fresh installed probe denied reads from both author trees;
181 loaded core modules came from that environment's site-packages and required-resource
negative cases still rejected missing files.

The public `build_geometry` owner completed
`20261109_173100__build__simion__geometry-e9142dbba3ee`: two-zone 185×145×406 and three-zone
145×145×401 full arrays at 0.25/0.25/0.1 mm pitch, descending native IDs beginning at 200,
and the example's actual mated nonidentity three-zone pose. The two raw PA files contain
87,127,656 and 67,448,256 bytes; their fractional companions contain 3,565,140 and 522,900
bytes. The 20,846-byte IOB was saved and cold-reopened with both real instances. Existing
Lua checks validated grid, metal/ideal-sheet/vacuum nodes, fractional-surface witnesses and
original rigid-transform readback. All four native process receipts record exit 0 and released
host leases; the terminal owner records success and stopped writers.

Refine, Fly, GUI and sampled-source calls were zero. Reopen was at the same execution
projection; relocation qualification was not assessed. This proves raw geometry and IOB
transport for this explicit two/three-zone request, not a solved field, particle experiment,
GUI/CAD validation, convergence, full variant baseline or Candidate/Formal qualification.
A later ordinary Python process opened the real published geometry product and verified all
nine manifest-bound data members with subprocess, mkdir and write guards active. It also
joined all 347 installed package files back to the same wheel after the native run. The retained
read-only evidence is `oa-native-fresh-readonly-proof.json` in the existing P4 takeover evidence
directory; its first attempted read used the wrong manifest filename and is preserved separately.
No native operation was repeated for the reader verification.

### Independent SIMION driven unsolved model

The existing `prepare_model` operation now accepts a published independent two/three-zone
OA geometry product. Supply the complete scientific-group `drive.groups` table, explicit
clock authority and the external-electrostatic boundary physics; no TOF, source or voltage
is invented. OA groups use the existing static/pulse representations, with explicit timing
only when pulse groups exist. The grounded shield remains static zero. The saved model
preserves each domain's raw PA, fractional surface, witnesses, pose and canonical group
mapping through the existing protected materializer and run owner. It is `not_solved` and
`not_requested` for fields and source; Refine/Fly/sample calls remain zero. Existing source-
free IOB build/reopen and saved drive readback are reused. Software/Lua and ordinary-install
protocol evidence does not grant native model, field, particle or Formal qualification;
independent OA field/Fly and COMSOL stage closure remain OPEN.

### Independent fractional field-family closure

The existing `solve_fields` operation now consumes actual independent OA PreparedModels
and plans one linear fractional electrode-response family per selected OA domain. It
uses the same refiner, auditor, protected materializer, original-producer reuse and run
owner as RF; no private OA PA-family copy or second cache exists. OA products declare
`producer_owned_oa_fractional_family`, their real OA groups/labels/grid/witnesses, and
`independent_component_domains`; mechanical mating is not a claim of joint field coupling.
Refinement uses explicit vendor-default or per-domain convergence, without source/Fly or
fake downstream TOF roles. Space-charge/self-consistent physics is not supported here.
The unchanged generic Lua utility retains its legacy RF-named report format; OA metadata
records that provenance explicitly. It is not an RF geometry/physical identity. Existing
RF operator identities remain reusable; an audit-label change alone does not force Refine.
Software and inert ordinary-install checks are distinct from native fields or scientific
qualification. OA native model/Refine/Fly acceptance remains OPEN pending authorization;
source and trajectory migration is separate.

This independent-domain slice does not implement or replace a parent-coupled/Dirichlet
field problem. The actual PreparedModel physics must be external linear electrostatics
with native-zero/Neumann boundaries; extraneous joint-coupling requests are rejected by
the same planner before execution. Existing legacy two-zone field/Fly and parent-coupled
capabilities remain a separate migration obligation where present. Multiple placed PA
instances alone do not establish a common field solution.

### Independent OA tracking software closure

The existing installed `track` operation now accepts the explicit two/three-zone OA
PreparedModel bound to its original independent fractional FieldBundle. It reuses the
single source/clock transform, ordinal unit dispatcher, protected original family,
IOB writer, collector, recovery and run owner. OA native roles, component/census and
metadata remain OA; the unchanged RF-named native-state wire is documented as legacy
shared transport format, with unknown native terminals never interpreted as losses.
No pulse-state observation is inferred from absent recordings.

Static and pulsed scientific group voltages come from the sole `model_drive.lua`.
Timed/held-off OA receives the existing pulse hook and voltage waveform implementation;
timed steps cap at both physical pulse edges in the canonical absolute instrument clock.
No source/Fly operation requests Refine or privately copies a published PA family.
The supplier basis is SIMION2020 Supplemental Documentation, `time_dependent_field.html`
([Time-Dependent Field](https://simion.com/info/time_dependent_field.html)), read 2026-11-10:
quasi-static fast-adjustable electrode superposition and explicit waveform timestep
control. Existing `single_flight_pulse_hook.lua`/`voltage_waveforms.lua` remain the
single step-gate implementation; no new field formula or radiation/collision model is added.

This independent-domain software slice does not replace legacy closed two-zone focus,
bounded Fast Adjust/ideal-field contrast workflows, parent-coupled/Dirichlet fields or
the remaining legacy seed-helper consumers. Those remain separate P4 migration work.
Actual OA native field/Fly, GUI and scientific qualification remain OPEN; software and
inert observed-process evidence must not be described as commercial solver acceptance.


### Installed legacy closed-focus source projection

`python -m msplatform.backends.simion.oa_focus_source` consumes explicit release receipt,
campaign, provider PA plan and optional resolved projection, and writes the selected FLY2,
source-state Lua and receipt paths. The original project source body is retired. This is
the legacy contiguous-ID, x-mirrored closed-focus PA-frame adapter with exit-z translation;
it does not replace the general canonical source/handoff API or resample particles.
Units, first-gap enclosure, energies, birth times and source/output byte identities remain
those of the existing release and projection contracts. No owner, Refine or Fly is required
for this vendor-independent serialization stage. The existing flight caller freezes and
executes this canonical implementation; the remaining focus analysis still has its own
explicit frozen project/profile closure.

P4 OPEN: closed-focus PA-plan/analysis/workflow/native migration, bounded FastAdjust and
ideal-field contrast, parent-coupled/Dirichlet paths and the eight legacy seed-closure
consumers. In particular, `component_focus_pa_plan.derive` currently disallows the
`mesh_mm_per_gu` projection key before reading it and consequently uses the fixed
0.25/0.25/0.1 mm grid. Explicit mesh authority must be resolved in the P4 plan migration;
this static constraint is not a reproduced native error and is not deferred to P5.


### OA to MR runtime receipt ownership

The component-focus workflow invokes `msplatform.workflows.oa_focus_mr_runtime_receipt`
for its existing manifest-bound, read-only PA metadata projection. Its active owner,
output path, gate and historical receipts retain their original meaning. This move
alone grants no native Fly or system qualification.

### Recorded-analysis workflow boundary correction

The sole recorded analyzer is `msplatform.workflows.oa_focus_analysis`, beside its
existing bounded-adjustment workflow. Its full module bytes, formulas, protocol2
result, explicit profile, mother cohort and instrument clock remain unchanged;
current Python/CLI/frozen consumers and API2/API3 declarations use that owner.
Historical frozen declarations and authority bytes are unchanged.

On isolated4576 plus this correction, six original OA modules passed50 parents,
three MR energy-consumer parents passed, and the public Changed routing parent passed.
The unchanged full dependency assertion now reports only the separately tracked IP
field-reference process edge; all seven OA reverse-import reports are resolved.
The actual ordinary wheel/sdist parent passed240.708s: both installed arms execute
the full recorded report and CLI and reject a physically missing canonical module.
All436 package payloads join the source/direct/rebuilt wheels. The first new probe
incorrectly expected LF instead of Windows text-output bytes; its original failure
is retained and only that expected serialization was corrected. These are software
and packaging checks, with no new native or scientific qualification.

After composition with the IP verifier repair, the unchanged complete dependency
boundary module and actual OA/MR consumers passed in a 63-parent batch (211 records,
25.778 seconds). Both ordinary installed arms passed in the original build parent
(216.730 seconds), with the IP and OA probes present together. The six-parent
installation module retained one separate cold-comparison fixture failure: its
extracted section omitted the real probe's earlier SciPy initialization. Restoring
that prerequisite outside the unchanged process/write guards made the original
failed parent pass in 1.270 seconds. Package and installed-probe bytes were unchanged
by this fixture-only correction; the failed module epoch remains recorded.

The standalone and internal TOF three-zone OA use the same physical construction and side-wall opening validation. Standalone first-gap ports and the bare frontend retain their study-specific first-gap checks. Instrument provenance remains explicit; the producer name does not decide physical validity.
