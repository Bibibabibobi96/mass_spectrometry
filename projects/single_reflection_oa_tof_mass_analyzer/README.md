# 单次反射正交加速飞行时间质量分析器

本项目维护正交加速、双级环栈反射镜oa-TOF分析器。项目当前状态、资格与开放任务只以
[`docs/PROJECT.md`](docs/PROJECT.md)为准；本页只负责导航。

二区／三区加速器的局部理论与复用实现由独立
[`orthogonal_accelerator`](../orthogonal_accelerator/README.md)项目维护；本项目仍负责反射器、整机
布局、加速器—反射器联合聚焦与检测分析。既有 Formal 和历史运行按原身份保留，不随代码迁移转移资格。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 修改时间聚焦、场强、电压或轴向长度时，读[`docs/theory/README.md`](docs/theory/README.md)。
4. 评估论文主张、证据边界或JASMS/Analytical Chemistry分工时，读
   [`docs/publication/README.md`](docs/publication/README.md)。
5. 涉及COMSOL实现、事件读取或数值审查时，按[`docs/COMSOL.md`](docs/COMSOL.md)开头的任务表选章节；
   通用API、排错与误差预算从[COMSOL阅读入口](../../docs/tools/COMSOL_GUIDE.md)选择，不作为无关任务的前置阅读。
   SIMION或CAD任务只进入相应[`docs/SIMION.md`](docs/SIMION.md)或[`docs/CAD.md`](docs/CAD.md)。
6. 只有追溯旧结论、run ID或失败链时才进入[历史索引](docs/history/README.md)。

## 机器权威

| 职责 | 权威入口 |
|---|---|
| 项目身份与生命周期 | [`config/project.json`](config/project.json) |
| 人工物理设计 | [`config/baseline.json`](config/baseline.json) |
| Formal科学合同 | [`config/modes/formal.json`](config/modes/formal.json) |
| 求解器数值合同 | [`config/formal_solver_numerics.json`](config/formal_solver_numerics.json) |
| 候选仪器布局 | [`config/single_flight_layout_profiles.json`](config/single_flight_layout_profiles.json) |
| 程序几何发布 | [`config/resolved_geometry.json`](config/resolved_geometry.json) |
| 下游集成required port | [`config/interfaces/required/oatof_accelerator_entry.json`](config/interfaces/required/oatof_accelerator_entry.json) |
| 分析定义 | [`config/analysis_contract.json`](config/analysis_contract.json) |
| 已冻结Formal验证记录 | [`config/formal_validation.json`](config/formal_validation.json) |
| SIMION资产身份 | [`config/simion_stable_entry.json`](config/simion_stable_entry.json) |
| 可执行workflow | [`config/execution_profiles.json`](config/execution_profiles.json) |
| 已完成的声明式Candidate campaign | [`config/experiment_campaign.json`](config/experiment_campaign.json)（retired；历史结果见history） |

参数不在文档复制：可调性、类型与约束只查[`config/design_variables.json`](config/design_variables.json)，
默认值只查[`config/baseline.json`](config/baseline.json)，数值设置只查
[`config/formal_solver_numerics.json`](config/formal_solver_numerics.json)；执行入口见下表。

## 活动入口

