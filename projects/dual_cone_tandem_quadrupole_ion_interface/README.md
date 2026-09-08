# 双锥串联四极杆离子传输接口

本项目维护大气压采样端之后的双锥差分抽气接口、椭圆杆前级 RF 四极导引器和圆杆后级 RF 四极
导引器。它是三重四极杆质量分析器 Q1 之前的独立离子传输组件；当前公开尺寸与 SCIEX QJet/Q0 类
前端相似，但尚无足够证据绑定厂商或型号。

当前资格、参数解释与开放问题只以 [`docs/PROJECT.md`](docs/PROJECT.md) 为准。

## 固定阅读顺序

1. 先读仓库根 [`README.md`](../../README.md)。
2. 再读 [`docs/PROJECT.md`](docs/PROJECT.md)。
3. 修改代码时读仓库根 [`docs/DEVELOPMENT_STANDARDS.md`](../../docs/DEVELOPMENT_STANDARDS.md)。

## 机器权威

| 职责 | 入口 |
|---|---|
| 项目身份与能力 | [`config/project.json`](config/project.json) |
| 用户尺寸与暂定解释 | [`config/baseline.json`](config/baseline.json) |
| 单向派生几何 | [`config/resolved_geometry.json`](config/resolved_geometry.json) |
| 筛选物理与暂定工况 | [`config/science.json`](config/science.json) |
| 时间积分设置 | [`config/solver_numerics.json`](config/solver_numerics.json) |
| 可执行入口 | [`config/execution_profiles.json`](config/execution_profiles.json) |

## 当前入口

```powershell
python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.resolve_geometry --check

python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.run_reduced_order_transport `
  --particle-count 100 `
  --seed 20260908 `
  --output-dir ..\artifacts\projects\dual_cone_tandem_quadrupole_ion_interface\runs\<run_id>
```

第二个入口是确定性的低成本阻尼轨迹筛选，不是 COMSOL、SIMION、CFD、扩散/离散碰撞、Candidate 或 Formal 证据。运行目录必须使用
仓库标准 `run_id`；入口发布 v2 compact `run_config.json`、`summary.json`、粒子状态、损失事件、诊断图
和 `run_manifest.json`。

## 目录职责

```text
dual_cone_tandem_quadrupole_ion_interface/
├─ config/       # baseline、resolved、物理、数值和执行合同
├─ analysis/     # 几何编译与求解器无关的低阶筛选模型
├─ tests/        # 静态、解析边界和确定性回归
└─ docs/         # 当前项目事实
```

大型结果与运行证据只进入工作区
`artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`，不进入 Git。
