# 双锥串联四极杆离子传输接口

本项目维护大气压采样端之后的双锥差分抽气接口、椭圆杆前级 RF 四极导引器和圆杆后级 RF 四极
导引器。它是三重四极杆质量分析器 Q1 之前的独立离子传输组件；当前公开尺寸与 SCIEX QJet/Q0 类
前端相似，但尚无足够证据绑定厂商或型号。

Installed SIMION preparation is `msplatform.backends.simion.dual_cone_transport`.
Managed fresh transport and independent geometry/model/field/tracking software
operations are described in [`docs/SIMION.md`](docs/SIMION.md); their actual native
acceptance and remaining limits are recorded in [`PROJECT`](docs/PROJECT.md).

Installed gas-flow operations and explicit deployment/profile usage are described in
[`docs/COMSOL.md`](docs/COMSOL.md); project parameters remain explicit research inputs.

Installed same-source declared CAD uses the `dual_cone_tandem_quadrupole` provider
and the existing Assembly/STEP exporter; see [CAD usage and profile limits](docs/CAD.md).

当前资格、参数解释与开放问题只以 [`docs/PROJECT.md`](docs/PROJECT.md) 为准。

## 固定阅读顺序

1. 先读仓库根 [`README.md`](../../README.md)。
2. 再读 [`docs/PROJECT.md`](docs/PROJECT.md)。
3. 操作 COMSOL 时读 [`docs/COMSOL.md`](docs/COMSOL.md)。
4. 操作 SIMION 时读 [docs/SIMION.md](docs/SIMION.md)。
5. 修改代码时按[开发标准阅读导航](../../docs/DEVELOPMENT_STANDARDS.md#阅读导航)读通用章节及任务触发专题。
6. 只有追溯已退役 Python 筛选时才进入 [历史索引](docs/history/README.md)。

## 机器权威

| 职责 | 入口 |
|---|---|
| 项目身份与能力 | [`config/project.json`](config/project.json) |
| 用户尺寸与暂定解释 | [`config/baseline.json`](config/baseline.json) |
| 单向派生几何 | [`config/resolved_geometry.json`](config/resolved_geometry.json) |
| COMSOL 气流物理 | [`config/gas_flow_science.json`](config/gas_flow_science.json) |
| COMSOL 数值 | [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json) |
| COMSOL→SIMION 气体场接口 | [`config/gas_field_interface.json`](config/gas_field_interface.json) |
| 均匀后端 400 Pa 原型场 | [`config/uniform_rear_gas_field.json`](config/uniform_rear_gas_field.json) |
| SIMION 离子输运物理 | [`config/ion_transport_science.json`](config/ion_transport_science.json) |
| N=100 圆柱离子释放 | [`config/cylindrical_ion_source.json`](config/cylindrical_ion_source.json)，由 `msplatform.ion_release` 物化和签收 |
| SIMION 数值 | [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json) |
| 已注册 COMSOL 计划级执行能力 | [`config/execution_profiles.json`](config/execution_profiles.json) |

## 工作流入口

| 任务 | 入口 |
|---|---|
| 几何新鲜度 | `verify_project.ps1 -Level Static`（项目脚本向规范组件显式传 baseline/resolved 路径） |
| 计算气流、导出和校验 | [COMSOL 实施说明](docs/COMSOL.md#运行) |
| SIMION 阶段能力与准备 | [SIMION 实施说明](docs/SIMION.md#当前能力与验证边界) |
| 规定均匀场对照／GEM smoke | [SIMION 实施说明](docs/SIMION.md) |

SIMION 的正式准备与运行实现归安装包；fresh 和独立阶段的软件入口使用现有公共 owner，
保留 fractional 表面与原始场族保护。四个旧原生 wrapper 和旧执行 profile 已退役，不恢复旧名或阻断 stub。
成功原生 Fly 及独立阶段的原生验收仍未完成；失败事实和历史资格见
[PROJECT](docs/PROJECT.md#当前资格)。已退役 Python 压力—阻尼积分器只从历史索引追溯。

## 目录职责

```text
dual_cone_tandem_quadrupole_ion_interface/
├─ config/       # 几何、气流、数值、mode和执行合同
├─ analysis/     # 轨迹投影等求解器无关诊断
├─ simion/       # 薄研究输入准备入口；正式 Program 与执行在安装包
├─ workflows/    # 研究配置与气流入口接线；不拥有另一套运行实现
├─ tests/        # 静态、合同和求解器适配边界回归
└─ docs/         # 当前PROJECT、软件说明与只读history
```

正式 SIMION 实现与资源位于 `src/msplatform/backends/simion/`，具名阶段工作流位于
`src/msplatform/workflows/dual_cone_stages.py`；上面的项目目录不复制这些生产职责。

不存在的实现目录不为空占位。大型模型、场、PA/IOB、轨迹、结果和日志只进入工作区
`artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`，不进入 Git。

## History索引

[历史索引](docs/history/README.md)集中列出已冻结实验、迁移和旧方案；需要追溯证据时按需进入。

Named target planning and explicit saved-product continuation use
`msplatform.workflows.dual_cone_stages.plan_to` / `run_to`; request groups call the
same four existing stages. See [PROJECT](docs/PROJECT.md#explicit-target-composition)
for dependency, read-only selection, reuse and validation limits.
