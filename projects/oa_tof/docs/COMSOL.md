# oa-TOF COMSOL 实施与验证

本文件只记录COMSOL实现。统一几何、粒子、FWHM定义、正式状态和下一步由
[`PROJECT.md`](PROJECT.md)定义。

## 正式入口

- 生产脚本：`../comsol/ms_oaTOF_two_stage_ringstack_reflectron.m`
- MATLAB R2025b全链路测试：`../tests/comsol/test_oatof_r2025b_full_chain.m`
- 静态同步检查：`../tests/comsol/verify_oatof_comsol_sync.m`
- 跨求解器门禁：`../tests/cross_solver/verify_geometry_contract.ps1`
- 正式MPH：工作区`artifacts/projects/oa_tof/models/comsol/formal/`

COMSOL 6.4通过MATLAB R2025b LiveLink/Java API运行。影响物理或数值结果的几何、选择集、
参数、材料、网格、物理场、Study、Solver、数据集和结果节点必须持久化到MPH并能由COMSOL
Desktop查看、修改和Compute；仅脚本内存状态通过不算验收。

所有任务只通过`../../../common/comsol/run_comsol_r2025b.ps1`建立连接，任务脚本禁止自行
`mphstart`。同一构建/验收任务复用一次连接；Compute后的大粒子数据提取使用第二个干净任务。
启动器只对报告创建前的MATLAB/COMSOL启动崩溃重试一次，业务失败不自动重算。

### 2026-07-18 模块化正式构建器

底层入口保留`ms_oaTOF_two_stage_ringstack_reflectron.m`，几何、网格、粒子物理和结果节点已拆为
八个稳定模块：加速器、反射器、检测器、漂移区、栅网、网格、粒子模型和结果节点。具名入口
`run_oatof_model.m`新增`OutputModelPath`，候选必须显式写入COMSOL模型根目录内的`.mph`，不再
依赖脚本内部固定正式路径。

模块化候选直接使用统一N=100检查档完整构建，并从保存后的MPH执行`std1/std2` GUI Compute。
重开检查确认`sol1/sol2`及`dset1/pdset1`关联；参数、几何、选择集、335972个四面体、5个数据集
和7个绘图组通过同步门禁。相对拆分前正式MPH，两边100/100命中，平均TOF差`1.30 ps`，逐粒子
TOF RMS/最大差`0.208/0.644 ns`，落点RMS/最大差`0.0137/0.0329 mm`，已转为固定正式MPH。
几何合同未改变，因此沿用已验证的25组件SolidWorks 2022装配，不重新导出机械几何。

## 当前状态

2026-07-16已从baseline重新生成并验证524 amu、固定N=100、真实场正式MPH。模型包含紧凑
加速器、`L_refl=206.8328 mm`、10 mm一体式封闭屏蔽罩和参数化出口栅网；正式日常数值档为
加速器`hmax=1 mm`、敏感窗口`0.2 ns`、无场区`50 ns`。100/100命中，平均TOF为
`71.9870907514 us`，统一Python直接质量FWHM为`0.017041315788 Da`，`R=30748.7994`。
COMSOL同步验证器已支持用`OATOF_COMSOL_MODEL_PATH`先验证候选，禁止为验证而提前覆盖正式模型。
正式MPH已在同一任务同步到SolidWorks 2022装配体。历史100 amu性能值只保留作历史参考。

正式MPH逐粒子CSV可由`tests/comsol/export_fixed_particle_arrivals_from_mph.m`导出。默认仍指向历史
候选以保持旧回归可复现；正式验证必须用`OATOF_COMSOL_MODEL_PATH`和
`OATOF_COMSOL_OUTPUT_CSV`显式指定输入/输出，避免覆盖冻结数据。2026-07-16正式同源N=100结果及
跨求解器峰形结论统一记录于`PROJECT.md`和`config/formal_validation.json`。

