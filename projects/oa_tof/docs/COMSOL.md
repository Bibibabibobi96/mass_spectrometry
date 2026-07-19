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

模块化候选先以N=5冒烟，再用固定N=100完整构建并从保存后的MPH执行`std1/std2` GUI Compute。
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

2026-07-18首次N=3、10 Da最小验证连续两次在`std2` Compute触发COMSOL原生
`csxmesh.dll`访问冲突；同样N=3、524 Da对照也失败，证明问题不来自低质量速度或新时间窗口。
用户随后把候选中间点改为500 Da并授权清理全部COMSOL/MATLAB计算进程。500 Da门禁能完成参数、
释放表、时间窗口和旧解清除，但仍在Study Compute崩溃；重建`sol2`、限制单核以及按COMSOL官方
接口从TBB scalable allocator切换到Windows native allocator均未消除错误。失败栈依次出现
`csxmesh.dll`、`tbbmalloc.dll`和Windows堆损坏，系统物理内存约49 GB且仍有约23 GB空闲，不是OOM。
这些未证实的求解器覆盖没有进入长期候选入口；启动器只保留默认不变的线程数/分配器诊断参数。
2026-07-18完整Windows重启后又以默认线程数、默认分配器和同源种子复跑500 Da、N=3；参数、释放
表、分段时间窗和旧`sol2`清除均通过，但`std2`约147秒后仍在`csxmesh.dll+0x6420df`发生
`EXCEPTION_ACCESS_VIOLATION`，LiveLink随后只收到`APIEngine.runMethod`空指针。崩溃时系统约
34.8 GB物理内存空闲，再次排除常规OOM。门禁证据位于
`artifacts/projects/oa_tof/runs/candidate_gate/mass_spectrum_mz500_N3_post_restart_20260718/`。
随后完成的受控矩阵修正了“整个宽质量求解器不可用”的过强判断：

| 对照 | 唯一关键差异 | 结果 |
|---|---|---|
| 正式524 Da、保存的N=100 | 零改写，只运行`std2`，不保存 | PASS，367.3 s |
| 524 Da、N=3 | 不清`sol2` | 同址FAIL，约66 s |
| 524 Da、N=3 | 不清`sol2`且不重写`pp1` | 同址FAIL，约64 s |
| 524 Da、N=100候选路径 | 重导入完整100粒子表 | PASS，100/100，粒子321.74 s |
| 500 Da、N=100 | 改质量、时间窗和释放表 | PASS，100/100，粒子318.05 s |
| 500 Da、N=40正式候选数 | 改质量、时间窗和释放表 | PASS，40/40，粒子295.73 s |

因此已证实的适用结论是：build 293在当前模型的极小N=3初始化路径会稳定触发
`Xmesh.assemInit`访问冲突；`clearSolutionData`、`pp1`重写、500 Da质量、时间窗、常规OOM、线程数和
分配器均不是必要条件。N=40和N=100能稳定绕开并完成全五质量候选，但“N=3为何产生无效
solution-mesh引用”和最小失效阈值尚未证明，后续仍应作为独立原生故障研究。证据分别位于
`artifacts/projects/oa_tof/runs/candidate_gate/`各具名目录；不得删除或用成功日志覆盖失败栈。

2026-07-19的500 Da单质量时间标定进一步说明为何不应把N=40作为长期默认值。复用正式`sol1`且
每档独立冷启动时，N=100/300/1000/5000的完整墙钟分别为`444.240/518.625/774.917/2135.133 s`，
其中`std2`粒子阶段为`316.004/390.247/635.909/1996.048 s`，全部100%到达。四点拟合的完整固定项
约`418.02 s`，每增加一个粒子的边际项约`0.3439 s`；因此从N=100增至N=300只增加约16.7%墙钟，却把样本数扩大
三倍。该拟合仅有一次递增顺序测量，用于当前机器批次规划；正式统计仍按N=1000门禁。

同日五质量各N=1000重追踪全部通过，10/100/500/1000/2000 Da的`std2`粒子时间分别为
`227.950/359.063/633.020/843.213/1319.289 s`，各1000/1000命中。首次10 Da启动在设置
`std2/time1/tlist`时出现一次`APIEngine.runMethod`空指针，下一次又在`mphload`报告未连接服务器；
第三次干净进程成功，后续五质量连续完成。这两次发生在Study Compute前，与N=3的
`csxmesh/Xmesh.assemInit`原生访问冲突不是同一失败点。失败报告以`.failed.<timestamp>`保留；宽质量
入口的Resume现会跳过已通过物种、保全失败报告并只重跑未完成物种。由于这些失败仍影响当前运行
策略，阶段性结论保留在本正式实现文档而非history；待版本更新或根因关闭后，再把过程迁入
`docs/history/`，本页只留最终结论和证据索引。

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
