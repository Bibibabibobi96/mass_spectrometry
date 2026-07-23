# RF 四极杆无碰撞传输与碰撞冷却项目

本项目以SIMION 2020自带`examples/quad`为共享硬件模板，验证无背景气体的RF约束与传输、RF+DC
质量过滤和分段杆轴向加速，并保留碰撞冷却为后续模式。各模式当前闭合状态、候选/正式资格和开放任务
只以[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)，确认通用规则和知识路由。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 操作 COMSOL 时读[`docs/COMSOL.md`](docs/COMSOL.md)。
4. 操作 SIMION 时读[`docs/SIMION.md`](docs/SIMION.md)。
5. 只有引入机械正式几何时才读/创建 CAD 文档。

详细验证与S1集成演进记录：
[`docs/history/20260722_rf-validation-and-s1-integration.md`](docs/history/20260722_rf-validation-and-s1-integration.md)；
已关闭的网格策略筛选记录：
[`docs/history/20260722_rf-mesh-strategy-screen.md`](docs/history/20260722_rf-mesh-strategy-screen.md)；
S2–S3连接功能闭环记录：
[`docs/history/20260722__rf-oatof-s2-s3-functional-closure.md`](docs/history/20260722__rf-oatof-s2-s3-functional-closure.md)。
迁移前小样本的传输、质量扫描和轴向加速证据见
[`docs/history/20260723__pre-n100-multipole-functional-evidence.md`](docs/history/20260723__pre-n100-multipole-functional-evidence.md)。

软件细节不相互横向引用；统一参数与跨求解器结论只写入 `PROJECT.md`。

## 权威入口

- 多极杆通用坐标、电压、Mathieu稳定区、碰撞模型和适用边界：仓库根
  [`docs/multipoles/index.md`](../../docs/multipoles/index.md)；该理论包不覆盖本项目当前参数或状态。
- 四、六、八极杆共同消费的运行时坐标、`r0`、RF/DC双极性组电压和配对多质量机制：
  [`../../common/multipole/README.md`](../../common/multipole/README.md)；项目baseline、mode和资格判据仍在本项目。
- 当前具体四极杆项目的机器身份、能力和成熟度：[`config/project.json`](config/project.json)；多级杆设计族不在本项目内虚构子项目。
- 现有入口可执行范围和组合命令链：[`config/execution_profiles.json`](config/execution_profiles.json)。
- 历史人工几何输入：[`config/baseline.json`](config/baseline.json)；它只服务尚未迁移的理论与分析
  检查，不是求解器运行时权威。
- Phase 2求解器无关设计入口：
  [`config/requests/baseline.json`](config/requests/baseline.json)冻结当前四极杆身份、几何、接口、
  五个数值驱动量和分段参考；[`config/design_variables.json`](config/design_variables.json)与
  [`config/optimization_envelope.json`](config/optimization_envelope.json)只声明候选编译范围，不改写
  当前baseline，也不授权求解器或CAD运行。
- Phase 4治理入口：[`config/design_profiles.json`](config/design_profiles.json)把完整request、适用变量
  目录、优化包络、SHA-256和拓扑身份绑定为命名profile。
- 程序统一入口：[`config/resolved_design_official.json`](config/resolved_design_official.json)，由
  `analysis/resolve_contract.py`委托公共治理编译器生成，禁止手改。
- MATLAB/COMSOL 契约加载器：[`load_rf_quadrupole_contract.m`](load_rf_quadrupole_contract.m)；
  SIMION GEM 发布器：[`analysis/sync_simion_geometry.py`](analysis/sync_simion_geometry.py)。两者都只消费
  `resolved_design_official.json`，GEM 是生成文件，禁止作为第二参数源手改。
- 当前活动resolved发布统一字段语义：器件几何只读`geometry_mm`及其`rod_array`、`enclosure`，接口面只读
  `interfaces_mm`，RF/DC只读`drive`，静态端电极只读`static_electrodes_V`，粒子初值只读
  `particle_source`或冻结的canonical CSV。运行mode只保留数值设置与验收门槛，不得覆盖这些物理字段。
