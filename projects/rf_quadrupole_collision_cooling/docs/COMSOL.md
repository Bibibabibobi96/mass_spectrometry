# COMSOL：RF 四极杆无碰撞候选

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。生产脚本为
`../comsol/ms_rf_quadrupole_no_collision.m`；工具版本、启动方式和共享LiveLink入口只采用仓库根
[`README.md`](../../../README.md#工具链与执行入口)及
[`common/comsol/README.md`](../../../common/comsol/README.md)的定义。

脚本通过`../load_rf_quadrupole_contract.m`读取解析发布，持久化四根圆杆、入口孔板、出口壳体、
检测器、真空选择、材料、ES/CPT、按粒子表行数生成的`ReleaseFromDataFile`节点、RF
`ElectricForce`、两个Study/已attach Solver、粒子数据集和轨迹图。几何、检测层厚度、RF和接口平面
不得在脚本中另设第二份数值。
静态 ES 使用杆组 ±100 V 单位场，CPT 乘 `V_rf/100[V]` 的正弦波；模型内不存在 Collisions 特征。
固定源位置按候选 IOB 实测基向量映射到 PA/COMSOL 坐标；速度则以 SIMION 实际轨迹的入口斜率为准：
Fly2 `standard_beam` 的角度在 IOB 放置前按局部束流基向量解释，故 `vSim=(vx,vy,vz)` 必须写为
`(-vy,-vz,vx)`。不能将位置变换机械复用于速度，也不能只做轴向交换。

空间审计表明预定义 mesh4 过粗，不得再作为基线。速度映射修正前的空间收敛数值已经失效；
修正后 mesh2（较粗）相对 mesh1 在 80 步/周期下仍为 25/25，但平均 TOF 为 49.62409 vs
50.11545 us（变化 0.98%），最大杆区半径为 0.51833 vs 0.54141 mm（变化 4.26%）。故 mesh2
不可替代 mesh1；该二级比较尚不能证明 mesh1 已达到渐近空间收敛。生产入口支持仅用于隔离候选的
`RFQUAD_COMSOL_HMAX_MM`：它会在 GUI 可见的全局 Mesh Size 节点设置 `custom=on,hmax`，并写入摘要。
显式 `hmax=0.5 mm` 候选仍为 25/25，但平均 TOF 为 49.93682 us（相对 mesh1 变化 0.356%）、最大杆区
半径为 0.46883 mm（变化 13.4%），故 mesh1 的渐近空间收敛尚未闭合；不得为贴近 SIMION 选择任一候选。
修正后在 mesh1 上重算 80→160 RF 步/周期，两端均为 25/25，
平均 TOF 从 50.11545 变为 50.14455 us（0.058%），最大杆区半径从 0.54141 变为 0.54395 mm
（0.47%）；故当前 80 步/周期已通过时间步收敛，继续冻结 mesh1、80 步/周期。
修正后的最终结果为 25/25、50.1155 us、最大杆区半径 0.5414 mm、`q=0.7060233`。

`tests/comsol/run_transport_candidate.ps1`是唯一候选运行入口：生成显式run config，调用统一LiveLink
启动器，随后重开MPH并通过GUI `Study -> Compute`复算，最后写入并复验manifest。MPH中持久化
`z_rod_exit=85.4 mm`、`z_handoff=90.2 mm`、`z_acceptance=95.2 mm`及GUI可见
`exp_phase_raw`数据导出节点。

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

## S1局部联合场粒子事件

`tests/comsol/run_s1_joint_field_candidate.ps1`在显式粒子输入下除100行物理孔终态清点外，还导出
`s1_pulse_capture_particles.csv`。该表只在统一脉冲开启时刻对每个仍有有限状态的粒子插值一次，保存
`particle_id`、全局仪器时刻、三维位置、三维速度及是否位于oa Formal理想释放参考体积；质量、电荷、
能量、速度模、方向角和入孔后时间由输入表与分析脚本派生，不逐行重复。`CAPTURE_ROWS`进入COMSOL
报告，CSV进入run manifest。此事件证明粒子在某时刻的位置和速度，不等同于密集轨迹，也不把理想
释放体积升级为硬接受度或捕获判据。

同一运行器随后必须调用`../analysis/plot_s1_pulse_geometry_snapshot.py`，在来源run的`results/`生成
`s1_pulse_geometry_snapshot.png/json`并纳入summary和manifest。固定两子图分别为RF注入轴与oa加速轴
构成的`x-z`平面、RF注入轴与横向轴构成的`x-y`平面；两图都叠加物理孔、接地加速器屏蔽、加速环
电极投影和虚线理想源边界。加速器中心、屏蔽、排斥极、栅网、环数量及尺寸只从本次冻结的oa baseline
派生，孔尺寸只从S1联合场合同读取，不允许绘图脚本另存几何硬数字。COMSOL粒子终止后可能在后续
时间网格保留最后有限坐标；绘图器必须联读终态事件，将位于有限厚入口壁且落在孔边界的
`electrode_or_boundary`终止粒子以及冻结在排斥极、grid1/grid2或加速环上的终止粒子从活动统计中排除。
这些碰壁坐标仍须在两个子图中分别用入口孔壁损失、加速器内部损失标记绘出，不能伪装成活动离子或
只藏在metadata里。grid1的xy半宽取带绝缘间隙的环电极外半宽，grid2才取屏蔽内半宽；`x-y`子图的
加速环内外边界均用实线。图的时刻语义固定为脉冲开启前的左极限`t_pulse^-`。有限电场阶跃不使位置或
速度瞬时跳变，因此可使用开关边界的连续状态。粒子标记面积以N=100为基准，快照行数更大时按
`min(1,sqrt(100/N))`缩放，避免N=1000等大样本遮蔽损失位置和几何边界。

脉冲时刻不再由固定14 mm传播距离或某一100 amu/5 eV常数给出。运行前由
`../analysis/derive_s1_centroid_pulse_time.py`读取canonical handoff表、oa baseline、S1孔和显式目标
`mass_amu + charge_state`：先以实际`vy/vx`、`vz/vx`预测粒子是否能穿过有限厚矩形孔，再解析求解其
x质心到达oa理想源中心的共享时刻。`run_s1_joint_field_candidate.ps1 -PulseSchedulePath`只接受PASS
schedule且强制核对粒子表SHA，然后从schedule读取脉冲时间和宽度。混合物种未显式选择时失败关闭；
能量只通过逐粒子实际速度进入，不在COMSOL运行器重复换算。该规则服务连续束时间切片弹射，不要求
紧凑储存或以命中率选择时刻。

`tests/comsol/run_rf_hybrid_mesh.ps1 -EnergyMatch`允许同一低成本混合网格消费显式5 eV命名源及其metadata，
但不改变COMSOL几何、电极电势、RF差分幅值或CPT力表达式。入口生成器对每种能量分布都消耗同一能量
分位随机数，保证固定能量与分布能量工况的后续方向采样逐粒子配对；旧生成器分支造成的首次非严格配对
run只保留为排错证据。能量匹配的正式比较由Python读取两份事件表和两份ION源，COMSOL不维护第二套
统计算法。
