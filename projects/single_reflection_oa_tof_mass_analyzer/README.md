# 单次反射正交加速飞行时间质量分析器

本项目维护正交加速、双级环栈反射镜oa-TOF分析器。项目当前状态、资格与开放任务只以
[`docs/PROJECT.md`](docs/PROJECT.md)为准；本页只负责导航。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 修改时间聚焦、场强、电压或轴向长度时，读[`docs/theory/README.md`](docs/theory/README.md)。
4. 评估论文主张、证据边界或JASMS/Analytical Chemistry分工时，读
   [`docs/publication/README.md`](docs/publication/README.md)。
5. 操作COMSOL、SIMION或CAD时，只读相应的
   [`docs/COMSOL.md`](docs/COMSOL.md)、[`docs/SIMION.md`](docs/SIMION.md)或
   [`docs/CAD.md`](docs/CAD.md)。
6. 只有追溯旧结论、run ID或失败链时才进入[`docs/history/`](docs/history/)。

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
| 下游集成required port | [`config/interfaces/required/oatof_accelerator_entry.json`](config/interfaces/required/oatof_accelerator_entry.json) |
| 分析定义 | [`config/analysis_contract.json`](config/analysis_contract.json) |
| 已冻结Formal验证记录 | [`config/formal_validation.json`](config/formal_validation.json) |
| SIMION资产身份 | [`config/simion_stable_entry.json`](config/simion_stable_entry.json) |
| 可执行workflow | [`config/execution_profiles.json`](config/execution_profiles.json) |
| 已完成的声明式Candidate campaign | [`config/experiment_campaign.json`](config/experiment_campaign.json)（retired；历史结果见history） |

数据流固定为`baseline + science + solver numerics → resolved → COMSOL/SIMION/CAD`。seed、run ID和
冻结路径只属于run instance；候选不得反写baseline或Formal资产。当前项目生命周期为
`formal`；当前Formal release、资格边界与开放任务详见PROJECT。

参数不在文档复制：可调性、类型与约束只查[`config/design_variables.json`](config/design_variables.json)，
默认值只查[`config/baseline.json`](config/baseline.json)，数值设置只查
[`config/formal_solver_numerics.json`](config/formal_solver_numerics.json)；执行入口见下表。

## 活动入口

