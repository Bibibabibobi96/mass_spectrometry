# SIMION：RF 四极杆无碰撞候选

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。项目 GEM 是内置 `examples/quad` 单体参考的受控副本；
`analysis/generate_fixed_fly2.py` 把共享 ION 表转换为显式 25 束 Fly2，候选 IOB 沿用官方文件并在
同目录绑定项目生成的 PA、Fly2 和 `quad_monolithic.lua`。

`simion/programs/quad_transport.lua` 只实现 RF-only Fast Adjust、静态电极、RF 步长上限、80 us
最长飞行及 CSV/JSON 统计；没有 collision、drag、pressure 或 buffer-gas 逻辑。两组杆为
±139.81792 V peak、1.1 MHz，其余电极 0 V。

`tests/simion/run_transport_candidate.ps1` 执行 Fly2 生成、GEM 编译、PA refine 和独立无界面 fly；
默认 quality 10、40 RF 步/周期，并禁用轨迹临时文件保留。20→40 步时 25/25 不变，平均 TOF
变化 0.00030%。最终为 25/25、49.7386 us、最大杆区半径 0.4729 mm、最大探测半径 1.4472 mm。

运行器同时设置 `RFQUAD_SIMION_TRAJECTORY_CSV`；Lua 在 PA/COMSOL 坐标的每 0.2 mm 轴向平面线性
插值导出逐粒子 `time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm`，并保留终止样本。此导出与 SIMION 内置 retained trajectories 无关，
用于与 COMSOL 的 `r(z)`、同 ID 差异和关键平面束斑作可重复比较。

`tests/simion/inspect_builtin_quad_reference.lua` 只加载已构建候选，不触发交互 refine；验证 IOB 单实例、
`quad_monolithic.pa0`、`39×39×477`、0.2 mm 单元及 PA→workbench 三轴基向量。候选可直接在 SIMION
GUI 中打开检查 Program、Adjustables、粒子定义和 PA 实例。
