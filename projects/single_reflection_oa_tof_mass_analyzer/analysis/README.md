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
- `analyze_paper1_c1_source.py`：冻结单一预脉冲源的C1诊断入口；验证母cohort收据与状态SHA，按粒子ID哈希登记四个cohort，并且仅以development/validation选择条件模型。它不生成C1 PASS结论，跨源资格仍由阶段合同决定。
- `analyze_paper1_c1_stage.py`：仅汇总两份已冻结、detector-blind的C1源诊断，核验各自母cohort、四个ID cohort和残差模态稳定性；它只关闭C1输入门禁，不生成J2/J3或性能结论。
- `paper1_c2_axial_oracle.py`：C2的低成本纵向淘汰实现。它把C1冻结的`z-v_z`源按粒子ID cohort映射到现有精确三区理想场 oracle，堆叠条件bin、保持`D1/D2`约束并比较两区零自由度与三区新增方向；其输出只能是后续C2导数与locked预测检验的输入，不能表述为6D、3D或分辨率证据。
- `analyze_paper1_c2_stage.py`：运行两份C1 assessment上的C2 axial screen，固定T5 ideal-field anchor与已有phase-match release coordinate，审计解析/中心差分`g`、`G`步长平台、两区零自由度、三区改善/零效/恶化排序及其locked bootstrap。它在J2不优于未加权基线时失败关闭，不授权C3。
- `paper1_candidate_control.py`：C3_J3的求解器无关候选控制编译器。它把事先声明的grid2/exit几何和电极电压方向编译为完整`-2h,-h,0,+h,+2h`家族，冻结数值身份并拒绝场反转、平面交叉、无界扰动和固定电极移动；它不启动SIMION、拟合方向或读取探测器结果。

正式数据优先CSV/JSON。XLSX只接收人工导出，导入后立即规范化。严格配对必须使用相同粒子ID，并区分
整体时移与去均值逐粒子残差。

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
