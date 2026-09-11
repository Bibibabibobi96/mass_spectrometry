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
[`术语定义`](../../common/multipole/README.md#统一术语)。

## 机器权威

参数、数值、源和资格合同统一由 [PROJECT 的机器权威表](docs/PROJECT.md#机器权威)导航。
项目发现使用 [project.json](config/project.json)，可执行入口注册见
[execution_profiles.json](config/execution_profiles.json)。

## 工作流入口

| 科学问题 | COMSOL | SIMION | 比较/判定 |
|---|---|---|---|
| 无碰撞部件回归 | `workflows/no_collision_transport/run_comsol.ps1` | `workflows/no_collision_transport/run_simion.ps1` | `workflows/no_collision_transport/compare_cross_solver.ps1` |
| 圆柱家族三模式实验 | 同一入口选择具名runtime profile | 同一入口选择具名runtime profile | 正式统计binding须事前完整预注册；既有run只可发布`POSTHOC_DESCRIPTIVE` binding |
| 接口就绪输运 | `workflows/interface_readiness/run_comsol.ps1` | `workflows/interface_readiness/run_simion.ps1` | `workflows/interface_readiness/compare_cross_solver.ps1` |
| RF+DC质量过滤 | `workflows/mass_filter_reference/run_comsol.ps1` | `workflows/mass_filter_reference/run_simion.ps1` | `workflows/mass_filter_reference/compare_responses.ps1` |
| 同求解器数值筛选 | — | — | `workflows/same_solver_convergence/run_comparison.ps1` |

多极杆分段杆和出口带孔接口板加速使用公共入口；具体命令与共同状态见公共multipole文档。
RF四极杆离子光学→单次反射oa-TOF物理连接属于
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`实例。已闭合的旧四极杆S2/S3迁移入口
退出活动树；当前四、六、八极杆同源功能闭合统一使用该integration内的
[`workflows/family_source_closure/execute.ps1`](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/workflows/family_source_closure/execute.ps1)；
内部stage不构成独立公开入口。
当前流程、电极映射和资格边界见
[`INTEGRATION.md`](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)。

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

## 项目边界

接口输运、无碰撞回归、质量过滤和轴向加速是不同科学声明。`official_transport` 矩形参考与圆柱
家族实验的消费边界见 [PROJECT](docs/PROJECT.md#当前机械与模式)；不能由粒子数或 `Mode` 隐式切换。


## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260722__rf-oatof-s2-s3-functional-closure](docs/history/20260722__rf-oatof-s2-s3-functional-closure.md)
- [20260722_rf-mesh-strategy-screen](docs/history/20260722_rf-mesh-strategy-screen.md)
- [20260722_rf-validation-and-s1-integration](docs/history/20260722_rf-validation-and-s1-integration.md)
- [20260723__pre-n100-multipole-functional-evidence](docs/history/20260723__pre-n100-multipole-functional-evidence.md)
- [20260728__pre-document-consolidation-comsol](docs/history/20260728__pre-document-consolidation-comsol.md)
- [20260728__pre-document-consolidation-project](docs/history/20260728__pre-document-consolidation-project.md)
- [20260728__pre-document-consolidation-readme](docs/history/20260728__pre-document-consolidation-readme.md)
- [20260728__pre-document-consolidation-simion](docs/history/20260728__pre-document-consolidation-simion.md)
- [20260729__superseded-rf-oatof-s2-s3-active-contracts](docs/history/20260729__superseded-rf-oatof-s2-s3-active-contracts.md)
- [20260911__solver-sensitivity-and-retired-interface](docs/history/20260911__solver-sensitivity-and-retired-interface.md)

</details>
