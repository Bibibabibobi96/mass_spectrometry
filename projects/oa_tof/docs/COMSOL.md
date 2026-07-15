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

## 当前状态

正式MPH仍是100 amu历史基线，尚未包含紧凑加速器候选。524 amu闭合不得复用历史100 amu
性能数值。紧凑候选转正前，COMSOL脚本中的参数化实现可以用于构建和验证，但正式MPH与
SolidWorks装配体必须保持“尚未转正”标记。

## 524 amu闭合要求

- 使用与SIMION相同的质量、电荷、释放体、`5±0.4 eV`分布和固定粒子样本。
- 探测有效面使用`z=19.83 mm`、半径40 mm；SIMION数值终止层厚度不得复制成机械厚度。
- 统一输出命中率、平均TOF、直接`FWHM_m`、`R=m/FWHM_m`和峰形指标。
- 先用SIMION网格探索结论选择最少COMSOL网格组合，不进行无目标的大范围扫描。
- COMSOL网格同样必须做收敛判断，不能把SIMION网格结论直接当作COMSOL误差上限。

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

`tests/comsol/analyze_fixed_particle_closure_from_mph.m`可只读打开已保存候选MPH，重新导出到达时间并核对
释放。结果证明`ReleaseFromDataFile`的位置列在本模型中按mm解释，`t=0`位置误差仅`7.1e-15 mm`，
速度模长误差仅`4.2e-4 m/s`；禁止再对ION表位置额外乘`1e-3`。峰形跨求解器比较属于项目级结论，
统一记录于`PROJECT.md`，本文件不重复维护SIMION数值。
