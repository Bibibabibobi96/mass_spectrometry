# RF四极杆离子光学

本项目维护同一四极杆机械模板上的无碰撞RF传输、RF+DC质量过滤和轴向加速功能；碰撞冷却尚未建立。
当前资格、有效证据与开放任务只以[`docs/PROJECT.md`](docs/PROJECT.md)为准。本页只负责导航，不维护
运行数字或软件实现时间线。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 操作COMSOL时读[`docs/COMSOL.md`](docs/COMSOL.md)。
4. 操作SIMION时读[`docs/SIMION.md`](docs/SIMION.md)。
5. 只有追溯旧结论、run ID或关闭过程时才进入[`docs/history/`](docs/history/)。

多极杆通用理论见[`../../docs/multipoles/index.md`](../../docs/multipoles/index.md)；四、六、八极杆共享
运行机制、公共坐标、电压语义及共同证据只由
[`../../common/multipole/README.md`](../../common/multipole/README.md)登记。项目README和软件文档
不得复制公共状态。轴向部件与物理面只采用该公共文档的
[`术语定义`](../../common/multipole/README.md#轴向部件与物理面术语)。

## 机器权威

| 职责 | 权威入口 |
|---|---|
| 项目身份与能力 | [`config/project.json`](config/project.json) |
| 可执行workflow | [`config/execution_profiles.json`](config/execution_profiles.json) |
| 命名设计profile | [`config/design_profiles.json`](config/design_profiles.json) |
| 圆柱全尺寸家族机械base与三种电气模式 | [`config/requests/baseline.json`](config/requests/baseline.json)与[`config/operating_modes.json`](config/operating_modes.json) |
| 家族N=100/N=1000母样本绑定 | [`config/particle_source_profiles.json`](config/particle_source_profiles.json) |
| 三模式N=100数值预注册与资格输入 | [`config/family_experiment/n100_convergence_preregistration.json`](config/family_experiment/n100_convergence_preregistration.json) |
| 官方传输物理发布 | [`config/resolved_design_official.json`](config/resolved_design_official.json) |
| 质量过滤物理发布 | [`config/resolved_design_mass_filter.json`](config/resolved_design_mass_filter.json) |
| 接口、质量过滤与旧同求解器比较的COMSOL数值 | [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json) |
| 圆柱家族三电气模式及数值档 | [`config/runtime_profiles.json`](config/runtime_profiles.json)绑定[`config/multipole_transport_comsol_solver_numerics.json`](config/multipole_transport_comsol_solver_numerics.json)与SIMION对应合同 |
| SIMION数值合同 | [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json) |
| 粒子状态与接口面 | [`config/interface_contract.json`](config/interface_contract.json) |
| oaTOF集成oracle专用出口端口 | [`config/interfaces/provided/rf_multipole_exit.json`](config/interfaces/provided/rf_multipole_exit.json) |
| 多极杆轴向加速共同证据 | [`../../common/multipole/family_contract.json`](../../common/multipole/family_contract.json) |

`config/baseline.json`只保留旧格式注册兼容，不是活动求解器参数源。活动runner只消费具名profile编译的
完整request/resolved发布；不得用任意路径或CLI标量覆盖几何、RF/DC、静态电极或轴向加速合同。

## 工作流入口

| 科学问题 | COMSOL | SIMION | 比较/判定 |
|---|---|---|---|
| 无碰撞部件回归 | `workflows/no_collision_transport/run_comsol.ps1` | `workflows/no_collision_transport/run_simion.ps1` | `workflows/no_collision_transport/compare_cross_solver.ps1` |
| 圆柱家族三模式实验 | 同一入口选择具名runtime profile | 同一入口选择具名runtime profile | 真实handoff输出生成后发布dispersion binding |
| 接口就绪输运 | `workflows/interface_readiness/run_comsol.ps1` | `workflows/interface_readiness/run_simion.ps1` | `workflows/interface_readiness/compare_cross_solver.ps1` |
| RF+DC质量过滤 | `workflows/mass_filter_reference/run_comsol.ps1` | `workflows/mass_filter_reference/run_simion.ps1` | `workflows/mass_filter_reference/compare_responses.ps1` |
| 同求解器数值筛选 | — | — | `workflows/same_solver_convergence/run_comparison.ps1` |

多极杆分段杆和出口带孔接口板加速使用公共入口；具体命令与共同状态见公共multipole文档。
RF四极杆离子光学→单次反射oa-TOF物理连接属于
`rf_quadrupole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`实例，当前累积入口为
`tests/cross_solver/run_s3_cumulative_chain.ps1`。

## 目录职责

```text
rf_quadrupole_ion_optics/
├─ config/       # 科学合同、数值合同、profile和resolved发布
├─ workflows/    # 按科学问题隔离的正式运行与比较
├─ analysis/     # 求解器无关分析和项目专属诊断
├─ runtime/      # 项目共享编排机制
├─ comsol/       # COMSOL生产任务
├─ simion/       # GEM与Program源码
├─ tests/        # 静态、分析、商业软件和跨求解器门禁
└─ docs/         # 当前PROJECT/软件说明与只读history
```

大型模型、PA/IOB、结果和日志只进入工作区
`artifacts/projects/rf_quadrupole_ion_optics/`，不进入Git源码树。

## 项目特有硬规则

- 接口输运、无碰撞回归、质量过滤和轴向加速是不同科学声明，不能由`Mode`或粒子数隐式切换。
- `official_transport`及其出口端口只服务矩形RF→oaTOF integration oracle；圆柱家族实验只消费
  `requests/baseline.json`、typed operating mode和公共家族母样本。
- 两个求解器必须消费同一受治理粒子bundle及各自实际表示；未消费文件不能冒充来源证据。
- 质量过滤专属Mathieu判据、方形出口罩和上述integration实例不得上移到公共multipole层。
- 功能PASS不代表跨求解器数值等价、网格收敛、机械、Candidate或Formal资格。
- 无加速N=100双求解器baseline、空间和时间敏感性矩阵已经完成；最终两求解器的100个RF-on粒子身份
  完全一致，功能传输闭合。连续相空间因无来源充分的误差预算仍为`INCONCLUSIVE`，当前不授权任何
  商业求解器运行；进一步加密、加速模式、N=1000及完整矩阵必须另行预注册。公共runner会在创建run目录前复核身份和数值参数，
  并执行`config/family_experiment/engineering_budget.json`的时间、内存和磁盘硬帽。
- 正式机械几何与CAD同步完成前，`verify_project.ps1 -Level Formal`必须失败关闭。

历史完整状态、实现清单和关闭过程冻结于
[`docs/history/20260728__pre-document-consolidation-project.md`](docs/history/20260728__pre-document-consolidation-project.md)
及同日软件快照；它们只用于追溯。

## History索引

- [`docs/history/20260722__rf-oatof-s2-s3-functional-closure.md`](docs/history/20260722__rf-oatof-s2-s3-functional-closure.md)
- [`docs/history/20260722_rf-mesh-strategy-screen.md`](docs/history/20260722_rf-mesh-strategy-screen.md)
- [`docs/history/20260722_rf-validation-and-s1-integration.md`](docs/history/20260722_rf-validation-and-s1-integration.md)
- [`docs/history/20260723__pre-n100-multipole-functional-evidence.md`](docs/history/20260723__pre-n100-multipole-functional-evidence.md)
- [`docs/history/20260728__pre-document-consolidation-comsol.md`](docs/history/20260728__pre-document-consolidation-comsol.md)
- [`docs/history/20260728__pre-document-consolidation-project.md`](docs/history/20260728__pre-document-consolidation-project.md)
- [`docs/history/20260728__pre-document-consolidation-readme.md`](docs/history/20260728__pre-document-consolidation-readme.md)
- [`docs/history/20260728__pre-document-consolidation-simion.md`](docs/history/20260728__pre-document-consolidation-simion.md)