正式MPH保留N=100已存解，便于GUI日常复算和与0.5 mm网格、1 ns时间输出做成对数值收敛；正式
统计闭合另以同源N=1000只读加载该MPH并复用`sol1`静电场，只重算`std2`。2026-07-18当前资产
直接重算的粒子阶段为`759.81 s`，1000/1000命中，初始位置/速度最大误差分别为
`7.11e-15 mm/5.00e-12 m/s`，平均TOF `71.9902138860 us`，统一直接KDE质量FWHM为
`0.0134671972344 Da`、`R=38909.36`。逐粒子结果和与SIMION的正式比较由
`config/formal_validation.json`冻结，不把大样本解另存成第二个“正式MPH”。

### 可组合场理想化诊断

`FieldMode`支持在保持静电场解`es`不变的前提下，对粒子力节点`ef1`施加可组合替换掩码。权威语法为
`ideal:<region>.<component>[+...]`；区域可选`accel/drift/stage1/stage2/reflectron/all`，分量可选
`ex/ey/ez/all`。例如`ideal:accel.ez+stage2.ex+stage2.ey`只替换加速区Ez及二级反射区Ex/Ey；
`ideal:all.ez`替换全轴向场；`ideal:stage2.all`替换单区域全部分量。旧`ideal_stage2`等名称继续兼容，
但只作为上述掩码的简写。

