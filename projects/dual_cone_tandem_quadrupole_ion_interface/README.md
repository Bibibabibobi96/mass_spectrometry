# 双锥串联四极杆离子传输接口

本项目维护大气压采样端之后的双锥差分抽气接口、椭圆杆前级 RF 四极导引器和圆杆后级 RF 四极
导引器。它是三重四极杆质量分析器 Q1 之前的独立离子传输组件；当前公开尺寸与 SCIEX QJet/Q0 类
前端相似，但尚无足够证据绑定厂商或型号。

当前资格、参数解释与开放问题只以 [`docs/PROJECT.md`](docs/PROJECT.md) 为准。

## 固定阅读顺序

1. 先读仓库根 [`README.md`](../../README.md)。
2. 再读 [`docs/PROJECT.md`](docs/PROJECT.md)。
3. 操作 COMSOL 时读 [`docs/COMSOL.md`](docs/COMSOL.md)。
4. 修改代码时读仓库根 [`docs/DEVELOPMENT_STANDARDS.md`](../../docs/DEVELOPMENT_STANDARDS.md)。
5. 只有追溯已退役 Python 筛选时才进入 [`docs/history/`](docs/history/)。

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

## 当前工作流边界

当前最简气流—轨迹原型的权威方向为：

```text
上游 101325 Pa / 300 K 储气腔 + 连通双锥通道 + 后端 400 Pa
  → COMSOL 二维轴对称 High-Mach 气体场
  → 带源合同哈希的 Lua gas-field + manifest
  → SIMION 气体辅助轨迹 run
  → trajectory samples + particle final state
```

COMSOL 场通过
[`workflows/gas_assisted_transport/run_comsol_field_prototype.ps1`](workflows/gas_assisted_transport/run_comsol_field_prototype.ps1)
进入真实 SIMION Fly。该入口与均匀场对照共同复用唯一的
[`run_gas_field_prototype.ps1`](workflows/gas_assisted_transport/run_gas_field_prototype.ps1)，后者负责 PA
缓存、官方 SDS、IOB 和 Fly；两种气体场只负责生成自己的严格 manifest。SIMION 不得目录搜索“最新场”。

当前 execution profile 仍只注册两个 `plan` profile；均匀 400 Pa 快速对照已有真实单离子 Fly 证据，
但不替代 COMSOL 场目标链，也不是 Candidate/Formal 资格。COMSOL 求解、场发布和下游 Fly 均保持失败
关闭。几何新鲜度入口为：

```powershell
python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.resolve_geometry --check
```

已退役的 Python 压力—阻尼积分器不再是活动入口，原声明与 run 身份见
[`docs/history/20260908__superseded-python-pressure-drag-screening.md`](docs/history/20260908__superseded-python-pressure-drag-screening.md)。

## 目录职责

```text
dual_cone_tandem_quadrupole_ion_interface/
├─ config/       # 几何、气流、数值、mode和执行合同
├─ analysis/     # 求解器无关几何编译与canonical输出校验
├─ comsol/       # 气流模型任务
├─ simion/       # 后续GEM、Workbench Program与气体辅助轨迹实现
├─ workflows/    # 后续按科学问题隔离的公开run入口
├─ tests/        # 静态、合同和求解器适配边界回归
└─ docs/         # 当前PROJECT、软件说明与只读history
```

不存在的实现目录不为空占位。大型模型、场、PA/IOB、轨迹、结果和日志只进入工作区
`artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`，不进入 Git。

## History索引

- [`docs/history/20260908__superseded-python-pressure-drag-screening.md`](docs/history/20260908__superseded-python-pressure-drag-screening.md)
