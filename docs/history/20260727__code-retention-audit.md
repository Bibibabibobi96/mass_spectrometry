# Git 跟踪代码保留审查（2026-07-27）

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文记录一次性审计、授权与实际处置；执行已经完成，
> 不再作为持续开放任务。稳定审计索引见[`../AUDITS.md`](../AUDITS.md)，后续审计创建新的日期化快照。

## 执行状态

用户已授权删除“高置信度小批次”中的前7项，并明确保留
`common/contracts/prune_migration_snapshot.py`；前7项已从活动树删除。用户另授权oa-TOF已替代RF诊断
包在活动性审计通过后迁入history，并授权Wehnelt历史谱系迁入history。两批源码均已按原字节冻结到
同名扁平payload、写入SHA-256清单并从活动路径移除。联合门禁已通过，处置由提交`5cbf38f`记录，并随
共享SIMION闭合提交`182314c`于2026-07-28推送到`origin/master`。

## 范围与方法

本报告只审查`simulation_repo`内792个Git跟踪文件，不审查或清理artifacts，也不改变任何物理合同、
运行入口、门禁或历史证据。审查交叉使用项目registry、七个项目的README与PROJECT、21个execution
profile入口、`git ls-files`、全仓文件名/模块名/import/call-site搜索、门禁清单和文档入口。CLOC采用
`cloc 2.10`逐文件统计。

“没有文本引用”本身不足以判定MATLAB、Lua或PowerShell文件无用；下列结论同时检查了动态wrapper、
公开文档和相邻工作流。本报告后续“建议”保留审计时点原判断，实际处置以本节“执行状态”和对应
history清单为准；未获授权的其他文件仍须用户对精确路径逐项批准。

## 高置信度小批次

|精确仓库相对路径|CLOC|证据|删除影响|建议|
|---|---:|---|---|---|
|`common/multipole/convert_legacy_particle_source.py`|106|生产调用为零，仅由配套测试引用；公共README已把旧ION11 source CLI列为删除候选，当前L3只消费canonical CSV|失去旧八列源的一次性转换便利，不影响当前固定源或solver runner|批准后删除|
|`common/multipole/test_convert_legacy_particle_source.py`|101|只测试上一项，无其他合同职责|随被测旧转换器一起失去历史迁移回归|与上一项成对删除|
|`common/multipole/generate_particle_source.py`|38|调用、文档和execution profile均为零；仍消费旧baseline/ideal source路径；当前六/八极杆使用共享固定CSV，四极杆使用项目专属生成器|可能影响未记录的手工CLI，不影响受管源入口|核对三个RF项目固定源SHA后删除|
|`common/multipole/simion_sample_pa_field.lua`|12|调用、环境变量引用、文档和execution profile均为零；当前SIMION runner不加载它|只失去未记录的手工PA采样脚本|SIMION源码合同静态测试通过后删除|
|`projects/oa_tof/simion/accelerator/verify_accelerator_override_field.lua`|20|调用、文档和execution profile均为零；活动加速器验收走现有tests/workbench入口|只失去未记录的override手工诊断|oa-TOF Static与SIMION静态合同通过后删除|
|`projects/oa_tof/simion/accelerator/verify_accelerator_variant.lua`|22|调用、文档和execution profile均为零；PA尺寸验收已有活动入口|只失去未记录的PA header手工检查|与上一项同批验证后删除|
|`common/solidworks/import_step_to_solidworks.ps1`|73|活动oa-TOF CAD链明确为`.m → .py`；本PS1无调用、文档或profile，并复制另一套COM导入实现|可能影响未记录的单零件手工入口，不影响当前CAD runner|oa-TOF CAD源码闭包测试通过后删除|
|`common/contracts/prune_migration_snapshot.py`|127|调用、测试、文档和profile均为零；它是带`--execute`删除能力的一次性v1快照清理器|不影响物理链；若仍要清理旧迁移快照，会失去受控清理工具|确认剩余snapshot无需处理后再删除；否则暂保留|

八项全部批准可减少**499 CLOC、8个脚本**。若暂保留
`common/contracts/prune_migration_snapshot.py`，则减少**372 CLOC、7个脚本**。删除前至少运行受影响
项目的定向静态测试、`common/verify_changed.ps1`、文档检查、`git diff --check`和正式CLOC delta；
不因这些纯源码删除重新运行商业求解器。

