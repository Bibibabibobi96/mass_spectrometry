# SIMION：RF 四极杆无碰撞候选

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。项目GEM由内置`examples/quad`单体参考派生；
`analysis/generate_fixed_fly2.py`按共享ION表的实际行数生成显式Fly2，候选IOB沿用官方文件并在
同目录绑定项目生成的 PA、Fly2 和 `quad_monolithic.lua`。

两份GEM由`analysis/sync_simion_geometry.py`从`config/resolved_geometry.json`生成，并嵌入解析发布
SHA-256；`verify_project.ps1 -Level Static`会拒绝过期GEM。官方`examples/quad`只保留来源依据，运行时
几何不再从安装目录复制，也不允许手改生成GEM形成第二权威源。

`simion/programs/quad_transport.lua`只实现RF-only Fast Adjust、静态电极、RF步长上限、最长飞行及
统一particle-state/轨迹/JSON统计；运行器必须显式传入几何、数值和工况配置。SIMION没有
`segment.load()`回调，配置在程序加载阶段读取，依赖配置的RF派生量必须在赋值后计算。此前N=25因
默认值与正式输入完全相同而未改变物理结果，但该缺陷会使新增非默认工况失效，现已修正。物理默认值
现为零占位并带正值断言；`official_config_authority_n25_20260718`在此条件下仍为25/25且manifest PASS。

Lua没有 collision、drag、pressure 或 buffer-gas 逻辑。两组杆为
±139.81792 V peak、1.1 MHz，其余电极 0 V。

`tests/simion/run_transport_candidate.ps1` 执行 Fly2 生成、GEM 编译、PA refine 和独立无界面 fly；
默认 quality 10、40 RF 步/周期，并禁用轨迹临时文件保留。20→40 步时 25/25 不变，平均 TOF
变化 0.00030%；40→80 步时平均 TOF 仅变化 `1.05e-6`、最大杆区半径变化 0.030%，最大逐粒子
到达时间变化 0.000157 us。最终为 25/25、49.7386 us、最大杆区半径 0.4729 mm、最大探测半径 1.4472 mm。

运行器在Fly前实际加载候选IOB，检查单实例、本地PA、放置变换、尺寸和0.2 mm单元；成功后为候选
目录生成完整`SHA256SUMS.csv`，并在独立run目录生成含输入/输出身份的`run_manifest.json`。
2026-07-18固定25粒子复验为25/25，候选哈希14/14通过；manifest保持candidate，不冒充正式资产。

新运行按mode隔离run目录，并输出`<mode>_particle_state_<run>.csv`、轨迹CSV和summary。接口mode
必须显式给出不少于100行的ION表及RF峰值，不能退回N25默认工况。权威ION表生成无BOM的
`source_states.lua`，因此source事件是积分前的精确初始状态，而不是
第一次`other_actions`回调后已前进的坐标。Lua在85.4和90.2 mm处对时间、位置、速度与能量插值，
并在terminal事件记录统一终止原因；`analysis/verify_particle_state_contract.py`按输入表实际粒子数
强制检查source身份、事件唯一性、平面坐标、RF相位和物理数值范围。旧solver-specific终点表不再生成。

2026-07-18命名N=100工况重新编译、refine并加载`39×39×477 @ 0.2 mm`候选，100/100命中、400条
事件、源身份/平面/manifest均PASS。它与COMSOL独立场的接口比较整体FAIL，故只作为有效负结果，
不能提升为正式接口模型。

运行配置显式给出轨迹CSV；Lua 在 PA/COMSOL 坐标的每 0.2 mm 轴向平面线性
插值导出逐粒子 `time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm`，并保留终止样本。此导出与 SIMION 内置 retained trajectories 无关，
用于与 COMSOL 的 `r(z)`、同 ID 差异和关键平面束斑作可重复比较。

Fly2 `standard_beam` 的 `az/el` 是在 IOB 放置前的局部束流角度，不等同于把 IOB 的位置变换直接
施加到速度分量。通过导出轨迹在入口的 `x(z),y(z)` 斜率已将这一定义固定为 COMSOL 的
`(-vSim_y,-vSim_z,vSim_x)` 映射；未来改动 IOB 或粒子生成器时必须重做该斜率审计。

`tests/simion/export_unit_rf_field.lua` 在已 refine 的官方 PA 上施加 `e1=+100 V,e2=-100 V`，以
PA/COMSOL 坐标导出 SIMION 自己求得的三维单位 RF 场。该文件只提供公共采样点和待比较数据，
不得导入 COMSOL、不得替代任一求解器的受力场；独立 FEM--PA 场差由
`analysis/compare_unit_rf_field.py` 计算。导出器可由 `RFQUAD_SIMION_PA_PATH` 直接打开隔离 PA；该路径
已与基线 IOB 路径在 192 个稀疏公共点逐分量验证，最大差 `3e-10 V/m`。

`tests/simion/test_pa_field_convergence.ps1` 只在运行时副本中把 GEM 单元由 0.2 mm 改为 0.1 mm，
生成 `77×77×953` PA 并独立 refine、导场。0.2→0.1 mm 自身场差在入口/杆区/出口分别为
3.396%/0.0467%/0.280%；说明官方 0.2 mm PA 的杆区场已收敛，但边缘区仍有明显离散敏感性。

`run_transport_candidate.ps1` 的 `SourceAxialOffsetMm` 仅用于隔离诊断：它把同一 25 粒子源沿 workbench
轴向平移，默认值 0 不改变权威基线；`CandidateSubdir` 保证候选 PA/IOB 不覆盖正式目录。

`tests/simion/inspect_builtin_quad_reference.lua` 只加载已构建候选，不触发交互 refine；验证 IOB 单实例、
`quad_monolithic.pa0`、`39×39×477`、0.2 mm 单元及 PA→workbench 三轴基向量。候选可直接在 SIMION
GUI 中打开检查 Program、Adjustables、粒子定义和 PA 实例。
