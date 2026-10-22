# 原生事件：积分器／方程形式隔离与曲面几何阶次收敛

DOC_STATUS: ARCHIVED_READ_ONLY

2026-10-22。本记录关闭三个有界解析小模型问题，不加载实际 OA MPH、不求电场，不改变生产提取器或
Formal 资格。原生事件准确、终态辅助变量可读、曲面几何准确是三个独立判据，不能合并成一个 PASS。
实际 OA 的空间网格及整机性能由对应新运行另行判断。

## 对象、来源与唯一变量

三个独立科学 run 的简称与权威入口如下；简称只用于本页。

| 简称 | run_id | 冻结记录 |
|---|---|---|
| M | `20261022_105532__test__comsol__oatof-tiny-event-matrix` | [manifest][m-manifest]、[逐案摘要][m-summary] |
| G | `20261022_110053__test__comsol__oatof-tiny-curved-convergence` | [manifest][g-manifest]、[逐案摘要][g-summary] |
| L | `20261022_111356__test__comsol__oatof-tiny-linear-identity` | [manifest][l-manifest]、[逐案摘要][l-summary] |

三者输入均为原 `20261022_085813__test__comsol__oatof-counter-precompute-readback` 的解析释放表；
SHA-256 为 `70892128AF5CB5FB8647228E3718EAB12B4FCB72B9ED2BCC28578E3A6DCD4976`。
它是此前 Counter 调查的 **解析 N100**，不是实际 OA 重追踪的 N100。六列初始状态、顺序与数量不变，
未移动源以适应曲面，也未剔除未释放或读取异常的粒子。质量 524 Da、+1，零外加场、无碰撞和粒子反馈。
共同控制为 Free、`rtol=1e-12`、初始步 0.1 ns、最大内部步 2 ns、输出 `0:2:30 ns`；
保存粒子状态、额外壁面信息与时间导数，关闭反力计算，目标 Wall 为 Freeze，仅目标 Wall 重置五个辅助量。

平面为 `z=0`；球面球心 `(0.35,0,0.65) mm`、半径 `0.6 mm`，全部原源点位于精确球内。
球面沿原负 z 速度的解析交点为 `z_hit=cz-sqrt(r²-(x-cx)²-(y-cy)²)`，
`t_hit=(z0-z_hit)/(-vz)`，使用一致单位。解析到达 1.27409～17.75054 ns，入射角约 14.639～77.263°。
目标边界是完整球外表面，既有另一平面 50/50 分类验证不在本页重复。
自动网格均为 hauto9；平面 72 tet，球面 62 tet／52 tri。球面各阶次保持相同几何与网格构造、
相同元素类型及数量；未逐案保存并逐位比较全部顶点和连接矩阵，不宣称这些矩阵逐位相同。

辅助量为 `impact_hit=1`、`impact_time_s=t/1[s]`、三个 `impact_*_mm=q*/1[mm]`；
释放初值均零、时间积分源项均零。原生门要求全部 ID、Freeze、目标 `bndenv(pcnt_det.Ob)==1`，
以及最大时间误差 ≤1 ps、最大坐标误差 ≤0.001 mm。终态 Aux 门另外要求全部 hit、记录时刻与位置
满足相同解析门。门值是此解析诊断的冻结判据，不是仪器通用要求。

## 受控矩阵与结果

M 交叉积分器与方程形式，并以自动几何阶次测试曲面；G 固定球面、GA 二阶及 hauto9，
仅改变组件 `sorder`。G 预登记：四档完成后，最低通过原生门的阶次再以 DP5 一阶复核；若无通过档，
只追加一次 quartic／hauto6，再仅当其通过时追加 DP5。实际 sextic 已通过，未触发 hauto6 分支。
L 只重跑相同 linear／GA 二阶／hauto9，补存原始身份及网格，检查 G 的初始身份拒绝原因。

