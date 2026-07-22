# RF 四极杆无碰撞传输与碰撞冷却项目

本项目以SIMION 2020自带`examples/quad`为共享硬件模板，验证三种运行模式：无背景气体的RF
约束与传输、RF+DC质量过滤，以及后续碰撞冷却。各模式当前闭合状态、候选/正式资格和开放任务
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
[`docs/history/20260722_rf-mesh-strategy-screen.md`](docs/history/20260722_rf-mesh-strategy-screen.md)。

软件细节不相互横向引用；统一参数与跨求解器结论只写入 `PROJECT.md`。

## 权威入口

- 多极杆通用坐标、电压、Mathieu稳定区、碰撞模型和适用边界：仓库根
  [`docs/multipoles/index.md`](../../docs/multipoles/index.md)；该理论包不覆盖本项目当前参数或状态。
- 当前具体四极杆项目的机器身份、能力和成熟度：[`config/project.json`](config/project.json)；多级杆设计族不在本项目内虚构子项目。
- 现有入口可执行范围和组合命令链：[`config/execution_profiles.json`](config/execution_profiles.json)。
- 共享几何契约：[`config/baseline.json`](config/baseline.json)
- 程序统一入口：[`config/resolved_geometry.json`](config/resolved_geometry.json)，由
  `analysis/resolve_contract.py`生成，禁止手改；它只代表官方回归profile。
- MATLAB/COMSOL 契约加载器：[`load_rf_quadrupole_contract.m`](load_rf_quadrupole_contract.m)；
  SIMION GEM 发布器：[`analysis/sync_simion_geometry.py`](analysis/sync_simion_geometry.py)。两者都只消费
  `resolved_geometry.json`，GEM 是生成文件，禁止作为第二参数源手改。
- 官方粒子源：[`config/official_particle_source.json`](config/official_particle_source.json)
- 当前传输模式：[`config/modes/transport_no_collision.json`](config/modes/transport_no_collision.json)
- 集成就绪解析入口：[`config/resolved_interface_readiness.json`](config/resolved_interface_readiness.json)，
  由`analysis/resolve_contract.py --profile interface`生成，禁止手改。
- 求解器无关相空间接口：[`config/interface_contract.json`](config/interface_contract.json)
- `particle_state.csv`的列、枚举和平面语义只以上述接口契约为准；
  [`analysis/verify_particle_state_contract.py`](analysis/verify_particle_state_contract.py)运行时读取该契约，
  不维护第二份列名或枚举。
- 集成就绪粒子族与模式：[`config/interface_readiness_particle_source.json`](config/interface_readiness_particle_source.json)、
  [`config/modes/transport_interface_readiness.json`](config/modes/transport_interface_readiness.json)
- 命名粒子表生成器：[`analysis/generate_interface_particle_table.py`](analysis/generate_interface_particle_table.py)，
  用固定种子生成任意 N 的可追溯 ION 表与元数据；求解器不得各自随机生成接口粒子。
- 预留质量过滤模式：[`config/modes/mass_filter_reference.json`](config/modes/mass_filter_reference.json)
- 求解器无关四极杆 L0 参考计算：[`analysis/quadrupole_l0.py`](analysis/quadrupole_l0.py)；只校验理想
  Mathieu 稳定区、质量尺度和预留模式的电压合同，不证明质量峰、透过率或求解器资格。
- COMSOL 候选生产入口：[`comsol/ms_rf_quadrupole_no_collision.m`](comsol/ms_rf_quadrupole_no_collision.m)
- 旧`comsol/ms_rf_quadrupole_collision_cooling.m`现为拒绝执行的兼容短桩；其150 mm旧几何、硬编码
  连接和未验证碰撞模型不得恢复为当前入口。未来碰撞模式必须从共享契约重新建立。
- SIMION 几何入口：[`simion/geometry/quad_monolithic.gem`](simion/geometry/quad_monolithic.gem)
- SIMION 传输程序：[`simion/programs/quad_transport.lua`](simion/programs/quad_transport.lua)
- COMSOL 构建/GUI复验入口：[`tests/comsol/run_transport_candidate.ps1`](tests/comsol/run_transport_candidate.ps1)
- SIMION 构建/验证入口：[`tests/simion/run_transport_candidate.ps1`](tests/simion/run_transport_candidate.ps1)
- SIMION IOB 结构门禁：[`tests/simion/inspect_builtin_quad_reference.lua`](tests/simion/inspect_builtin_quad_reference.lua)
- 跨求解器门禁：[`tests/cross_solver/verify_transport_candidate.ps1`](tests/cross_solver/verify_transport_candidate.ps1)
- 全项目门禁：`verify_project.ps1 -Level Static|Candidate|Formal`；Candidate必须显式给出 mode、COMSOL、
  SIMION和比较运行标签，Formal在机械几何与SolidWorks同步前固定拒绝执行。
