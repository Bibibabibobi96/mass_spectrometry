# SIMION：RF四极杆传输与质量过滤

返回项目统一状态：[`PROJECT.md`](PROJECT.md)。项目GEM由内置`examples/quad`单体参考派生；
`analysis/generate_fixed_fly2.py`按共享ION表的实际行数生成显式Fly2，候选IOB沿用官方文件并在
同目录绑定项目生成的 PA、Fly2 和 `quad_monolithic.lua`。

两份GEM由`analysis/sync_simion_geometry.py`从`config/resolved_geometry.json`生成，并嵌入解析发布
SHA-256；`verify_project.ps1 -Level Static`会拒绝过期GEM。官方`examples/quad`只保留来源依据，运行时
几何不再从安装目录复制，也不允许手改生成GEM形成第二权威源。

本文中出现的N=25、25粒子、25/25及其run ID均是迁移前历史回归，只记录当时的实现、数值设置和故障修复，
不构成当前功能、Candidate或Formal闭合证据。

`simion/programs/quad_transport.lua`实现RF-only或RF+DC Fast Adjust、静态电极、RF步长上限、最长飞行及
统一particle-state/轨迹/JSON统计；运行器必须显式传入几何、数值和工况配置。SIMION没有
`segment.load()`回调，配置在程序加载阶段读取，依赖配置的RF派生量必须在赋值后计算。此前N=25因
默认值与正式输入完全相同而未改变物理结果，但该缺陷会使新增非默认工况失效，现已修正。物理默认值
现为零占位并带正值断言；`official_config_authority_n25_20260718`在此条件下仍为25/25且manifest PASS。

Lua没有 collision、drag、pressure 或 buffer-gas 逻辑。RF-only模式两组杆为±139.81792 V peak、
1.1 MHz且其余电极0 V；质量过滤模式由冻结运行合同另加每组±22.76301494 V DC、−8 V公共偏置和
既有端电极电压，不能把每组DC幅值误作组间差值。

每次运行先由公共多极杆适配器生成`inputs/family_operating_contract.json`，再由PowerShell和Lua消费
相同的RF幅值、DC幅值、公共偏置、频率和相位。接口模式的RF幅值允许显式运行绑定；未在接口mode重复
保存的求解器步数和静态端电极从基础RF-only mode继承，不使用代码硬数字。

`tests/simion/run_transport_candidate.ps1` 执行 Fly2 生成、GEM 编译、PA refine 和独立无界面 fly；
默认 quality 10、40 RF 步/周期，并禁用轨迹临时文件保留。20→40 步时 25/25 不变，平均 TOF
变化 0.00030%；40→80 步时平均 TOF 仅变化 `1.05e-6`、最大杆区半径变化 0.030%，最大逐粒子
到达时间变化 0.000157 us。最终为 25/25、49.7386 us、最大杆区半径 0.4729 mm、最大探测半径 1.4472 mm。

同一入口的`mass_filter_reference`模式从N=100功能源构造七质量配对表，一次Fly'm保持各质量相同的
位置、速度、出生时间和ID次序，只改变质量。迁移前历史run
`20260722_210300__sim__simion__mass-filter__n175__r03`得到96～106 Th七点透过率
`0%、32%、96%、100%、60%、40%、8%`，功能判据PASS；输出位于该run的`results/`并由manifest冻结。
它曾证明有限几何中的RF+DC质量选择，但已不再是当前权威响应；新的SIMION与跨求解器结论须等待
N=100复验，不构成质量分辨能力资格。

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

S1下游由`tests/cross_solver/run_s1_physical_end_to_end.ps1`消费COMSOL局部出口事件。ION表行数决定实际
发射数；SIMION命令行`default-num-particles`只使用其支持的100粒子预设，两者分别写入run合同，不能
把39行ION误写成不受支持的默认值。`row_map.csv`保存SIMION行号到原始粒子ID和逐粒子绝对出生时刻的
唯一映射，Program直接使用绝对`ion_time_of_flight`延续同一有限脉冲，不重置时钟或波形。下游分析按
oaTOF冻结`resolved_geometry.json`把SIMION全局落点转换为探测器局部坐标，并复用oaTOF统一峰形合同；
S1小样本结果只允许功能与诊断声明。

`analysis/audit_s1_state_chain.py`是该链的最小只读审计器：以canonical单事件状态为权威，独立反解ION
角度经过accelerator实例3轴映射后的全局三维速度，并核对COMSOL出口、ION位置/能量/出生时刻、
`row_map`原始ID、SIMION初始状态和`InstrumentTimeUs=出生时刻+TofUs`。它只输出汇总JSON，不复制逐粒子
表或密集轨迹。S1直接使用`oatof_global`；只有S2出现真实相对位姿时才引入由部件pose派生的
`instrument_global`变换。

当前累积S3的统一入口是`tests/cross_solver/run_s3_cumulative_chain.ps1`；它先取得匹配连接器案例的S2和
S3 COMSOL状态，再调用SIMION下游阶段，不允许从共享目录猜测来源。默认1 mm运行
`20260722_165527__sim__cross__rf-oatof-s3-end-to-end-gap1__n100`从31个真实局部出口状态得到7个探测命中；0 mm运行
`20260722_164341__sim__cross__rf-oatof-s3-end-to-end-gap0__n100`从39个真实局部出口状态得到9个探测命中，
保持粒子ID、三维速度、全局时钟和同一脉冲结束时刻。该结果仅证明功能贯通，不是峰形、分辨率或接口
资格结论。