| run／配置 | Study.run / s | 原生时间最大误差 / ps | 终态 Aux hit | 原生门 | 终态 Aux 门 |
|---|---:|---:|---:|---|---|
| M／平面 GA／Newtonian | 0.9117700 | `1.98523e-11` | 100 | PASS | PASS |
| M／平面 GA／FirstOrder | 1.0629992 | `2.97785e-11` | 100 | PASS | PASS |
| M／平面 DP5／FirstOrder | 0.5475192 | `3.30872e-12` | 0 | PASS | FAIL |
| M／平面 DP5／Newtonian | 0.4842057 | `3.30872e-12` | 0 | PASS | FAIL |
| M／曲面 GA／Newtonian／automatic | 0.4136804 | 605.365888 | 100 | FAIL | FAIL |
| M／曲面 DP5／FirstOrder／automatic | 0.5399941 | 605.365888 | 47 | FAIL | FAIL |
| G／曲面 GA／Newtonian／linear | 1.0488624 | 未进入误差验收 | 未取得 | 初始身份拒绝 | 未验收 |
| G／曲面 GA／Newtonian／quadratic | 0.4923242 | 605.365888 | 100 | FAIL | FAIL |
| G／曲面 GA／Newtonian／quartic | 0.6327279 | 5.065948 | 100 | FAIL | FAIL |
| G／曲面 GA／Newtonian／sextic | 0.4799390 | 0.255616 | 100 | PASS | PASS |
| G／曲面 DP5／FirstOrder／sextic | 0.7544378 | 0.255616 | 48 | PASS | FAIL |
| L／曲面 GA／Newtonian／linear 原始回读 | 2.1552993 | 未授予完整 N100 事件门 | 88 | 12 个未释放 | 不合格 |

三个摘要逐项核对为 **6+5+1=12 次真实 Compute**，均执行完成；运行完成不等于科学门全通过。
M 四种组合在真实 Study Compute 后保持活动算法、Free 和方程形式。此 fixture 中 DP5 两种方程形式
均出现终态 Aux 零值，而 GA 两种形式均正确，排除了“只有一阶方程才导致该现象”的解释；
限定结论是该积分器设置下的保存／回读行为不同，未解析闭源保存公式，也不推广到全部模型。

G 的显式 `sorder` 在 Compute 前后回读一致，`mphcomponentinfo` 亦保存实际组件设置。
GA quadratic／quartic／sextic 三案的终态 Aux 时间、位置与原生事件对应值之差均为零。
其解析误差随几何阶次下降，表明该受控例的主要剩余误差是曲面网格表示，不能靠把 Aux 当成另一个真值消除。
sextic 两积分器的事件 XYZ 最大误差均为 `7.0294393e-6 mm`，全部原生目标身份正确；
GA 终态 Aux 通过，DP5 仅在准确原生事件时刻读到全部 100 个正确 Aux hit。
DP5 晚期 Aux 相对原生事件最大时间差约 17.0846 ns、位置差约 0.437504 mm，仍明确拒用。
这里没有把 sextic 晋升为 OA 或全仓默认，也没有把极小的平面舍入误差当作仪器绝对精度。

## linear 身份缺口的闭合

G 的 linear 案 Compute 成功，但原 harness 在初始状态匹配数量非 1 时拒绝，错误文字为
`Initial source identity is ambiguous`；旧案未保存该原始矩阵，不能仅凭文字判断是重复身份还是缺失状态。
L 在任何身份断言之前保存全部初始 pidx、XYZ、速度、原生 st／fs 以及终态全部 14 个通道，另存
网格顶点／三角形和逐源半空间包含测试。精确 CAD 球内的点可能落在线性内接多面体之外。

独立用冻结顶点及 SciPy `ConvexHull` 重建半空间，得到源在 linear mesh 外的 ID 集合：
`{1,2,11,12,21,31,61,71,81,82,91,92}`。它与初始六维状态非有限的 ID、终态 `fs=0` 的 ID
集合严格相同。初始及终态均保留 100 个唯一 pidx，顺序逐位一致；88 个有限初始六维状态与原源及
G quadratic 案已验证的 pidx→SourceIon 映射一致。最大网格外法向距离约 `0.063096344281 mm`；
包含判定的 `1e-12 mm` 仅是浮点舍入余量，远小于该距离，不改变事件验收门。

因此该缺口已闭合为：**粗 linear 边界表示将 12 个本来位于 CAD 球内的源排除出离散域，
这些粒子未释放；不是重复 pidx，也不是飞行后丢失或 Counter 漏计。** 最终为 88 frozen、12 unreleased、
0 disappeared；未删除这 12 行，也未只用 88 粒子宣布 N100 通过。
原始证据为 L 的 [初始表][l-initial]、[终态表][l-terminal]、[包含表][l-containment]和[边界网格][l-mesh]。
`fs` 即使在 `t=0` 查询也表示最终步状态，不能将该列解释为初始瞬时状态。

## 完整成本与资源边界

每次独立启动串行执行，2 核、600 s、8 GiB 上限，每案元素总数硬帽 10,000；未加载仪器模型、
未运行大型场或保存 MPH。完整外层计时覆盖准备、容量准入、排队、商业软件启动、Compute、读取、
封存及许可释放，范围不同于表中的 Study.run。

| run | 完整流程 / s | 外层进程族采样峰值 / B |
|---|---:|---:|
| M | 91.3153 | 3777241088 |
| G | 80.0436 | 3639357440 |
| L | 134.6947 | 3355680768 |

