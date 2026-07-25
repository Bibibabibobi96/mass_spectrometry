# COMSOL：RF 四极杆无碰撞候选

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。接口输运科学入口为
`../comsol/prepare_interface_readiness_run.m`，workflow中性的共享求解机制为
`../comsol/solve_deterministic_rf_quadrupole_particles.m`；工具版本、启动方式和共享LiveLink入口只采用仓库根
[`README.md`](../../../README.md#工具链与执行入口)及
[`common/comsol/README.md`](../../../common/comsol/README.md)的定义。

专用接口入口只接受`transport_interface_readiness`的冻结run config，复核现有resolved、interface、
scientific mode和bundle在内存编译出的scientific spec，再调用共享机制。共享机制不读取`Mode`、不选择
workflow或科学gate；它通过`../load_rf_quadrupole_contract.m`读取解析发布，持久化四根圆杆、入口孔板、出口壳体、
检测器、真空选择、材料、ES/CPT、按粒子表行数生成的`ReleaseFromDataFile`节点、RF或RF+DC
`ElectricForce`、两个Study/已attach Solver、粒子数据集和轨迹图。几何、检测层厚度、RF和接口平面
不得在脚本中另设第二份数值。
传输模式使用杆组±100 V差分单位场，CPT乘`V_rf/100[V]`正弦波。质量过滤模式在同一几何中显式求解
`Vdiff`差分单位势和`Vstatic`公共偏置/静态端部势，CPT叠加`(V_dc+V_rf sin)/100 V`倍差分场与静态场；
不依赖COMSOL自动生成的`es/es2`变量名。两个模式都不存在Collisions特征。
`axial_acceleration_reference`仍使用独立的公共multipole入口、源、RF和项目专属端部几何，并通过公共分段杆builder
把每根杆分为4段、段间绝缘间隙0.4 mm；每段两种RF极性共享`0/-1/-2/-3 V`公共模，出口罩和检测
参考区保持-3 V。模型在同一静电解上推进“轴向场开启”和“同几何同RF、轴向场缩放为0”两套轨迹，
能量按检测面三维速度派生，不修改粒子速度。该模式使用300 s任务报告窗口以容纳配对推进，常规模型
仍保持120 s；这不改变网格、时间步或物理输入。
固定源位置按候选 IOB 实测基向量映射到 PA/COMSOL 坐标；速度则以 SIMION 实际轨迹的入口斜率为准：
Fly2 `standard_beam` 的角度在 IOB 放置前按局部束流基向量解释，故 `vSim=(vx,vy,vz)` 必须写为
`(-vy,-vz,vx)`。不能将位置变换机械复用于速度，也不能只做轴向交换。

以下出现的N=25、25/25及其run ID均是迁移前历史数值调查，仅用于追溯当时网格、时间步和GUI行为，
不构成当前功能、Candidate或Formal闭合证据。

空间审计表明预定义 mesh4 过粗，不得再作为基线。速度映射修正前的空间收敛数值已经失效；
修正后 mesh2（较粗）相对 mesh1 在 80 步/周期下仍为 25/25，但平均 TOF 为 49.62409 vs
50.11545 us（变化 0.98%），最大杆区半径为 0.51833 vs 0.54141 mm（变化 4.26%）。故 mesh2
不可替代 mesh1；该二级比较尚不能证明 mesh1 已达到渐近空间收敛。历史隔离候选曾使用
`RFQUAD_COMSOL_HMAX_MM`在 GUI 可见的全局 Mesh Size节点设置`custom=on,hmax`并写入摘要；当前接口
生产入口已删除该环境/CLI覆盖，唯一数值合同的两个注册profile均明确关闭hmax override。
显式 `hmax=0.5 mm` 候选仍为 25/25，但平均 TOF 为 49.93682 us（相对 mesh1 变化 0.356%）、最大杆区
半径为 0.46883 mm（变化 13.4%），故 mesh1 的渐近空间收敛尚未闭合；不得为贴近 SIMION 选择任一候选。
修正后在 mesh1 上重算 80→160 RF 步/周期，两端均为 25/25，
平均 TOF 从 50.11545 变为 50.14455 us（0.058%），最大杆区半径从 0.54141 变为 0.54395 mm
（0.47%）；故当前 80 步/周期已通过时间步收敛，继续冻结 mesh1、80 步/周期。
修正后的最终结果为 25/25、50.1155 us、最大杆区半径 0.5414 mm、`q=0.7060233`。

`workflows/interface_readiness/run_comsol.ps1`是唯一接口候选运行入口：它没有`Mode`或数值标量开关，
必须绑定[`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)及其中的
具名profile。普通profile只使用`baseline`；160步/周期只允许
`same_solver_numerical_convergence`预注册实验。schema、role、contract ID、current状态和重算逻辑
SHA-256共同构成仓库权威；自定义路径仅在逻辑完全相同时可用，运行中仍冻结仓库文件。PowerShell
support是唯一profile validator/compiler；run config顶层派生字段与`compiled_solver_numerics`来自
同一对象。MATLAB不再读合同或选择profile，但会在COMSOL import前核对compiled envelope身份及顶层
identity/数值镜像；任何篡改均早停。runner先创建interrupted三件套，再冻结和验证resolved、
interface、scientific mode、bundle与numerics；任何预检或后续错误都写入可由冻结verifier复核的failed
三件套并恢复环境。通过预检后才调用统一LiveLink启动器，随后重开MPH并通过GUI
`Study -> Compute`复算，最后写入并复验success manifest。MPH中持久化
`z_rod_exit=85.4 mm`、`z_handoff=90.2 mm`、`z_acceptance=95.2 mm`及GUI可见
`exp_phase_raw`数据导出节点。
在LiveLink启动前，runner还通过接口workflow的`particle_source_policy.py`复验bundle两点与能量政策，
并把接口CLI、policy、中性bundle机制及其`common`导入闭包按原包路径冻结到run的`input/code`树。
该预检子进程的`PYTHONPATH`只含冻结代码根且固定`PYTHONNOUSERSITE=1`；run config记录逐文件SHA-256、
包根、模块实际来源和NumPy版本/安装根，缺失或篡改任一闭包文件均在商业启动前失败关闭。中性analysis
机制不保存接口point ID、workflow role或能量判据。

2026-07-25的接口N=100重跑在stationary场解完成后、逐粒子
`ReleaseFromDataFile`构建期间停止：runtime已写到`particle_065.txt`，Java栈在创建`rel065`时由
`PhysicsClient.create`抛出空指针；尚未执行该节点的属性设置、数据导入、粒子Study或粒子Solver，
也没有原生崩溃日志。它与oaTOF历史上发生在Study solution-mesh初始化阶段的原生崩溃不是同一失败
阶段；历史RF接口、当前S2和S3均已有同型100个release节点成功证据，因此不得把本次失败解释为64节点
硬上限，也不得用变N、拆批或合并release规避。

为在不改变科学或数值输入的前提下定位该失败，接口runner提供显式
`-ReleaseConstructionGate`诊断执行阶段。它仍完整冻结和验证正式interface resolved、scientific mode、
paired N=100 bundle和`baseline` COMSOL numerics，并严格拒绝非100粒子；这不是新Mode、profile或
Candidate入口。专用MATLAB任务在模型构建前先发布`STATUS=RUNNING`任务报告，随后保持`std1/sol1`
前置场解和100个独立`rel001...rel100`、一行六列文件及100个格式化后仍唯一的逐粒子`rt`，为create、label、各属性设置和
import逐步追加关闭文件后的JSONL breadcrumb。诊断机制只允许在全部release节点验收后、创建
`ElectricForce`、`std2`或`sol2`前返回，生成带100个GUI可见release节点的诊断MPH、结构化结果和
success/failed manifest；它不运行粒子Study，不生成传输率或任何物理资格结论。该代码路径目前只有
静态与求解器无关门禁，真实Gate A尚未执行。runner在写success manifest前还从本次run冻结的Python
validator重新读取official ION11、100个实际release文件和1000条breadcrumb，逐条复核sequence、phase、
tag/count演进、文件SHA-256、`Filename`和`rt`。validator还只从冻结run config中的
`compiled_scientific_spec.source_axial_offset_mm`与ION11质量、能量、方位角和仰角独立重算每个六列
release状态；同步篡改文件、result SHA和breadcrumb SHA仍必须失败。MATLAB result中的计数字段本身
不能使Gate通过。

`workflows/mass_filter_reference/run_comsol.ps1`是RF+DC功能扫描入口；其MATLAB任务固定为
`comsol/mass_filter_reference/run_scan.m`。入口要求显式传入`SourceIonPath`，只接受仓库政策允许的
N=100或N=1000源，并从冻结源真实行数派生每质量粒子数。它派生七个只改变质量的
单质量表，在一个LiveLink会话中顺序求解，并按冻结的中心透过、端点抑制和对比度判据汇总。每个质量
只保留`particle_state.csv`和`solver_summary.json`，101.5 Th额外保存一份GUI可检查MPH。该runner不读取
L1或SIMION run，也不产生跨来源结论；`workflows/mass_filter_reference/compare_responses.ps1`作为
独立analysis入口显式消费COMSOL、SIMION和L1成功manifest。比较差异只作诊断，不构成网格或分辨能力资格。迁移前小N结果
仅为历史证据；新的COMSOL、SIMION及跨求解器权威响应须等待N=100复验后建立。

标准逐粒子结果为`<mode>_particle_state_<run>.csv`；官方回归的mode仍为`transport_no_collision`。
每个粒子写出精确source、杆端、
交接面和terminal事件，包含位置、SI速度、能量、发散角、RF相位及终止原因。跨面状态由同一COMSOL
粒子数据集线性插值，原始轨迹由MPH内Export节点导出；旧solver-specific终点表不再由新运行生成。

同一次生产运行还导出 `runs/<run_id>/results/trajectory_samples.csv`：每个粒子每 5 个
已存储时间点取一个有限样本，并始终包含最后一个有限样本；列为统一 PA/COMSOL 坐标的
`particle_id,time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm`。它只用于求解器无关的轨迹诊断，
不承载任何未持久化的 COMSOL 物理或数值逻辑。

`tests/comsol/verify_nocollision_comsol.m`只接受显式`RFQUAD_COMSOL_MODEL_PATH`，重开MPH后按输入粒子
表检查GUI release节点数量、接口平面参数、无碰撞、选择集、Export和Solver attach，并分别调用
`model.study('std1').run`、`std2.run`。2026-07-18相空间候选复验为25/25、平均检测时间
50.1154545 us、`q=0.706023302`，Solver标签保持`sol1,sol2`。

N=100接口候选重开后GUI Compute仍为100/100，`std1/std2`分别约9.43/23.35 s，平均检测时间
50.43318 us、`q=0.706023302`。该复验只证明MPH自包含和GUI等价，不把未通过的跨求解器相空间目标
改写为PASS。

`tests/comsol/export_fem_unit_rf_field.m` 只从候选 MPH 的 `dset1` 采样 COMSOL 自己的
`es.Ex/Ey/Ez`，采样坐标取自 SIMION 导出的公共格点；它不创建插值函数、不写入 Electric Force，
输出仅供 `analysis/compare_unit_rf_field.py` 与独立 PA 场比较。

mesh1→显式 `hmax=0.5 mm` 的自身单位场差在入口/杆区/出口分别为 1.945%/0.271%/3.239%。
与 0.2 mm PA 比较时，细 FEM 的杆区/出口差降至 0.0521%/0.384%；与 0.1 mm PA 比较时为
0.0289%/0.359%。入口细化后仍为 4.466%，因此入口差不能单独归因于某一求解器，须按两端几何边界
离散敏感性处理。

`RFQUAD_SOURCE_AXIAL_OFFSET_MM` 只平移 25 个 GUI 可见 `ReleaseFromDataFile` 的轴向位置，并记录在
摘要中；默认 0。它用于绕开入口边缘场的隔离测试，不改变静电场、RF 力、Study 或 Solver。

## 连续屏蔽候选的网格策略

连续圆柱屏蔽候选不再用全域各向同性四面体加密。均匀杆区采用横截面自由三角形后沿轴向扫掠：
工作核心`r<=8 mm`及杆边界最大单元`0.2 mm`，外部真空最大单元`1.0 mm`，轴向40层；入口与出口
端区使用自由四面体。`tests/comsol/run_rf_hybrid_mesh.ps1`可在完全相同的粒子、RF波形、时间步和
交接面下运行端区`0.5/0.25 mm`配对诊断。导体实体故意不做体网格，完整性按内部真空覆盖、无mesh
problem、求解成功和有限场样本判断，不得把全模型`iscomplete=false`误报为物理域缺失。

两级混合网格均为100/100通过，分类不变，出口RMS半径、发散和平均能量的相对差分别约为
`0.514%/1.042%/0.050%`；但逐粒子RF相位RMS差仍为`0.369 rad`。因此端区`0.5 mm`只作为下一阶段
低成本候选，`0.25 mm`保留为参考，禁止继续运行`0.125 mm`。两份出口状态在同一SIMION oa静电
Formal分析器中的E2投影保持相同r99失败分类，传输差为1个百分点且分类互换只发生在探测器最外
1.72%半径区域，故`0.5 mm`保留用于下一阶段。隔离SIMION有限脉冲功能链现已PASS；真实连接器与
联合场建立后仍须配对复验；局部场
最大值、通过率或相位差中的任一项都不能单独决定最终网格。

分段全器件扫掠曾在拓扑变化段出现源/目标面不兼容；一次真空拓扑印记修正后仍在杆出口过渡段失败。
该策略已关闭，不再通过反复指定局部面或增加第三套层数继续调试。

## RF→oaTOF活动COMSOL链

`tests/comsol/build_s2_passive_connector_model.m`是共享几何的唯一MATLAB构建函数；活动求解入口
`tests/comsol/run_s2_passive_connector_field.ps1`调用它建立无脉冲S2连接器场，并作为统一S3累积链的内部步骤。
孔、局部域和场基只从`config/rf_to_oatof_shared_physical_port_joint_geometry.json`读取；1 mm标称间距与
0 mm直接共面案例均由同一S2合同和拓扑案例解析器派生，不另存第二套几何。

S2 runner在建立run package后按`s2_passive_connector` consumer冻结依赖。Python解析、校验、handoff和
manifest生命周期只从nested runtime snapshot执行；同SHA顶层oa baseline/builder副本仅供MATLAB环境变量
兼容。runner、support和run package初始化属于snapshot建立前的live bootstrap，冻结完成后不再允许live
provider Python cwd或module path。该隔离先由纯分析poison与失败恢复测试覆盖，随后已完成下述真实COMSOL复验。

当前1 mm N=100功能运行得到61个oa入口过面和39个端壁损失；0 mm得到77个入口事件和23个入口壁损失。
两种模式均保持粒子ID、三维状态和全局时钟，不加入oa提取脉冲，也不保存MPH。数值重启的`0.001 mm`
仅是求解器适配量，不是器件间距、孔厚或物理容差。上述结果没有获得网格收敛、最低传输率或阶段资格。

S3通过`tests/cross_solver/run_s3_cumulative_chain.ps1`统一执行S2无脉冲接口、共享时钟脉冲和SIMION下游。
MATLAB求解脚本只写terminal census与脉冲左极限状态，不维护公共28列canonical schema或重复动能公式；
冻结的`analysis/build_s3_local_exit_component_state.py`按来源ID连接terminal出口状态，复用公共列顺序、
validator和粒子物理公式生成局部出口canonical CSV。runner固定按COMSOL→adapter立即验证→链审计→SIMION
失败关闭。脉冲时刻由`analysis/derive_shared_centroid_pulse_time.py`从真实状态与共享端口几何派生，图审由
`analysis/plot_shared_pulse_geometry_snapshot.py`生成。退役阶段只在
[`history/20260722_rf-validation-and-s1-integration.md`](history/20260722_rf-validation-and-s1-integration.md)
追溯；独立build-only/审计入口和既有artifacts都不是活动入口。

`tests/comsol/run_s3_pulse_capture.ps1`与`tests/cross_solver/run_s3_end_to_end.ps1`已分别按consumer冻结
依赖、来源manifest及Python/manifest闭包；累积runner使用end-to-end run内的冻结verifier复核阶段manifest。
迁移后的1 mm链已由统一累积入口在同一`20260724_205559`时间戳下完成真实COMSOL S2、COMSOL S3
和SIMION E2E复验，得到`100→61→31→31→7`且三阶段manifest均为success。该结果只证明N=100功能链和快照隔离，
不构成stage PASS、N=1000、收敛、分辨率或Formal资格。

S3静态校验同时闭合resolved S2 registration、共享入口面/法向/孔径、oa屏蔽0 V公共参考、canonical
frame与clock epoch以及目标质量/电荷选择。调度输入必须具有唯一粒子ID、有限三维状态、正向入口速度
和真实`oatof_entry/transmitted`事件；端口接受度相对合同中心计算，不假定横向中心为零。局部链审计
再按粒子ID复核质量、电荷、species ID和三类累计时钟，任何冲突均失败关闭。

`tests/comsol/run_rf_hybrid_mesh.ps1 -EnergyMatch`允许同一低成本混合网格消费显式5 eV命名源及其metadata，
但不改变COMSOL几何、电极电势、RF差分幅值或CPT力表达式。入口生成器对每种能量分布都消耗同一能量
分位随机数，保证固定能量与分布能量工况的后续方向采样逐粒子配对；旧生成器分支造成的首次非严格配对
run只保留为排错证据。能量匹配的正式比较由Python读取两份事件表和两份ION源，COMSOL不维护第二套
统计算法。