- 终点分布诊断图：[`analysis/plot_terminal_distribution.py`](analysis/plot_terminal_distribution.py)
- 轴向轨迹诊断图：[`analysis/plot_transport_trajectory_diagnostics.py`](analysis/plot_transport_trajectory_diagnostics.py)
- 相位--轨迹差诊断图：[`analysis/plot_transport_phase_diagnostics.py`](analysis/plot_transport_phase_diagnostics.py)
- 场分辨率收敛：[`tests/simion/test_pa_field_convergence.ps1`](tests/simion/test_pa_field_convergence.ps1)、
  [`analysis/compare_field_resolution_convergence.py`](analysis/compare_field_resolution_convergence.py)
- 杆内释放诊断：[`analysis/compare_internal_release.py`](analysis/compare_internal_release.py)
- 边缘定位、接口差异评估与oa-TOF集成门禁：
  [`analysis/assess_interface_integration_gate.py`](analysis/assess_interface_integration_gate.py)
- 通用部件链时钟、RF→oa-TOF候选投影合同与派生器：
  [`config/rf_to_oatof_handoff.json`](config/rf_to_oatof_handoff.json)、
  [`analysis/build_oatof_handoff.py`](analysis/build_oatof_handoff.py)。合同当前是禁止打包的draft；完整状态包
  保存全局仪器时间和粒子谱系，11列ION只是当前静电oa-TOF消费者的派生输入。
- 双边界、时变兼容的物理接口候选：
  [`config/rf_to_oatof_interface_candidate.json`](config/rf_to_oatof_interface_candidate.json)、
  [`analysis/build_interface_handoff.py`](analysis/build_interface_handoff.py)。它把RF出口面、尚未冻结的
  oa入口面和脉冲时刻捕获状态分开；canonical CSV只保存每粒子一次带全局时间的出口相空间事件，
  三维快照和求解器输入均按需派生。RF与oa在统一仪器坐标中的位姿分别冻结，相对平移/转角只能由
  两者派生；坐标变换不代替连接器内的真实输运。当前审计还确认oa加速器屏蔽沿注入轴没有侧孔，
  连接器必须包含参数化屏蔽开孔和接地注入管候选。该合同只通过静态门禁，不授权物理连接或运行打包。
- RF→oa接口分阶段实施顺序：
  [`config/rf_to_oatof_interface_stages.json`](config/rf_to_oatof_interface_stages.json)；从无物理资格的
  S0数据直连参考开始，逐级增加开孔、被动通道、脉冲、必要的主动光学及最终跨求解器/CAD门禁，禁止跳级。
- S0求解器无关执行入口：
  [`analysis/run_interface_s0_reference.py`](analysis/run_interface_s0_reference.py)及
  [`config/modes/rf_to_oatof_s0_reference.json`](config/modes/rf_to_oatof_s0_reference.json)；只复用已冻结
  N=100源证据并生成虚拟入口事件和run三件套，不运行求解器、不裁剪孔径、不授权物理连接。
- S1轴向孔径—接受率预检：
  [`analysis/analyze_s1_aperture_acceptance.py`](analysis/analyze_s1_aperture_acceptance.py)及
  [`config/modes/rf_to_oatof_s1_aperture_precheck.json`](config/modes/rf_to_oatof_s1_aperture_precheck.json)；
  从S0虚拟入口事件计算严格理论上限内的最佳轴向几何通过率，不选择最终孔径、不替代三维联合场。
- S1局部联合场特征化合同：
  [`config/rf_to_oatof_s1_joint_field.json`](config/rf_to_oatof_s1_joint_field.json)、
  [`analysis/validate_s1_joint_field.py`](analysis/validate_s1_joint_field.py)及
  [`analysis/analyze_s1_joint_field.py`](analysis/analyze_s1_joint_field.py)；旧闭合场阈值只作L0诊断告警，
  不直接接受或拒绝连接器，并分别报告`Ex/Ey/Ez`诊断量。