外层观察器每约 3 s 对受管进程族逐 PID 求 `max(working_set,private)` 后求和，包含包装器和观察器；
内层每约 1 s 采样公共启动器后代，作用域不同。二者均为采样峰，不是连续峰、唯一物理页或全机占用。
三次科学任务不同且启动／调度有波动，不由上述完整秒数给出算法速度排行。
上述完整量测、全部内外层源码快照与采样身份已由独立[量测发布 run][flow-manifest]封存并完整核验；
[汇总表][flow-results]逐项重算采样峰值及全过程覆盖，不依赖已删除的 scratch 执行路径。
另一次 11:08:02 附近外层准备被工具上下文刷新中断，未建立科学 run 或启动 Compute；
其工具观察单独保留，不计为第十三次小模型求解，也不记成模型 FAIL。

## 官方依据、复现与未授予范围

[Geometry and Mesh Settings][geometry-doc]明确粒子与边界网格交互而非精确参数曲面，曲面近似会影响
事件时间、位置和法向；本机 `ParticleTracingModuleUsersGuide.pdf` 第 41–42 页只读核对一致，
文件 SHA 及查证范围已写入 G／L inputs 的官方证据 JSON。
[组件 API][component-doc]提供 `component.sorder()` 及显式阶次设置；
[网格数据 API][mesh-doc]提供双输出 `mphmeshstats` 的顶点与连接关系。
[状态定义][status-doc]规定 `fs=0/1/2/3/4` 分别为未释放／active／frozen／stuck／disappeared，
且后处理读取的是最终步状态。[时间求解器][time-doc]提供算法选择；默认算法不代表全部组合已经实测支持。

复现从对应 run 的 `inputs` 恢复 `.m.txt`／`.ps1.txt` 为去掉末尾 `.txt` 的同名文件，
将 `official_tiny_evidence.json.txt` 恢复为相应 `diagnostic_tiny[_curved|_linear]_official_evidence.json`；
在任务独占 scratch 恢复全部源后核对 SHA，不改旧 run，不覆盖旧输出。三类前缀分别为
`diagnostic_tiny`、`diagnostic_tiny_curved`、`diagnostic_tiny_linear`，入口组合为 `_measure.ps1`
与 `_launch.ps1`。例如曲面阶次复现：

```powershell
pwsh -NoProfile -File <恢复目录>/diagnostic_tiny_curved_measure.ps1 -InnerScript <恢复目录>/diagnostic_tiny_curved_launch.ps1 -SourceRepoRoot C:/Users/Liao/mass_spectrometry/simulation_repo -Arm curved-reproduction -ProcessorCount 2 -WallSeconds 600 -MemoryLimitBytes 8589934592
```

这些是冻结的一次性诊断，不是新公共 CLI。配置、原解析释放表、公共启动器及主机支持依赖必须存在并
符合新冻结身份；原脚本固定本机 MainRepoRoot，路径部署不同须登记变化，不能宣称字节不变复现。
源及轻量负结果保留，运行内可执行副本由公共机制清理；任务内 scratch 在实际 OA 对照结束后统一清理。
本页不授予真实 OA 电场收敛、整机提速、复杂碰撞／多次反射、其他曲面或 GUI Compute 资格。

[m-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_105532__test__comsol__oatof-tiny-event-matrix/run_manifest.json
[m-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_105532__test__comsol__oatof-tiny-event-matrix/results/tiny_event_matrix_summary.json
[g-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_110053__test__comsol__oatof-tiny-curved-convergence/run_manifest.json
[g-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_110053__test__comsol__oatof-tiny-curved-convergence/results/tiny_curved_summary.json
[l-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_111356__test__comsol__oatof-tiny-linear-identity/run_manifest.json
[l-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_111356__test__comsol__oatof-tiny-linear-identity/results/tiny_linear_summary.json
[l-initial]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_111356__test__comsol__oatof-tiny-linear-identity/results/linear_initial.csv
[l-terminal]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_111356__test__comsol__oatof-tiny-linear-identity/results/linear_terminal.csv
[l-containment]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_111356__test__comsol__oatof-tiny-linear-identity/results/linear_source_containment.csv
[l-mesh]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_111356__test__comsol__oatof-tiny-linear-identity/results/linear_boundary_mesh.json
[flow-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_112139__analysis__python__oatof-tiny-event-flow/run_manifest.json
[flow-results]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_112139__analysis__python__oatof-tiny-event-flow/results/measurements.json
[geometry-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.10.html
[component-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.23.html
[mesh-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_model.6.25.html
[status-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html
[time-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.139.html