- 官方粒子源：[`config/official_particle_source.json`](config/official_particle_source.json)
- 当前传输模式：[`config/modes/transport_no_collision.json`](config/modes/transport_no_collision.json)
- 轴向加速模式：[`config/modes/axial_acceleration_reference.json`](config/modes/axial_acceleration_reference.json)；
  当前实现已迁移到仓库统一粒子数合同；两类轴向加速已通过四、六、八极杆双求解器N=100功能复验，
  但不代表参数优化、数值等价或机械资格。
- 集成就绪profile与官方传输共用
  [`config/resolved_design_official.json`](config/resolved_design_official.json)；执行
  `analysis/resolve_contract.py --profile interface`会复核同一publication。旧interface publication仅为迁移期
  保留文件，不是活动消费者入口。
- 求解器无关相空间接口：[`config/interface_contract.json`](config/interface_contract.json)
- `particle_state.csv`的列、枚举和平面语义只以上述接口契约为准；
  仓库公共校验器[`../../common/contracts/particle_state.py`](../../common/contracts/particle_state.py)运行时读取该契约，
  不维护第二份列名或枚举。
- 集成就绪粒子族与模式：[`config/interface_readiness_particle_source.json`](config/interface_readiness_particle_source.json)、
  [`config/modes/transport_interface_readiness.json`](config/modes/transport_interface_readiness.json)
- 命名粒子表生成器：[`analysis/generate_interface_particle_table.py`](analysis/generate_interface_particle_table.py)，
  用固定种子生成任意 N 的可追溯 ION 表与元数据；求解器不得各自随机生成接口粒子。
- 质量过滤模式：[`config/modes/mass_filter_reference.json`](config/modes/mass_filter_reference.json)；与RF-only
  传输共用同一几何源，仅切换RF+DC运行合同。
- 求解器无关四极杆 L0 参考计算：[`analysis/quadrupole_l0.py`](analysis/quadrupole_l0.py)；只校验理想
  Mathieu 稳定区、质量尺度和预留模式的电压合同，不证明质量峰、透过率或求解器资格。
- 求解器无关有限长度 L1 功能扫描：[`analysis/run_mass_filter_l1.py`](analysis/run_mass_filter_l1.py)；使用
  当前79.6 mm杆长、4 mm场半径和官方源包络，输出质量响应、规范图和run三件套。它证明同一几何能
  形成理论一致的通带，但不包含边缘场，也不替代COMSOL/SIMION Candidate资格。
- COMSOL 候选生产入口：[`comsol/ms_rf_quadrupole_no_collision.m`](comsol/ms_rf_quadrupole_no_collision.m)
- 旧`comsol/ms_rf_quadrupole_collision_cooling.m`现为拒绝执行的兼容短桩；其150 mm旧几何、硬编码
  连接和未验证碰撞模型不得恢复为当前入口。未来碰撞模式必须从共享契约重新建立。
- SIMION 几何入口：[`simion/geometry/quad_monolithic.gem`](simion/geometry/quad_monolithic.gem)
- SIMION RF-only/RF+DC程序：[`simion/programs/quad_transport.lua`](simion/programs/quad_transport.lua)
- COMSOL RF-only构建/GUI复验入口：[`tests/comsol/run_transport_candidate.ps1`](tests/comsol/run_transport_candidate.ps1)；
  RF+DC七质量功能入口：[`tests/comsol/run_mass_filter_candidate.ps1`](tests/comsol/run_mass_filter_candidate.ps1)，
  使用配对源输出L0/L1/SIMION/COMSOL比较CSV与规范图，仅中心质量保存一份MPH。
- SIMION 构建/验证入口：[`tests/simion/run_transport_candidate.ps1`](tests/simion/run_transport_candidate.ps1)
 ；同一入口的`mass_filter_reference`模式生成配对七质量表并输出质量响应CSV、指标JSON和规范图。
