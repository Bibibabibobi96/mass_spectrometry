# 双锥串联四极杆离子传输接口

本项目维护大气压采样端之后的双锥差分抽气接口、椭圆杆前级 RF 四极导引器和圆杆后级 RF 四极
导引器。它是三重四极杆质量分析器 Q1 之前的独立离子传输组件；当前公开尺寸与 SCIEX QJet/Q0 类
前端相似，但尚无足够证据绑定厂商或型号。

当前资格、参数解释与开放问题只以 [`docs/PROJECT.md`](docs/PROJECT.md) 为准。

## 固定阅读顺序

1. 先读仓库根 [`README.md`](../../README.md)。
2. 再读 [`docs/PROJECT.md`](docs/PROJECT.md)。
3. 操作 COMSOL 时读 [`docs/COMSOL.md`](docs/COMSOL.md)。
4. 操作 SIMION 时读 [docs/SIMION.md](docs/SIMION.md)。
5. 修改代码时读仓库根 [`docs/DEVELOPMENT_STANDARDS.md`](../../docs/DEVELOPMENT_STANDARDS.md)。
6. 只有追溯已退役 Python 筛选时才进入 [`docs/history/`](docs/history/)。

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
| SIMION 数值 | [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json) |
| 计划级执行能力 | [`config/execution_profiles.json`](config/execution_profiles.json) |

## 工作流入口

| 任务 | 入口 |
|---|---|
| 几何新鲜度 | `python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.resolve_geometry --check` |
| 计算气流、导出和校验 | [COMSOL 实施说明](docs/COMSOL.md#运行) |
| 消费 COMSOL 场进行飞行 | [run_comsol_field_prototype.ps1](workflows/gas_assisted_transport/run_comsol_field_prototype.ps1) |
| 规定均匀场对照／GEM smoke | [SIMION 实施说明](docs/SIMION.md) |

两种气体来源复用同一 Fly 核心，并以显式 manifest 交接；当前注册能力与实际原型证据的区别见
[PROJECT](docs/PROJECT.md#当前资格)。已退役 Python 压力—阻尼积分器只从历史索引追溯。

## 目录职责

```text
dual_cone_tandem_quadrupole_ion_interface/
├─ config/       # 几何、气流、数值、mode和执行合同
├─ analysis/     # 求解器无关几何编译与canonical输出校验
├─ comsol/       # 气流模型任务
├─ simion/       # GEM、Workbench Program与气体辅助轨迹实现
├─ workflows/    # 按科学问题隔离的原型与准备入口
├─ tests/        # 静态、合同和求解器适配边界回归
└─ docs/         # 当前PROJECT、软件说明与只读history
```

不存在的实现目录不为空占位。大型模型、场、PA/IOB、轨迹、结果和日志只进入工作区
`artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`，不进入 Git。


## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260908__superseded-python-pressure-drag-screening](docs/history/20260908__superseded-python-pressure-drag-screening.md)

- [空包络气流与传输原型](docs/history/20260911__empty-enclosure-gas-transport-prototype.md)

</details>
