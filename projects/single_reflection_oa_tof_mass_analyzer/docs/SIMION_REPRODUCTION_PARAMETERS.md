# oa-TOF SIMION复现交接

本文件是面向GUI复核人员的**派生导航**，不是参数权威，也不能驱动Candidate、PA重建或Formal发布。
精确几何、电压、网格、粒子和资产SHA必须在复现时从下列机器合同读取；若本文与合同冲突，以合同为准。

## 权威输入

| 职责 | 机器合同 |
|---|---|
| 物理设计 | [`baseline.json`](../config/baseline.json) |
| Formal科学模式 | [`modes/formal.json`](../config/modes/formal.json) |
| 求解器数值 | [`formal_solver_numerics.json`](../config/formal_solver_numerics.json) |
| resolved几何 | [`resolved_geometry.json`](../config/resolved_geometry.json) |
| Formal资产清单 | [`formal_assets.json`](../config/formal_assets.json) |
| SIMION稳定入口 | [`simion_stable_entry.json`](../config/simion_stable_entry.json) |
| 冻结验证结果 | [`formal_validation.json`](../config/formal_validation.json) |

完整参数由`baseline + formal science + solver numerics → resolved`单向派生。不要从本文件抄录旧电极表
后分别手改GEM、Lua或IOB。

## 坐标与四PA

- 全局`+z`从加速器指向反射器，检测有效面中心和一阶时间焦点为全局`z=0`。
- 正式独立oaTOF Workbench恰好有4个实例：
  `1 flight_tube`、`2 reflectron`、`3 accelerator`、`4 detector`。
- 实例顺序、GUI priority、PA路径和数组身份以Formal manifest与稳定入口为准。
- detector PA是GUI可见数值终止层，不是机械检测器厚度。
- grid1、grid2、entgrid和midgrid是理想透明栅网；SIMION数值层必须由Program透明跨越。

RF多极杆集成的第3槽可以替换为combined frontend，但那是run-local integration候选，不是本项目独立
Formal包。其电极映射和PA重构只查
[integration当前文档](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)。

## GUI复核步骤

1. 复制完整Formal SIMION目录，不单独移动IOB或只复制`pa0`。
2. 先用`simion_stable_entry.json`和asset manifest复核IOB、CON、Lua、Fly2、ION及全部PA家族SHA。
3. 打开IOB，确认4个PA实例、角色、相对路径、变换、数组尺寸和GUI priority与manifest一致。
4. 确认Program与Data Recording均启用；关闭设置窗口不等于Disable Program。
5. 核对栅网跨越、Fast Adjust电极角色、detector捕获参数和trajectory quality。
6. 日常功能使用机器合同绑定的N=100前缀；峰形、尾部和Formal统计使用同源N=1000。
7. 保存Ion Number、TOF、位置、PA instance和Event，运行后用
   `formal_validation.json`而不是本文数值进行复核。

## PA重建

正式GEM使用`surface=fractional`。Refine必须从头执行并使用
`formal_solver_numerics.json`给出的convergence；不得Resume旧解。完整PA家族和`.pa-surf`必须保留，
因为Lua Fast Adjust依赖各电极数组。

任何源宽、加速器、无场长度或反射器变量变化都属于隔离Candidate。候选编译器根据变量目录自动重算
理论派生量和rebuild plan，只重建run-local受影响PA；通过Candidate、GUI和独立晋升前，不得覆盖Formal。

## 复现完成条件

文件存在不等于复现。至少需要：

- manifest与全部输入SHA通过；
- IOB重开后4实例、路径、变换和priority正确；
- Program/Recording真实启用；
- PA Refine设置和完整数组族一致；
- 固定粒子表真实Fly完成；
- 输出由项目正式分析与门禁复核。

当前Formal性能、资格和兼容边界只查[`PROJECT.md`](PROJECT.md)。