- SIMION IOB 结构门禁：[`tests/simion/inspect_builtin_quad_reference.lua`](tests/simion/inspect_builtin_quad_reference.lua)
- 跨求解器门禁：[`tests/cross_solver/verify_transport_candidate.ps1`](tests/cross_solver/verify_transport_candidate.ps1)
- 全项目门禁：`verify_project.ps1 -Level Static|Candidate|Formal`；Candidate必须显式给出 mode、COMSOL、
  SIMION和比较运行标签，Formal在机械几何与SolidWorks同步前固定拒绝执行。
- 历史诊断图源码：
  [`analysis/plot_terminal_distribution.py`](analysis/plot_terminal_distribution.py)、
  [`analysis/plot_transport_trajectory_diagnostics.py`](analysis/plot_transport_trajectory_diagnostics.py)、
  [`analysis/plot_transport_phase_diagnostics.py`](analysis/plot_transport_phase_diagnostics.py)。三者没有现行
  managed-run入口，只用于重建历史图；新的证据必须由绑定manifest、frame与clock epoch的managed runner生成。
- 场分辨率收敛：[`tests/simion/test_pa_field_convergence.ps1`](tests/simion/test_pa_field_convergence.ps1)、
  [`analysis/compare_field_resolution_convergence.py`](analysis/compare_field_resolution_convergence.py)
- 杆内释放诊断：[`analysis/compare_internal_release.py`](analysis/compare_internal_release.py)
- 边缘定位、接口差异评估与oa-TOF集成门禁：
  [`analysis/assess_interface_integration_gate.py`](analysis/assess_interface_integration_gate.py)
- 通用部件链时钟、RF→oa-TOF候选投影合同与派生器：
  [`config/rf_to_oatof_handoff.json`](config/rf_to_oatof_handoff.json)、
  [`analysis/build_oatof_handoff.py`](analysis/build_oatof_handoff.py)。该合同现已被S2/S3物理链取代为
  活动入口，只保留旧刚体投影、时钟适配回归和历史run复现；完整状态包语义仍可追溯，但不得把该旧入口
  的projection PASS解释为当前物理连接器资格。
- RF→oaTOF活动物理接口由共享物理端口合同、内部S2被动连接器步骤和单一S3累积入口组成：
  [`config/rf_to_oatof_interface_stages.json`](config/rf_to_oatof_interface_stages.json)、
  [`config/rf_to_oatof_shared_physical_port_joint_geometry.json`](config/rf_to_oatof_shared_physical_port_joint_geometry.json)、
  [`config/rf_to_oatof_s2_passive_connector.json`](config/rf_to_oatof_s2_passive_connector.json)、
  [`tests/comsol/run_s2_passive_connector_field.ps1`](tests/comsol/run_s2_passive_connector_field.ps1)及
  [`tests/cross_solver/run_s3_cumulative_chain.ps1`](tests/cross_solver/run_s3_cumulative_chain.ps1)。共享合同是孔、
  局部域和场基的唯一活动权威；S2只作为S3内部的无脉冲连接器求解步骤，不再提供独立build-only或审计入口。
  当前1 mm功能证据为`100→61→31→31→7`，0 mm兼容证据为`100→77→39→39→9`；两者均不授权阶段资格、
  网格收敛、分辨率或Formal声明。
- 脉冲调度与快照使用阶段中性的共享实现：
  [`analysis/derive_shared_centroid_pulse_time.py`](analysis/derive_shared_centroid_pulse_time.py)和
  [`analysis/plot_shared_pulse_geometry_snapshot.py`](analysis/plot_shared_pulse_geometry_snapshot.py)。调度按显式
  `mass_amu + charge_state`选择目标物种，并以实际入口时刻和三维速度求质心到达oa理想源中心的共享时刻。
