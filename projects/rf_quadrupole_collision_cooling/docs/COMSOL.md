# COMSOL：RF 四极杆无碰撞候选

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。生产脚本为
`../comsol/ms_rf_quadrupole_no_collision.m`，只通过根目录 `common/comsol/run_comsol_r2025b.ps1`
与 MATLAB R2025b 启动。

脚本持久化四根圆杆、入口孔板、出口壳体、检测器、真空选择、材料、ES/CPT、25 个
`ReleaseFromDataFile` 节点、RF `ElectricForce`、两个 Study/已 attach Solver、粒子数据集和轨迹图。
静态 ES 使用杆组 ±100 V 单位场，CPT 乘 `V_rf/100[V]` 的正弦波；模型内不存在 Collisions 特征。
固定源位置和速度按候选 IOB 实测基向量映射到 PA/COMSOL 坐标，不能只做轴向交换。

空间审计表明预定义 mesh4 过粗，不得再作为基线。完整三轴对齐后，mesh2→mesh1 时传输均为
25/25，平均 TOF 变化 0.28%、最大杆区半径变化 9.82%；mesh1 上 80→160 RF 步/周期时平均
TOF 变化 0.05%、最大杆区半径变化 0.89%。因此冻结 mesh1、80 步/周期。
最终结果为 25/25、50.1673 us、最大杆区半径 0.4944 mm、`q=0.7060233`。

`tests/comsol/verify_nocollision_comsol.m` 重开 MPH，检查参数、25 个 GUI release 节点、无碰撞、
选择集和 Solver attach，并分别调用 `model.study('std1').run`、`std2.run`；结果 25/25，且 Solver
标签始终为 `sol1,sol2`。先前 150 mm 简化直杆 MPH 仅是失效候选。
