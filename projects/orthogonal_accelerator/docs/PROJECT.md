# 正交脉冲加速器项目状态

本页维护独立器件的能力、资格和开放动作。理论、源码和操作从[项目入口](../README.md)进入；
完整迁移、组件实验及实现修复记录见[文档收口里程碑](history/20261026__assembly-documentation-consolidation.md)。

## 部件职责与输入权威

本项目提供二区／三区正交脉冲加速器的局部理论、参数化几何、电极身份和独立验证。
二区／三区是结构变体，各自保持冻结请求、几何与证据身份，不能用一种变体的通过替代另一种。
仪器项目保留系统布局约束和联合聚焦；跨组件装配、执行与链路证据归[统一集成](../../../integrations/README.md)。
本项目不继承 oa-TOF 或 MR-TOF 的资格。

| 对象 | 唯一入口与边界 |
|---|---|
| 公共发现、结构变体与能力 | [project.json](../config/project.json)，二区／三区分别登记，不能隐式代选 |
| 器件API、变体和具名几何profile | [component_contract.json](../config/component_contract.json) |
| 机械端口与物理电极视图 | [assembly_interface.py](../analysis/assembly_interface.py)，消费同一冻结请求和现有几何编译器 |
| 组件焦点实验 | [two_zone_component_focus_campaign.json](../config/two_zone_component_focus_campaign.json) |
| 二区／三区及有符号源理论 | [理论导航](theory/README.md) |
| 独立构建、飞行与验收 | [项目执行入口](../README.md#阅读与入口) |

当前交付是可调用器件机制与具名profile，尚无覆盖两种变体的独立器件baseline。
旧OA电压、MR孔径及测试样例不是本项目隐含默认硬件。各API显式声明局部轴、单位与变体；
消费者负责正规刚体映射，位置含平移、速度只旋转。第一时间焦面、自由飞行观察面和机械检测器分别解释。

## 当前能力

| 能力 | 已有范围 | 不包含 |
|---|---|---|
| 解析理论 | 二区时间焦距、位置—速度相关导数、三区精确局部时间及固定净增益灵敏度 | 三维边缘场、实际丝网和仪器位姿选择 |
| SIMION几何 | 二区／三区、方／圆截面、环／屏蔽、显式侧孔及原生PA构建 | 任意拓扑或未声明的隐藏尺寸、电压 |
| COMSOL几何 | 同源实体及零厚栅构造；当前装配消费支持方形截面 | 三区新装配的真实求解、保存重开与GUI验收 |
| 机械接口 | 两种变体的真实端面、截面、外法向、壁厚及物理电极身份；直接消费者纯回归通过 | 孔内整面电位、源、时钟或粒子交接资格 |
| 封闭二区组件实验 | 具名源、完整电极电压、-z焦面、真实N100出口与候选收据 | 独立全变体Candidate/Formal或整机分辨率 |

几何由提供者单次解析发布，消费者不重画电极或用局部PA编号作为全局物理身份。
封闭二区只发布实际轴向出口；选择侧孔的独立几何才发布侧入口。三区保留真实侧口和理想零厚栅面，
不将数值bounds或理想sheet冒充机械法兰。COMSOL的零厚栅应保持内部电位面语义，不能改成有厚碰撞实体。

封闭二区可用SIMION的planar x镜像存储半域；物理跨度、存储跨度、镜像面和IOB原点均进入身份。
带侧孔几何不复用封闭PA资格。提供者机制的调用与冻结闭包回归不等于新的原生场或飞行验收。

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

组件焦面事件使用公共 scientific_event_csv writer／scientific_event_io 流式 reader；列顺序、12位有效数字、每ID时钟、原母群与原物理门槛保持。飞行入口冻结实际 writer companion 并纳入结果 manifest，项目继续拥有穿面、步长及终止政策。既有两档步长 N100 原生证据验证原事件政策，不能表述为本次 CSV 运输修改已新增原生 Fly 或科学资格。
