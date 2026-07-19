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

软件细节不相互横向引用；统一参数与跨求解器结论只写入 `PROJECT.md`。

## 权威入口

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
- 集成就绪粒子族与模式：[`config/interface_readiness_particle_source.json`](config/interface_readiness_particle_source.json)、
  [`config/modes/transport_interface_readiness.json`](config/modes/transport_interface_readiness.json)
- 命名粒子表生成器：[`analysis/generate_interface_particle_table.py`](analysis/generate_interface_particle_table.py)，
  用固定种子生成任意 N 的可追溯 ION 表与元数据；求解器不得各自随机生成接口粒子。
- 预留质量过滤模式：[`config/modes/mass_filter_reference.json`](config/modes/mass_filter_reference.json)
- COMSOL 候选生产入口：[`comsol/ms_rf_quadrupole_no_collision.m`](comsol/ms_rf_quadrupole_no_collision.m)
- 旧`comsol/ms_rf_quadrupole_collision_cooling.m`现为拒绝执行的兼容短桩；其150 mm旧几何、硬编码
  连接和未验证碰撞模型不得恢复为当前入口。未来碰撞模式必须从共享契约重新建立。
- SIMION 几何入口：[`simion/geometry/quad_monolithic.gem`](simion/geometry/quad_monolithic.gem)
- SIMION 传输程序：[`simion/programs/quad_transport.lua`](simion/programs/quad_transport.lua)
- COMSOL 构建/GUI复验入口：[`tests/comsol/run_transport_candidate.ps1`](tests/comsol/run_transport_candidate.ps1)
- SIMION 构建/验证入口：[`tests/simion/run_transport_candidate.ps1`](tests/simion/run_transport_candidate.ps1)
- SIMION IOB 结构门禁：[`tests/simion/inspect_builtin_quad_reference.lua`](tests/simion/inspect_builtin_quad_reference.lua)
- 跨求解器门禁：[`tests/cross_solver/verify_transport_candidate.ps1`](tests/cross_solver/verify_transport_candidate.ps1)
- 全项目门禁：`verify_project.ps1 -Level Static|Candidate|Formal`；Candidate必须显式给出COMSOL、SIMION
  和比较运行标签，Formal在机械几何与SolidWorks同步前固定拒绝执行。
- 终点分布诊断图：[`analysis/plot_terminal_distribution.py`](analysis/plot_terminal_distribution.py)
- 轴向轨迹诊断图：[`analysis/plot_transport_trajectory_diagnostics.py`](analysis/plot_transport_trajectory_diagnostics.py)
- 相位--轨迹差诊断图：[`analysis/plot_transport_phase_diagnostics.py`](analysis/plot_transport_phase_diagnostics.py)
- 场分辨率收敛：[`tests/simion/test_pa_field_convergence.ps1`](tests/simion/test_pa_field_convergence.ps1)、
  [`analysis/compare_field_resolution_convergence.py`](analysis/compare_field_resolution_convergence.py)
- 杆内释放诊断：[`analysis/compare_internal_release.py`](analysis/compare_internal_release.py)
- 边缘定位、接口差异评估与oa-TOF集成门禁：
  [`analysis/assess_interface_integration_gate.py`](analysis/assess_interface_integration_gate.py)
- 路径解析：[`rf_quadrupole_paths.m`](rf_quadrupole_paths.m)

大型 MPH、PA、IOB、Fly'm 输出和图像一律放在
`artifacts/projects/rf_quadrupole_collision_cooling/`，不进入 Git。历史 `test3` 仅保留在
artifact archive，不能作为候选或正式基线。

## 目录职责

```text
rf_quadrupole_collision_cooling/
├─ config/    # 同源机器可读基线
├─ docs/      # PROJECT、COMSOL、SIMION
├─ comsol/    # MATLAB LiveLink 生产脚本
├─ simion/    # GEM、Lua、Fly2/PA 构建入口
└─ tests/     # 可复用 COMSOL、SIMION、跨求解器门禁
```

## 项目特有硬规则

- 两求解器必须从 `config/` 的共享几何、粒子源与 mode 契约派生同一输入；无碰撞基线不得创建或启用任何碰撞/阻尼模型。
- 参数链固定为 `baseline + source + mode + interface -> resolved -> COMSOL/SIMION生成资产`。安装目录中的
  SIMION官方例程只提供来源依据，不再是运行时权威；任何下游硬编码或反向抄写都视为失效实现。
- 官方回归与集成就绪验证严格分离：不得覆盖`official_fixed_25.ion`或借新增工况改写已闭合的 N25 结果。
- 新运行只以统一`particle_state.csv`、`summary.json`、稀疏轨迹和manifest为权威结果；不再生成旧版
  solver-specific粒子终点表。每份manifest在比较前必须重新计算全部文件哈希。
- 部件交接面、杆端诊断面和独立传输检测面必须分别读取接口机器契约，不得相互替代。
- 机械正式资格适用根README的SolidWorks同步门禁；当前项目状态只查PROJECT。
- 集成仪器中，传输四极杆和质量过滤四极杆是同一硬件模板的两个实例；共享几何/粒子接口，分别绑定 mode 配置和空间变换，不复制成两套几何源。

通用GUI对等、参数单向派生、产物清理和SolidWorks同步规则直接适用根README与仓库`AGENTS.md`。
