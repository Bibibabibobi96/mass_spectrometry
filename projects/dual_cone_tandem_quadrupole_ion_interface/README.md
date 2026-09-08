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
| SIMION 离子输运物理 | [`config/ion_transport_science.json`](config/ion_transport_science.json) |
| SIMION 数值 | [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json) |
| 计划级执行能力 | [`config/execution_profiles.json`](config/execution_profiles.json) |

## 当前工作流边界

权威方向固定为：

```text
COMSOL 可压缩气流 run
  → canonical gas-field + 来源 manifest
  → SIMION 气体辅助轨迹 run
  → canonical particle state / events
```

COMSOL 气流与 SIMION 轨迹是两个不同科学声明。SIMION 必须消费复制到本次 run、经哈希复核的
canonical 气体场和成功 COMSOL manifest；不得目录搜索“最新场”。这是一条依赖链，不是两个求解器
对同一轨迹物理的独立闭合。

当前只注册两个 `plan` profile；公开 COMSOL run 生命周期、canonical gas-field handoff 和 SIMION Fly
入口尚未全部闭合，因此不能从 execution profile 启动商业求解。项目内 MATLAB 任务和 SIMION GEM
编译器是受测实现部件，不是绕过 run 生命周期的第二公开入口。几何新鲜度入口为：

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
