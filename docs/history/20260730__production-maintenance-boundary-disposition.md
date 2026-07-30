# Production维护边界处置（2026-07-30）

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文是
> [`20260730__production-maintenance-surface-baseline.md`](20260730__production-maintenance-surface-baseline.md)
> 的首次生命周期处置记录，不是第二份目录分类规则或持续审计入口。当前职责、生命周期和执行入口仍只
> 以根[`README.md`](../../README.md)、项目`README.md → docs/PROJECT.md`和机器合同为准。

## 决策边界

处置基线为提交`9006fe88be471bf2bbf43203bd996a987c33b883`。外部评审和一次性CLOC审计只作为
待核验证据；每个文件均按当前文档、execution profile、真实消费者、冻结artifact身份和Git历史复核。
本次不修改当前科学参数、Formal资产、当前RF→oaTOF energy contract或integration运行时冻结合同；
仅把旧hybrid config路径压缩为只读兼容描述符。本次不恢复已关闭实验，也不删除七个用途仍不明确的
人工供应商导出协议。

本次把四个纯测试support迁入`test_support/`，把一个当前诊断runner迁入具名workflow，并把其MATLAB
导出器迁入项目`comsol/`。旧路径全部删除，父runner、最近文档和布局门禁同步更新：

- `projects/rf_quadrupole_ion_optics/tests/simion/export_unit_rf_field.lua` →
  `projects/rf_quadrupole_ion_optics/tests/simion/test_support/export_unit_rf_field.lua`
- oa-TOF `tests/comsol/run_oatof_matlab_unit_tests.m`和
  `run_oatof_formal_write_contract_tests.m` → `tests/comsol/test_support/`
- oa-TOF `tests/simion/export_accelerator_grid_phase_field.lua` → `tests/simion/test_support/`
- oa-TOF `tests/comsol/run_accelerator_transverse_field_uniformity.ps1` →
  `workflows/accelerator_transverse_field_uniformity/`
- oa-TOF `tests/comsol/export_accelerator_transverse_field_uniformity.m` → `comsol/`

## RF兼容边界

`projects/rf_quadrupole_ion_optics/config/rf_hybrid_mesh_candidate.json`保留同一路径，但由可执行候选压缩为
`rf_legacy_hybrid_mesh_compatibility_descriptor`。描述符明确禁止当前科学权威、执行、生成和晋升，并记录：

- 原合同repository SHA-256：
  `143917752A0DD2C41BBE1161B272D57AC47FA854521B63CB3A32BEBA1AB3FF40`
- 代表性来源run：
  `20260722_193000__sim__comsol__rf-input5ev-handoff__n100__r02`
- artifact合同SHA-256：
  `9D54CE5AB5456AA487F4F534BBDB372BCB1018339C70F246936122C98D57C6A8`
- 当前runtime权威：
  `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/legacy_quadrupole_n100_source_contract.json`

`validate_rf_energy_match.py`成为该描述符的唯一活动校验消费者，失败关闭地核验role、status、原身份、
证据basename/SHA/run及四个否定授权标志。Static/public clone不要求本机artifact存在。

## 已批准删除清单

下列41个Git路径已逐项取得用户批准并删除。Git公开历史和已冻结artifact继续保存可追溯身份。

### RF analysis与config（13）

- `projects/rf_quadrupole_ion_optics/analysis/analyze_rf_continuous_shield_2d.py`
- `projects/rf_quadrupole_ion_optics/analysis/analyze_rf_continuous_shield_3d.py`
- `projects/rf_quadrupole_ion_optics/analysis/compare_rf_continuous_shield_3d.py`
- `projects/rf_quadrupole_ion_optics/analysis/compare_rf_continuous_shield_n100.py`
- `projects/rf_quadrupole_ion_optics/analysis/compare_rf_hybrid_mesh.py`
- `projects/rf_quadrupole_ion_optics/analysis/compare_rf_rod_region_swept_mesh.py`
- `projects/rf_quadrupole_ion_optics/analysis/validate_rf_continuous_shield.py`
- `projects/rf_quadrupole_ion_optics/analysis/validate_rf_hybrid_mesh.py`
- `projects/rf_quadrupole_ion_optics/analysis/validate_rf_piecewise_swept_mesh.py`
- `projects/rf_quadrupole_ion_optics/analysis/validate_rf_rod_region_swept_mesh.py`
- `projects/rf_quadrupole_ion_optics/config/rf_continuous_grounded_shield_candidate.json`
- `projects/rf_quadrupole_ion_optics/config/rf_piecewise_swept_mesh_candidate.json`
- `projects/rf_quadrupole_ion_optics/config/rf_rod_region_swept_mesh_candidate.json`

### RF tests/analysis（10）

