# oa-TOF 项目使用指南（AI 与人类共用）

本目录是独立的 oa-TOF 项目，不是某个“components”分类下的附属部件。当前分析器方案为
正交加速、双级环栈反射镜；离子源、多级杆和电子枪分别属于其他平级项目。

本文件既是入口，也是本项目的知识路由规则。开始任务时先读本文件，再按任务类型选择一份
权威文档；不要默认从COMSOL、SIMION或历史日志开始阅读。

## 固定阅读顺序

1. 所有任务先读[`docs/PROJECT.md`](docs/PROJECT.md)，确认当前参数、正式/候选状态和开放任务。
2. 修改加速器或反射器的时间聚焦、场强、电压或轴向长度时，先读`docs/theory/`中对应推导；
   入口见[`docs/theory/README.md`](docs/theory/README.md)。旧 DOCX 仅为 superseded 历史输入。
3. 操作COMSOL时再读[`docs/COMSOL.md`](docs/COMSOL.md)。
4. 操作SIMION时再读[`docs/SIMION.md`](docs/SIMION.md)。
5. 操作STEP/SolidWorks时再读[`docs/CAD.md`](docs/CAD.md)。
6. 只有追溯旧结论时才进入`docs/history/`；历史文件不能覆盖当前项目结论。

历史入口仅由本文件提供：`docs/history/PROJECT_HISTORY.md`、
`docs/history/SIMION_VALIDATION.md`、`docs/history/SUPERSEDED_RESULTS.md`和
`docs/history/NUMERICAL_VALIDATION_20260716_18.md`、
`docs/history/COMSOL_EXTREME_N_CRASH_20260718_19.md`、
`docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md`、
`docs/history/CANDIDATE_WORKFLOW_VALIDATION_20260720.md`和
`docs/history/20260720__midgrid-candidate-runtime-coverage.md`、
`docs/history/20260720__oatof-theory-refactor-review.md`及
`docs/history/20260721__superseded-theory-docx.md`。四份日常文档不再横向链接历史。

## 本项目的知识边界

知识归属、提升条件和星形引用规则以仓库根[`README.md`](../../README.md)为唯一权威。本项目只补充：
人工设计写入`config/baseline.json`，程序读取自动生成且禁止手改的`config/resolved_geometry.json`；
分析契约、迁移基准和正式闭合结果分别写入`config/analysis_contract.json`、
`config/analysis_baselines.json`和`config/formal_validation.json`。当前统一结论只写`docs/PROJECT.md`。

## 权威入口

- 项目机器身份、能力和成熟度：[`config/project.json`](config/project.json)；它不保存物理参数或取代PROJECT。
- 现有入口可执行范围：[`config/execution_profiles.json`](config/execution_profiles.json)；固定复验入口及
  零变化结构候选入口不等于已实现任意参数优化或性能目标评价。
- 设计变量与当前优化包络：[`config/design_variables.json`](config/design_variables.json)、
  [`config/optimization_envelope.json`](config/optimization_envelope.json)；包络可审查扩大，不等于正式baseline。
- 纯静态候选编译：[`analysis/compile_candidate_design.py`](analysis/compile_candidate_design.py)；只写隔离合同，不运行求解器或CAD。
- 候选消费准备：[`analysis/prepare_candidate_consumers.py`](analysis/prepare_candidate_consumers.py)按
  [`config/candidate_consumers.json`](config/candidate_consumers.json)把同一resolved候选绑定到COMSOL、
  生成SIMION自包含文本，并把CAD输入锁定为该候选的MPH；只证明静态输入路由，不替代运行时门禁。
- 候选运行冻结与排序：[`analysis/prepare_candidate_run.py`](analysis/prepare_candidate_run.py)按
  [`config/candidate_workflow.json`](config/candidate_workflow.json)先在scratch冻结计划，预声明单一run和阶段依赖；
  自动计划不包含晋升，正式baseline与formal在候选期保持只读。
- 候选运行三件套生命周期：[`analysis/candidate_run_lifecycle.py`](analysis/candidate_run_lifecycle.py)；
  从scratch原子启动完整run，冻结request/proposal/baseline/resolved/diff五项输入，并对
  success/failed/interrupted统一写根`summary.json/run_manifest.json`。
- 集成候选执行：[`analysis/run_candidate_workflow.py`](analysis/run_candidate_workflow.py)；顺序调用N=100
  粒子表、COMSOL、SIMION、CAD和结构/合同验收，任何终态均由上述生命周期后端统一收口，不含晋升。
