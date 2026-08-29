# oa-TOF统一分析入口

本目录只负责求解器无关的理论闭合、指标、统计和图形。COMSOL模型树由MATLAB维护，SIMION几何与
运行时由GEM/Lua/Fly2维护；Python不直接解析MPH或PA。

## 环境与权威

Python版本、虚拟环境和依赖重建只认仓库根
[`README.md#正式工具链基线`](../../../README.md#正式工具链基线)。
`pyproject.toml`声明依赖，`requirements-lock.txt`冻结版本。

输入权威分层为：

- 科学：`../config/baseline.json`、`../config/modes/formal.json`；
- 求解器数值：`../config/formal_solver_numerics.json`；
- 变量与包络：`../config/design_variables.json`、`../config/optimization_envelope.json`；
- 派生几何：`../config/resolved_geometry.json`，只读且不可反写；
- 分析定义与Formal结果：`../config/analysis_contract.json`、`../config/formal_validation.json`。

run ID、seed、冻结路径和候选override只属于run instance，不能写回Formal。

## 理论与候选编译

| 职责 | 实现 | 理论来源 |
|---|---|---|
| 三栅加速器一阶时间聚焦 | `accelerator_time_focus.py` | `../docs/theory/oaaccelerator_time_focus.md` |
| 双级反射器闭式解 | `reflectron_dual_stage_solver.py` | `../docs/theory/dual_stage_reflectron.md` |
| 加速器—反射器纵向耦合 | `oatof_oaaccelerator_coupling.py` | `../docs/theory/oatof_oaaccelerator_coupling.md` |
| finite-interval整机设计原子编译 | `finite_interval_design_compiler.py` | 复用上述三层理论，原子发布几何/电压/反射器耦合/rebuild plan |
| Arm 8轴上全理论解析闭合 | `verify_axial_ideal_closure.py` | 复用上述耦合理论与统一`peak_metrics.py` |
| 参数候选编译 | `compile_candidate_design.py` | design-variable catalog与优化包络 |

候选只允许修改变量目录登记的连续量或整数离散量。理论派生量由编译器重算，拓扑变量使用专用编译
路径；范围只代表编译安全边界，不代表可行或最优。编译器输出candidate baseline、resolved、diff和
PA/COMSOL/SIMION/CAD重建影响，不能直接晋升Formal。

T5三区理论结果沿用`three_zone_t5_simion_candidate.py`唯一CLI进入后续Candidate。canonical发布使用
`--run-dir artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/<candidate-run>`，并同时传入
`--campaign`和`--t5-receipt`；发布器排他、原子地产生
`results/three_zone_t5_simion_candidate_resolved.json`、`run_config.json`、`summary.json`和
`run_manifest.json`，固定`formal_gate_passed=false`。持久化身份路径为workspace或run-relative，
resolved Candidate只属于`artifacts/`且不得提交Git。原有`--output`仅保留单文件编译兼容性。

跨项目finite-interval布局只能把四个物理相空间量、源宽和一级长度作为request传给项目公共
`compile_finite_interval_oatof_design` API。加速器电压与轴向平移、源几何、线性导数、耦合反射器、
shield边界和rebuild plan均由该函数一次性闭合。API严格拒绝profile路径、run、checkpoint、cohort、
粒子数等integration provenance；这些事实只能由integration写入自己的layout derivation。数值政策
唯一登记在同模块`FINITE_INTERVAL_COMPILER_POLICY`，消费者不得另传默认值。

## Candidate生命周期

`prepare_candidate_run.py`冻结候选合同、N=100粒子计划和COMSOL/SIMION/CAD执行计划；
`candidate_run_lifecycle.py`在scratch组装三件套后原子发布run。完整Candidate workflow随后真实构建
并冻结PA/IOB、COMSOL、SIMION、CAD和跨软件验收证据；不是“只生成Lua/Fly2”。

唯一公开入口为：

```text
../workflows/design_candidate/run_candidate.py
```

生产seed必须来自`run_config.run_instance.particle_source_seed`。success固定表示
`candidate_accepted_not_promoted`和`formal_eligible=false`；晋升由独立Formal事务完成。

## 核心分析

- `ideal_source_comparison.py`：可控均匀空间源、线性/二次速度关系和独立Gaussian残差；复用精确轴向TOF与canonical峰宽，保留完整母cohort及模型域/碰撞分类。工作点仅重算反射器电压，不移动加速器或漂移参考面。
- `ideal_source_experiment.py`：版本化实验校验、残差优先的确定性case计划和自动科学结论；执行成功不等于假设成立。活动入口和自动续跑说明见下节。
- `ideal_acceptance_theory.py`、`ideal_acceptance_linear_design.py`：从精确时间的空间Taylor系数诊断有限束宽误差，以三乘三线性聚焦方程反求后两段场强、长度和匹配反射器场；不以粒子峰宽调压。
- `ideal_acceptance_design.py`、`ideal_acceptance_experiment.py`：规定源的加权求积、有限包络检查、总方差分解、等概率总体近似及独立粒子验收；区分方差目标与直接FWHM。
- `ideal_acceptance_density.py`：从精确残差到时间映射求总体推前密度，不使用有限粒子KDE带宽；复用canonical半高交点并保留质量密度Jacobian、概率积分和单调性适用域。
- `peak_metrics.py`：KDE、直接FWHM和分辨率的唯一参考实现。
- `reference_analysis.py`：CSV/XLSX/TRACE导入、Recording审计、source mapping、bootstrap和CLI。
- `mass_spectrum.py`：五质量标定、峰形与探测落点比较。
- `compare_field_profiles.py`：同坐标轴场比较。
- `compare_vector_field_samples.py`：同坐标三维场分量比较。
- `compare_particle_trajectories.py`：代表粒子轨迹和关键面到达时间。
- `analyze_longitudinal_closure.py`：纵向场与逐粒子TOF差解释。
- `analyze_accelerator_transverse_field_uniformity.py`：轴心/偏轴场均匀性诊断。
- `truncation_diagnostics.py`：能量窗、检测半径和源宽截断。
- `paper1_focusability.py`：C1 detector-blind条件源模型以及C2局部受限白化投影；时序预脉冲记录必须显式选择一个锚点样本，且只允许作为状态输入，不可混入检测器结果。
- `paper1_j2_real_field_selection.py`：J2真实场公平选择的纯分析入口。它只以冻结C1条件源协方差和具有内容哈希的真实场局部灵敏度收据，对同一候选池分别计算未加权与源白化分数；拒绝来源、状态尺度或候选池身份不一致，且绝不读取探测器、峰宽或传输结果。
- `paper1_j2_candidate_pool.py`：J2真实场的公共候选池编译器。它在预注册边界内扰动三区grid2/末端几何、电极及反射器控制，并从每个候选的平面和电势重新导出区长、场强和焦点漂移；候选池本身不评分、不运行SIMION，也不接触检测器结果。
- `paper1_j2_real_field_sensitivity.py`：把同一数值身份下、同一局部初态的`+/-`真实场到达时间中心差分压缩为六维灵敏度收据。它只接受预注册步长和候选池身份，拒绝FWHM、传输、尾部及锁定结果字段。
- `analyze_paper1_c1_source.py`：冻结单一预脉冲源的C1诊断入口；验证母cohort收据与状态SHA，按粒子ID哈希登记四个cohort，并且仅以development/validation选择条件模型。它必须标记`DEVELOPMENT_ONLY`或`PROSPECTIVE`，不生成C1 PASS结论。
- `analyze_paper1_c1_stage.py`：仅汇总两份已冻结、detector-blind的C1源诊断，核验各自母cohort、四个ID cohort和残差模态稳定性；只在两份输入均为`PROSPECTIVE`时关闭C1输入门禁，历史`DEVELOPMENT_ONLY`输入必为`INCONCLUSIVE_REVISE`。
- `analyze_paper1_connector_gap_residual.py`：两臂残差比较以及 C1 S1 `0/51.2/102.4 mm`三臂发布入口。三臂 request 必须声明唯一 checkpoint mode；可用 fixed-pulse，或经 resolved-pulse-epoch、RF、场、数值和source身份逐项核验的`PRE_PULSE_EQUIVALENT_TIME_SERIES`。未验证或混合模式必须失败关闭为`INCONCLUSIVE_REVISE`，不能生成性能结论。
- `paper1_c2_axial_oracle.py`：C2的低成本纵向淘汰实现。它把C1冻结的`z-v_z`源按粒子ID cohort映射到现有精确三区理想场 oracle，堆叠条件bin、保持`D1/D2`约束并比较两区零自由度与三区新增方向；其输出只能是后续C2导数与locked预测检验的输入，不能表述为6D、3D或分辨率证据。
- `analyze_paper1_c2_stage.py`：运行两份C1 assessment上的C2 axial screen，固定T5 ideal-field anchor与已有phase-match release coordinate，审计解析/中心差分`g`、`G`步长平台、两区零自由度、三区改善/零效/恶化排序及其locked bootstrap。它在源分布加权的受约束到达时间聚焦预测不优于未加权基线时失败关闭，不授权C3。
- `paper1_candidate_control.py`：C3_J3的求解器无关候选控制编译器。它把事先声明的grid2/exit几何和电极电压方向编译为完整`-2h,-h,0,+h,+2h`家族，冻结数值身份并拒绝场反转、平面交叉、无界扰动和固定电极移动；它不启动SIMION、拟合方向或读取探测器结果。
- `paper1_c3_j3_mapping.py`：从通过的C2_J3结果提取已锁定的improve/zero/worsen方向，并在每个`k*h`上重新推导三区几何、电位和反射器控制。它拒绝非对称方向，避免把非线性的`eta`误写成线性电压插值；输出仍只是C3真实PA编译输入。
- `paper1_c3_j3_publish.py`：将上述五点物理控制家族和每一个schema-valid Candidate原子发布为一个非Formal artifact run。它只冻结C2→物理控制的映射与文件身份；不构建PA、不启动SIMION、不读取探测器结果，也不产生C3结论。
- `paper1_c4_locked_prediction.py`：C4_J3锁定三维预测分析。它必须先读取C3_J3的`PASS_CONTINUE`五件套，随后才读取已完成的三方向run receipt；核验锁定ID、共同脉冲、母cohort分母、直接FWHM顺序和传输防御，不启动求解器。

正式数据优先CSV/JSON。XLSX只接收人工导出，导入后立即规范化。严格配对必须使用相同粒子ID，并区分
整体时移与去均值逐粒子残差。

## 自动理想场比较

从仓库根使用Python 3.11运行：

```powershell
.\.venv\Scripts\python.exe -m projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison --seed 20260827
```

默认一次完成残差扫描、两区/三区束宽比较，逐case输出进度，自动保存粒子终态CSV、峰宽/尾部/模式、
电压、阶段结论、总报告与schema-v2 manifest。`--plan`只列计划；`--config`选择有版本角色的科学配置。
科学配置控制源分布、固定几何、扫描轴和科学阈值；峰宽数值口径仍来自项目分析合同；seed/run ID只在
run instance冻结。`--resume-from <旧run目录>`保持相同配置和seed，自动创建新run，校验代码/配置/环境
及已完成case内容后复用；旧run及失败证据不改写，不需要手工指定下一阶段。未原子发布的case重算。

运行状态为`success/failed/interrupted`，科学状态独立报告`SUPPORTED/NOT_SUPPORTED/INCONCLUSIVE`
或已表征的接受范围；负结果不阻止另一项低成本比较。技术异常停止并保存`failure_stage`、`failure_reason`
和`logs/failure.log`。同种子不重新抽样、归一化残差或挑选共同命中交集；不同seed给出重复范围而非CI。
束宽接受为从最小已测束宽起、所有seed均通过R与完整母cohort模型可达率的连续已测范围；未知峰或模型
不支持的反射器一级折返不作为已确认物理上限。最后一个采样点仍通过时只给下界，不外推极限。

此入口属于长期正式分析功能，但结果仅为合成源、理想轴向场的探索证据。它不复用历史T0—T5漏斗的
人工逐阶段操作，也不改变其只读历史语义；共同模型/指标直接复用。它不启动SIMION/COMSOL、不改Formal，
不声称实际RF源、真实孔径收集率、完整电压/几何最优化或论文新颖性已证明。

`ideal_source_affine_slope_scan.json`是该入口的最小机制模式：在同一均匀位置、Gaussian随机残差与
随机种子下，比较`k=0`、一个历史标量参考和现有人造源的线性`z-v_z`斜率。历史输入只是一份带哈希的
标量receipt，不读取或拟合其粒子表。每个非零`k`把第一场、源到grid1距离、grid2电位比例和反射器一级
电压冻结，再由`a1=a2=a3=0`反求后两区场/长度与反射器二级场；所以结果检验“已知线性关系是否可被理论
工作点利用”，不是对峰宽或全部工程变量的寻优。

### 从聚焦方程重设计宽束接受

同一入口加上`--config projects/single_reflection_oa_tof_mass_analyzer/config/experiments/ideal_acceptance_theory.json`
即可自动运行理论重设计。流程先诊断原工作点高阶系数，再枚举声明的理论控制域、解
`a1=a2=a3=0`线性方程，由正逆场派生长度；以精确总体相对时间方差选择各束宽候选，最后冻结候选进行
等概率总体近似与独立粒子检验。不是先对粒子分辨率寻优再解释理论，也不启动三维求解器。

源斜率、中心速度和10 m/s残差保持不变；第一场区采用显式的居中设计族，长度和场强比可变。
当前比较固定中心静电能、反射器长度和无场路径。这些是比较范围，不是三区结构的普适限制。
首轮总体近似使用等概率节点及canonical KDE；Gauss求积节点只用于加权矩和方差，不冒充等权粒子。
配置包含`numerics.density`时，改用不依赖KDE带宽的精确总体推前密度；`population_orders`两列此时
分别是位置积分阶数与时间网格点数。数值收敛与三组粒子重复分别报告，所有母粒子保留分类。

[`ideal_acceptance_fixed_length.json`](../config/experiments/ideal_acceptance_fixed_length.json)另增加总长
20.25 mm的长度方程，从每个正场分支求镜一级电势；场区分配可变，但不能通过延长整个加速器换取
分辨率。它仍使用同一入口。有限电压网格只定义检测到的根，不构成连续域根完备性或全局上界证明。
总体密度在有限Gaussian包络内计算并报告遗漏尾概率；有限粒子分辨率继续沿用原canonical KDE。

[`ideal_acceptance_200mm.json`](../config/experiments/ideal_acceptance_200mm.json)把三区总长固定为200 mm；
[`ideal_acceptance_200mm_boundary.json`](../config/experiments/ideal_acceptance_200mm_boundary.json)只加密该扫描
的3.2--5.0 mm过渡区。两者保持相同源、能量、反射器、门槛和粒子政策，结果见
[`200 mm扫描快照`](../docs/history/20260827__200mm-ideal-acceptance-scan.md)。

[`ideal_acceptance_300mm.json`](../config/experiments/ideal_acceptance_300mm.json)与200 mm主扫描使用完全
相同的离散宽度点、控制域、源、能量、反射器和数值/粒子合同，唯一科学变量是总加速器长度300 mm；
它不自动补密边界。理论模式默认最多使用8个纯Python进程，先并行解独立控制根、再按预估工作量并行
完成不同束宽；每个束宽内部仍保持“总体筛选后再粒子确认”的因果顺序。`--max-workers`只降低本次运行的
执行并发，不改变冻结的科学输入或数值身份，也不调用SIMION资源调度器。

`ideal_acceptance_300mm_simion_candidate.py`是这一个已选`300 mm / 4 mm`理想轴向点进入真实场的唯一
候选编译器。它不重搜参数，必须绑定已发布的理想场configuration、manifest和已通过独立粒子检验的
selected result；`--run-dir`原子发布一个`CANDIDATE_ONLY`候选，`--output`只用于临时单文件检查。集成
侧的`three_zone_ideal_acceptance_300mm_square_v1`与`..._cylindrical_v1`必须消费同一候选的四个轴向平面、
电位和反射器工作点；二者只允许改变横截面。候选的坐标会整体平移到现有多极杆直连端口，内部长度、
场强和相对焦点不变；这不是额外加上一段300 mm连接器。真实方/圆场、孔径收集、轴场等价和数值收敛
仍需由对应SIMION运行单独验证。

`analyze_square_cylindrical_axis_target.py`是这对方形/圆形真实PA运行后的只读比较入口。它失败关闭地核验同一Candidate SHA、四个轴向平面与电位、加速器环位置、数值profile、脉冲和上游源身份；随后从两份`total_axis_field.csv`分别积分三区及总电势降，并报告方减圆的轴向`E_z` RMS/max诊断。若另行提供身份相同的完整飞行run，它只从已保存的`pre_pulse_state`和`local_accelerator_exit`调用独立轴场积分器；没有保存状态时明确`NOT_RUN`，绝不启动求解器或伪造参考轨迹。它不将同轴目标或小轴场差异表述为三维场、收集率或分辨率等价。

`analyze_ideal_acceptance_aperture_campaign.py`只读八臂预脉冲屏幕，量化完整`N=5000`母cohort上的源侧收集、加速方向`z`展宽及`z-v_z`线性残差；它明确不报告分辨率。`analyze_ideal_acceptance_aperture_full_flight.py`消费同一八臂的已发布全脉冲飞行run，逐臂核验Candidate和输出身份，并在不取共同命中交集的前提下报告完整母cohort传输/损失、预脉冲展宽和线性残差，以及每一臂自身全部探测命中的直接FWHM、分辨率、峰形和bootstrap。二者都只是方形/圆形、孔高对照的真实场探索分析，不证明横向场等价、优化或Formal性能。

`publish_ideal_acceptance_aperture_comparison.py`是上述两类八臂比较的唯一正式发布入口。它先运行对应的失败关闭读取器，再在项目canonical artifact根原子发布比较JSON、`run_config.json`、`summary.json`和`run_manifest.json`；预脉冲模式绑定campaign与八个父run manifest，全飞行模式还逐一绑定八个已核验的SIMION子run manifest。读取器拒绝任一臂时不会留下部分或成功样式的分析产物。发布结果仍分别仅为`DETECTOR_BLIND_SOURCE_ONLY`或真实场探索证据，不能据此作Formal或三维横向场等价声明。

真实PA的轴向细网格若不能表示连续理论平面，可显式传入`--axial-grid-z-mm`。编译器只将三区长度投影到
该已声明网格、保持300 mm总长与第一场区/源契约固定，并重新求解同一`a1=a2=a3=0`方程；结果模式为
`IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1`，会记录网格、三段长度和方程残差。它不是电压或几何搜索，
也不把网格闭合误称为真实场等价。当前真实运行使用已注册的`0.05 mm`轴向overlay网格，故其网格可实现
候选为`7.000 / 56.150 / 236.850 mm`。

每个束宽可以有不同理论候选；“最大已验证宽度”不是一个冻结设计覆盖全部较小束宽的证明，也不是
全局极限。该模式暂不支持`--resume-from`，失败会输出具体阶段及完整日志，修正后用新run自动重算；
原残差/束宽比较模式的断点复用行为不变。所有新增实现是维护中的正式分析功能，结果仍为理想场探索证据。

## Formal与跨求解器

Formal唯一入口：

```powershell
../workflows/formal_reference/run_formal_validation.ps1 -Phase Validate|Publish|Verify
```

`Validate`从成功的零物理变化候选冻结输入，以同一N=1000粒子表串行重算；`Publish`只接受晋升
request和独立GUI/CAD evidence；`Verify`只读复核当前Formal。禁止手改
`formal_validation.json`。

跨求解器诊断入口为
[`run_cross_solver_diagnostics.ps1`](../workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1)。
它只读当前Formal资产，在独立run中冻结身份后调用求解器适配器；本目录算法不直接启动商业软件。
诊断PASS只说明导出、配对、分析和manifest成功，不代表场或轨迹等价。

## 门禁与维护

- 回归入口：`verify_reference_analysis.ps1`。
- `R=m/FWHM_m`和直接FWHM只在`peak_metrics.py`维护。
- 修改KDE带宽、网格点数或半高交点算法时，先提升分析合同版本再更新基准。
- MATLAB图只作GUI展示，正式统计必须与冻结Python实现核对。
- 修改加速器电压、间距、源宽、无场长度或反射器参数时，必须重新运行理论闭合并按rebuild plan更新
  所有受影响实现。
- Arm 8解析闭合通过`python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.verify_axial_ideal_closure
  ../config/diagnostics/axial_ideal_arm8_analytic_closure.json --output <receipt.json>`运行。receipt明确标记为
  solver-independent analytic closure，不得表述为SIMION、COMSOL或Formal结果。
- 通用代码只有第二个项目实际复用后才能上移`common/`。
