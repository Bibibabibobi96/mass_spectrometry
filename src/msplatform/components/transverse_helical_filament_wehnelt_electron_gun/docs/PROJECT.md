# 横置螺旋灯丝Wehnelt电子枪当前状态

## C 生命周期切片：build-only 注册链接管 Store（2026-11-28）

`wehnelt_build_only_smoke`现由注册profile直接编译为`python -m msplatform.cli wehnelt-build-only`。
组合根消费带逐项身份的编译输入，加载显式`ExecutionContext`并构造调用者选择的`ArtifactStore`，随后
直接调用`msplatform.backends.comsol.build_wehnelt_model`。科学baseline、numerical modes、resolved
和mode的身份与canonical freshness均在商业启动前复核；真实operation继续由原`model_execution`和
`run_managed_stage`完成资源冻结、来源保护、native build/cold-verify、成功或失败发布及恢复。

旧`wehnelt_build_only.ps1`、`build_wehnelt_build_only_task.m`和
`write_wehnelt_build_only_report.m`已退出活动树；不再保留`New-RunPackage`、多次手工checkpoint、
旧success/failed writer或`ResumeFinalization`旁路。三个科学MATLAB阶段、原MPH文件名、显式电子入口
数量和build-only不求解边界未改变。新run只进入显式Store，不改写旧组件run或历史资格。

本轮只执行源码、注册、输入正负例及惰性native的Store owner回归，未启动MATLAB/COMSOL，未新增原生、
GUI、Candidate或Formal资格。共享门禁目录中已删除旧报告资源的精确路由仍需主线统一移除。

## C1 电子质量单位一致性修正（2026-11-27）