- 设计计划绑定入口：[`analysis/run_bound_candidate_workflow.py`](analysis/run_bound_candidate_workflow.py)；
  只执行同获批request、同run_id且变量属于已验证运行时覆盖的冻结候选计划；当前覆盖为零变化及
  `reflectron_midgrid_voltage`，范围由
  [`config/modes/design_candidate.json`](config/modes/design_candidate.json)限制。
- 人工设计入口：[`config/baseline.json`](config/baseline.json)；程序入口为自动生成的
  [`config/resolved_geometry.json`](config/resolved_geometry.json)，禁止手改。
- 全项目门禁：`verify_project.ps1 -Level Static|Candidate|Formal`。
  `Candidate`用`-CandidateTarget SIMION|COMSOL|CAD`只启动目标软件；COMSOL还需
  `-CandidateModelPath`，CAD需候选装配和导出报告路径。`Formal`单命令包含工具链、正式MPH重开与
  静电Compute、SIMION/CAD/COMSOL资产合同和Python正式分析。
- SIMION正式交付与收敛参考冻结清单：[`config/simion_stable_entry.json`](config/simion_stable_entry.json)。
  它冻结IOB、完整PA家族、Program、Fly2和粒子表的实现身份，不定义或替代统一物理baseline。
- 正式COMSOL生产脚本：
  [`comsol/run_oatof_model.m`](comsol/run_oatof_model.m)（具名参数稳定入口）；底层模型树构建器为
  `comsol/ms_oaTOF_two_stage_ringstack_reflectron.m`，物理组件实现位于同目录`oatof_*.m`模块。
- SIMION正式文本入口：
  [`simion/workbench/formal/oatof_ideal_grounded.lua`](simion/workbench/formal/oatof_ideal_grounded.lua)和
  [`simion/workbench/formal/oatof_ideal_grounded.fly2`](simion/workbench/formal/oatof_ideal_grounded.fly2)
- SIMION正式交付构建：[`simion/workbench/build_formal_delivery.ps1`](simion/workbench/build_formal_delivery.ps1)
- SIMION加速器网格相位诊断：
  [`tests/simion/test_accelerator_grid_phase.ps1`](tests/simion/test_accelerator_grid_phase.ps1)；统一分析为
  [`analysis/analyze_accelerator_grid_phase.py`](analysis/analyze_accelerator_grid_phase.py)。
