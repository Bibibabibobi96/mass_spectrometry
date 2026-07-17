# RF 四极杆无碰撞传输与碰撞冷却项目

本项目以SIMION 2020自带`examples/quad`为共享硬件模板，验证三种运行模式：无背景气体的RF
约束与传输、RF+DC质量过滤，以及后续碰撞冷却。当前只闭合`transport_no_collision`，不能称为
冷却结果、质量过滤结果或正式机械几何。

## 固定阅读顺序

1. 先读[`docs/PROJECT.md`](docs/PROJECT.md)。
2. 操作 COMSOL 时读[`docs/COMSOL.md`](docs/COMSOL.md)。
3. 操作 SIMION 时读[`docs/SIMION.md`](docs/SIMION.md)。
4. 只有引入机械正式几何时才读/创建 CAD 文档。

软件细节不相互横向引用；统一参数与跨求解器结论只写入 `PROJECT.md`。

## 权威入口

- 共享几何契约：[`config/baseline.json`](config/baseline.json)
- 官方粒子源：[`config/official_particle_source.json`](config/official_particle_source.json)
- 当前传输模式：[`config/modes/transport_no_collision.json`](config/modes/transport_no_collision.json)
- 预留质量过滤模式：[`config/modes/mass_filter_reference.json`](config/modes/mass_filter_reference.json)
- COMSOL 候选生产入口：[`comsol/ms_rf_quadrupole_no_collision.m`](comsol/ms_rf_quadrupole_no_collision.m)
- SIMION 几何入口：[`simion/geometry/quad_monolithic.gem`](simion/geometry/quad_monolithic.gem)
- SIMION 传输程序：[`simion/programs/quad_transport.lua`](simion/programs/quad_transport.lua)
- COMSOL 验证门禁：[`tests/comsol/verify_nocollision_comsol.m`](tests/comsol/verify_nocollision_comsol.m)
- SIMION 构建/验证入口：[`tests/simion/run_transport_candidate.ps1`](tests/simion/run_transport_candidate.ps1)
- SIMION IOB 结构门禁：[`tests/simion/inspect_builtin_quad_reference.lua`](tests/simion/inspect_builtin_quad_reference.lua)
- 跨求解器门禁：[`analysis/verify_cross_solver_transport.py`](analysis/verify_cross_solver_transport.py)
- 终点分布诊断图：[`analysis/plot_terminal_distribution.py`](analysis/plot_terminal_distribution.py)
- 轴向轨迹诊断图：[`analysis/plot_transport_trajectory_diagnostics.py`](analysis/plot_transport_trajectory_diagnostics.py)
- 相位--轨迹差诊断图：[`analysis/plot_transport_phase_diagnostics.py`](analysis/plot_transport_phase_diagnostics.py)
- 场分辨率收敛：[`tests/simion/test_pa_field_convergence.ps1`](tests/simion/test_pa_field_convergence.ps1)、
  [`analysis/compare_field_resolution_convergence.py`](analysis/compare_field_resolution_convergence.py)
- 杆内释放诊断：[`analysis/compare_internal_release.py`](analysis/compare_internal_release.py)
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

## 工具链基线

本项目的 MATLAB/COMSOL 任务只使用 MATLAB **R2025b**；未来引入 STEP、零件或装配时只使用
**SolidWorks 2022**。不再支持 MATLAB R2022 或 SolidWorks 2013。求解器无关分析固定使用
仓库 `.venv` 的 Python 3.11。

## 硬规则

- 两求解器必须从 `config/` 的共享几何、粒子源与 mode 契约派生同一输入；无碰撞基线不得创建或启用任何碰撞/阻尼模型。
- COMSOL 的几何、选择、物理、Study、Solver、数据集和结果节点必须持久化到候选 MPH，并以 Study Compute 路径复核。
- SIMION 的 PA/IOB、Program、Fast Adjust 电压、粒子定义和检测记录必须可在 GUI 中检查。
- 本阶段只验证候选物理与数值实现；未完成 SolidWorks 同步前不得声称机械正式完成。
- 集成仪器中，传输四极杆和质量过滤四极杆是同一硬件模板的两个实例；共享几何/粒子接口，分别绑定 mode 配置和空间变换，不复制成两套几何源。