- `projects/rf_quadrupole_ion_optics/tests/analysis/run_rf_continuous_shield_3d_comparison.ps1`
- `projects/rf_quadrupole_ion_optics/tests/analysis/run_rf_continuous_shield_n100_comparison.ps1`
- `projects/rf_quadrupole_ion_optics/tests/analysis/run_rf_hybrid_mesh_comparison.ps1`
- `projects/rf_quadrupole_ion_optics/tests/analysis/run_rf_hybrid_n100_comparison.ps1`
- `projects/rf_quadrupole_ion_optics/tests/analysis/run_rf_rod_region_swept_mesh_comparison.ps1`
- `projects/rf_quadrupole_ion_optics/tests/analysis/test_compare_rf_continuous_shield_3d.py`
- `projects/rf_quadrupole_ion_optics/tests/analysis/test_compare_rf_continuous_shield_n100.py`
- `projects/rf_quadrupole_ion_optics/tests/analysis/test_compare_rf_hybrid_mesh.py`
- `projects/rf_quadrupole_ion_optics/tests/analysis/test_compare_rf_rod_region_swept_mesh.py`
- `projects/rf_quadrupole_ion_optics/tests/analysis/test_rf_continuous_shield_3d.py`

### RF tests/comsol（11）

- `projects/rf_quadrupole_ion_optics/tests/comsol/build_rf_continuous_shield_2d.m`
- `projects/rf_quadrupole_ion_optics/tests/comsol/build_rf_continuous_shield_3d.m`
- `projects/rf_quadrupole_ion_optics/tests/comsol/build_rf_hybrid_mesh.m`
- `projects/rf_quadrupole_ion_optics/tests/comsol/build_rf_piecewise_swept_mesh.m`
- `projects/rf_quadrupole_ion_optics/tests/comsol/build_rf_rod_region_swept_mesh.m`
- `projects/rf_quadrupole_ion_optics/tests/comsol/run_rf_continuous_shield_2d.ps1`
- `projects/rf_quadrupole_ion_optics/tests/comsol/run_rf_continuous_shield_3d.ps1`
- `projects/rf_quadrupole_ion_optics/tests/comsol/run_rf_hybrid_mesh.ps1`
- `projects/rf_quadrupole_ion_optics/tests/comsol/run_rf_piecewise_swept_mesh.ps1`
- `projects/rf_quadrupole_ion_optics/tests/comsol/run_rf_rod_region_swept_mesh.ps1`
- `projects/rf_quadrupole_ion_optics/tests/comsol/export_fem_unit_rf_field.m`

### oa-TOF tests（7）

- `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/build_accelerator_geometry_candidate.m`
- `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/diagnose_oatof_bracket_field.m`
- `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/export_fixed_particle_arrivals_from_mph.m`
- `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/promote_verified_candidate_to_formal.m`
- `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/run_field_idealization_sweep.m`
- `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/run_oatof_524amu_fixed_particle_candidate.m`
- `projects/single_reflection_oa_tof_mass_analyzer/tests/simion/inspect_formal_instances.lua`

## 验证与规模结果

无商业求解器的RF Core/Static分别PASS；RF Static运行295项Python测试。oa-TOF Static PASS并运行155项
Python测试。迁移后的MATLAB runner经正式MATLAB R2025b/COMSOL 6.4入口执行：单元测试11/11通过，
Formal写入合同的普通写入拒绝、promotion精确目标授权及目标不匹配拒绝全部通过。Ruff、PowerShell
解析、JSON解析、开发规范和文档门禁均通过；未运行真实粒子/场求解或GUI/CAD复验，因为本次未改变
物理、数值、Formal二进制或CAD。

权威入口`common/report_cloc_delta.ps1`使用CLOC 2.10比较基线与排除任务前未跟踪`.tmp/`的Git树快照。
过滤口径与一次性基线相同；classifier和language definition SHA-256均未变化。结果为：

|分类|基线files/code|处置后files/code|delta files/code|
|---|---:|---:|---:|
|total|880 / 136,637|839 / 133,764|-41 / -2,873|
|production|666 / 96,950|644 / 95,314|-22 / -1,636|
|tests|189 / 38,072|188 / 38,132|-1 / +60|
|unclassified|25 / 1,615|7 / 318|-18 / -1,297|

处置后输入身份SHA-256为
`9dc78d7ba4f3901cf6870b84263ade56243ef19c3dc4462661f459e82d5ba53c`。剩余七个unclassified正是
基线中保留的人工导出协议，没有新增未分类文件。

## 常规化结论

本记录完成第一次生命周期处置，但仍不把二级production分类加入L1、CI或常规开发。只有再发生一次
独立生命周期事件，并同时满足基线审计列出的机器入口覆盖、两次互斥规则复现、同一权威by-file结果、
实际决策收益和单独L1批准条件时，才重新评估常规化。
