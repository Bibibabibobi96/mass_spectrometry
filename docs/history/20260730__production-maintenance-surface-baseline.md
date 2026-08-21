# Production维护面一次性基线（2026-07-30）

DOC_STATUS: ARCHIVED_READ_ONLY

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文记录提交
> `57647c5b23ab07e367bfc2961dd78baefe3c968f`上的一次性CLOC语义审计，不是新的持续规范、
> 项目状态或文件生命周期机器权威。稳定审计索引见[`../AUDITS.md`](../AUDITS.md)；当前职责仍以
> 根[`README.md`](../../README.md)、项目`README.md → docs/PROJECT.md`和机器合同为准。

## 范围与方法

本次审计回答两个问题：当前CLOC是否暴露仓库或项目负担异常，以及`production`能否进一步解释为
活跃维护面。判断顺序固定为根README的目录职责与生命周期、`AGENTS.md`、完整开发规范、项目当前
文档、机器入口和真实消费者；不按行数、文件名、Git最近修改时间或异构`status`字段直接推断生命周期。

规范计数入口为`common/report_cloc_delta.ps1`，使用CLOC 2.10。提交快照的计数身份为：

- classifier SHA-256：
  `e9b0dfc62b4a9c76f06a55f301e09d92d6ed1641957a00a500ecbea28abe017f`
- language definition SHA-256：
  `985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`
- 选中文件：880
- input identity SHA-256：
  `20713d313a928c0a869bf1bef8fe7cf81a47a820a1e8261869151f082fe9f21a`

本次二级聚合复用同一880文件的`--by-file --skip-uniqueness`结果、MATLAB/Lua/GEM语言覆盖和既有
history、scratch、artifact、generated、vendor、run排除，不建立第二个行数统计器。任务开始前已有
未跟踪`.tmp/`不属于提交快照，未被读取为权威输入、修改或清理。

## 仓库与项目判断

### 一级统计

|分类|files|code|占比|
|---|---:|---:|---:|
|production|666|96,950|70.95%|
|tests|189|38,072|27.86%|
|unclassified|25|1,615|1.18%|
|total|880|136,637|100.00%|

主要语言为Python 72,634、JSON 30,084、PowerShell 18,113、MATLAB 13,343、Lua 2,106、
SIMION GEM 246、YAML 87和TOML 24。Python中production为38,841、tests为33,793；测试规模本身
没有显示异常，也不能由代码行占比推断覆盖率。30,084行JSON全部落入一级`production`，只表示
非测试责任面，不能解释为30,084行活跃算法。

### 项目与共享热点

|区域|生命周期/职责|total|production|tests|unclassified|判断|
|---|---|---:|---:|---:|---:|---|
|RF四极杆|Candidate|34,011|22,680|10,804|527|多workflow体量与状态相符；测试边界和integration所有权需收口|
|单反射oa-TOF|Formal|26,848|20,344|5,416|1,088|Formal链体量合理；测试目录内混有当前诊断和旧入口|
|RF六极杆|Static|10,785|8,146|2,639|0|其中8,048为JSON，应按资格记录生命周期解释|
|RF八极杆|Static|4,592|3,804|788|0|其中3,705为JSON，不是算法膨胀|
|Wehnelt电子枪|Prototype|3,564|2,422|1,142|0|无CLOC异常|
|EI离子源|Prototype|1,403|1,103|300|0|无CLOC异常|
|MR-TOF|Prototype|52|52|0|0|当前只有描述符，与尚无求解器模型的状态一致|
|`common/multipole`|三项目共享机制|20,210|13,408|6,802|0|三个真实消费者支持当前职责|
|RF→oaTOF integration|跨项目连接|16,567|12,385|4,182|0|功能链已闭合；仍有源码所有权偏移|
|`common/contracts`|仓库合同机制|10,744|7,805|2,939|0|存在真实跨项目消费者，不支持整体拆分|
|`common/comsol`|供应商公共边界|2,854|393|2,461|0|测试多于生产符合公共供应商原语的回归职责|

因此当前没有“仓库规模危机”。RF四极杆和oa-TOF较大、MR-TOF很小，均能由生命周期、工具链和
机器权威解释；整数CLOC上限、机械删测试或按体量平均项目都没有证据基础。

## Production二级语义基线

现有机器权威不足以自动建立跨Python、PowerShell、MATLAB、Lua和JSON的完整可达闭包。
execution profile能证明直接入口下界，但项目README还登记未进入profile的COMSOL、CAD、L2/L3与
手工入口；动态跨语言调用和SHA冻结合同也不能由import图完整恢复。因此本次采用守恒的保守分区：

