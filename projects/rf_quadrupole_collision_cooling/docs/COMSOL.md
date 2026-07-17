# COMSOL：RF 四极杆无碰撞候选

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。生产脚本为
`../comsol/ms_rf_quadrupole_no_collision.m`，只通过根目录 `common/comsol/run_comsol_r2025b.ps1`
与 MATLAB R2025b 启动。

脚本持久化四根圆杆、入口孔板、出口壳体、检测器、真空选择、材料、ES/CPT、25 个
`ReleaseFromDataFile` 节点、RF `ElectricForce`、两个 Study/已 attach Solver、粒子数据集和轨迹图。
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

逐粒子 CSV 除到达时间和径向统计外还写入最终有限样本的 `terminal_x/y/z_mm`，供跨求解器终点诊断图
保留探测器命中与任何半路终止的位置。

同一次生产运行还导出 `results/comsol/transport_no_collision_trajectory_samples.csv`：每个粒子每 5 个
已存储时间点取一个有限样本，并始终包含最后一个有限样本；列为统一 PA/COMSOL 坐标的
`particle_id,time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm`。它只用于求解器无关的轨迹诊断，
不承载任何未持久化的 COMSOL 物理或数值逻辑。

`tests/comsol/verify_nocollision_comsol.m` 重开 MPH，检查参数、25 个 GUI release 节点、无碰撞、
选择集和 Solver attach，并分别调用 `model.study('std1').run`、`std2.run`；结果 25/25，且 Solver
标签始终为 `sol1,sol2`。先前 150 mm 简化直杆 MPH 已删除。

`tests/comsol/export_fem_unit_rf_field.m` 只从候选 MPH 的 `dset1` 采样 COMSOL 自己的
`es.Ex/Ey/Ez`，采样坐标取自 SIMION 导出的公共格点；它不创建插值函数、不写入 Electric Force，
输出仅供 `analysis/compare_unit_rf_field.py` 与独立 PA 场比较。

mesh1→显式 `hmax=0.5 mm` 的自身单位场差在入口/杆区/出口分别为 1.945%/0.271%/3.239%。
与 0.2 mm PA 比较时，细 FEM 的杆区/出口差降至 0.0521%/0.384%；与 0.1 mm PA 比较时为
0.0289%/0.359%。入口细化后仍为 4.466%，因此入口差不能单独归因于某一求解器，须按两端几何边界
离散敏感性处理。

`RFQUAD_SOURCE_AXIAL_OFFSET_MM` 只平移 25 个 GUI 可见 `ReleaseFromDataFile` 的轴向位置，并记录在
摘要中；默认 0。它用于绕开入口边缘场的隔离测试，不改变静电场、RF 力、Study 或 Solver。