## 需要单独审批的大包

### oa-TOF 已替代RF诊断包

**处置：活动性审计通过后已按用户授权迁入
`projects/oa_tof/docs/history/20260727__superseded-rf-handoff-diagnostics*`。**

以下闭包共**2304 CLOC**，包括7个脚本和3个配置：

- `projects/oa_tof/analysis/analyze_rf_handoff_projection.py`
- `projects/oa_tof/analysis/analyze_rf_handoff_pulse.py`
- `projects/oa_tof/analysis/prepare_rf_handoff_projection.py`
- `projects/oa_tof/config/modes/rf_handoff_projection.json`
- `projects/oa_tof/config/modes/rf_handoff_pulse.json`
- `projects/oa_tof/config/modes/rf_hybrid_mesh_projection.json`
- `projects/oa_tof/diagnostics/legacy_rf_projection/verify_inputs.ps1`
- `projects/oa_tof/tests/analysis/test_rf_handoff_projection.py`
- `projects/oa_tof/tests/cross_solver/run_rf_handoff_projection.ps1`
- `projects/oa_tof/tests/cross_solver/run_rf_handoff_pulse.ps1`

活动性审计确认它们不属于capability、execution profile或Static gate，oa-TOF Static与联合changed gate
均通过；原字节payload与SHA-256清单保留旧刚体投影、网格投影和共享时钟诊断的源码级追溯。

### Wehnelt 历史谱系

**处置：已按用户授权迁入
`projects/wehnelt_electron_gun/docs/history/20260713__pre-transverse-wehnelt-lineages*`。**

以下9个MATLAB脚本共**1206 CLOC**：

- `projects/wehnelt_electron_gun/legacy/solid_cathode/phase1_geometry.m`
- `projects/wehnelt_electron_gun/legacy/solid_cathode/phase2_electrostatics.m`
- `projects/wehnelt_electron_gun/legacy/solid_cathode/phase3_particle_tracing.m`
- `projects/wehnelt_electron_gun/legacy/solid_cathode/gpu_solver_comparison.m`
- `projects/wehnelt_electron_gun/legacy/axial_coil/phase1_geometry_coil.m`
- `projects/wehnelt_electron_gun/legacy/axial_coil/phase2_electrostatics_coil.m`
- `projects/wehnelt_electron_gun/legacy/axial_coil/phase3_particle_tracing_coil.m`
- `projects/wehnelt_electron_gun/legacy/axial_coil/phase4_thermal_emission_coil.m`
- `projects/wehnelt_electron_gun/legacy/axial_coil/phase5_wehnelt_sweep.m`

项目README明确这些脚本已被横置基线取代且不得作为新工作起点。删除不影响当前横置三阶段入口，但会
失去实心阴极和轴向线圈的源码级历史复现，因此必须由用户独立决定是否接受该损失。

## 明确保留或后置

- RF四极杆continuous-shield、hybrid、piecewise和rod-region网格实验共33个文件、2102 CLOC。
  虽然实验结论已关闭，但其中9个validator仍由项目Static gate直接调用，部分S2/S3合同仍引用其输出
  语义；当前保留，待多极杆N=100主线闭合后再审查脱钩。
- `common/multipole/resolve_finite_3d_contract.py`仍被family foundation和六/八极杆L1测试调用；待这些
  消费者迁到current compiled resolved后再删除。
- `common/multipole/compare_simion_comsol_l3.py`是六/八极杆受管跨求解器闭合的邻近实现，保留。
- `projects/oa_tof/analysis/prepare_formal_promotion.py`属于Candidate成功后的显式promotion路线，保留。
- `common/contracts/migrate_artifacts_v2.py`承担换机或目录迁移的兼容价值，暂保留。
- `common/verify_lightweight.ps1`由根README明确规定为L1兼容入口，保留。
- `common/solidworks/repair_assembly_references.ps1`和`verify_assembly_references.ps1`对应MR-TOF当前
  装配引用开放任务，保留。
- `common/comsol/test_*.m`由公共COMSOL README逐项登记为长期组件验证，不按零profile删除。

任何后续删除都应以本报告中的精确路径重新取得用户批准；不得把目录级批准扩大到未列文件。