当前唯一质量数据为`electron_mass_codata2022_repository_u_v1`：kg值沿用[NIST CODATA 2022电子质量](https://physics.nist.gov/cgi-bin/cuu/Value?me)的`9.1093837139e-31 kg`，u值由仓库现有`1.66053906660e-27 kg/u`推导为`0.0005485799098091511 u`。此前`0.0005485799090441 u`使用2022 u，与仓库冻结2018质量单位不一致。本轮修正活动baseline/profile及由resolver生成的resolved模型；质量数据version与SHA随输入冻结，baseline/resolved身份改变，旧输入不得误作当前缓存。原科学run/历史数据原字节保留，未重跑COMSOL，未新增热发射或轨迹科学资格。

唯一值由`contracts.particle_physics`加载`physics/data/electron.json`；kg↔u不再各自指定。冻结包由模块的具名数据声明包含JSON，缺件/篡改失败关闭。以下此前所有权迁移的参数不变与逐字相同说明记录当时阶段；不覆盖本轮明确单列的数值修正。

活动实现、科学配置、当前文档和长期测试已迁出 `projects/transverse_helical_filament_wehnelt_electron_gun/`；该旧树不再存在。规范owner为本组件目录，来源固定为`7c272feb442945b2a415e1673a760e66ae098243`。该次仅迁移源码所有权和路径；当时的科学参数、build-only边界、来源哈希、防缺件／篡改、失败释放及资格状态不变。当前注册生命周期见上节。

迁移后的公开Static入口通过49个父测试（183条outcome，53秒）和Ruff；真实operation、能力查询及编译输入定向套件通过6个父测试（10条outcome，4秒）。纯MATLAB合同20项通过（15秒），未启动COMSOL或执行求解。五份科学／身份JSON与来源SHA-256逐字一致；完整编译、wheel/sdist和全活动文档仍待其他并行迁移与共享registry／gate收口，不把其共享失败归因于本组件或原生模型。

The project verifier now loads the installed execution lease resource with an explicit HostContext. Callers must select Python through `-PythonExe` or `SIMULATION_PYTHON_EXE`; the verifier no longer assumes a checkout `.venv`. Contract checks, tests and scientific behavior are unchanged.

本文件是项目当前事实、资格与开放任务的唯一权威。COMSOL实现见[`COMSOL.md`](COMSOL.md)；选型依据
和旧实验见[`../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/PROJECT_HISTORY.md`](../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/PROJECT_HISTORY.md)；2026-07-28以前的完整runner
故障与修复时间线冻结在
[`../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/20260728__pre-document-consolidation-project.md`](../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/20260728__pre-document-consolidation-project.md)。

Current Wehnelt inputs and run records no longer carry `candidate_evidence_allowed`,
`formal_performance_claim_allowed` or `formal_gate_passed`. Build-only execution facts, particle-count minima and
actual asset-modification facts remain explicit; existing frozen inputs and historical manifests are not rewritten.

## 当前基线

当前物理基线为5匝横置螺旋钨丝、2700 K热发射的Wehnelt电子枪，面向EI离子源的电子利用率，不声明
成像级轴对称束斑。活动源码链为：

1. [`phase1_geometry_coil_transverse.m`](../../../../../src/msplatform/backends/comsol/matlab/phase1_geometry_coil_transverse.m);
2. [`phase2_electrostatics_coil_transverse.m`](../../../../../src/msplatform/backends/comsol/matlab/phase2_electrostatics_coil_transverse.m);
3. [`phase4_thermal_emission_coil_transverse.m`](../../../../../src/msplatform/backends/comsol/matlab/phase4_thermal_emission_coil_transverse.m).

机器参数链为`config/baseline.json + config/numerical_modes.json →
msplatform.components.transverse_helical_filament_wehnelt_electron_gun.resolve_contract →
config/resolved_model.json`。唯一解析与派生几何实现位于安装包组件；电子质量、电荷与元电荷常量直接来自
`msplatform.contracts.particle_physics`。MATLAB只消费resolved并绑定GUI参数，不从源码、环境或旧MPH回退物理值。
build-only入口冻结实际MATLAB、解析器与公共运行依赖；源码闭包回归只证明准备与身份链，
不构成新的COMSOL求解或功能资格。运行与失败收尾见[COMSOL说明](COMSOL.md)。

公共预算观测的冷加载回归同时执行入口已有的规范核心及包资源选择器，再从冻结资源加载唯一实现；
不再把旧公共桥的文件位置当作函数正文位置。显式公共表不再重复登记已由整包选择覆盖的host policy、
machine contracts和recorded removal；回归按实际目的路径拒绝任何重复，同时保持严格校验。该定向软件验证通过，
生产选择器与物理输入未改变，未启动MATLAB或COMSOL。
The retired naming/input adapters now come only from the canonical package selector. Bootstrap
identity checks use their exact frozen relative paths, without duplicate manifest entries; the
existing real-selector test and changed-bootstrap negative test retain these guarantees.
Changed routing now selects the original EI/Wehnelt project owners and existing
common model/capability behavior suites for Python and MATLAB implementation
changes; native freezing/resource registration also selects ordinary installation.
Two planner tests, nine managed model tests and fourteen capability tests passed.
This is build-only software selection evidence, with no Compute, GUI or new
scientific qualification.
Manifest publication and verification are likewise frozen only by the canonical
package selector. Their separate live-bootstrap identities and frozen-path hash
checks remain; duplicate common-table entries are removed. The unchanged full
MATLAB contract-binding module passed 27 parents (157 records) in 29.724 seconds,
including the real-selector duplicate-destination regression. This is software
freezing evidence, with no MATLAB or COMSOL execution or new model qualification.
The explicit archive input now names `src/msplatform/execution/artifact_identity_archive.py`;
its original frozen-freshness method passed in 18.094 s without changing the declared input set.
实心阴极与轴向线圈源码已冻结到
[`../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/20260713__pre-transverse-wehnelt-lineages.md`](../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/20260713__pre-transverse-wehnelt-lineages.md)。

The former registered PowerShell task and text-report adapter are retired. The current registered CLI and Store-aware owner retain the three MPH outputs and build/cold-verify acceptance without adding native qualification.

## Installed implementation migration

The installed builders require explicit resolved-contract and owner-run paths.
They retain the original geometry, mesh, ES/CPT configuration, intermediate MPH
filenames, full-mode science and negative electron charge/mass. The project copies
and `egun_paths` are retired. One canonical table supplies all 41 GUI bindings to
the setter and independent read-only verification; cold verification never repairs
saved values. The MATLAB `build_wehnelt_model` wrapper retains all three stage
reports. The Python operation shares the existing managed-owner/launcher execution
implementation with EI, with explicit scientific inputs and engineering policy.

Integrated software validation passed 47 parents (197 outcome records) in 47.923
seconds, including the original binding/freezer checks and both model operations'
owner success/failure paths. All 20 pure MATLAB cases passed in 0.5630784 seconds.
Ordinary wheel/sdist acceptance passed five parents in 127.916 seconds. Original
builder bodies and the parameter table/formatting are preserved after explicit
signature/path wiring and trailing-newline normalization.

Ordinary-wheel native run `20261109_164018__build__comsol__wehnelt-model-972f8cf52b6d`
saved the original three-stage chain (751,590 / 15,624,994 / 15,788,416 bytes) and
reopened the final model in a separate COMSOL process. It confirmed four physical
domains, a complete mesh, the original study/solver trees, empty solution data,
electron mass and charge −1, requested inlet count 3, Thermal distribution and
Freeze walls. All three MPH identities were unchanged across cold verification.
All 343 installed files matched the accepted wheel; all 104 loaded package origins
were in its fresh site-packages. Both observed operations exited zero and released
host leases; the owner published a complete unsolved `prepared_model` with writers
stopped. No field/particle solving, current/efficiency, GUI or new Candidate/Formal
qualification is claimed.

Exact P4 source `2026e814` also passed build/save/cold-reopen in
`20261116_191003__build__comsol__wehnelt-model-fcb9ebf30f2b` (145.709 seconds
including admission). The three MPH files are 751,606 / 15,625,008 / 15,788,430
bytes with respective SHA-256 values
`28411949FAD50C64854B05199E4074EE3695BE93CE6F1AE6E1D5C899D5CC2043`,
`16F604C47006631F6677491E8B981FFDD4FE91CE46D20E0F937D57AD81036324` and
`E864FEC21BCB47803BD19814F21B8B899A617E3CAFC92E1785B1ED9F375D6A35`.
Cold reopen retained four physical domains, complete mesh, original Study/Solver
trees, empty solutions, electron mass/charge −1, three inlets, Thermal emission
and Freeze walls, with zero Compute and no model rewrite. Independent hashes
matched publication, writers stopped and both COMSOL leases released. This
closes only the current-source build-only scope, not functional or scientific
qualification.

## 资格状态

| 层级 | 当前证据 | 状态 |
|---|---|---|
| Static | 合同、resolver、MATLAB绑定和项目门禁 | PASS |
| build-only | 真实R2025b/COMSOL 6.4三阶段构建，冻结输入与manifest闭合 | PASS |
| 功能粒子求解 | `functional_reference`尚未注册或运行 | NOT RUN |
| Candidate | 无受治理N≥100功能证据 | BLOCKED |
| Formal | 旧MPH早于现行合同，最终CPT未完成现行GUI Compute | BLOCKED |

当前闭合build-only证据只证明几何、网格、静电/CPT模型树、电子质量/电荷、`Freeze`壁面和GUI参数
绑定；没有运行静电或粒子求解器。旧34.18%收集效率是历史结果，不能作为当前性能结论。

## 当前物理与实现限制

- baseline是电子species、质量、电荷、发射分布、材料身份和终态语义的唯一权威。
- 钨只表示材料身份；尚未建立Richardson发射率或真实束流，测试粒子不支持`beam_current`声明。
- COMSOL默认随机采样seed尚未冻结，当前单次粒子实现不可复现。
- 非有限末态只能报告为未分类，不得推断为灯丝或Wehnelt自吸收。
- 横置Wehnelt参数扫描尚未建立；旧phase5属于轴向灯丝，只支持非单调性的历史假设。

## 开放任务

1. 为`functional_reference`建立受治理的N=100运行器，冻结可复现母样本、seed、逐粒子身份、终态和
   完备损失分类；建立真实收集面/穿越事件后才允许定义收集效率。
2. 在功能run中形成完整run config、summary、manifest与资产SHA，并重开最终CPT模型完成GUI
   Study Compute；通过前不得进入Candidate评审。
3. 只有下游设计明确需要时才建立横置谱系参数扫描或EI源接口合同；不得复用轴向phase5的具体最优值。

## 产物边界

当前没有通过现行门禁的Formal资产。旧模型、结果与谱系按原manifest身份只读保存在
`artifacts/components/transverse_helical_filament_wehnelt_electron_gun/archive/20260801_130004__migration-snapshot__repo__wehnelt-electron-gun/legacy-project-root/`；
不改写、不追加新run，也不改变原资格和声明边界。新build-only运行只进入调用者显式选择的
ArtifactStore，其run布局、来源保护、保留和恢复遵循[生命周期](../../../../../docs/LIFECYCLE.md#新参考链-artifactstore)；
旧组件根不是新Store的隐式回退。

## 构建准入与软件验证

普通build-only编译结果固定baseline、numerical_modes、resolved_model及build-only mode，经
`--compiled-inputs`交给真实公共CLI，不再选择当前默认或调用旧runner。适配器验证逐项文件身份并调用
canonical resolver比较完整resolved；缺件、重复、路径漂移、字节篡改和过期输入均失败关闭。科学输入
不包含checkout测试、仓库门禁工具或`pyproject.toml`。

实际native资源继续由`model_execution`的现有freezer从所选安装包取得，由run owner登记和保护。
profile的`action=build`且科学结果未评价；`wehnelt_verify.ps1`继续独立验证软件。真实owner回归同时
覆盖成功产品与原生异常后的failed manifest，证明注册链没有第二发布者；这些惰性native结果不构成
商业构建、求解、GUI或Candidate／Formal资格。

## 机器能力与解析输入

build-only profile传入本次解析输入，现有Store-aware owner冻结和保护实际执行输入；普通物理工作流
不默认包含整套Static。能力查询与执行编译见[公共合同](../../../../../tools/repository/README.md#执行dry-run)；
READY仅描述声明条件，不证明部署、许可、原生构建或科学验收已经通过。