|二级角色|files|code|可解释范围|
|---|---:|---:|---|
|`current_execution_source_upper_bound`|359|65,248|排除显式仓库tooling后的非测试源码责任上界，不等于精确active LOC|
|`repository_tooling`|12|2,101|当前CLOC、changed-scope、文档/规范/仓库门禁、根Ruff与CI配置|
|`current_contract_residual_upper_bound`|205|21,297|排除文档明示证据、兼容和tooling后的机器合同责任上界|
|`current_evidence_explicit`|64|6,710|当前文档明示的qualification/family-experiment、Formal验证与预注册证据包|
|`compatibility_retained_explicit_minimum`|26|1,594|当前README/PROJECT明示且仍由兼容消费者读取的只读资产下界|
|**production**|**666**|**96,950**|五类严格加总|

production内源码责任总量为66,755行，即表中65,248行项目/共享源码加1,507行源码型仓库tooling；
其余tooling为594行JSON/YAML/TOML。它只是对production内执行源码的保守上界，不覆盖tests或
unclassified，也仍包含诊断、兼容实现和未注册手工入口，不能改名为“精确活跃代码”。

机器合同分区同样是边界而非永久真值。兼容下界由以下文档明示组构成：

|兼容组|files|code|边界|
|---|---:|---:|---|
|integration三个`legacy_*`合同与`migration_oracles.json`|4|501|当前迁移/等价复核消费|
|RF六极杆旧baseline、finite-3D、三request、四专属catalog/envelope和两evidence|11|457|PROJECT明确只供历史/兼容读取|
|RF八极杆旧baseline、finite-3D、三request和四专属catalog/envelope|9|434|README/PROJECT明确为兼容或历史快照|
|RF四极杆旧`config/baseline.json`|1|58|尚未迁移的专用workflow只读消费|
|oa-TOF `config/analysis_baselines.json`|1|144|条目均为历史记录，但当前分析门禁仍读取|
|**显式兼容下界**|**26**|**1,594**|不等于完整兼容面|

证据包由RF六极杆qualification 33文件/4,784行、RF八极杆qualification 14/779、RF四极杆
family-experiment 13/771、integration两项预注册1/54和1/98，以及oa-TOF
`formal_validation.json`与`formal_assets.json`各一项、合计1/194和1/30组成。Schema和
`common/multipole/numerical_qualification.json`属于合同/方法，不按名称中的qualification误归为证据。

仍有不能自动落位的混合资产：RF四极杆11个旧`rf_to_oatof_*`合同合计1,237行，同时被文档描述为
只读oracle和当前迁移入口；RF六/八极部分静态resolved/evidence仍有当前发布或人工复核消费者。
它们保守留在`current_contract_residual_upper_bound`，不能按文件名自动移入兼容类。
`terminal`表示一次执行或结果终态，不自动表示文件已退休；只有当前消费者为零且结论已冻结后，才可
提出归档或删除。

## 25个未分类文件

25个文件全部位于RF四极杆和oa-TOF的`tests/`。两个项目的execution profile、当前README/PROJECT和
`verify_project.ps1`均未直接绑定这25项；changed-scope触发项目gate也不表示目标脚本实际获得覆盖。
按真实消费者、当前文档入口和明确关闭/替代证据，1,615行可完整分解为：

|处置组|files|code|结论|
|---|---:|---:|---|
|`test_support_candidate`|4|182|由具名测试runner直接消费或自身只枚举/断言测试|
|`current_workflow_candidate`|1|43|当前分析文档登记、runner冻结并调用的生产诊断|
|`retirement_candidate`|13|1,072|已有明确关闭、替代入口或当前零消费者证据；删除仍需用户批准|
|`ambiguous`|7|318|静态不可达，但邻近当前诊断能力仍存在，不能证明可删|
|**unclassified**|**25**|**1,615**|四组严格加总|

### 测试support候选

- RF四极杆`tests/simion/export_unit_rf_field.lua`由
  `test_pa_field_convergence.ps1`直接消费。
- oa-TOF的`tests/comsol/run_oatof_matlab_unit_tests.m`和
  `run_oatof_formal_write_contract_tests.m`只执行具名测试并断言结果。
- oa-TOF的`tests/simion/export_accelerator_grid_phase_field.lua`由
  `test_accelerator_grid_phase.ps1`直接消费；父网格相位实验是否继续保留仍应单独按生命周期复核。

后续若实施，应把这四项迁入明确`test_support`边界并同步消费者；本次不移动文件。

### 当前workflow候选

oa-TOF的`tests/comsol/export_accelerator_transverse_field_uniformity.m`由
`run_accelerator_transverse_field_uniformity.ps1`直接消费，当前`analysis/README.md`仍登记该
saved-solution导出入口。它应按当前生产诊断处理，后续迁出`tests/`到最邻近的analysis/workflow边界。

### 退役候选

