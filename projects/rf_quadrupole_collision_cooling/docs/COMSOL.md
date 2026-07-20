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
