# RF四极杆离子光学：COMSOL实施与验证

本文只说明COMSOL模型入口、模型树边界、当前数值限制和GUI验收。跨求解器状态与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整诊断过程冻结在
[`history/20260728__pre-document-consolidation-comsol.md`](history/20260728__pre-document-consolidation-comsol.md)。
多极杆各轴向实体与事件面只采用
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)的统一术语。

## 活动入口

| 科学问题 | 入口 |
|---|---|
| 接口就绪输运 | `../workflows/interface_readiness/run_comsol.ps1` |
| 无碰撞部件回归 | `../workflows/no_collision_transport/run_comsol.ps1` |
| RF+DC质量过滤 | `../workflows/mass_filter_reference/run_comsol.ps1` |
| release构造诊断 | `../comsol/interface_readiness/run_release_construction_gate.m` |
| RF四极杆离子光学→单次反射oa-TOF S2/S3 | `../tests/cross_solver/run_s3_cumulative_chain.ps1` |

所有任务通过仓库统一R2025b/COMSOL入口建立连接，不自行`mphstart`。版本、启动、重试及
`EXECUTION_ENVIRONMENT_BLOCKED`分类只采用根README和`common/comsol/README.md`。

## 模型与合同

接口就绪、质量过滤和旧同求解器比较只消费具名profile冻结的resolved、科学mode、粒子bundle和
`../config/comsol_solver_numerics.json`。普通接口profile固定使用`baseline`数值身份；
`time_refined_160`只允许预注册的same-solver实验。MATLAB不选择profile，也不从环境或源码回退
物理/数值默认值。

公共多极杆L3传输的三种typed电气模式及其N=100数值三档只由`../config/runtime_profiles.json`绑定
`../config/multipole_transport_comsol_solver_numerics.json`。它不属于上述专用workflow，专用workflow
也不得读取该合同；两种作用域都不允许wrapper暴露自由design/numerics profile。

共享求解实现`../comsol/solve_deterministic_rf_quadrupole_particles.m`只负责几何、场、求解器release节点、轨迹
和状态导出，不按workflow名称选择科学问题。接口准备任务负责验证RF-only、无碰撞、无静态端场；
质量过滤任务显式建立差分RF/DC与静态公共偏置；轴向加速走公共multipole模型入口。

标准输出为canonical逐粒子事件表、稀疏轨迹、solver summary、MPH及run三件套。求解器专属终点表
不是新运行的稳定接口。跨软件统计只由Python参考分析执行。

## 数值与物理边界

- 基线网格、RF步数与最长时间只来自COMSOL数值合同；生产入口不接受hmax或步数标量覆盖。
- 无加速N=100基线与局部`0.5→0.35 mm`空间敏感性档已在四段杆实体几何上完成；两档均为
  RF-on 100/100、zero-RF 21/100，RMS半径相对变化约`0.92%`。v3当前只授权固定`0.35 mm`、
  `80→160`步/周期的时间敏感性档也已完成，RMS半径相对变化约`0.20%`。没有连续量误差预算，
  空间/时间功能PASS不得改称连续数值收敛；分段杆轴向加速baseline已完成。首次N=100空间档在
  `MESH_COMPLETE`后仅因17.752 GB超过原17.180 GB进程树帽而失败，预算v7保留8.59 GB系统
  可用内存底线、将进程树帽调整为21.475 GB后，唯一人工替代运行仍升至21.835 GB，同时系统
  可用内存降至7.653 GB。空间收敛因此为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不再重跑；
  当前商业求解器授权已关闭。
- 分段杆轴向加速使用四段、0.4 mm绝缘间隙和公共模电势；出口带孔接口板加速与显式多级案例均由各自具名合同
  决定，不在MATLAB中维护第二份电势。
- 当前模型无碰撞；旧碰撞脚本不得恢复。
- RF四极杆离子光学→单次反射oa-TOF的S2/S3是候选局部联合链，不修改下游Formal资产，也不证明
  接口场连续或整机Formal。

## GUI验收

适用的COMSOL候选必须：

1. 保存MPH后由Desktop重开；
2. 核对几何、选择集、网格、物理、Study/Solver、数据集与结果节点；
3. 核对`std1/std2`和`sol1/sol2`附着关系；
4. 由GUI `Study → Compute`等价重算；
5. 按冻结粒子表复核`ReleaseFromDataFile`节点、源释放面、出口孔穿越面、规范交接面、
   近接口统计面、输出列与manifest；
6. 不用旧解、残留报告或第二次启动覆盖首次失败。

release构造Gate只验证完整N=100输入下100个GUI可见`ReleaseFromDataFile`节点、文件与breadcrumb
闭包；这里的release是COMSOL求解器节点，不是粒子源合同或带孔接口板。Gate不运行
粒子Study，也不能产生传输或资格结论。历史`rel065`调查、Unicode报告修复和runner收尾过程只从
同日history快照追溯。

## 当前限制

- 圆柱家族三模式的COMSOL N=100完整数值矩阵未运行；当前只有四极杆无加速空间档完成，
  acceptance预算不足时结论固定为INCONCLUSIVE。
- RF四极杆离子光学→单次反射oa-TOF连接场、时间步、N=1000和机械资格未完成。
- 正式机械几何与CAD同步前不得提升Formal。
- 已关闭的连续屏蔽、piecewise swept和hybrid网格筛选数字不再保留在current文档；需要复核时使用
  history及来源manifest。