- RF→oaTOF空间注册只发布活动S2装配：
  [`analysis/resolve_spatial_registration.py`](analysis/resolve_spatial_registration.py)生成并校验
  [`config/resolved_rf_to_oatof_s2_spatial_registration.json`](config/resolved_rf_to_oatof_s2_spatial_registration.json)。
  发布保存来源SHA-256、组件pose、唯一相对变换和电气标量绑定；COMSOL只消费冻结发布。
- S3脉冲前同ID checkpoint仍是来源run的只读派生诊断：
  [`analysis/analyze_rf_oatof_checkpoints.py`](analysis/analyze_rf_oatof_checkpoints.py)及
  [`tests/analysis/run_rf_oatof_checkpoint_diagnostic.ps1`](tests/analysis/run_rf_oatof_checkpoint_diagnostic.ps1)。
  它冻结共享物理端口合同、S2 registration、oa baseline和来源状态，不维护第二套几何或坐标权威。
- 已退役阶段的叙事只见
  [`docs/history/20260722_rf-validation-and-s1-integration.md`](docs/history/20260722_rf-validation-and-s1-integration.md)；
  已生成run仍保留在工作区`artifacts/`，但都不是活动导入、路径或入口。
- RF入口能量匹配候选：[`config/rf_to_oatof_energy_match_candidate.json`](config/rf_to_oatof_energy_match_candidate.json)、
  [`analysis/validate_rf_energy_match.py`](analysis/validate_rf_energy_match.py)及
  [`analysis/compare_rf_input_energy.py`](analysis/compare_rf_input_energy.py)；它用独立命名的100 amu、5 eV
  入射工况保持几何、RF和其他逐粒子源变量不变，不覆盖2 eV官方回归源，也不在handoff重写速度；
  通过能量合同、运行配置和manifest身份校验后，该模式可作为现有canonical交接转换器的显式候选来源。
- RF连续接地屏蔽候选：
  [`config/rf_continuous_grounded_shield_candidate.json`](config/rf_continuous_grounded_shield_candidate.json)及
  [`analysis/validate_rf_continuous_shield.py`](analysis/validate_rf_continuous_shield.py)；现有COMSOL/SIMION
  参考几何没有贯穿杆区的接地侧壁，故先独立扫描同轴圆柱内半径，再恢复局部联合场。圆柱尺寸不由oa外壳
  决定，未完成RF场、传输和馈通审查前不修改Formal资产。二维执行入口为
  [`tests/comsol/run_rf_continuous_shield_2d.ps1`](tests/comsol/run_rf_continuous_shield_2d.ps1)，当前只把
  `19.776/26.368 mm`保留到三维验证，没有选定物理半径。三维分析合同已冻结为杆中段—出口多截面
  谐波和`Ex/Ey/Ez`诊断；三份场运行已完成，出口中心区网格变化仍大于半径效应，现只允许同一最小
  半径的N=100配对网格敏感度诊断，仍不允许选择壳体或声明连接完成。
- 场到粒子性能的分阶段实验：
  [`config/rf_to_oatof_field_performance_experiment.json`](config/rf_to_oatof_field_performance_experiment.json)及
  [`analysis/validate_field_performance_experiment.py`](analysis/validate_field_performance_experiment.py)；保持一个
  当前Formal baseline，按E0场诊断、E1连接专用数值验证、E2 N=100无oa脉冲筛选、E3 N=1000完整
  脉冲/分辨率确认和E4相位、公差、跨软件鲁棒性顺序执行。
- oa入口孔L0上限参考：[`analysis/entry_aperture_l0.py`](analysis/entry_aperture_l0.py)；从当前耦合
  oa baseline重算上限并失败关闭候选，适用结论和未决约束见[`docs/PROJECT.md`](docs/PROJECT.md)。
- 路径解析：[`rf_quadrupole_paths.m`](rf_quadrupole_paths.m)

大型 MPH、PA、IOB、Fly2 输出和图像一律放在
`artifacts/projects/rf_quadrupole_collision_cooling/`，不进入 Git。历史 `test3` 仅保留在
artifact archive，不能作为候选或正式基线。

## 目录职责

