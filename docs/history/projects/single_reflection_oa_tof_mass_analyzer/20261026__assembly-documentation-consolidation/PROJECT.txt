# 单次反射正交加速飞行时间质量分析器当前状态

本文件是项目当前事实、资格与开放任务的唯一权威。机器精确值分别由[`config/`](../config/)中的物理、数值、
resolved、分析和资产合同管理；实现细节见[`COMSOL.md`](COMSOL.md)、[`SIMION.md`](SIMION.md)与
[`CAD.md`](CAD.md)。2026-07-28以前的完整状态和时间线冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 统一组装迁移任务

状态为代码迁移中，依赖[统一组装计划M1/M3/M4](../../../docs/ROADMAP.md#统一组装迁移计划)；
职责见[组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)。尚未完成的整机入口继续活动，
在途求解、Formal合同及资产身份保持。

本项目保留反射器、仪器布局约束、加速器—反射器联合聚焦、检测与自身验收；继续提供required port、
resolved几何及分析器接口。待办是在统一配方中明确分析器与OA实例边界，避免重复装入加速器，并将跨项目
适配与连接编排随现有integration迁移。关闭条件是原分段／连续整机工作流的冻结输入、端口、驱动、事件、
母群和时钟经相称对照一致，调用与身份同步切换；独立器件或局部前端通过不授予整机或Formal资格。

候选加速器实体尺寸、屏蔽外壁和环位置现由项目
[`accelerator_geometry.py`](../analysis/accelerator_geometry.py) 解析，直属共享 frontend 的粗场、主场及
入口局部场复用同一提供者的几何／显式开孔投影，原 sectioned renderer 和 GEM 构造不变。
[`assembly_interface.py`](../analysis/assembly_interface.py) 发布完整器件接口；其中
`accelerator_side_shield` 只表示方形加速器的连续侧屏蔽与后壁，provider-local 物理 ID `1` 只标识该实体，
不表示整套 oa-TOF 的电极清单，也不是 SIMION PA 编号。接口沿用 `oatof_global`，取实际金属外表面、
壁厚和矩形孔截面；开孔中心与尺寸必须来自显式请求，不能从粒子源或 Formal required port 推定。
入口局部场已投影的实际孔径与粗场／主场参考孔径分别保持各自职责；机械接口必须消费实际孔径投影。
圆柱实现继续使用既有渲染，但没有可冒充平面的统一外侧孔端面，当前机械接口明确拒绝该 variant。

本次无商业软件回归覆盖独立 300 mm／20 环夹具、真实 frontend／局部场消费、公共 Schema、
外壁／半壁偏移拒绝及孔径变化；二区、三区和 300 mm 前端的迁移前后 GEM 字节相同。
这是已接入现有渲染的提供者边界，不代表新整机 recipe、完整电极绑定、连续飞行或 Formal 验收完成；
统一组装还需直接消费此机械视图并闭合原有母群、时钟和实际场链。

最终候选 resolved 的 PA 内部实例位置、网格尺寸及场采样点现统一由
[`geometry_contract.derive_simion_geometry`](../analysis/geometry_contract.py) 派生；baseline 解析和
集成的合成候选测试夹具在最终坐标修改后共用该函数，避免保留旧
`derived.simion_instances`／`field_sample_points_mm`。原集成布局编译器已无生产消费者，所需科学计算原样移入
测试边界，不再作为运行依赖。提取前后 baseline 序列化输出相同，纯回归覆盖
非零反射器轴、独立尺寸向量和完整三区候选。此处不改变实体、场、电压或已冻结运行。
分析器Lua可在新实际分段前端及已支持三区OA拓扑下消费显式provider placements；Program核对已装入位置，
不重算或覆盖。三区OA局部路径不伪装为分段杆模型；范围、场与源由集成冻结输入决定。
新旧Python生成器及普通Lua回归通过，具体边界见[统一集成状态](../../../integrations/docs/INTEGRATION.md)。
无实际消费者的`static_electrode_plans` API及初始化中的重复静态计划已退役，实际电压写入、理想场、位姿、
探测器和时钟保持。原纯Lua夹具与生成Program行为回归经公共GATE通过；不据此授予原生Repeat Fly或GUI资格。
完整器件接口现消费最终resolved与实际OA投影；提供者`resolve_physical_geometry`统一真实电极对象、
外罩分片、反射器环位和电压，既有三套GEM／builder及Formal调压直接读取同份冻结Lua投影。
共同外罩保留一个物理身份；真实1 mm探测器与0.1 mm数值marker分开，不把数值吸收体当作额外物理电极。
已删除旧scalar几何参数路径、GEM重复派生和PowerShell分压数学；Formal调压使用17位往返文本保留实际double值。
Candidate也改为从既有冻结code root执行同一具名编译模块，编译来源及传递依赖纳入原source closure，
不再仅记录源码却调用活动仓库中已导入的编译器。
冻结compiler返回非零时，错误现保留实际退出码、日志路径及末尾最多4 KiB stderr，
使临时计划目录清理后仍能定位真实失败；成功路径和依赖清单不变。Candidate与成对场adapter两完整模块
77项97.997 s通过，含真实Python子进程exit17及长Unicode stderr；该回归不授予新商业或物理资格。
真实GEM／网格／Formal电压及冻结编译6项通过；12个消费者模块首轮203项中202通过，
唯一不完整两区夹具修复后单项通过。既有生成Lua完成一次格式新鲜度刷新，公开静态几何门禁通过。
科学resolved JSON、粒子源及原资产不变；旧direct refine-all的12位电压文本与新版有微小差异，
源码身份不同的旧场不能自动获得新版资格。本轮未执行新Refine、Fly、COMSOL或GUI／CAD验收。
无活动注册的旧N=100源码构建／跟踪包装已删除；相同构建与transport由既有Candidate入口承担，
原先三次SIMION缺参探针改为实际builder的纯Lua快速回归，不再为参数错误启动求解器。
仅属于该包装的当前引用退出，原始运行及只读历史保留；没有旧CLI转发。
组件的`diagnostics.post_pulse_observation_window_us`现接受显式`false`，表示只观察状态、由调用workflow
控制停止；原有限正观察窗的行为保留。新整机采用此关闭值，避免旧脉冲后观察窗成为第二个停止权威。
末步状态仍完整更新，原生检测器碰撞仍由同一`terminate`判定，不新增软件平面命中或修改Formal控制。
旧活动消费者仍使用原位姿路径；实际PA几何、场包和完整Fly尚未验证，不能由非零轴回调夹具推定整机物理贯通。
检测器网格现由同一提供者按原生Lua的`floor(span/cell + 0.5)+1`派生，下游不再复制网格公式，
避免半cell输入触发Python偶数舍入与原生尺寸不一致。18项相关纯回归覆盖半格尺寸、容量边界与无staging拒绝；
baseline完整resolved序列化前后SHA相同。该修复不改变机械尺寸、电压或既有冻结运行，不代表已通过原生构建。

候选单飞布局由本项目的 [`single_flight_layout_profiles.json`](../config/single_flight_layout_profiles.json)
唯一发布，包括 300 mm／20 环实现与显式有限区间设计条件；集成准备器和项目诊断消费同一份配置。
有限区间布局编译仅消费该 profile 显式提供的相空间、源宽和首区长度，不再隐式读取集成历史拟合文件。
集成的历史相空间拟合合同仍供其真实源物化消费者使用；布局中的设计条件不替代实际母群或出生时钟，
脉冲调度仍由集成负责。本次归属收敛不改变物理数值、已冻结运行或 Formal 资产。

加速器 ON 电压由 [`accelerator_electrical.py`](../analysis/accelerator_electrical.py) 的
`resolve_accelerator_electrical_design` 从最终 resolved 发布，返回真实端面、环位置及语义电极电压，
不编号求解器电极，也不读取粒子源。环电压的 Python 线性分压由同模块
`linear_ring_electrode_voltages` 统一计算；它只接受 grid1、可选 intermediate2、grid2 的有序端点，
环不得越界外推。三区 topology 与 resolved 电极表冲突时拒绝发布；OFF 电压及脉冲时序由实验显式声明。
纯回归覆盖二区与 300 mm／20 环既有 Python 计划的逐值一致性、非零出口电位和非法输入；
这只完成提供者电压边界，不改变既有 Lua、冻结输入、真实场或 Formal 资格。

共同静态采样比较现按唯一`point_id`对齐两后端的完整坐标及电场，静态图固定为三个分量面板，
不随采样点数增加子图；离散点不连成空间曲线。
样点完整配对和RMS归一化统一由[`common.analysis.field_comparison`](../../../common/analysis/field_comparison.py)
提供；三个项目分析消费者及成对场工作流直接调用，原项目模块和无人生产调用的收敛判定已删除。
样本选择、单位及数值／物理资格仍由各科学合同拥有。两个纯函数算法不变，四个完整分析模块23项通过，
成对静态场完整11项（含脱仓冻结）通过；这些回归不新增求解器或物理资格。
512点反向行序的真实渲染回归核对完整ID关联、
V/m到V/mm显示转换及来源元数据，比较器完整5项测试通过，合成预览已目视复核。
该证据只验证比较与显示机制；静态结果标为`COMPARISON_COMPLETE`，没有获批容差时不判数值等价，
也不表示两个求解器已完成共同边值问题的原生求解。
共同静态场COMSOL函数负责实际求解、保存及采样；2026-10-25移除误写的`MATLAB_BUILD_ONLY`标记，
恢复其真实执行职责。构建专用函数的门禁保持不变，本次仅纠正声明，不改变求解、模型或输入。

CAD实体清单现直接消费完成模型的feature tags；OA与两段反射器共用同一自然排序，固定五OA环及旧重复发现代码已删除。
原Formal五OA环／10+5反射器环的25实体顺序保持，新20OA环模型会列出40实体；理想栅及布尔辅助体不作为机械部件。
现有CAD单元已扩为8项，另两项原生Integration保留；CAD单元及ArtifactContext的10项已在下述原生run全部通过。
OA-only共同场MPH缺少完整仪器的反射器、飞行管和探测器，不能用于完整oaTOF CAD验收；完整跨项目装配还须真实多极杆。
具名构建API提供显式GeometryOnly停止点，避免仅为CAD重新建网或求场。
[075441受管验收](../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261026_075441__test__comsol__geo/summary.json)
已通过18项MATLAB Unit（12.225 s）、完整组件几何保存、独立进程重开及headless STEP导出。
模型45域、40物理对象，physics／mesh／study为空；重开清单相同，STEP AP203／mm整包及40独立部件全部发布。
原110745冻结几何、电压投影和外壁侧孔保持，新MPH为2,774,497 bytes，不执行ES／CPT／Fly。
本次只取得`geometry_save_reopen_step_only`，不包含上游多极杆、SolidWorks、GUI或Formal资格；GUI继续按用户决定暂缓。
Candidate源码闭包已补齐公共COMSOL入口实际依赖的预算脚本；真实冻结加载及原共享调度继承回归1项5.698 s通过，
无Limits不生成usage产物。这只证明脱仓接线，不包含新的COMSOL执行或危险处置验收。

## 当前状态

反射器调压的[045007隔离诊断](../../../../artifacts/projects/instrument_assembly/runs/20261026_045007__test__simion__reflectron-api-isolation/summary.json)
保留115004已完成Refine的原19电极double电压及独立私有family副本。旧builder的`adjust-only`
在同长度路径再次以0xC0000005退出；PA API的调压／保存及独立进程重开均退出0，19电极电压及8个场样点核对通过。
整个诊断未Refine、Fly或启动GUI；总终态failed保留CLI负结果，不能据API子阶段成功改写为整链通过。
原`simion.command`调压已替换为官方`pa:fast_adjust`，不改变几何、原电压表或数值精度。
38项提供者／下游回归通过；130533整机续接的反射器构建、调压、导出及原生审计已通过。
后继134240复用这些场，N=100基线与保存默认回放均完成且比较差异为空；完整链结论与零探测器命中的资格边界见集成状态。
官方[内存与PA API说明](https://simion.com/info/ram_and_memory.html)明确该接口自8.1提供，适用于本机SIMION 2020；
仓库公共导出工具已采用同一路径。资料核验于2026-10-26；本次隔离不定位供应商内部崩溃原因，也不授予整机物理资格。

- OA-only共同场的有限脉冲消费者已实现为
  [`run_paired_accelerator_pulse.m`](../comsol/run_paired_accelerator_pulse.m)，读取同一已解ES模型和完整实录Cartesian源，
  保持绝对时钟及原粒子映射，只新增CPT；成功Compute后先保存粒子解，再导出。原生输入合同运行
  `20261026_022056__test__comsol__paired-pulse-input-contracts`中12项MATLAB测试通过，未打开模型或求解。
  新集成owner的真实N=100 CPT已完成，保存raw粒子解后导出完整初态和声明时刻状态，
  其原生事实、后端差异与阶段恢复边界统一见[集成状态](../../../integrations/docs/INTEGRATION.md#共同场与有限脉冲)。
  此局部模型不等于完整反射器仪器MPH，不替代下面的整机、GUI／CAD或Formal资格。

- 有限 ON/OFF 脉冲的原生 COMSOL 微例程已在受管运行
  `20261024_163000__test__comsol__finite-pulse-superposition-timecap1ns` 完成。它只覆盖 10 mm 立方体、
  静态 17 V/m 横场、0.371--1.613 us 的 43 V/m 脉冲和一个 100 u、+1 粒子；字段实际采样为
  `[17,0,0]`／`[17,0,43]` V/m，fine 解析误差为 `4.223698e-10 m`、`4.810830e-4 m/s`，保存重开后的
  默认 Study Compute 重复同一结果。COMSOL 6.4
  [Time API 表 6-74](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html)
  说明 `strict` 只保证输出时刻为内部步而不限制间隔；该夹具因此冻结 `tstepsgenalpha=strict`、`tout=tlist`
  及 `maxstepconstraintgenalpha=const`、`maxstepgenalpha=1 ns`，未放宽 1 nm／1 mm/s 判据。每次成功的
  原生粒子 Compute 都在任何轨迹读取、CSV 或后处理前保存具名 raw MPH checkpoint；后处理失败不能声称可
  从未保存状态恢复。此前 `160500` 的默认稳态场误差、`161000` 的单粒子数组形状假设、`161500` 和
  `162000` 的不足时间步均以 failed 受管 run 保留，未被成功记录覆盖。此结果只验证具名有限脉冲机制，
  不授予仪器、N100、跨求解器或 Formal 资格。

- COMSOL具名入口现接受现有`AcceleratorGeometry`、`AcceleratorElectricalDesign`及显式机械
  `SideOpening`，两份投影必须成对提供；三区缺投影明确拒绝。器件实体／零厚栅构造由OA项目共用实现，
  本项目只负责真空嵌入、选择集和电压消费；原二区仍为独立有效结构。当前三区ON模型只完成纯回归及
  静态接线检查，未生成匹配新整机的MPH，不授予有限脉冲、跨求解器或Formal资格；后续真实边界见
  [直属集成状态](../../../integrations/docs/INTEGRATION.md)。`FixedParticleTable`仍是既有ION角度／能量表，
  不接受把Cartesian重追踪CSV当作该表输入。
  具名入口新增`FieldDesignOnly`与互斥的`CartesianRelease`：前者只构建几何／网格、求解一次静态ES、
  配置CPT后保存，不执行粒子或fallback；后者仅配置此源MPH，和集成重追踪共用真实CSV reader，保留
  原ID／行序及直接Cartesian速度。实体检测器读取resolved有限的直接x/z，与理论focus派生值解耦。
  `ArtifactRoot`沿公共路径解析显式绑定生命周期产物根，冻结源码可脱离活动仓库执行，普通输出的
  runs／scratch及Formal写保护仍有效。接口和操作边界见[COMSOL输入合同](COMSOL.md#模型与合同)。
  本次19项真实MATLAB纯测试与28项Python回归通过；冻结源码22文件依赖闭包不读取活动仓库，且实际
  192618数据的100个预脉冲原ID／状态已读入核对。MATLAB范围为
  `OaTofCartesianReleaseTest`、`OaTofResolvedLayoutTest`和`OaTofArtifactContextTest`；Python范围为
  `test_comsol_accelerator_projection`和`test_comsol_prepulse_replay`。这些均属于无COMSOL求解的准备检查。
  同父plan派生的OA局部scope排除上游MP RF，仅冻结其drive与唯一绝对clock作为来源说明；
  当前源模型仍声明静态ON，不授予RF等价、有限脉冲、detector命中或Formal资格，matching MPH尚未完成。
  随后的32 GiB磁盘／24 GiB内存准入在[公共容量门][matching-capacity-failure]被拒绝，未启动COMSOL；失败run按公共owner封存，
  不降预算或提高水位绕过。容量释放后也不得自动启动；必须先以新run身份冻结并闭合同域、实体与边界匹配，再按相同预算准入，不能继续失败run写入。
  此前Static门禁的413项分析测试（1项跳过）通过；随后直接检测器接线修复后的首次完整检查执行
  417项，因旧Candidate冻结器仍改写`workspaceRoot`而产生32个错误，失败日志保留。移除该私有源码
  替换、冻结公共路径依赖并使COMSOL／CAD消费同一runtime产物根后，公开`verify_project -Level Static`
  执行418项分析测试、1项跳过，最终退出0（门禁155.109 s）；Formal静态几何合同检查通过。
  `test_formal_reference_workflow_layout`覆盖直接接线与旧覆盖拒绝，Candidate回归覆盖源码不改写和
  COMSOL／CAD根传递；CAD纯Unit共3项通过，其中2项验证显式产物根的Formal保护在原生打开前拒绝。
  这些结果不包含新的商业软件求解、CAD实体／GUI验收或Formal资产复验。

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
- 当前Formal坐标以检测器有效面中心和精确一阶时间焦点为`z=0`，`+z`从加速器指向反射器。SIMION局部PA
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
  [integration当前文档](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20261024__legacy-family-retirement.md)。
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
[integration当前文档](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20261024__legacy-family-retirement.md)。

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

[matching-capacity-failure]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261024_210625__sim__comsol__192618-oatof-local-static-on-field/summary.json