| 用途 | 唯一入口 | 合同或资格边界 |
|---|---|---|
| COMSOL生产 | [`comsol/run_oatof_model.m`](comsol/run_oatof_model.m) | `config/baseline.json`与显式Candidate合同 |
| SIMION交付构建 | [`simion/workbench/build_formal_delivery.ps1`](simion/workbench/build_formal_delivery.ps1) | Formal只读；Candidate输出不得反写Formal |
| 单个结构Candidate | [`workflows/design_candidate/run_candidate.py`](workflows/design_candidate/run_candidate.py) | 获批request、显式seed、完整COMSOL/SIMION/CAD链 |
| 预注册Candidate campaign | [`workflows/experiment_campaign/run_campaign.py`](workflows/experiment_campaign/run_campaign.py) | 默认合同已完成并retired；新campaign须使用新的合同与run ID，执行时显式选择实验或`--all` |
| Formal验证、发布、复核 | [`workflows/formal_reference/run_formal_validation.ps1`](workflows/formal_reference/run_formal_validation.ps1) | `-Phase Validate|Publish|Verify` |
| 五质量候选 | [`workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1`](workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1) | 五个固定质量点，不自动推广Formal |
| Formal跨求解器诊断 | [`workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1`](workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1) | 只读冻结场与轨迹，只发布diagnostic结果 |
| 加速器横向场均匀性 | [`workflows/accelerator_transverse_field_uniformity/run_accelerator_transverse_field_uniformity.ps1`](workflows/accelerator_transverse_field_uniformity/run_accelerator_transverse_field_uniformity.ps1) | 只读Formal COMSOL保存场，不重求粒子 |
| oaTOF径向紧凑化 | [`workflows/radial_compaction/run_campaign.py`](workflows/radial_compaction/run_campaign.py) | [`config/radial_compaction_campaign.json`](config/radial_compaction_campaign.json)；SIMION-only Candidate，不自动推广Formal；独立case按共享调度器的CPU、当前可用内存和已观测峰值分波执行 |
| 反射器电压场补偿 | [`workflows/reflectron_voltage_compensation/run_compensation.py`](workflows/reflectron_voltage_compensation/run_compensation.py) | 固定端点、单调环电压；复用PA，先测量单批峰值内存，再自动分批比较原场/补偿场/理想场 |
| CAD导出 | [`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m) | 读取指定模型与合同 |
| 项目门禁 | `verify_project.ps1 -Level Static|Candidate|Formal` | 按证据等级执行 |

所有workflow从本表导航；目录内不再复制合同和资格说明。命令行细节由入口的`--help`/参数块给出，
SIMION运行边界见[`docs/SIMION.md`](docs/SIMION.md)，Formal与开放任务见[`docs/PROJECT.md`](docs/PROJECT.md)。
Candidate campaign的仓库模块入口为`workflows.experiment_campaign.run_campaign`。

RF多极杆离子光学→单次反射oa-TOF的活动实现由
[`../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md`](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)
规定的项目端口、公共解析器和
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`实例承载。本项目required port描述
对上游粒子、入口面、公共电位、场边界和时钟的接受要求。当前连接状态、oracle结论与资格边界只查
[`docs/PROJECT.md`](docs/PROJECT.md)和
[`integration当前文档`](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)，
本入口不复制运行结论。

## 目录职责

```text
single_reflection_oa_tof_mass_analyzer/
├─ config/       # 科学、数值、resolved、分析和资产身份合同
├─ workflows/    # Formal、Candidate和质量谱科学工作流
├─ comsol/       # COMSOL模型机制
├─ simion/       # GEM、Lua、Fly2和交付构建
├─ cad/          # STEP与SolidWorks同步
├─ analysis/     # 求解器无关理论、分析和候选编译
├─ tests/        # 静态、软件及跨求解器门禁
└─ docs/         # 当前文档、理论、投稿边界和只读history
```

新运行和未来vNext Formal只写入工作区
`artifacts/projects/single_reflection_oa_tof_mass_analyzer/`。重命名前的Formal、run与archive已按
原manifest身份只读迁入该根的
`archive/20260801_130003__migration-snapshot__repo__oa-tof/legacy-project-root/`；不得改写、追加新run
或在新身份下晋升。映射由
[`config/project.json`](config/project.json)的`legacy_identities`声明。两处产物的生命周期均采用
根README，不在本项目复制。

## 项目特有硬规则

- COMSOL、SIMION和CAD必须消费同一resolved几何；正式比较必须使用同一粒子表、有效探测面和FWHM定义。
- SIMION检测器PA是GUI可见数值终止层，不是机械检测器厚度。
- Program与Data Recording必须同时开启；关闭Program窗口不等于禁用Program。
- Candidate成功不自动恢复Formal资格，也不授权性能声明或baseline晋升。
- 理论、投稿主张、机器合同、软件实现和历史各自只维护本层职责，不在README重复状态正文。

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
- [`docs/history/20260729__formal-vnext-zero-change-requests.md`](docs/history/20260729__formal-vnext-zero-change-requests.md)
- [`docs/history/20260802__reflectron-midgrid-campaign-authorization.md`](docs/history/20260802__reflectron-midgrid-campaign-authorization.md)
- [`docs/history/20260802__formal-simion-integrity-recovery.md`](docs/history/20260802__formal-simion-integrity-recovery.md)
- [`docs/history/20260817__three-zone-accelerator-external-document-review.md`](docs/history/20260817__three-zone-accelerator-external-document-review.md)
- [`docs/history/20260817__three-zone-observed-transverse-sensitivity.md`](docs/history/20260817__three-zone-observed-transverse-sensitivity.md)
- [`docs/history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md`](docs/history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md)
- [`docs/history/20260823__three-zone-completed-results-snapshot.md`](docs/history/20260823__three-zone-completed-results-snapshot.md)
- [`docs/history/CANDIDATE_WORKFLOW_VALIDATION_20260720.md`](docs/history/CANDIDATE_WORKFLOW_VALIDATION_20260720.md)
- [`docs/history/COMSOL_EXTREME_N_CRASH_20260718_19.md`](docs/history/COMSOL_EXTREME_N_CRASH_20260718_19.md)
- [`docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md`](docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md)
- [`docs/history/NUMERICAL_VALIDATION_20260716_18.md`](docs/history/NUMERICAL_VALIDATION_20260716_18.md)
- [`docs/history/PROJECT_HISTORY.md`](docs/history/PROJECT_HISTORY.md)
- [`docs/history/SIMION_VALIDATION.md`](docs/history/SIMION_VALIDATION.md)
- [`docs/history/SUPERSEDED_RESULTS.md`](docs/history/SUPERSEDED_RESULTS.md)

## 历史补充索引
- [20260801__oatof-legacy-artifact-migration-audit](docs/history/20260801__oatof-legacy-artifact-migration-audit.md)