| 用途 | 唯一入口 | 合同或资格边界 |
|---|---|---|
| 理想场残差、仿射斜率与束宽设计比较 | [统一分析入口](analysis/README.md#自动理想场比较) | 同一 workflow 按科学配置选择比较；配置角色、运行方法及声明边界在分析说明维护 |
| COMSOL生产 | [`comsol/run_oatof_model.m`](comsol/run_oatof_model.m) | `config/baseline.json`与显式Candidate合同 |
| SIMION交付构建 | [`simion/workbench/build_formal_delivery.ps1`](simion/workbench/build_formal_delivery.ps1) | Formal只读；Candidate输出不得反写Formal |
| 单个结构Candidate | [`workflows/design_candidate/run_candidate.py`](workflows/design_candidate/run_candidate.py) | 获批request、显式seed、完整COMSOL/SIMION/CAD链 |
| 预注册Candidate campaign | [`workflows/experiment_campaign/run_campaign.py`](workflows/experiment_campaign/run_campaign.py) | 默认合同已完成并retired；新campaign须使用新的合同与run ID，执行时显式选择实验或`--all` |
| Formal验证、发布、复核 | [`workflows/formal_reference/run_formal_validation.ps1`](workflows/formal_reference/run_formal_validation.ps1) | `-Phase Validate`、`Publish` 或 `Verify` |
| 五质量候选 | [`workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1`](workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1) | 五个固定质量点，不自动推广Formal |
| Formal跨求解器诊断 | [`workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1`](workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1) | 只读冻结场与轨迹，只发布diagnostic结果 |
| 加速器横向场均匀性 | [`workflows/accelerator_transverse_field_uniformity/run_accelerator_transverse_field_uniformity.ps1`](workflows/accelerator_transverse_field_uniformity/run_accelerator_transverse_field_uniformity.ps1) | 只读Formal COMSOL保存场，不重求粒子 |
| oaTOF径向紧凑化 | [`workflows/radial_compaction/run_campaign.py`](workflows/radial_compaction/run_campaign.py) | 默认[`campaign合同`](config/radial_compaction_campaign.json)，新建可显式`--campaign`；续跑用新run ID与`--resume-from`，范围见[项目状态](docs/PROJECT.md)；SIMION-only Candidate，不自动推广Formal |
| 反射器电压场补偿 | [`workflows/reflectron_voltage_compensation/run_compensation.py`](workflows/reflectron_voltage_compensation/run_compensation.py) | 固定端点、单调环电压；复用PA，先测量单批峰值内存，再自动分批比较原场/补偿场/理想场 |
| CAD导出 | [`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m) | 读取指定模型与合同 |
| 项目门禁 | [`verify_project.ps1`](verify_project.ps1)，选择 `-Level` | 按证据等级执行 |

静态Python测试通过公共计时runner即时报告失败和逐测试耗时，原测试发现范围保持完整。

所有workflow从本表导航；目录内不再复制合同和资格说明。命令行细节由入口的`--help`/参数块给出，
SIMION运行边界见[`docs/SIMION.md`](docs/SIMION.md)，Formal与开放任务见[`docs/PROJECT.md`](docs/PROJECT.md)。
径向紧凑化和单个结构Candidate将公共owner的小Result保留在项目`scratch/workflow_results/<run_id>/result.json`。
收尾中断时分别通过原入口的`--resume-finalization`（径向入口同时指定`--run-id`，Candidate指定run目录）
复用冻结request和Result；显式PA handoff Result可用`--owner-result`指定。该动作只恢复收尾，不重新飞行。
Candidate campaign从仓库根通过以下模块查看参数，再提供表中要求的显式输入：

```powershell
.\.venv\Scripts\python.exe -m projects.single_reflection_oa_tof_mass_analyzer.workflows.experiment_campaign.run_campaign --help
```

RF多极杆离子光学→单次反射oa-TOF的新装配与整机运行从
[统一集成入口](../../integrations/README.md)进入；目录与职责遵循
[连接标准](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)。本项目required port描述
对上游粒子、入口面、公共电位、场边界和时钟的接受要求。当前连接状态、oracle结论与资格边界只查
[`docs/PROJECT.md`](docs/PROJECT.md)和
[统一集成状态](../../integrations/docs/INTEGRATION.md)，
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

产物定位与历史身份见 [PROJECT](docs/PROJECT.md#产物与历史)；生命周期见
[仓库生命周期](../../docs/LIFECYCLE.md)。求解器专有操作要求在对应实施说明维护。

## History索引

[历史索引](docs/history/README.md)集中列出已冻结实验、迁移和旧方案；需要追溯证据时按需进入。