- CAD正式入口：[`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m)
- 跨求解器门禁：
  [`tests/cross_solver/verify_geometry_contract.ps1`](tests/cross_solver/verify_geometry_contract.ps1)
- 统一分析契约：[`config/analysis_contract.json`](config/analysis_contract.json)
- 当前正式跨求解器验证：[`config/formal_validation.json`](config/formal_validation.json)
- 当前N=1000正式结果与图片：`artifacts/projects/oa_tof/formal/results/`；只包含当前baseline的
  COMSOL/SIMION粒子表、新理论验证、跨求解器峰形/落点/源映射图片、源运行manifest和完整SHA256清单。
- 当前正式发布总清单：`artifacts/projects/oa_tof/formal/asset_manifest.json`；统一关联来源run三件套、
  `config/formal_validation.json`及COMSOL、SIMION、SolidWorks和结果清单，不复制大结果。
- 宽质量标定候选模式：[`config/modes/mass_spectrum.json`](config/modes/mass_spectrum.json)；只评价
  峰位、标定和传输率，不替代正式分辨率基线。
- RF外部handoff功能投影候选：
  [`config/modes/rf_handoff_projection.json`](config/modes/rf_handoff_projection.json)、
  [`analysis/prepare_rf_handoff_projection.py`](analysis/prepare_rf_handoff_projection.py)、
  [`tests/cross_solver/run_rf_handoff_projection.ps1`](tests/cross_solver/run_rf_handoff_projection.ps1)；
  只读复用正式静电资产，恢复部件链时钟，允许记录损失，但不表示电气/机械接口已连接。
- RF混合网格配对投影：[`config/modes/rf_hybrid_mesh_projection.json`](config/modes/rf_hybrid_mesh_projection.json)；
  比较同一RF-COMSOL模型的低成本/参考网格出口状态并选择当前功能链网格，不替代真实连接器。
- RF共享时钟有限脉冲功能入口：[`config/modes/rf_handoff_pulse.json`](config/modes/rf_handoff_pulse.json)、
  [`tests/cross_solver/run_rf_handoff_pulse.ps1`](tests/cross_solver/run_rf_handoff_pulse.ps1)；从Formal Program
  确定性生成隔离候选，按instrument-time从等效入口面注入并连续计算脉冲前后轨迹，不修改Formal资产。
- 未来RF→oa物理接口的双边界及时变合同当前仍由RF项目候选
  [`../rf_quadrupole_collision_cooling/config/rf_to_oatof_interface_candidate.json`](../rf_quadrupole_collision_cooling/config/rf_to_oatof_interface_candidate.json)
  管理并从本项目耦合baseline重算入口上限；本README不复制接口判据。当前动态消费者只允许声明
  投影功能链，真实oa入口、连接器场和有限边沿冻结前不得宣称物理连接，当前影响见
  [`docs/PROJECT.md`](docs/PROJECT.md)。
- 正式跨求解器直接重算与发布入口：
  [`tests/cross_solver/run_formal_validation.ps1`](tests/cross_solver/run_formal_validation.ps1)；发布器只在
  两端达到机器契约样本量、统一比较PASS且当前资产/结果SHA齐全时更新机器契约。
- 耦合纵向baseline的老/新理论与老/新N=1000主比较入口：
  [`tests/cross_solver/run_coupled_baseline_validation.ps1`](tests/cross_solver/run_coupled_baseline_validation.ps1)。
- 三栅加速器时间聚焦参考实现：
  [`analysis/accelerator_time_focus.py`](analysis/accelerator_time_focus.py)
- 二级反射器闭式解参考实现：
  [`analysis/reflectron_dual_stage_solver.py`](analysis/reflectron_dual_stage_solver.py)
- 加速器—反射器整机纵向耦合参考实现：
  [`analysis/oatof_oaaccelerator_coupling.py`](analysis/oatof_oaaccelerator_coupling.py)；已用于当前
  Formal baseline的反射器电压、二级长度、完整释放到探测器时间和时间窗口派生。
- Python参考分析：[`analysis/README.md`](analysis/README.md)
- 路径解析：[`oatof_paths.m`](oatof_paths.m)

## 目录职责

```text
oa_tof/
├─ README.md          # 本文件：项目入口和知识路由
├─ config/            # 跨软件机器参数契约
├─ docs/              # PROJECT/COMSOL/SIMION/CAD、理论推导及只读历史
├─ comsol/            # COMSOL/MATLAB正式生产源码
├─ simion/            # GEM、Lua、Fly2及构建/分析源码
├─ cad/               # COMSOL→STEP→SolidWorks可复现源码
├─ analysis/          # 与求解器无关的轻量分析
└─ tests/             # COMSOL、SIMION、CAD和跨求解器长期门禁
```

大型模型和结果位于工作区同级的`artifacts/projects/oa_tof/`，不进入Git。正式资产进入`formal/`；
候选模型、运行结果和日志统一进入来源`runs/<run_id>/`；冻结证据进入`archive/<archive_id>/`；
临时任务进入`scratch/<task_id>/`。不得重建顶层`models/`、`results/`、`cad/`、`logs/`或旧的
`artifacts/components/...`路径。

## 项目特有硬规则

- COMSOL与SIMION联动时必须使用同一几何、坐标、有效探测面、粒子表和FWHM定义。
- 正式或候选的几何尺寸必须参数化联动，禁止手工移动一个器件后遗漏相关选择集、屏蔽件或探测面。
- SIMION检测器PA是高于飞行管屏蔽罩的GUI可见数值终止层，只表示有效面和口径，不等于机械
  检测器厚度；Lua/Data Recording槽位与GUI优先级必须匹配当前机器契约。
- Program与Data Recording必须同时开启；关闭Program对话框不等于禁用Program。

通用GUI对等、SolidWorks同步、清理和参数单向派生规则不在本项目重复，直接适用根README与
仓库`AGENTS.md`。

## 修改后的最低检查

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tests\cross_solver\verify_geometry_contract.ps1 -SkipRuntime
.\analysis\verify_reference_analysis.ps1
git diff --check
git status --short --branch
```

正式COMSOL、SIMION或SolidWorks入口发生变化时，还必须执行对应软件文档规定的运行时验收。
完整粒子重算和SolidWorks装配重建仍按变更类型及当前机器契约触发，不纳入每次`Formal`身份检查。
