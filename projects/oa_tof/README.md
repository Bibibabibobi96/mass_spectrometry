# oa-TOF 项目

本项目维护正交加速、双级环栈反射镜oa-TOF分析器。项目当前状态、资格与开放任务只以
[`docs/PROJECT.md`](docs/PROJECT.md)为准；本页只负责导航。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 修改时间聚焦、场强、电压或轴向长度时，读[`docs/theory/README.md`](docs/theory/README.md)。
4. 操作COMSOL、SIMION或CAD时，只读相应的
   [`docs/COMSOL.md`](docs/COMSOL.md)、[`docs/SIMION.md`](docs/SIMION.md)或
   [`docs/CAD.md`](docs/CAD.md)。
5. 只有追溯旧结论、run ID或失败链时才进入[`docs/history/`](docs/history/)。

2026-07-28以前四份current文档的完整内容已冻结为`docs/history/20260728__pre-document-consolidation-*.md`；
它们保留全部实施时间线和数值，但不覆盖当前文档。

## 机器权威

| 职责 | 权威入口 |
|---|---|
| 项目身份与生命周期 | [`config/project.json`](config/project.json) |
| 人工物理设计 | [`config/baseline.json`](config/baseline.json) |
| Formal科学合同 | [`config/modes/formal.json`](config/modes/formal.json) |
| 求解器数值合同 | [`config/formal_solver_numerics.json`](config/formal_solver_numerics.json) |
| 程序几何发布 | [`config/resolved_geometry.json`](config/resolved_geometry.json) |
| 分析定义 | [`config/analysis_contract.json`](config/analysis_contract.json) |
| 已冻结Formal历史结果 | [`config/formal_validation.json`](config/formal_validation.json) |
| SIMION资产身份 | [`config/simion_stable_entry.json`](config/simion_stable_entry.json) |
| 可执行workflow | [`config/execution_profiles.json`](config/execution_profiles.json) |

数据流固定为`baseline + science + solver numerics → resolved → COMSOL/SIMION/CAD`。seed、run ID和
冻结路径只属于run instance；候选不得反写baseline或Formal资产。当前项目生命周期为
`formal_revalidation_pending`，详见PROJECT。

## 活动入口

- COMSOL生产：[`comsol/run_oatof_model.m`](comsol/run_oatof_model.m)
- SIMION交付构建：[`simion/workbench/build_formal_delivery.ps1`](simion/workbench/build_formal_delivery.ps1)
- Candidate唯一入口：[`workflows/design_candidate/run_candidate.py`](workflows/design_candidate/run_candidate.py)
- 当前Formal验证入口：
  [`workflows/formal_reference/run_formal_validation.ps1`](workflows/formal_reference/run_formal_validation.ps1)
- 五质量候选：
  [`workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1`](workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1)
- CAD入口：[`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m)
- 项目门禁：`verify_project.ps1 -Level Static|Candidate|Formal`

RF→oaTOF物理连接、连接器、共享时钟、漏斗和恢复条件只由
[`../rf_quadrupole_collision_cooling/docs/PROJECT.md`](../rf_quadrupole_collision_cooling/docs/PROJECT.md)
维护；本项目只提供下游格式适配和只读分析器消费，不复制接口阶段数字。

## 目录职责

```text
oa_tof/
├─ config/       # 科学、数值、resolved、分析和资产身份合同
├─ workflows/    # Formal、Candidate和质量谱科学工作流
├─ comsol/       # COMSOL模型机制
├─ simion/       # GEM、Lua、Fly2和交付构建
├─ cad/          # STEP与SolidWorks同步
├─ analysis/     # 求解器无关理论、分析和候选编译
├─ tests/        # 静态、软件及跨求解器门禁
└─ docs/         # 当前文档、理论和只读history
```

大型模型和结果只位于工作区`artifacts/projects/oa_tof/`。Formal、run、archive和scratch生命周期
完全采用根README，不在本项目复制。

## 项目特有硬规则

- COMSOL、SIMION和CAD必须消费同一resolved几何；正式比较必须使用同一粒子表、有效探测面和FWHM定义。
- SIMION检测器PA是GUI可见数值终止层，不是机械检测器厚度。
- Program与Data Recording必须同时开启；关闭Program窗口不等于禁用Program。
- Candidate成功不自动恢复Formal资格，也不授权性能声明或baseline晋升。
- 理论、机器合同、软件实现和历史各自只维护本层职责，不在README重复状态正文。

## History索引

- [`docs/history/20260716__simion-gui-recording-and-program-audit.md`](docs/history/20260716__simion-gui-recording-and-program-audit.md)
- [`docs/history/20260719__analysis-scaling-and-field-diagnostics.md`](docs/history/20260719__analysis-scaling-and-field-diagnostics.md)
- [`docs/history/20260720__midgrid-candidate-runtime-coverage.md`](docs/history/20260720__midgrid-candidate-runtime-coverage.md)
- [`docs/history/20260720__oatof-theory-refactor-review.md`](docs/history/20260720__oatof-theory-refactor-review.md)
- [`docs/history/20260721__superseded-theory-docx.md`](docs/history/20260721__superseded-theory-docx.md)
- [`docs/history/20260727__superseded-rf-handoff-diagnostics.md`](docs/history/20260727__superseded-rf-handoff-diagnostics.md)
- [`docs/history/20260728__pre-document-consolidation-comsol.md`](docs/history/20260728__pre-document-consolidation-comsol.md)
- [`docs/history/20260728__pre-document-consolidation-project.md`](docs/history/20260728__pre-document-consolidation-project.md)
- [`docs/history/20260728__pre-document-consolidation-readme.md`](docs/history/20260728__pre-document-consolidation-readme.md)
- [`docs/history/20260728__pre-document-consolidation-simion.md`](docs/history/20260728__pre-document-consolidation-simion.md)
- [`docs/history/CANDIDATE_WORKFLOW_VALIDATION_20260720.md`](docs/history/CANDIDATE_WORKFLOW_VALIDATION_20260720.md)
- [`docs/history/COMSOL_EXTREME_N_CRASH_20260718_19.md`](docs/history/COMSOL_EXTREME_N_CRASH_20260718_19.md)
- [`docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md`](docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md)
- [`docs/history/NUMERICAL_VALIDATION_20260716_18.md`](docs/history/NUMERICAL_VALIDATION_20260716_18.md)
- [`docs/history/PROJECT_HISTORY.md`](docs/history/PROJECT_HISTORY.md)
- [`docs/history/SIMION_VALIDATION.md`](docs/history/SIMION_VALIDATION.md)
- [`docs/history/SUPERSEDED_RESULTS.md`](docs/history/SUPERSEDED_RESULTS.md)