- RF四极杆五个旧模型/网格构建器：
  `build_rf_continuous_shield_2d.m`、`build_rf_continuous_shield_3d.m`、
  `build_rf_hybrid_mesh.m`、`build_rf_piecewise_swept_mesh.m`和
  `build_rf_rod_region_swept_mesh.m`。它们只被同名wrapper消费，当前COMSOL文档已关闭对应筛选，
  当前混合网格活动使用公共multipole profile。
- RF四极杆`export_fem_unit_rf_field.m`当前无消费者，唯一文档依据已进入history。
- oa-TOF的`build_accelerator_geometry_candidate.m`、`promote_verified_candidate_to_formal.m`和
  `run_oatof_524amu_fixed_particle_candidate.m`已分别被当前Candidate、Formal发布和候选入口取代。
- oa-TOF的`tests/comsol/diagnose_oatof_bracket_field.m`和
  `tests/comsol/run_field_idealization_sweep.m`对应调查已关闭到history。后者不是另一个仍由测试
  消费、按权威规则属于production的`tests/simion/run_field_idealization_sweep.ps1`。
- oa-TOF的`export_fixed_particle_arrivals_from_mph.m`已由当前
  `comsol/run_fixed_particle_retrace.m`路径取代。
- oa-TOF的`inspect_formal_instances.lua`只有打印诊断，当前IOB runtime合同已有具名验证入口。

这13项只能组成待批准退役包；正式删除前还必须核对冻结artifact/manifest中的代码身份，且删除必须
单独取得用户确认。

### 仍不明确

- oa-TOF `compare_oatof_particle_exports.ps1`
- oa-TOF COMSOL
  `export_accelerator_vector_field_samples.m`、`export_axis_field_profiles.m`、
  `export_selected_particle_trajectories.m`
- oa-TOF SIMION
  `export_accelerator_vector_field_samples.lua`、`export_axis_field_profiles.lua`及其PowerShell wrapper

这些文件没有当前静态消费者，但当前analysis仍保留粒子、矢量场和轴场比较能力，无法排除人工供应商
导出协议。本次继续保留为`ambiguous`，不得用“零rg引用”自动退役。

## 结构性维护信号

RF→oaTOF的三个family dependency合同各有52个冻结依赖、各692行JSON，合计2,076行。它们不是无效
重复：当前runtime binding和发布测试消费完整路径与SHA。但三份合同共同冻结下列六个仍位于RF四极杆
`analysis/`的连接级脚本：

- `derive_shared_centroid_pulse_time.py`
- `plot_shared_pulse_geometry_snapshot.py`
- `audit_pulse_capture_pulse_chain.py`
- `build_pulse_capture_local_exit_component_state.py`
- `analyze_analyzer_transport.py`
- `validate_oatof_formal_analyzer_release.py`

这构成已核实的所有权偏移。后续应先形成独立integration迁移包，同步三份依赖合同、runtime SHA和
三个family分支回归；oa-TOF正式资产验证仍留在oa-TOF职责内。依赖合同只有在base+family overlay解析
后得到完全相同的52项完整路径、身份和SHA时才可压缩，不能仅因文本相似合并。

`common/verify_development_standards.py --show-review`当前报告126个长度审查信号、0个硬错误。长文件
同时存在于共享合同、多极杆、RF四极杆、oa-TOF和测试，说明长度是职责审查队列而不是CLOC违规。
应只拆分确有混合职责且能建立窄回归的实现，不建立统一行数上限。

## 后续审批包与常规化判据

本次不移动、删除或重构源码。后续按三个独立主题审批：

1. 四项测试support迁移、一项当前诊断迁出`tests/`、十三项退役候选删除和七项人工协议确认。
2. 六个连接级分析脚本迁入integration，并原子更新三family依赖合同及SHA回归。
3. 六/八极qualification和其他JSON逐项区分当前合同、当前证据与兼容保留；消费者为零且结论已冻结
   的记录才进入归档/删除审批，同时独立验证family dependency base+overlay可行性。

当前**不建议**把二级分类固化为常规审计：源码仍只能给出责任上界，兼容与证据仍依赖语义复核，
立即自动化会把文件名启发式固化成第二份生命周期权威。

完成本次一次性审计后，只有同时满足以下条件才重新评估常规化：

- 至少完成一次上述生命周期/所有权处置，并在另一次独立生命周期事件中确有重复审计需求；
- project/integration机器入口和例外清单能够稳定覆盖手工入口、兼容资产与终态证据，不靠Git时间或
  自由文本`status`猜测；
- 后续两次独立审计以明示的同一互斥规则复现、分别记录规则摘要/identity、保持加法守恒，并实际改变
  了归档、所有权或退役决策；
- 实现复用权威CLOC的同一次by-file结果，不增加第二CLI、常驻生成物或商业软件运行；
- 先作为显式架构/发布审计运行并测量维护收益；是否进入L1必须另行批准，不能由“常规化”自动推出。