- S1真实过孔动态功能链：
  [`analysis/build_s1_downstream_handoff.py`](analysis/build_s1_downstream_handoff.py)、
  [`analysis/analyze_s1_end_to_end.py`](analysis/analyze_s1_end_to_end.py)、
  [`analysis/plot_s1_loss_atlas.py`](analysis/plot_s1_loss_atlas.py)、
  [`analysis/compare_s1_entry_to_oatof_ideal_source.py`](analysis/compare_s1_entry_to_oatof_ideal_source.py)及
  [`analysis/plot_s1_pulse_geometry_snapshot.py`](analysis/plot_s1_pulse_geometry_snapshot.py)；
  执行入口为[`tests/cross_solver/run_s1_physical_end_to_end.ps1`](tests/cross_solver/run_s1_physical_end_to_end.ps1)；
  COMSOL在真实`1.0×0.9 mm`孔和局部联合场中完成按时进入及统一有限脉冲，SIMION从局部出口真实三维
  状态继续到分析器；成功的联合场run可直接作为下游来源，无需复制成仅为修复旧布尔解析问题而保留的
  reanalysis run。2 eV功能基线清点为`100→88→28→9`；5 eV候选为`100→77→39→37`。两者都只证明
  功能贯通，不授权分辨率、阶段PASS或Formal晋升。每个启用粒子和统一脉冲的S1 COMSOL run还必须在
  自身`results/`生成参数化双投影脉冲快照；图中的oa加速器尺寸读取baseline，孔尺寸读取S1合同。
  活动离子、入口孔壁损失和加速器内部损失必须用不同标记同时显示；grid1/grid2投影分别使用各自
  baseline尺寸，不能把内部grid1误画成密封整个屏蔽腔。
- S1状态驱动脉冲定时：[`config/rf_to_oatof_pulse_timing.json`](config/rf_to_oatof_pulse_timing.json)、
  [`analysis/derive_s1_centroid_pulse_time.py`](analysis/derive_s1_centroid_pulse_time.py)及
  [`analysis/validate_s1_pulse_timing.py`](analysis/validate_s1_pulse_timing.py)；按显式`mass_amu + charge_state`
  选择目标物种，用实际逐粒子入口时刻和三维速度预测有限厚孔后的粒子组，再求其x质心到达当前oa理想
  源中心的共享脉冲时刻。能量变化由实际速度自然进入，禁止为某个质量、能量或电荷态硬编码时间；混合
  物种必须显式选组或分别生成调度。
- S2有限间距被动连接器静态合同：
  [`config/rf_to_oatof_s2_passive_connector.json`](config/rf_to_oatof_s2_passive_connector.json)及
  [`analysis/validate_s2_passive_connector.py`](analysis/validate_s2_passive_connector.py)；当前只冻结1 mm
  标称间距、同轴位姿、接地圆柱腔和既有`1.0×0.9 mm`oa入口孔，不授权场求解、粒子运行、S2 PASS或
  Formal晋升。
- RF入口能量匹配候选：[`config/rf_to_oatof_energy_match_candidate.json`](config/rf_to_oatof_energy_match_candidate.json)、
  [`analysis/validate_rf_energy_match.py`](analysis/validate_rf_energy_match.py)及
  [`analysis/compare_rf_input_energy.py`](analysis/compare_rf_input_energy.py)；它用独立命名的100 amu、5 eV
  入射工况保持几何、RF和其他逐粒子源变量不变，不覆盖2 eV官方回归源，也不在handoff重写速度；
  通过能量合同、运行配置和manifest身份校验后，该模式可作为现有canonical交接转换器的显式候选来源。
- RF连续接地屏蔽候选：
  [`config/rf_continuous_grounded_shield_candidate.json`](config/rf_continuous_grounded_shield_candidate.json)及
  [`analysis/validate_rf_continuous_shield.py`](analysis/validate_rf_continuous_shield.py)；现有COMSOL/SIMION
  参考几何没有贯穿杆区的接地侧壁，故先独立扫描同轴圆柱内半径，再恢复S1联合场。圆柱尺寸不由oa外壳
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
| Static | 源配置与解析发布是否同步、GEM是否同步、固定粒子表、四极杆L0理论/电压合同、静态投影及双边界draft合同、分析测试和PowerShell入口语法是否通过 | 可执行 |
| Candidate | 指定mode的两份成功manifest、统一事件表和跨求解器功能指标是否通过 | 可执行；接口N=100已有有效FAIL证据 |
| Formal | 机械正式几何、SolidWorks装配与求解器资产是否同任务同步并复验 | 固定阻断，直到正式机械几何被选定 |

`transport_no_collision`与`transport_interface_readiness`共享硬件和RF-only基础物理，但运行目录、输出文件
和比较报告按mode隔离。接口mode还必须显式给出不少于100行的粒子表和RF峰值，不能靠N25默认值伪装成
接口候选。隔离规则落地前已经存在的接口运行可由跨求解器门禁只读复验；门禁仍检查其run config中的
真实mode，不要求重跑，也不再向旧路径写入新结果。

## 项目特有硬规则

- 两求解器必须从 `config/` 的共享几何、粒子源与 mode 契约派生同一输入；无碰撞基线不得创建或启用任何碰撞/阻尼模型。
- 参数链固定为 `baseline + source + mode + interface -> resolved -> COMSOL/SIMION生成资产`。安装目录中的
  SIMION官方例程只提供来源依据，不再是运行时权威；任何下游硬编码或反向抄写都视为失效实现。
- 官方回归与集成就绪验证严格分离：不得覆盖`official_fixed_25.ion`或借新增工况改写已闭合的 N25 结果。
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