```text
rf_quadrupole_collision_cooling/
├─ config/                       # 人工源配置、解析发布、模式和运行模板
├─ analysis/                     # 契约解析、校验、比较和诊断工具
├─ docs/                         # PROJECT、COMSOL、SIMION；需要时才建history/CAD
├─ comsol/                       # MATLAB LiveLink 生产实现
├─ simion/                       # 生成GEM、Lua和Fly2/PA构建入口
├─ tests/                        # COMSOL、SIMION、跨求解器复验入口
├─ load_rf_quadrupole_contract.m # MATLAB解析契约加载器
├─ rf_quadrupole_paths.m         # 工作区与artifact路径解析
└─ verify_project.ps1            # Static/Candidate/Formal统一门禁
```

三层门禁职责固定如下；高层包含低层，不互相替代：

| 层级 | 回答的问题 | 当前状态 |
|---|---|---|
| Static | 源配置与解析发布是否同步、GEM是否同步、固定粒子表、四极杆L0理论/电压合同、质量过滤L1合同、静态投影及双边界draft合同、分析测试和PowerShell入口语法是否通过 | 可执行 |
| Candidate | 指定mode的两份成功manifest、统一事件表和跨求解器功能指标是否通过 | 可执行；接口N=100已有有效FAIL证据 |
| Formal | 机械正式几何、SolidWorks装配与求解器资产是否同任务同步并复验 | 固定阻断，直到正式机械几何被选定 |

`transport_no_collision`与`transport_interface_readiness`共享硬件和RF-only基础物理，但运行目录、输出文件
和比较报告按mode隔离。接口mode还必须显式给出不少于100行的粒子表和RF峰值，不能靠遗留小样本默认值伪装成
接口候选。隔离规则落地前已经存在的接口运行可由跨求解器门禁只读复验；门禁仍检查其run config中的
真实mode，不要求重跑，也不再向旧路径写入新结果。

## 项目特有硬规则

- 两求解器必须从 `config/` 的共享几何、粒子源与 mode 契约派生同一输入；无碰撞基线不得创建或启用任何碰撞/阻尼模型。
- 参数链固定为 `baseline + source + mode + interface -> resolved -> COMSOL/SIMION生成资产`；四极杆与
  六、八极杆共同调用`common/multipole/round_rod_geometry.py`和`interface_geometry.py`，项目不得再按
  `0/90/180/270°`自行派生正式杆坐标。安装目录中的
  SIMION官方例程只提供来源依据，不再是运行时权威；任何下游硬编码或反向抄写都视为失效实现。
- 官方回归与集成就绪验证严格分离：不得覆盖活动`official_fixed_100.ion`或借新增工况改写已冻结运行；
  迁移前小N结果只在历史运行中保留。
- 所有run config都同时记录共享硬件解析发布和本次mode解析发布；接口mode是对已闭合RF-only基础物理的
  资格叠加，不得隐式继承未记录的运行参数。
- 新运行只以统一`particle_state.csv`、`summary.json`、稀疏轨迹和manifest为权威结果；不再生成旧版
  solver-specific粒子终点表。每份manifest在比较前必须重新计算全部文件哈希。
- 部件交接面、杆端诊断面和独立传输检测面必须分别读取接口机器契约，不得相互替代。
- 跨部件时间不得在求解器边界丢失：状态包累计全局仪器时间、谱系年龄、当前粒子年龄和末组件耗时；静态求解器可在
  保留逐粒子时间映射时使用局部零时刻；状态包还须区分根源粒子谱系年龄与当前粒子年龄，时变场必须
  消费全局时间或严格等价的时钟/相位偏移。
- 机械正式资格适用根README的SolidWorks同步门禁；当前项目状态只查PROJECT。
- 集成仪器中，传输四极杆和质量过滤四极杆是同一硬件模板的两个实例；共享几何/粒子接口，分别绑定 mode 配置和空间变换，不复制成两套几何源。

通用GUI对等、参数单向派生、产物清理和SolidWorks同步规则直接适用根README与仓库`AGENTS.md`。