理想横向分量为0，理想Ez使用各轴向区域的分段理论值；未选分量始终保留真实`es.E*`。12个
`ideal_<region>_<component>`全局参数和最终三个场表达式均持久化在MPH，可在Model Builder检查和
修改。本节只定义COMSOL实现；实验顺序、交互效应和因果边界见根
[`VALIDATION_METHODS.md`](../../../docs/VALIDATION_METHODS.md#受控理想化场替换与原因隔离)，跨求解器
能力与统一结论见[`PROJECT.md`](PROJECT.md#场方向归因实例)。

2026-07-19首次实现冒烟使用`ideal:accel.ez+stage2.ex+stage2.ey`与统一N=100检查档，100/100到达；
重开保存的MPH后，三个选中参数均为1，`ideal_accel_ex`和`ideal_stage2_ez`两个未选对照均为0。
运行配置、摘要、报告、候选MPH和manifest位于
`artifacts/projects/oa_tof/runs/field_idealization_smoke/composable_mask_n100_20260719/`。该结果只证明
组合机制和GUI持久化有效，不是三个分量对当前TOF偏差贡献大小的物理结论。

长期扫掠入口为`tests/comsol/run_field_idealization_sweep.m`，从一份已保存、含GUI可见掩码参数的
N=100 MPH出发，只改变12个`ideal_<region>_<component>`参数并重算`sol2`；求解器无关汇总由
`analysis/analyze_field_idealization_sweep.py`完成。全局分量、单区域Ez和选择性交互三组运行均完成
manifest复核。COMSOL独立结果是Ez控制理想化时间端点、加速区控制主要均值响应，且加速区与二级
反射区的峰宽响应非加性；本轮不继续做N=1000精确贡献率或无目标组合扫描。

扫掠入口现从保存解和MPH参数读取实际粒子数与`ion_mass_amu`，配置中的N/质量只作一致性断言，因而
不再把524 Da、N=100藏成工具常数。检测事件由`comsol/oatof_extract_detector_arrivals.m`统一提取：
先要求转向后的真实向下跨面，或在1 um容差内确认稳定Wall/Freeze平台；后者再用检测面前0.5 mm内
的碰撞前运动段外推到精确平面，避免直接取Freeze输出时刻造成约0.8 ns采样量化。合成轨迹4项测试和
保存N=100 MPH只读复核均PASS，后者100/100均分类为`frozen_on_detector`，未运行Study。

### 2026-07-16 场与代表轨迹诊断

`tests/comsol/export_axis_field_profiles.m`从正式MPH导出轴向场；
`export_selected_particle_trajectories.m`导出18、52、97号粒子的稀疏轨迹；
`export_accelerator_vector_field_samples.m`在与SIMION完全相同的实际加速段坐标导出Ex/Ey/Ez。
求解器无关比较由Python完成，不在MATLAB内重复统计。

反射器内部场已闭合到`0.000528%`相对RMS；释放区轴向场与SIMION仍有约`0.8396%`平均差。
COMSOL离轴Ex/Ey存在明显单元尺度锯齿，符合有限元电势梯度跨单元面不连续的特征；其网格归因
已由下述局部收敛实验闭合。反射器内部无需重复全域加密。

### 2026-07-16 加速器局部网格收敛

在正式MPH只读加载后，对参数联动选择`selbracket`增加全加速器域Size，比较正式、`hmax=1 mm`
和`hmax=0.5 mm`。一个关键错误是：COMSOL网格节点严格按序执行；用API新建Size时它默认追加在
`ftet1`之后，虽然GUI可见却不会控制已经执行的Free Tetrahedral，造成单元数不变的静默no-op。
诊断入口必须把Size移动到`ftet1`之前，并断言节点顺序后才能把结果称为网格收敛。
长期入口为`tests/comsol/test_accelerator_mesh_vector_field.m`和
`test_accelerator_mesh_particle_candidate.m`，求解器无关汇总由
`analysis/analyze_accelerator_mesh_convergence.py`完成。

有效运行的1/0.5 mm网格分别有336077/659685个单元。从1 mm到0.5 mm，同坐标Ex/Ey/Ez变化RMS
为`79.47/75.09/80.05 V/m`；0.5 mm相对SIMION的Ex/Ey差异RMS仅`61.90/42.62 V/m`，原锯齿可判为
粗网格伪影。剩余Ez差异RMS为`781.70 V/m`、平均`COMSOL-SIMION=-612.80 V/m`。

0.5 mm固定N=100高精度档的静电求解约19.1秒、粒子求解约1478.6秒，100/100命中，直接FWHM
`R=28837.88`。当前正式1 mm日常档为`R=30748.80`，高`6.63%`；两档标准化KDE重叠`0.9677`，
KS距离`0.07`且`p=0.9684`，峰结构一致。两档同粒子落点平均/RMS/最大距离为
`0.2309/0.2695/0.7115 mm`。结论是1 mm适合日常计算，0.5 mm保留为正式收敛项；本轮没有
几何变化，故无需更新SolidWorks装配体。

2026-07-19用保存的轴线场与当前正式N=1000配对结果补做纵向闭合，不重跑求解器。释放区
COMSOL由电势数值导数得到的Ez与直接`es.Ez`内点RMS差为`7.206 V/m`，而同坐标SIMION-COMSOL
Ez RMS为`1344.091 V/m`，前者只占`0.536%`，故COMSOL场梯度读取不是释放区差异主因。逐粒子
`SIMION-COMSOL TOF`与初始z的相关系数为`0.97150`；z二次项解释`94.9506%`差值方差，加入能量、
x和y只增至`94.9564%`。统一baseline已排除有意的电极位置/电压差，剩余证据与两端对栅网、边界
和局部场的数值表示不同一致，并通过z-to-TOF映射放大；保存数据不能唯一指认某个闭源内部插值
实现。可复算入口为`analysis/analyze_longitudinal_closure.py`，结果与11项输出manifest位于
`artifacts/projects/oa_tof/results/cross_solver/longitudinal_closure/current_assets_n1000_20260719/`。

### 2026-07-16 参数化分段时间输出

`comsol/configure_oatof_segmented_output.m`用质量、电荷、加速电压、`L_accel/L_flight`和两级
反射器参数解析计算加速器出口、反射器进出和检测器到达时间。所有预测量、步长和安全裕量均写入
Global Definitions参数，Study `std2/time1`的Output times只引用这些参数。细窗口边界必须向外取整到
同一个以`t=0`为原点的`0.2 ns`时间格；未对齐时即使物理窗口完全覆盖，也会造成最大`0.335 ns`
逐粒子TOF差和`7.30%`的R变化。

相位对齐后，N=20的`50 ns`无场区档相对高精度大窗口基线最大TOF差仅
`2.98e-7 ns`、R变化`2.40e-6%`、最大落点差`1.45e-9 mm`，粒子阶段从`906.59`降到
`313.72 s`（`2.89x`）。N=100的`50 ns`档相对`1 ns`分段档最大TOF差`8.25e-8 ns`、R变化
`1.39e-7%`，粒子阶段从`646.72`降到`366.24 s`（`1.77x`）。正式MPH保存`cpt_dt_fine=0.2 ns`、
`cpt_dt_drift=50 ns`、`tstepsbdf=free`、`tout=tlist`，关闭额外墙时间和粒子状态存储。运行后事件
门禁要求实际加速器/反射器/检测器事件均留在细窗口安全裕量内。
`tests/comsol/test_cpt_wall_time_storage_api.m`长期验证这两个GUI复选框的COMSOL 6.4 API映射。

### 2026-07-17 严格聚焦几何提升

`tests/comsol/build_accelerator_geometry_candidate.m`只读加载正式MPH，按候选契约持久化
`z_accel_origin`、局部加速长度、五环位置、源体、grid1/grid2、选择集和固定检测面，并通过GUI
附着的`std1`重算独立静电场。迁移后原`selb_grid2`同时选中`38x38 mm`屏蔽端面和`30x30 mm`
grid2；候选入口现把选择框收紧到grid2实际包络，最终grid1/grid2均只选中一个正确边界。

候选经COMSOL/SIMION同源粒子、解析焦点、GUI Compute和SolidWorks同步门禁后已提升为正式几何；
随后模块化构建器又通过N=100等价门禁并转为当前正式MPH。2026-07-18使用当前正式MPH直接重算
N=1000进一步消除了结果身份歧义；早期candidate目录不再是正式运行依赖。

## 524 amu闭合要求

- 使用与SIMION相同的质量、电荷、释放体、`5±0.4 eV`分布和固定粒子样本。
- 探测有效面使用当前统一全局坐标`z=0`、半径40 mm。旧几何中的`19.83 mm`是平移前坐标，
  不得与当前正式模型混用；SIMION数值终止层厚度也不得复制成机械厚度。
- 统一输出命中率、平均TOF、直接`FWHM_m`、`R=m/FWHM_m`和峰形指标。
- 先用SIMION网格探索结论选择最少COMSOL网格组合，不进行无目标的大范围扫描。
- COMSOL网格同样必须做收敛判断，不能把SIMION网格结论直接当作COMSOL误差上限。

## 宽质量候选重追踪

`tests/comsol/test_accelerator_mesh_particle_candidate.m`现从固定ION表读取并验证单一质量和整数电荷，
不再把524 amu写死在粒子质量、初速度、分段时间窗口和预计到达时间中。重追踪保留GUI求解器节点和
独立`sol1`静电场，不改写正式MPH；是否显式清除旧`sol2`数据和是否重写`pp1`是可记录的诊断开关，
正式宽质量入口不清旧解、但显式写入目标质量/电荷。五质量候选由
`tests/cross_solver/run_mass_spectrum_candidate.ps1`分批调用，配置见`config/modes/mass_spectrum.json`。
每个COMSOL物种的ReleaseFromDataFile中间表按输出CSV stem和实际N唯一命名，防止同目录、同N的
五个物种互相覆盖；运行manifest同时索引逐物种ION、CSV、报告和现存释放表。该修复不能恢复历史
运行中已经被覆盖的四份同名中间表，但历史逐物种ION、到达CSV和报告仍完整，可继续做结果复算。

### 极小粒子数限制（已绕开）

COMSOL 6.4 build 293在当前CPT模型的极小求解粒子数路径存在原生不稳定；N=30是固定500 Da序列的
最低实测全链路成功点，不是通用或单调阈值。该限制不影响N=100检查档和N=1000统计档，当前不再做
小N边界扫描，也不把工程绕行表述为内部缺陷已经修复。

日常入口统一求解N=100。确需逻辑小样本时，只在无空间电荷、粒子间碰撞或其他集体效应的前提下，
求解N=100同源承载集合并截取目标前缀；运行记录必须区分`solver_particle_count`和
`logical_particle_count`。启用任何粒子间耦合后该绕行立即失效。保留的诊断入口
`tests/comsol/run_extreme_particle_count_case.ps1`仅用于满足PROJECT所列重启条件后的受控复核，
不属于日常或正式门禁；详细矩阵、启动干扰项和原始证据路径已冻结到项目history。

500 Da单质量时间标定进一步说明为何统一N=100与N=1000。复用正式`sol1`且
每档独立冷启动时，N=100/300/1000/5000的完整墙钟分别为`444.240/518.625/774.917/2135.133 s`，
其中`std2`粒子阶段为`316.004/390.247/635.909/1996.048 s`，全部100%到达。四点拟合的完整固定项
约`418.02 s`，每增加一个粒子的边际项约`0.3439 s`。该拟合仅有一次递增顺序测量，用于当前机器
批次规划；新日常运行不再引入N=40或N=300，检查固定N=100，正式统计固定N=1000，N=5000仅用于
明确的性能或统计收敛专项。

五质量各N=1000重追踪全部通过，10/100/500/1000/2000 Da的`std2`粒子时间分别为
`227.950/359.063/633.020/843.213/1319.289 s`，各1000/1000命中。首次10 Da启动在设置
`std2/time1/tlist`时出现一次`APIEngine.runMethod`空指针，下一次又在`mphload`报告未连接服务器；
第三次干净进程成功，后续五质量连续完成。宽质量入口的Resume会跳过已通过物种、保全失败报告并
只重跑未完成物种。

共享LiveLink入口现仅把同时含`mphload`、`mphopen`和`Not connected to a server`的首次模型打开失败
判为可重试启动瞬态，并在干净重启前归档失败报告。发生在`configure_oatof_segmented_output`的API
空指针不满足该白名单，仍立即失败；N=3的Study Compute原生崩溃也不会被重试。这样解决连接偶发
阻塞，同时保留程序/求解器缺陷的可见性。

## GUI与求解器检查

1. 保存后重新打开MPH。
2. 核对`std1/std2`与`sol1/sol2`附着关系，防止GUI Compute生成新solver并显示旧解。
3. 核对所有随加速器迁移的几何选择集和网格选择集仍使用参数表达式。
4. 在GUI路径重算静电场和粒子追踪。
5. 核对命中判据、结果表、FWHM和图标题与脚本输出一致。

## 2026-07-15 固定粒子峰形审计（候选）

`tests/comsol/run_oatof_524amu_fixed_particle_candidate.m`以N=100固定SIMION ION表运行真实场候选。
在`0.2 ns`细输出步下，100/100命中、平均TOF为`71.98684756 us`、直接质量FWHM为`0.01760645 Da`
（`R=29761.82`）。细输出步不能无限制地直接调用默认`mphparticle`：默认会传回所有存储时间点，
0.2 ns时会使客户端JVM在提取`qz`时耗尽堆空间。生产脚本现明确对最终位置和轨迹提取传入`t`，保留
全程稀疏诊断点和预计到达附近的细采样点；这不改变求解或FWHM插值，只缩小LiveLink传输负载。

`tests/comsol/export_fixed_particle_arrivals_from_mph.m`可只读打开已保存候选MPH，重新导出到达时间并核对
释放。结果证明`ReleaseFromDataFile`的位置列在本模型中按mm解释，`t=0`位置误差仅`7.1e-15 mm`，
速度模长误差仅`4.2e-4 m/s`；禁止再对ION表位置额外乘`1e-3`。该脚本不再读取SIMION结果或计算
FWHM/bootstrap；跨求解器统计统一由`analysis/reference_analysis.py compare`完成。峰形比较属于
项目级结论，统一记录于`PROJECT.md`，本文件不重复维护SIMION数值。
